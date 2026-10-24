"""Shared HTTP helpers for the public social / prediction-market endpoints.

These three sources (Reddit RSS, StockTwits, Polymarket Gamma) are all
keyless public endpoints, and they share two failure modes that the rest of
this project's fetchers do not have to think about:

1. They rate-limit per IP, so a burst of indicator refreshes can get a 429
   that a single backoff would have survived.
2. They are the only sources here where "the fetch failed" and "the fetch
   succeeded and there was nothing" are both plausible and mean opposite
   things. See :class:`SourceUnavailable`.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import requests

from common.logger import get_logger

LOGGER = get_logger("social.http")

# Reddit blocks generic/anonymous tokens such as the bare "Mozilla/5.0" string
# in common.config.HTTP_HEADERS, but serves a descriptive, identified client.
# Identify the project rather than spoofing a browser — it is also what
# Reddit's and StockTwits' API etiquette asks for.
USER_AGENT = "stock-index-engine/0.1 (market sentiment indicators)"

DEFAULT_TIMEOUT = 15.0

# These feeds are small (one page of results). Cap the body so a misbehaving
# or compromised endpoint cannot stream an unbounded response into memory.
MAX_BODY_BYTES = 5 * 1024 * 1024

# Backoff when a 429 carries no Retry-After. Reddit's search RSS still 429s at
# 8-30s of spacing and recovers around 60s, so a shorter wait just spends the
# one retry on a request that cannot succeed.
RETRY_FALLBACK_SECONDS = 60.0


class SourceUnavailable(RuntimeError):
    """A fetch failed — the data was never observed.

    Deliberately distinct from a successful fetch that returned nothing. If
    the two were collapsed, a rate-limited request would be recorded as
    "no bullish messages today", i.e. a sentiment reading the indicator never
    actually saw. An unavailable source must leave a gap in the series, not a
    zero, or every outage silently becomes a bearish data point.
    """


def _jitter(seconds: float, frac: float = 0.2) -> float:
    """``seconds`` with +/-``frac`` random jitter.

    Keeps concurrent refreshes sharing one IP from retrying in lockstep and
    re-colliding on the same per-IP limit.
    """
    return seconds * (1.0 + random.uniform(-frac, frac))


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    """Seconds to wait from a 429's ``Retry-After``, capped at 60s.

    Returns None when the header is absent or unparseable. A valid
    ``Retry-After: 0`` returns 0.0 (retry at once), not None.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return min(float(raw), RETRY_FALLBACK_SECONDS)
    except (TypeError, ValueError):
        return None


def _read_capped(response: requests.Response) -> bytes:
    """Read a response body bounded to :data:`MAX_BODY_BYTES`."""
    chunks = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        chunks.extend(chunk)
        if len(chunks) > MAX_BODY_BYTES:
            raise SourceUnavailable(
                f"response body exceeded {MAX_BODY_BYTES} bytes; refusing to parse"
            )
    return bytes(chunks)


def fetch(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    accept: str = "*/*",
    timeout: float = DEFAULT_TIMEOUT,
    source: str = "source",
    _retry: bool = True,
) -> bytes:
    """GET ``url`` and return the body, retrying once on a 429.

    Raises:
        SourceUnavailable: on any network error, non-2xx status, or oversized
            body. Never returns a partial or placeholder body — callers rely
            on the exception to tell "failed" apart from "empty".
    """
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    try:
        response = requests.get(
            url, params=params, headers=headers, timeout=timeout, stream=True
        )
    except requests.RequestException as exc:
        raise SourceUnavailable(f"{source} request failed: {exc}") from exc

    if response.status_code == 429 and _retry:
        wait = _retry_after_seconds(response)
        if wait is None:
            wait = RETRY_FALLBACK_SECONDS
        wait = _jitter(wait)
        LOGGER.warning("%s rate-limited (429); backing off %.1fs", source, wait)
        response.close()
        time.sleep(wait)
        return fetch(
            url, params=params, accept=accept, timeout=timeout,
            source=source, _retry=False,
        )

    try:
        if response.status_code >= 400:
            raise SourceUnavailable(
                f"{source} returned HTTP {response.status_code}"
            )
        return _read_capped(response)
    finally:
        response.close()
