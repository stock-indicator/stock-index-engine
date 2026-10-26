from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from common.config import OUTPUT_DIR
from common.db import get_psql_connection
from common.logger import get_logger
from common.utils import sanitize_column_name, utc_now, write_text_atomic
from services.output import LOG_CSV_PATH, sanitize_for_json


logger = get_logger("services.history")
HISTORY_DIR = OUTPUT_DIR / "history"

# Parsed history files keyed by slug, reused until the file changes. A daily
# series with decades of data is several MB of JSON, and the dashboard asks
# for every indicator's history at once.
_HISTORY_CACHE: Dict[str, Tuple[int, Dict[str, object]]] = {}
_HISTORY_CACHE_LOCK = threading.Lock()
# Statuses that mark a signal; downsampling keeps these points visible.
_SIGNAL_STATUSES = {"high", "low"}


def _strip_source_fields(value):
    if isinstance(value, dict):
        return {k: _strip_source_fields(v) for k, v in value.items() if "source" not in k.lower()}
    if isinstance(value, list):
        return [_strip_source_fields(item) for item in value]
    return value


def _build_alias_map(indicators: Iterable) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for indicator in indicators:
        slug = indicator.slug
        aliases = {slug, sanitize_column_name(indicator.metadata.name)}
        markets = [sanitize_column_name(market) for market in indicator.metadata.markets]
        if markets:
            aliases.add("_".join(markets + [slug]))
            for market_alias in markets:
                aliases.add(f"{market_alias}_{slug}")
        for alias in aliases:
            if alias:
                alias_map[alias] = slug
    return alias_map


