from __future__ import annotations

from common.fetchers import MarketDataFetcher, fetch_multpl_value
from indicators.base import BaseIndicator, IndicatorMetadata


class ShillerCAPEIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="CAPE Ratio",
        category="Valuation",
        threshold="> 35",
        markets=["US Market", "S&P 500"],
        topics=["Valuation", "Cycles"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):  # fetcher unused
        data = fetch_multpl_value("shiller-pe")
        if not data:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to scrape Shiller PE from multpl.com.",
            )
        date_text, value = data
        status = "high" if value > 35 else "normal"
        pure_value = [{"market": "S&P 500", "cape": value}]
        return self.build_result(
            raw_value=f"{value:.2f} (as of {date_text})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com Shiller CAPE table.",
        )
