from __future__ import annotations

from common.fetchers import MarketDataFetcher, fetch_multpl_value
from indicators.base import BaseIndicator, IndicatorMetadata


class SP500PEIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Index PE",
        category="Valuation",
        threshold="> 35",
        markets=["US Market", "S&P 500"],
        topics=["Valuation"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):  # fetcher unused
        data = fetch_multpl_value("s-p-500-pe-ratio")
        if not data:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to scrape S&P 500 PE from multpl.com.",
            )
        date_text, value = data
        status = "high" if value > 35 else "normal"
        pure_value = [{"market": "S&P 500", "pe": value}]
        return self.build_result(
            raw_value=f"{value:.2f} (as of {date_text})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com monthly PE table.",
        )
