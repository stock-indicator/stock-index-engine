from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from common.config import INDEX_TICKERS, MOVING_AVG_WINDOW
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator
from common.models import IndicatorResult


class BasePrice200DMADeviationIndicator(PriceSeriesIndicator):
    market_label: str
    threshold_pct: float = 25.0
    tickers: Dict[str, str]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        series_map = self.prepare_price_series(clean_df)
        del fetcher
        series = series_map.get(self.market_label)
        if series is None or series.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"No price history available for {self.market_label}.",
            )

        ma_series = series.rolling(window=MOVING_AVG_WINDOW).mean()
        if ma_series.empty or pd.isna(ma_series.iloc[-1]):
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Insufficient data to compute 200DMA for {self.market_label}.",
            )

        latest_ma = float(ma_series.iloc[-1])
        latest_price = float(series.iloc[-1])
        deviation = (latest_price - latest_ma) / latest_ma * 100 if latest_ma else 0.0
        status = "high" if deviation > self.threshold_pct else "normal"
        note = f"200DMA deviation for {self.market_label}"
        if status == "high":
            note += f" above {self.threshold_pct:.0f}%"

        details_entry = {
            "market": self.market_label,
            "indicator_value": deviation,
            "deviation_pct": deviation,
            "adj_close": latest_price,
            "moving_average": latest_ma,
        }

        return self.build_result(
            raw_value=f"{deviation:.2f}%",
            pure_value=[details_entry],
            status=status,
            notes=note,
        )

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: int,
    ) -> Optional[List[Dict[str, object]]]:
        series_map = self.prepare_price_series(clean_df)
        series = series_map.get(self.market_label)
        if series is None or series.empty:
            return None

        cutoff_date = as_of.date() - timedelta(days=lookback_days)
        upper_date = as_of.date()
        series = series[(series.index.date >= cutoff_date) & (series.index.date <= upper_date)]
        if series.empty:
            return None

        ma_series = series.rolling(window=MOVING_AVG_WINDOW).mean().dropna()
        ma_series = ma_series[(ma_series.index.date >= cutoff_date) & (ma_series.index.date <= upper_date)]
        if ma_series.empty:
            return None

        aligned_prices = series.reindex(ma_series.index)
        deviation_series = ((aligned_prices - ma_series) / ma_series * 100).dropna()
        if deviation_series.empty:
            return None

        history: List[Dict[str, object]] = []
        for ts, deviation in deviation_series.items():
            date_key = ts.date().isoformat()
            deviation_value = float(deviation)
            details = {
                "market": self.market_label,
                "indicator_value": deviation_value,
                "deviation_pct": deviation_value,
                "adj_close": float(aligned_prices.loc[ts]),
                "moving_average": float(ma_series.loc[ts]),
            }
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": deviation_value,
                    "details": details,
                }
            )

        history.sort(key=lambda item: item["date"])
        return history


class Price200DMASP500Indicator(BasePrice200DMADeviationIndicator):
    market_label = "S&P 500"
    slug_override = "price_vs_200dma_s_p_500"
    metadata = IndicatorMetadata(
        name="Price vs 200DMA (S&P 500)",
        category="Technical",
        threshold="> 25%",
        markets=[market_label],
        topics=["Technical", "Trend"],
    )
    tickers = {market_label: INDEX_TICKERS["S&P 500"]}


class Price200DMANasdaqIndicator(BasePrice200DMADeviationIndicator):
    market_label = "Nasdaq 100"
    slug_override = "price_vs_200dma_nasdaq_100"
    metadata = IndicatorMetadata(
        name="Price vs 200DMA (Nasdaq 100)",
        category="Technical",
        threshold="> 25%",
        markets=[market_label],
        topics=["Technical", "Trend"],
    )
    tickers = {market_label: INDEX_TICKERS["Nasdaq 100"]}
