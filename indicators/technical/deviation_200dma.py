from __future__ import annotations

from typing import Dict

import pandas as pd

from common.config import INDEX_TICKERS, MOVING_AVG_WINDOW
from common.utils import summarize_values
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


class Price200DMADeviationIndicator(PriceSeriesIndicator):
    metadata = IndicatorMetadata(
        name="Price vs 200DMA",
        category="Technical",
        threshold="> 25%",
        markets=["US Market", "S&P 500", "Nasdaq 100"],
        topics=["Technical", "Trend"],
    )
    tickers: Dict[str, str] = INDEX_TICKERS

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        series_by_market = self.prepare_price_series(clean_df)
        values: Dict[str, float] = {}
        missing: Dict[str, str] = {}
        for market, series in series_by_market.items():
            try:
                ma = series.rolling(window=MOVING_AVG_WINDOW).mean()
                latest_ma = ma.iloc[-1]
                latest_price = series.iloc[-1]
                if pd.isna(latest_ma):
                    raise ValueError("Insufficient data for 200DMA")
                deviation = (latest_price - latest_ma) / latest_ma * 100
                values[market] = float(deviation)
            except Exception as exc:  # pylint: disable=broad-except
                missing[market] = str(exc)

        if not values:
            note = "200DMA deviation failed for all indices: " + "; ".join(
                f"{k} ({v})" for k, v in missing.items()
            )
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=note,
            )

        status = "high" if any(val > 25 for val in values.values()) else "normal"
        note_suffix = ""
        if missing:
            note_suffix = "; missing: " + "; ".join(f"{k} ({v})" for k, v in missing.items())

        pure_value = [
            {"market": market, "deviation_pct": float(value)}
            for market, value in values.items()
        ]

        return self.build_result(
            raw_value=summarize_values(values, unit="%"),
            pure_value=pure_value,
            status=status,
            notes="Deviation from 200-day moving average" + note_suffix,
        )
