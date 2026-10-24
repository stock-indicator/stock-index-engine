"""StockTwits bull/bear ratio from the public per-symbol stream.

``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` needs no API key,
no OAuth and no registration. Its value here is that posters *self-label*
their messages Bullish or Bearish, so a directional sentiment reading falls
out of counting labels — no NLP, no model, nothing to tune or drift.

Only a minority of messages carry a label, so the labelled count is reported
alongside the ratio: a 100% bullish reading off four labelled messages is
noise, and the indicator needs to be able to tell that apart from a real one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Sequence

from common.logger import get_logger

from .http import SourceUnavailable, fetch

LOGGER = get_logger("social.stocktwits")

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

# Broad-market proxies. SPY is the market; QQQ carries the growth/tech tilt
# that retail sentiment swings hardest on. Both are among the most-posted
# symbols on StockTwits, so their streams stay dense enough to read daily.
DEFAULT_SYMBOLS = ("SPY", "QQQ")

# Below this many labelled messages the ratio is noise rather than signal.
MIN_LABELLED = 10


def _labelled_counts(messages: Sequence[dict]) -> tuple:
    """(bullish, bearish) counts over the self-labelled messages."""
    bullish = bearish = 0
    for message in messages:
        entities = message.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        if not isinstance(sentiment_obj, dict):
            continue
        basic = sentiment_obj.get("basic")
        if basic == "Bullish":
            bullish += 1
        elif basic == "Bearish":
            bearish += 1
    return bullish, bearish


def _fetch_symbol(ticker: str, timeout: float) -> list:
    body = fetch(
        _API.format(ticker=ticker.strip().upper()),
        accept="application/json",
        timeout=timeout,
        source=f"StockTwits({ticker})",
    )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceUnavailable(f"StockTwits returned non-JSON for {ticker}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceUnavailable(f"StockTwits returned an unexpected shape for {ticker}")
    return payload.get("messages") or []


def fetch_stocktwits_sentiment(
    symbols: tuple = DEFAULT_SYMBOLS,
    timeout: float = 15.0,
) -> Dict[str, object]:
    """Aggregate bull/bear ratio across ``symbols``, as a snapshot of right now.

    A symbol whose stream fails is skipped rather than failing the whole
    reading — the aggregate is still meaningful on the remainder, and
    ``symbols_ok`` records what it was actually built from. The fetch only
    fails outright when *no* symbol could be read.

    Returns:
        A dict with ``bull_ratio`` (0-1 over labelled messages), the
        ``bullish``/``bearish``/``labelled``/``total`` counts, ``symbols_ok``
        and ``as_of``.

    Raises:
        SourceUnavailable: every symbol failed, or too few labelled messages
            came back to form a ratio.
    """
    bullish = bearish = total = 0
    ok: list = []
    errors: list = []

    for ticker in symbols:
        try:
            messages = _fetch_symbol(ticker, timeout)
        except SourceUnavailable as exc:
            LOGGER.warning("StockTwits stream unavailable for %s: %s", ticker, exc)
            errors.append(f"{ticker}: {exc}")
            continue
        sym_bull, sym_bear = _labelled_counts(messages)
        bullish += sym_bull
        bearish += sym_bear
        total += len(messages)
        ok.append(ticker.upper())

    if not ok:
        raise SourceUnavailable(
            "StockTwits unavailable for every symbol (" + "; ".join(errors) + ")"
        )

    labelled = bullish + bearish
    if labelled < MIN_LABELLED:
        raise SourceUnavailable(
            f"only {labelled} self-labelled StockTwits messages across "
            f"{', '.join(ok)}; need {MIN_LABELLED} for a usable ratio"
        )

    return {
        "as_of": datetime.now(timezone.utc),
        "symbols_ok": ",".join(ok),
        "bull_ratio": round(bullish / labelled, 4),
        "bullish": bullish,
        "bearish": bearish,
        "labelled": labelled,
        "total": total,
    }
