from __future__ import annotations

from typing import Dict

import pandas as pd

from common.config import INDEX_TICKERS, RSI_PERIOD
from common.fetchers import MarketDataFetcher
from common.utils import summarize_values
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator
from common.models import IndicatorResult


def _compute_rsi(prices: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class RSIIndicator(PriceSeriesIndicator):
    metadata = IndicatorMetadata(
        name="RSI 14",
        category="Technical",
        threshold="> 80",
        markets=["US Market", "S&P 500", "Nasdaq 100"],
        topics=["Technical", "Momentum"],
    )
    tickers: Dict[str, str] = INDEX_TICKERS

    def compute(self, clean_df: pd.DataFrame, fetcher: MarketDataFetcher) -> IndicatorResult:
        series_by_market = self.prepare_price_series(clean_df)
        values: Dict[str, float] = {}
        missing: Dict[str, str] = {}
        for market, series in series_by_market.items():
            if series.empty:
                missing[market] = "No price history"
                continue
            rsi = _compute_rsi(series)
            if rsi.empty or pd.isna(rsi.iloc[-1]):
                missing[market] = "Insufficient data"
                continue
            values[market] = float(rsi.iloc[-1])

        if not values:
            note = "RSI calculation failed for all indices: " + "; ".join(
                f"{k} ({v})" for k, v in missing.items()
            )
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=note,
            )

        status = "high" if any(val > 80 for val in values.values()) else "normal"
        note_suffix = ""
        if missing:
            note_suffix = "; missing: " + "; ".join(f"{k} ({v})" for k, v in missing.items())

        pure_value = [
            {"market": market, "value": float(value)}
            for market, value in values.items()
        ]

        return self.build_result(
            raw_value=summarize_values(values),
            pure_value=pure_value,
            status=status,
            notes="14-day RSI using adjusted close prices" + note_suffix,
        )
