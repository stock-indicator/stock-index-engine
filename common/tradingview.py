"""Daily bars from TradingView's public chart websocket.

A minimal port of the chart-session protocol used by
https://github.com/Mathieu2301/TradingView-API: connect anonymously, resolve a
symbol, request a daily series, and collect bars until the server reports the
series complete. Anonymous sessions get each symbol's full daily history for
the index, breadth (``INDEX:S5TH``), CBOE (``USI:PCCE``) and FRED-mirror
(``FRED:BAMLH0A0HYM2``) symbols the indicators use.

This is an unofficial interface: TradingView can change it at any time.
Callers must treat a failure as "no new data" and keep what they already have.
"""

from __future__ import annotations

import json
import secrets
import string
import time
from typing import Dict, List

import pandas as pd
from websockets.sync.client import connect

from .logger import get_logger

logger = get_logger("tradingview")

WEBSOCKET_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart&type=chart"
ORIGIN = "https://www.tradingview.com"
USER_AGENT = "stock-index-engine/0.1 (market indicators)"
# More bars than any daily series has: ~36 years of trading days is ~9,000.
DEFAULT_BAR_COUNT = 20000
TIMEOUT_SECONDS = 60
_ERROR_METHODS = {"symbol_error", "series_error", "critical_error", "protocol_error"}


class TradingViewError(RuntimeError):
    """TradingView refused the request or the connection failed."""


def _encode(method: str, params: list) -> str:
    payload = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _decode(message: str) -> List[str]:
    """Split one websocket message into its ``~m~<len>~m~<payload>`` frames."""
    frames: List[str] = []
    position = 0
    while message.startswith("~m~", position):
        length_end = message.index("~m~", position + 3)
        length = int(message[position + 3:length_end])
        start = length_end + 3
        frames.append(message[start:start + length])
        position = start + length
    return frames


def _session_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase
    return prefix + "".join(secrets.choice(alphabet) for _ in range(12))


def fetch_daily_bars(symbol: str, *, count: int = DEFAULT_BAR_COUNT) -> pd.DataFrame:
    """Daily OHLCV bars for ``symbol`` (e.g. ``"INDEX:S5TH"``), oldest first.

    Returns a DataFrame with columns ``date`` (naive, UTC calendar date),
    ``open``, ``high``, ``low``, ``close`` and ``volume``. Raises
    ``TradingViewError`` when the symbol cannot be loaded.
    """
    chart_session = _session_id("cs_")
    bars: Dict[int, list] = {}
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with connect(
            WEBSOCKET_URL,
            origin=ORIGIN,
            user_agent_header=USER_AGENT,
            max_size=None,
            open_timeout=20,
        ) as ws:
            ws.send(_encode("set_auth_token", ["unauthorized_user_token"]))
            ws.send(_encode("chart_create_session", [chart_session, ""]))
            symbol_init = "=" + json.dumps({"symbol": symbol, "adjustment": "splits"})
            ws.send(_encode("resolve_symbol", [chart_session, "ser_1", symbol_init]))
            ws.send(_encode("create_series", [chart_session, "$prices", "s1", "ser_1", "1D", count]))
            completed = False
            while not completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TradingViewError(f"Timed out loading {symbol}")
                message = ws.recv(timeout=remaining)
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                for frame in _decode(message):
                    if frame.startswith("~h~"):
                        # Heartbeats must be echoed or the server drops us.
                        ws.send(f"~m~{len(frame)}~m~{frame}")
                        continue
                    try:
                        packet = json.loads(frame)
                    except json.JSONDecodeError:
                        continue
                    method = packet.get("m")
                    params = packet.get("p") or []
                    if method in ("timescale_update", "du"):
                        data = params[1] if len(params) > 1 and isinstance(params[1], dict) else {}
                        for bar in (data.get("$prices") or {}).get("s", []):
                            values = bar.get("v") or []
                            if len(values) >= 5:
                                bars[int(values[0])] = values
                    elif method == "series_completed":
                        completed = True
                    elif method in _ERROR_METHODS:
                        raise TradingViewError(f"{method} for {symbol}: {params}")
    except TradingViewError:
        raise
    except Exception as exc:  # websockets raises a spread of OSError/ConnectionClosed/TimeoutError
        raise TradingViewError(f"Connection to TradingView failed for {symbol}: {exc}") from exc

    if not bars:
        raise TradingViewError(f"TradingView returned no bars for {symbol}")
    rows = [
        {
            "date": pd.Timestamp(timestamp, unit="s").normalize(),
            "open": values[1],
            "high": values[2],
            "low": values[3],
            "close": values[4],
            "volume": values[5] if len(values) > 5 else None,
        }
        for timestamp, values in sorted(bars.items())
    ]
    frame = pd.DataFrame(rows).drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    logger.info(
        "Fetched %d TradingView bars for %s (%s to %s)",
        len(frame),
        symbol,
        frame["date"].iloc[0].date(),
        frame["date"].iloc[-1].date(),
    )
    return frame
