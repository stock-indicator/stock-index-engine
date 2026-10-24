"""Polymarket prediction-market odds via the public Gamma API.

``gamma-api.polymarket.com`` needs no key and no auth. A market's
``outcomePrices`` are the implied probabilities of its outcomes, so a "Yes"
trading at 0.23 means the crowd is pricing a 23% chance.

This complements the rest of the engine rather than duplicating it: FRED says
where the economy *is*, price and breadth indicators say what the market has
*done*, and prediction-market odds say what money is betting happens *next*.

No historical vintage
---------------------
Gamma serves live odds on open markets only — there is no as-of endpoint and
no way to ask what the odds were last Tuesday. The indicator built on this
therefore accumulates its series forward from first run and can never be
backfilled. Treating a live quote as a historical observation would put
post-event information into a backtest, so it is not offered at all.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from common.logger import get_logger

from .http import SourceUnavailable, fetch

LOGGER = get_logger("social.polymarket")

_SEARCH = "https://gamma-api.polymarket.com/public-search"

# The default topic. Recession odds are the single most useful forward-looking
# macro gauge for a market-state engine, and Polymarket keeps a liquid market
# on them more or less continuously.
DEFAULT_TOPIC = "recession"

# A market this thin is a quote, not a consensus; its "probability" moves on
# a few hundred dollars of flow.
MIN_VOLUME = 10_000.0


def _parse_json_list(value) -> List:
    """Gamma encodes ``outcomes`` / ``outcomePrices`` as JSON-string arrays."""
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _volume(market: dict) -> float:
    try:
        return float(market.get("volume") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_forward_looking(market: dict, now: datetime) -> bool:
    """Open markets that resolve in the future.

    ``closed`` is the reliable resolved flag — ``active`` stays True even on
    settled markets — and a past ``endDate`` means the event already happened.
    Either way it carries no forward-looking information.
    """
    if market.get("closed"):
        return False
    end_date = market.get("endDate")
    if end_date:
        try:
            if datetime.fromisoformat(str(end_date).replace("Z", "+00:00")) < now:
                return False
        except (TypeError, ValueError):
            pass  # unparseable date: fall through to the outcome check
    return bool(_parse_json_list(market.get("outcomePrices"))) and bool(
        _parse_json_list(market.get("outcomes"))
    )


def _yes_probability(market: dict) -> Optional[float]:
    """The market's implied probability of "Yes", or None if it is not binary."""
    outcomes = [str(o).strip().lower() for o in _parse_json_list(market.get("outcomes"))]
    prices = _parse_json_list(market.get("outcomePrices"))
    if len(outcomes) != len(prices) or "yes" not in outcomes:
        return None
    try:
        return float(prices[outcomes.index("yes")])
    except (TypeError, ValueError, IndexError):
        return None


def fetch_polymarket_odds(
    topic: str = DEFAULT_TOPIC,
    timeout: float = 15.0,
) -> Dict[str, object]:
    """Implied probability of the most-traded open market matching ``topic``.

    Returns:
        A dict with ``probability`` (0-1), the market ``question``, its
        ``volume``, ``end_date``, the ``topic`` searched and ``as_of``.

    Raises:
        SourceUnavailable: the search failed, or matched no open binary
            market above :data:`MIN_VOLUME`.
    """
    body = fetch(
        _SEARCH,
        params={"q": topic, "limit_per_type": 20},
        accept="application/json",
        timeout=timeout,
        source="Polymarket",
    )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceUnavailable(f"Polymarket returned non-JSON: {exc}") from exc

    now = datetime.now(timezone.utc)
    candidates = [
        market
        for event in (payload.get("events") or [])
        for market in (event.get("markets") or [])
        if _is_forward_looking(market, now)
        and _volume(market) >= MIN_VOLUME
        and _yes_probability(market) is not None
    ]
    if not candidates:
        raise SourceUnavailable(
            f"no open Polymarket market for {topic!r} above "
            f"${MIN_VOLUME:,.0f} volume"
        )

    best = max(candidates, key=_volume)
    probability = _yes_probability(best)
    LOGGER.debug(
        "Polymarket %r -> %.3f on %r (volume %.0f)",
        topic, probability, best.get("question"), _volume(best),
    )
    return {
        "as_of": now,
        "topic": topic,
        "probability": round(probability, 4),
        "question": best.get("question"),
        "volume": round(_volume(best), 2),
        "end_date": best.get("endDate"),
    }
