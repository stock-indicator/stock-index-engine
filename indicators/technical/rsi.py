from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from common.config import INDEX_TICKERS, RSI_PERIOD
from common.fetchers import MarketDataFetcher
from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


def _compute_rsi(prices: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class BaseRSIIndicator(PriceSeriesIndicator):
    market_label: str
    overbought_threshold: float = 80.0
    tickers: Dict[str, str]

    def compute(self, clean_df: pd.DataFrame, fetcher: MarketDataFetcher) -> IndicatorResult:
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

        rsi_series = _compute_rsi(series).dropna()
        if rsi_series.empty or pd.isna(rsi_series.iloc[-1]):
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Insufficient history to compute RSI for {self.market_label}.",
            )

        latest_rsi = float(rsi_series.iloc[-1])
        status = "high" if latest_rsi > self.overbought_threshold else "normal"
        note = f"14-day RSI for {self.market_label}"
        if status == "high":
            note += f" above {self.overbought_threshold}"

        details_entry = {
            "market": self.market_label,
            "indicator_value": latest_rsi,
            "rsi": latest_rsi,
            "adj_close": float(series.iloc[-1]),
        }

        return self.build_result(
            raw_value=f"{latest_rsi:.2f}",
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

        rsi_series = _compute_rsi(series).dropna()
        rsi_series = rsi_series[(rsi_series.index.date >= cutoff_date) & (rsi_series.index.date <= upper_date)]
        if rsi_series.empty:
            return None

        aligned_prices = series.reindex(rsi_series.index)
        history: List[Dict[str, object]] = []
        for ts, value in rsi_series.items():
            date_key = ts.date().isoformat()
            rsi_value = float(value)
            details = {
                "market": self.market_label,
                "indicator_value": rsi_value,
                "rsi": rsi_value,
                "adj_close": float(aligned_prices.loc[ts]),
            }
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": rsi_value,
                    "details": details,
                }
            )

        history.sort(key=lambda item: item["date"])
        return history


class RSISP500Indicator(BaseRSIIndicator):
    market_label = "S&P 500"
    slug_override = "rsi_14_s_p_500"
    metadata = IndicatorMetadata(
        name="RSI 14 (S&P 500)",
        category="Technical",
        threshold="> 80",
        markets=[market_label],
        topics=["Technical", "Momentum"],
        description="The Relative Strength Index (RSI) is a momentum oscillator that measures the speed and change of price movements. A reading above 80 is often considered an overbought signal.",
    )
    tickers = {market_label: INDEX_TICKERS["S&P 500"]}


class RSINasdaq100Indicator(BaseRSIIndicator):
    market_label = "Nasdaq 100"
    slug_override = "rsi_14_nasdaq_100"
    metadata = IndicatorMetadata(
        name="RSI 14 (Nasdaq 100)",
        category="Technical",
        threshold="> 80",
        markets=[market_label],
        topics=["Technical", "Momentum"],
    )
    tickers = {market_label: INDEX_TICKERS["Nasdaq 100"]}
