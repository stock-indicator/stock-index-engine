from __future__ import annotations

from typing import Dict, List

import pandas as pd

from common.config import INDEX_TICKERS, RSI_PERIOD
from common.fetchers import MarketDataFetcher
from common.utils import summarize_values
from indicators.base import BaseIndicator, IndicatorMetadata


def _compute_rsi(prices: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class RSIIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="RSI 14",
        category="Technical",
        threshold="> 80",
        markets=["US Market", "S&P 500", "Nasdaq 100"],
        topics=["Technical", "Momentum"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        values: Dict[str, float] = {}
        missing: Dict[str, str] = {}
        for market, ticker in INDEX_TICKERS.items():
            try:
                history = fetcher.get_price_history(ticker, period="2y")
                adj_close = history["Adj Close"].dropna()
                rsi_series = _compute_rsi(adj_close)
                if rsi_series.empty or pd.isna(rsi_series.iat[-1]):
                    raise ValueError("Insufficient data")
                values[market] = float(rsi_series.iat[-1])
            except Exception as exc:  # pylint: disable=broad-except
                missing[market] = str(exc)

        if not values:
            note = "RSI calculation failed for all indices: " + "; ".join(
                f"{k} ({v})" for k, v in missing.items()
            )
            return self.build_result(raw_value=None, pure_value=None, status="unavailable", notes=note)

        status = "high" if any(val > 80 for val in values.values()) else "normal"
        note_suffix = ""
        if missing:
            note_suffix = "; missing: " + "; ".join(f"{k} ({v})" for k, v in missing.items())

        ordered_markets: List[str] = [m for m in self.metadata.markets if m in values]
        pure_value = [
            {"market": market, "value": float(values[market])}
            for market in ordered_markets
        ]

        return self.build_result(
            raw_value=summarize_values(values),
            pure_value=pure_value,
            status=status,
            notes="14-day RSI using adjusted close prices" + note_suffix,
        )
