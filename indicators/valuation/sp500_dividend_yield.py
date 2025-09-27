from __future__ import annotations

from common.fetchers import MarketDataFetcher, fetch_multpl_value
from indicators.base import BaseIndicator, IndicatorMetadata


class SP500DividendYieldIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Dividend Yield",
        category="Valuation",
        threshold="< 1.2%",
        markets=["US Market", "S&P 500"],
        topics=["Valuation", "Income"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):  # fetcher unused
        data = fetch_multpl_value("s-p-500-dividend-yield")
        if not data:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to scrape dividend yield from multpl.com.",
            )
        date_text, value = data
        status = "high" if value < 1.2 else "normal"
        pure_value = [{"market": "S&P 500", "dividend_yield_pct": value}]
        return self.build_result(
            raw_value=f"{value:.2f}% (as of {date_text})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com dividend yield table.",
        )
