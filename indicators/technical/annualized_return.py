from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from common.config import INDEX_TICKERS, ANNUAL_RETURN_WINDOW
from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


class BaseAnnualizedReturnIndicator(PriceSeriesIndicator):
    market_label: str
    threshold_pct: float = 40.0
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

        if len(series) <= ANNUAL_RETURN_WINDOW:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Insufficient history for 12-month return on {self.market_label}.",
            )

        current_price = float(series.iloc[-1])
        past_price = float(series.iloc[-ANNUAL_RETURN_WINDOW])
        if past_price == 0:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Encountered zero price {ANNUAL_RETURN_WINDOW} days ago for {self.market_label}.",
            )

        annual_return = (current_price / past_price - 1) * 100
        status = "high" if annual_return > self.threshold_pct else "normal"
        note = f"Trailing 252-trading-day return for {self.market_label}"
        if status == "high":
            note += f" above {self.threshold_pct:.0f}%"

        details_entry = {
            "market": self.market_label,
            "indicator_value": annual_return,
            "annualized_return_pct": annual_return,
            "current_price": current_price,
            "price_252d_ago": past_price,
        }

        return self.build_result(
            raw_value=f"{annual_return:.2f}%",
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

        lookback_prices = series.shift(ANNUAL_RETURN_WINDOW)
        returns = ((series / lookback_prices) - 1) * 100
        combined = pd.DataFrame(
            {
                "annualized_return_pct": returns,
                "current_price": series,
                "price_lookback": lookback_prices,
            }
        ).dropna()
        combined = combined[(combined.index.date >= cutoff_date) & (combined.index.date <= upper_date)]
        combined = combined[combined["price_lookback"] != 0]
        if combined.empty:
            return None

        history: List[Dict[str, object]] = []
        for ts, row in combined.iterrows():
            date_key = ts.date().isoformat()
            return_value = float(row["annualized_return_pct"])
            details = {
                "market": self.market_label,
                "indicator_value": return_value,
                "annualized_return_pct": return_value,
                "current_price": float(row["current_price"]),
                "price_252d_ago": float(row["price_lookback"]),
            }
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": return_value,
                    "details": details,
                }
            )

        history.sort(key=lambda item: item["date"])
        return history


class AnnualizedReturnSP500Indicator(BaseAnnualizedReturnIndicator):
    market_label = "S&P 500"
    slug_override = "12m_annualized_return_s_p_500"
    metadata = IndicatorMetadata(
        name="12M Annualized Return (S&P 500)",
        category="Technical",
        threshold="> 40%",
        markets=[market_label],
        topics=["Technical", "Momentum"],
    )
    tickers = {market_label: INDEX_TICKERS["S&P 500"]}


class AnnualizedReturnNasdaqIndicator(BaseAnnualizedReturnIndicator):
    market_label = "Nasdaq 100"
    slug_override = "12m_annualized_return_nasdaq_100"
    metadata = IndicatorMetadata(
        name="12M Annualized Return (Nasdaq 100)",
        category="Technical",
        threshold="> 40%",
        markets=[market_label],
        topics=["Technical", "Momentum"],
    )
    tickers = {market_label: INDEX_TICKERS["Nasdaq 100"]}