def generate_indicator_histories(
    *,
    indicators: Iterable,
    as_of: datetime,
    lookback_days: Optional[int] = None,
) -> None:
    """Write ``output/history/<slug>.json`` for each indicator.

    ``lookback_days`` of ``None`` (the default) exports everything in the clean
    data; the API trims to the requested range when serving it.
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    indicators = list(indicators)
    alias_map = _build_alias_map(indicators)
    status_lookup = _load_status_history(
        as_of=as_of,
        lookback_days=lookback_days,
        alias_map=alias_map,
    )
    for indicator in indicators:
        slug = indicator.slug
        clean_df = indicator.load_clean_data()
        if clean_df is None or clean_df.empty:
            logger.debug("No clean data available for %s; skipping history export", slug)
            continue
        status_map = status_lookup.get(slug, {})
        custom_series = indicator.build_history_series(
            clean_df=clean_df,
            status_map=status_map,
            as_of=as_of,
            lookback_days=lookback_days,
        )
        if custom_series is not None:
            series = _append_status_only_entries(
                custom_series, status_map, as_of=as_of, lookback_days=lookback_days
            )
            series.sort(key=lambda item: item["date"])
        else:
            series = _build_series(
                indicator_slug=slug,
                clean_df=clean_df,
                status_map=status_map,
                as_of=as_of,
                lookback_days=lookback_days,
            )
        _apply_rule_statuses(indicator, series)
        payload = {
            "indicator": slug,
            "display_name": indicator.metadata.name,
            "category": indicator.metadata.category,
            "markets": indicator.metadata.markets,
            "topics": indicator.metadata.topics,
            "threshold": indicator.metadata.threshold,
            "updated_at": as_of.isoformat(timespec="seconds"),
            "series": series,
        }
        _write_history_file(slug, payload)
        _upsert_history_to_db(slug, series)


def _apply_rule_statuses(indicator, series: List[Dict[str, object]]) -> None:
    """Mark each plotted point with the status the indicator's current rule gives it.

    The rule wins over the logged status: the run log only starts at the
    first deploy and records the rule of its day, so when a band is added
    (e.g. RSI < 30 as "low"), every point, logged or not, is re-read under
    the same rule. Indicators without a value rule keep the logged statuses,
    as do status-only entries, which carry no value.
    """
    for item in series:
        value = _coerce_numeric(item.get("summary_value"))
        if value is None:
            continue
        status = indicator.status_for_value(value)
        if status is not None:
            item["status"] = status


def load_indicator_history(slug: str) -> Optional[Dict[str, object]]:
    """The parsed history file for ``slug``. Callers must not mutate it."""
    path = HISTORY_DIR / f"{slug}.json"
    try:
        mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    with _HISTORY_CACHE_LOCK:
        cached = _HISTORY_CACHE.get(slug)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
        logger.warning("Failed to read history file %s: %s", path, exc)
        return None
    with _HISTORY_CACHE_LOCK:
        _HISTORY_CACHE[slug] = (mtime_ns, history)
    return history


def load_and_filter_history(
    slug: str,
    lookback_days: Optional[int] = None,
    max_points: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    """History for ``slug`` trimmed to ``lookback_days`` and at most ``max_points`` points."""
    history = load_indicator_history(slug)
    if history is None:
        return None
    series = history.get("series")
    if not isinstance(series, list):
        return dict(history)

    if lookback_days is not None:
        cutoff = (utc_now().date() - timedelta(days=lookback_days)).isoformat()
        # ISO dates compare correctly as strings.
        series = [item for item in series if str(item.get("date", "")) >= cutoff]
    if max_points is not None:
        series = downsample_series(series, max_points)
    return {**history, "series": series}


def downsample_series(series: List[Dict[str, object]], max_points: int) -> List[Dict[str, object]]:
    """Thin a date-sorted series to at most ``max_points`` points for charting.

    A series that already fits is returned unchanged. Otherwise status-only
    entries (no value; they only plot as gaps) are dropped, the rest is split
    into equal runs of consecutive points, and each run is represented by one
    real point: its last high/low point when it has one, so signals stay
    visible on a decades-long chart, else its last point.
    """
    if max_points <= 0 or len(series) <= max_points:
        return series
    valued = [item for item in series if item.get("summary_value") is not None]
    if len(valued) <= max_points:
        return valued
    step = math.ceil(len(valued) / max_points)
    thinned: List[Dict[str, object]] = []
    for start in range(0, len(valued), step):
        bucket = valued[start:start + step]
        flagged = [item for item in bucket if item.get("status") in _SIGNAL_STATUSES]
        thinned.append(flagged[-1] if flagged else bucket[-1])
    # The newest reading always stays the last point.
    thinned[-1] = valued[-1]
    return thinned



def _write_history_file(slug: str, payload: Dict[str, object]) -> None:
    path = HISTORY_DIR / f"{slug}.json"
    sanitized = sanitize_for_json(payload)
    write_text_atomic(path, _serialize_history(sanitized))
    # Refreshes run inside the API process (scheduler, POST /refresh), so seed
    # the read cache with what was just written instead of re-parsing ~50 MB
    # of history on the first dashboard load after every refresh.
    with _HISTORY_CACHE_LOCK:
        _HISTORY_CACHE[slug] = (path.stat().st_mtime_ns, sanitized)
    logger.info("Wrote history series for %s to %s", slug, path)


def _serialize_history(payload: Dict[str, object]) -> str:
    """JSON with one compact line per series point.

    Daily series reach back to 1927, so pretty-printing every point roughly
    doubles the file; one line per point keeps it small and keeps a refresh's
    diff to the lines that changed.
    """
    head = {key: value for key, value in payload.items() if key != "series"}
    points = ",\n".join(
        "    " + json.dumps(point, separators=(",", ":")) for point in payload.get("series", [])
    )
    head_json = json.dumps(head, indent=2)
    return head_json[:-2] + ',\n  "series": [\n' + points + "\n  ]\n}\n"


def _load_status_history(
    *, as_of: datetime, lookback_days: Optional[int], alias_map: Dict[str, str]
) -> Dict[str, Dict[str, str]]:
    if not LOG_CSV_PATH.exists():
        return {}
    try:
        df = pd.read_csv(LOG_CSV_PATH)
    except Exception:  # pragma: no cover
        # Statuses are an overlay on the series, so a bad log degrades the
        # history to values without statuses instead of failing the refresh.
        # Keep the traceback: this is the only trace of why they went missing.
        logger.exception("Failed to read history log %s", LOG_CSV_PATH)
        return {}
    if df.empty or "date" not in df.columns:
        return {}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if lookback_days is not None:
        cutoff = (as_of - timedelta(days=lookback_days)).date()
        df = df[df["date"].dt.date >= cutoff]
    status_lookup: Dict[str, Dict[str, str]] = {}
    for column in df.columns:
        if column in {"date", "generated_at", "mode", "triggered_available", "total_available", "triggered_total", "total_total"}:
            continue
        slug = _match_column_to_slug(column, alias_map)
        if not slug:
            continue
        for _, row in df.iterrows():
            date_value = row["date"]
            if pd.isna(date_value):
                continue
            status = row[column]
            if isinstance(status, float) and np.isnan(status):
                continue
            date_key = pd.Timestamp(date_value).date().isoformat()
            status_lookup.setdefault(slug, {})[date_key] = str(status)
    return status_lookup


def _match_column_to_slug(column: str, alias_map: Dict[str, str]) -> Optional[str]:
    normalized = column.strip().lower()
    for alias, slug in alias_map.items():
        if normalized == alias or normalized.endswith(f"_{alias}"):
            return slug
    return None


def _build_series(
    *,
    indicator_slug: str,
    clean_df: pd.DataFrame,
    status_map: Dict[str, str],
    as_of: datetime,
    lookback_days: Optional[int],
) -> List[Dict[str, object]]:
    df = clean_df.copy()
    upper_ts = pd.Timestamp(as_of.date())
    cutoff_ts = (
        upper_ts - pd.Timedelta(days=lookback_days) if lookback_days is not None else pd.Timestamp.min
    )
    if "data_start_date" in df.columns:
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        df = df[(df["data_start_date"] >= cutoff_ts) & (df["data_start_date"] <= upper_ts)]
        df = df.sort_values("data_start_date")
    elif "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df[(df["date"] >= cutoff_ts) & (df["date"] <= upper_ts)]
        df = df.sort_values("date")
    else:
        df = df.reset_index(drop=True)
    series: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        date_value = row.get("data_start_date") or row.get("date")
        if pd.isna(date_value):
            continue
        date_ts = pd.Timestamp(date_value)
        if date_ts.date() > as_of.date():
            continue
        date_key = date_ts.date().isoformat()
        details = _row_to_details(row)
        summary_value = _extract_summary_value(details)
        if summary_value is not None:
            series.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": summary_value,
                    "details": details,
                }
            )
    series = _append_status_only_entries(
        series, status_map, as_of=as_of, lookback_days=lookback_days
    )
    series.sort(key=lambda item: item["date"])
    return series


def _append_status_only_entries(
    series: List[Dict[str, object]],
    status_map: Dict[str, str],
    *,
    as_of: datetime,
    lookback_days: Optional[int],
) -> List[Dict[str, object]]:
    """Add entries for dates that carry a status but no observation.

    ``details`` is left empty rather than copied from another date's row.
    Stamping the latest observation's values onto a date that had none would
    invent data the series never carried -- that is what the original append
    did, and why disabling it was the right call; the copying is the part not
    worth keeping, not the feature. ``summary_value`` is null, which the
    frontend already types as nullable and renders as a gap in the line.

    Entries are bounded to the same window ``_build_series`` applies to the
    data rows, so a status outside the requested lookback cannot leak in.
    """
    if not status_map:
        return series
    existing_dates = {item.get("date") for item in series}
    upper = as_of.date()
    cutoff = upper - timedelta(days=lookback_days) if lookback_days is not None else date.min
    for status_date, status_value in status_map.items():
        if status_date in existing_dates:
            continue
        try:
            parsed = date.fromisoformat(status_date)
        except (TypeError, ValueError):
            continue
        if not cutoff <= parsed <= upper:
            continue
        series.append(
            {
                "date": status_date,
                "status": status_value,
                "summary_value": None,
                "details": {},
            }
        )
    return series



def _row_to_details(row: pd.Series) -> Dict[str, object]:
    details: Dict[str, object] = {}
    for column, value in row.items():
        if column in {"data_start_date", "data_end_date", "date"}:
            continue
        if isinstance(value, float) and np.isnan(value):
            continue
        if isinstance(value, pd.Timestamp):
            details[column] = value.isoformat()
        elif hasattr(value, "isoformat"):
            try:
                details[column] = value.isoformat()
            except Exception:  # pragma: no cover
                details[column] = str(value)
        else:
            details[column] = value
    return details


def _extract_summary_value(details: Dict[str, object]) -> Optional[float]:
    preferred_keys = [
        "indicator_value",
        "value",
        "score",
        "ratio",
        "deviation_pct",
        "annualized_return_pct",
        "macd",
        "rsi",
        "reading",
        # Price rows (e.g. VIX) carry OHLC columns. Without these the fallback
        # below picks "open", which yfinance reports as 0.0 for some bars.
        "adj_close",
        "close",
    ]
    for key in preferred_keys:
        value = details.get(key)
        numeric = _coerce_numeric(value)
        if numeric is not None:
            return numeric
    for value in details.values():
        numeric = _coerce_numeric(value)
        if numeric is not None:
            return numeric
    return None


def _coerce_numeric(value) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and np.isnan(value):
            return None
        return float(value)
    try:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            if not stripped:
                return None
            return float(stripped)
    except ValueError:
        return None
    return None


def _upsert_history_to_db(slug: str, series: List[Dict[str, object]]) -> None:
    if not series:
        return
    conn = get_psql_connection()
    if conn is None:
        return
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS indicator_history_series (
        indicator_slug TEXT NOT NULL,
        as_of_date DATE NOT NULL,
        status TEXT,
        summary_value DOUBLE PRECISION,
        details JSONB,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (indicator_slug, as_of_date)
    )
    """
    insert_sql = """
    INSERT INTO indicator_history_series (indicator_slug, as_of_date, status, summary_value, details)
    VALUES (%s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (indicator_slug, as_of_date)
    DO UPDATE SET
        status = EXCLUDED.status,
        summary_value = EXCLUDED.summary_value,
        details = EXCLUDED.details,
        updated_at = NOW()
    """
    rows = []
    for item in series:
        stripped_details = _strip_source_fields(item.get("details", {}))
        details_payload = sanitize_for_json(stripped_details)
        rows.append(
            (
                slug,
                item.get("date"),
                item.get("status"),
                _coerce_numeric(item.get("summary_value")),
                json.dumps(details_payload),
            )
        )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(create_table_sql)
            cur.executemany(insert_sql, rows)
    except Exception:  # pragma: no cover
        # Postgres is a best-effort sink; the JSON history file has already
        # been written by the time we get here.
        logger.exception("Failed to upsert history for %s", slug)
    finally:
        conn.close()

