from __future__ import annotations

import time
from typing import Optional

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


class VIXLevelIndicator(PriceSeriesIndicator):
    metadata = IndicatorMetadata(
        name="VIX Level",
        category="Technical",
        threshold="< 10",
        markets=["US Market"],
        topics=["Volatility"],
        description="The CBOE Volatility Index (VIX) is a real-time index representing the market's expectation of 30-day forward-looking volatility. It is a widely used measure of market risk, often referred to as the 'fear gauge'.",
    )
    tickers = {"US Market": "^VIX"}

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        series_by_market = self.prepare_price_series(clean_df)
        series = series_by_market.get("US Market")
        if series is None or series.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No VIX data available.",
            )
        latest_vix = float(series.iloc[-1])
        if latest_vix == 0:
            self.logger.info("VIX value is zero, retrying in 10 seconds...")
            time.sleep(10)
            # Refetch
            # A short period bypasses the run cache, which holds the zero bar.
            raw_df = fetcher.get_price_history(self.tickers["US Market"], period="1mo")
            if raw_df.empty:
                return self.build_result(status="unavailable", notes="No VIX data on retry.")

            raw_df = raw_df.reset_index().rename(columns={"Date": "date"})
            raw_df["ticker"] = self.tickers["US Market"]
            raw_df["market"] = "US Market"

            clean_df = self.clean_data(raw_df)
            series_by_market = self.prepare_price_series(clean_df)
            series = series_by_market.get("US Market")

            if series is None or series.empty:
                return self.build_result(
                    raw_value=None,
                    pure_value=None,
                    status="unavailable",
                    notes="No VIX data available after retry.",
                )
            latest_vix = float(series.iloc[-1])
            if latest_vix == 0:
                self.logger.warning("VIX value is still zero after retry, skipping.")
                return self.build_result(
                    raw_value=0,
                    pure_value=None,
                    status="unavailable",
                    notes="VIX value is zero after retry, skipping.",
                )

        status = "high" if latest_vix < 10 else "normal"
        pure_value = [
            {"market": "US Market", "vix": latest_vix}
        ]
        return self.build_result(
            raw_value=f"{latest_vix:.2f}",
            pure_value=pure_value,
            status=status,
            notes="Low VIX signals complacency",
        )

    def status_for_value(self, value: float) -> Optional[str]:
        # yfinance reports 0.0 for some bars; that is missing data, not calm.
        if value <= 0:
            return None
        return "high" if value < 10 else "normal"
