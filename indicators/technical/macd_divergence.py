from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd

from common.config import (
    INDEX_TICKERS,
    MACD_FAST,
    MACD_LOOKBACK,
    MACD_SIGNAL,
    MACD_SLOW,
)
from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


def _compute_macd(prices: pd.Series) -> pd.DataFrame:
    ema_fast = prices.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = prices.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": histogram})


class MACDDivergenceIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="MACD Divergence",
        category="Technical",
        threshold="Bearish divergence",
        markets=["US Market", "S&P 500", "Nasdaq 100"],
        topics=["Technical", "Trend"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        values: Dict[str, Tuple[bool, bool, float]] = {}
        missing: Dict[str, str] = {}
        for market, ticker in INDEX_TICKERS.items():
            try:
                history = fetcher.get_price_history(ticker, period="3y")
                adj_close = history["Adj Close"].dropna()
                macd_df = _compute_macd(adj_close)
                if macd_df.empty:
                    raise ValueError("Insufficient data")
                price_window = adj_close.iloc[-MACD_LOOKBACK:]
                macd_window = macd_df["macd"].iloc[-MACD_LOOKBACK:]
                if price_window.empty or macd_window.empty:
                    raise ValueError("Not enough lookback data")
                price_new_high = adj_close.iat[-1] >= price_window.max() * 0.999
                macd_new_high = macd_df["macd"].iat[-1] >= macd_window.max() * 0.999
                values[market] = (
                    price_new_high,
                    macd_new_high,
                    float(macd_df["macd"].iat[-1]),
                )
            except Exception as exc:  # pylint: disable=broad-except
                missing[market] = str(exc)

        if not values:
            note = "MACD evaluation failed for all indices: " + "; ".join(
                f"{k} ({v})" for k, v in missing.items()
            )
            return self.build_result(raw_value=None, pure_value=None, status="unavailable", notes=note)

        divergence_detected = any(p and not m for p, m, _ in values.values())

        def _format(entry: Tuple[bool, bool, float]) -> str:
            price_new, macd_new, macd_value = entry
            return (
                f"price_new_high={price_new}; macd_new_high={macd_new}; macd={macd_value:.2f}"
            )

        raw_value = "; ".join(
            f"{market}: {_format(data)}" for market, data in values.items()
        )
        note_suffix = ""
        if missing:
            note_suffix = "; missing: " + "; ".join(f"{k} ({v})" for k, v in missing.items())

        pure_value = [
            {
                "market": market,
                "price_new_high": vals[0],
                "macd_new_high": bool(vals[1]),
                "macd": float(vals[2]),
            }
            for market, vals in values.items()
        ]

        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status="high" if divergence_detected else "normal",
            notes="Bearish divergence if price makes new high but MACD does not" + note_suffix,
        )
