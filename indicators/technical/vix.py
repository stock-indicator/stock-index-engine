from __future__ import annotations

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class VIXLevelIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="VIX Level",
        category="Technical",
        threshold="< 10",
        markets=["US Market"],
        topics=["Volatility"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        try:
            history = fetcher.get_price_history("^VIX", period="2y")
            close_price = history["Adj Close"].dropna()
            if close_price.empty:
                raise ValueError("No VIX data")
            latest_vix = float(close_price.iat[-1])
            status = "high" if latest_vix < 10 else "normal"
            pure_value = [{"market": "US Market", "vix": latest_vix}]
            return self.build_result(
                raw_value=f"{latest_vix:.2f}",
                pure_value=pure_value,
                status=status,
                notes="Low VIX signals complacency",
            )
        except Exception as exc:  # pylint: disable=broad-except
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"VIX fetch failed: {exc}",
            )
