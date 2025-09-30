from __future__ import annotations

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
