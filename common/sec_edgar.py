"""SEC EDGAR Form 4 access for insider-trading indicators.

edgartools handles the HTTP session (SEC identity header, the ~9 req/s rate
limit, its own HTTP cache) and the XML parsing. This module adds a local cache
on top of that.

Each Form 4 accession number is parsed once and stored as its own JSON file in
``resources/raw/sec_form4/filings/``. Accession numbers are immutable on EDGAR,
so the cache never goes stale. It also survives indicator purges, because a
full refresh only clears the indicator's own folder. An interrupted run resumes
by skipping the accessions already on disk.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import pandas as pd
from edgar import Company

from common.logger import get_logger


LOGGER = get_logger("sec.form4")

EDGAR_IDENTITY_ENV = "EDGAR_IDENTITY"
FORM4_CACHE_DIR = Path("resources/raw/sec_form4/filings")
FORM4_WORKERS = 8  # edgartools throttles to SEC's ~9 req/s; extra workers hide latency
FETCH_ATTEMPTS = 3
PROGRESS_EVERY = 500

TRANSACTION_COLUMNS = [
    "accession_number",
    "filing_date",
    "issuer_cik",
    "issuer_ticker",
    "transaction_date",
    "code",
    "acquired_disposed",
    "shares",
    "price",
    "equity_swap",
    "tax_related",
    "plan_10b5_1",
]

# Sell-to-cover sales (shares sold to pay tax on vesting awards) carry code S but
# are not a discretionary view on the stock. Detected from footnote text.
_TAX_FOOTNOTE = re.compile(r"\btax", re.IGNORECASE)
_TAX_PURPOSE = re.compile(r"withh|cover|satisf|liabilit|obligation", re.IGNORECASE)
_PLAN_10B5_1 = re.compile(r"10b5-1", re.IGNORECASE)
_FOOTNOTE_ID = re.compile(r"[A-Za-z]+\d+")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class EdgarIdentityMissing(RuntimeError):
    """SEC rejects requests without a contact identity in the User-Agent."""


@dataclass
class SyncStats:
    companies: int = 0
    failed_companies: int = 0
    listed: int = 0
    cached: int = 0
    fetched: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)


def require_edgar_identity() -> str:
    """Return the SEC identity or raise before edgartools can prompt for it."""

    identity = os.environ.get(EDGAR_IDENTITY_ENV, "").strip()
    if not identity:
        raise EdgarIdentityMissing(
            'EDGAR_IDENTITY is not set. Add EDGAR_IDENTITY="Name email" to api.key '
            "or the environment; SEC requires a contact identity."
        )
    return identity


def resolve_ciks(tickers: Iterable[str]) -> Dict[int, str]:
    """Map configured tickers to CIKs. Unknown tickers are logged and skipped."""

    resolved: Dict[int, str] = {}
    for ticker in tickers:
        symbol = str(ticker).strip().upper()
        if not symbol:
            continue
        try:
            resolved[int(Company(symbol).cik)] = symbol
        except Exception as exc:  # edgartools raises CompanyNotFoundError and friends
            LOGGER.warning("Could not resolve ticker %s to a CIK: %s", symbol, exc)
    return resolved


# ----------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------
def _cache_path(accession_number: str) -> Path:
    return FORM4_CACHE_DIR / f"{accession_number}.json"


def is_cached(accession_number: str) -> bool:
    return _cache_path(accession_number).exists()


def _write_cache(accession_number: str, payload: Dict[str, Any]) -> None:
    FORM4_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(accession_number)
    tmp = path.parent / f"{path.name}.tmp"
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a killed run never leaves a half-written JSON


def load_cached_transactions(issuer_ciks: Set[int], start: date, end: date) -> pd.DataFrame:
    """Flatten cached open-market transactions for issuers in the universe.

    Only filters are applied here. Rules such as dropping equity swaps or
    sell-to-cover sales live in the indicator, so changing them never needs a
    re-download.
    """

    rows: List[Dict[str, Any]] = []
    if not FORM4_CACHE_DIR.exists():
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    lower, upper = start.isoformat(), end.isoformat()
    for path in FORM4_CACHE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Skipping unreadable Form 4 cache file %s: %s", path, exc)
            continue
        if payload.get("issuer_cik") not in issuer_ciks:
            continue
        for tx in payload.get("transactions", []):
            if lower <= tx["transaction_date"] <= upper:
                rows.append(
                    {
                        **tx,
                        "accession_number": payload["accession_number"],
                        "filing_date": payload["filing_date"],
                        "issuer_cik": payload["issuer_cik"],
                        "issuer_ticker": payload.get("issuer_ticker"),
                    }
                )
    return pd.DataFrame(rows, columns=TRANSACTION_COLUMNS)


# ----------------------------------------------------------------------
# Fetching and parsing
# ----------------------------------------------------------------------
def _trade_date(value: Any) -> Optional[str]:
    """Return the ISO date in a transaction cell. Some filings append footnote
    markers, e.g. "2026-02-17 [F2]", which pandas refuses to parse."""

    match = _ISO_DATE.search(str(value))
    return match.group(0) if match else None


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _footnote_text(form4: Any, footnote_ids: Any) -> str:
    if not isinstance(footnote_ids, str):
        return ""
    footnotes = getattr(form4, "footnotes", None)
    if footnotes is None:
        return ""
    texts = [footnotes.get(fid) or "" for fid in _FOOTNOTE_ID.findall(footnote_ids)]
    return " ".join(text for text in texts if text)


def parse_form4(filing: Any) -> Dict[str, Any]:
    """Parse one Form 4 filing into the cache payload.

    Only market trades are kept (edgartools' ``market_trades``: codes P and S).
    Grants (A), option exercises (M), tax withholding (F) and gifts (G) are
    dropped at this step.
    """

    form4 = filing.obj()
    transactions: List[Dict[str, Any]] = []
    trades = form4.market_trades
    if trades is not None and not trades.empty:
        for row in trades.itertuples(index=False):
            trade_date = _trade_date(row.Date)
            if trade_date is None:
                continue
            notes = _footnote_text(form4, row.footnotes)
            transactions.append(
                {
                    "transaction_date": trade_date,
                    "code": row.Code,
                    "acquired_disposed": row.AcquiredDisposed,
                    "shares": _finite_or_none(row.Shares),
                    "price": _finite_or_none(row.Price),
                    "equity_swap": bool(row.EquitySwap),
                    "tax_related": bool(_TAX_FOOTNOTE.search(notes) and _TAX_PURPOSE.search(notes)),
                    "plan_10b5_1": bool(_PLAN_10B5_1.search(notes)),
                }
            )
    return {
        "accession_number": filing.accession_no,
        "filing_date": str(filing.filing_date),
        "issuer_cik": int(form4.issuer.cik),
        "issuer_ticker": form4.issuer.ticker,
        "transactions": transactions,
    }


def list_form4_filings(cik: int, start: date, end: date) -> List[Any]:
    """Form 4 filings (no amendments) filed by ``end`` and on or after ``start``."""

    filings = Company(cik).get_filings(
        form="4",
        amendments=False,
        filing_date=f"{start.isoformat()}:{end.isoformat()}",
    )
    return list(filings) if filings is not None else []


def _index_filings(
    ciks: Sequence[int],
    start: date,
    end: date,
    workers: int,
    stats: SyncStats,
) -> List[Any]:
    """Return filings not yet cached. The same accession can appear under two
    companies (issuer and reporting owner), so it is de-duplicated here."""

    listed: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(list_form4_filings, cik, start, end): cik for cik in ciks}
        for future in as_completed(futures):
            cik = futures[future]
            try:
                filings = future.result()
            except Exception as exc:
                stats.failed_companies += 1
                LOGGER.warning("Form 4 index lookup failed for CIK %s: %s", cik, exc)
                continue
            for filing in filings:
                listed.setdefault(filing.accession_no, filing)
    stats.listed = len(listed)
    pending = [filing for accession, filing in listed.items() if not is_cached(accession)]
    stats.cached = stats.listed - len(pending)
    return pending


def _fetch_one(filing: Any) -> Optional[str]:
    """Parse and cache one filing. Returns an error string instead of raising,
    so one bad filing cannot stop the run. Failures are not cached, so the next
    run retries them. Retries absorb transient errors: edgartools' HTTP cache can
    hit file locks under concurrent writes, and SEC occasionally returns an
    empty body under load."""

    error = ""
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            _write_cache(filing.accession_no, parse_form4(filing))
            return None
        except Exception as exc:
            error = f"{filing.accession_no}: {type(exc).__name__}: {exc}"
            if attempt < FETCH_ATTEMPTS:
                time.sleep(attempt)
    return error


def _fetch_pending(pending: List[Any], workers: int, stats: SyncStats) -> None:
    total = len(pending)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_one, filing) for filing in pending]
        for done, future in enumerate(as_completed(futures), start=1):
            error = future.result()
            if error is None:
                stats.fetched += 1
            else:
                stats.failed += 1
                if len(stats.errors) < 20:
                    stats.errors.append(error)
            if done % PROGRESS_EVERY == 0 or done == total:
                elapsed = max(time.monotonic() - started, 1e-6)
                rate = done / elapsed
                eta = timedelta(seconds=int((total - done) / rate)) if rate else "unknown"
                LOGGER.info(
                    "Form 4 progress: %d/%d filings parsed (failed=%d, %.1f/s, eta=%s)",
                    done,
                    total,
                    stats.failed,
                    rate,
                    eta,
                )


def sync_form4_filings(
    ciks: Sequence[int],
    start: date,
    end: date,
    *,
    workers: int = FORM4_WORKERS,
) -> SyncStats:
    """Bring the Form 4 cache up to date for the given issuers and filing window.

    Cheap when nothing is new: each company's filing index is listed, and only
    accessions missing from the cache are downloaded.
    """

    require_edgar_identity()
    stats = SyncStats(companies=len(ciks))
    LOGGER.info(
        "Syncing Form 4 filings for %d companies (filed %s to %s)",
        len(ciks),
        start.isoformat(),
        end.isoformat(),
    )
    pending = _index_filings(ciks, start, end, workers, stats)
    LOGGER.info(
        "Form 4 index: %d filings listed, %d cached, %d to download (%d company lookups failed)",
        stats.listed,
        stats.cached,
        len(pending),
        stats.failed_companies,
    )
    if pending:
        _fetch_pending(pending, workers, stats)
    LOGGER.info(
        "Form 4 sync done: fetched=%d failed=%d",
        stats.fetched,
        stats.failed,
    )
    for error in stats.errors:
        LOGGER.warning("Form 4 parse failure: %s", error)
    return stats
