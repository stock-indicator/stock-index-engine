from __future__ import annotations

from typing import List, Optional

from indicators.base import BaseIndicator, IndicatorMetadata


class UnavailableIndicator(BaseIndicator):
    def __init__(
        self,
        *,
        name: str,
        category: str,
        market: List[str],
        threshold: str,
        notes: str,
        topics: Optional[List[str]] = None,
    ) -> None:
        self.metadata = IndicatorMetadata(
            name=name,
            category=category,
            threshold=threshold,
            markets=market,
            topics=topics or [category],
        )
        self._notes = notes
        super().__init__()

    def evaluate(self, fetcher):  # fetcher unused
        return self.build_result(
            raw_value=None,
            pure_value=None,
            status="unavailable",
            notes=self._notes,
        )


PLACEHOLDER_INDICATORS: List[UnavailableIndicator] = [
    UnavailableIndicator(
        name="Index PE",
        category="Valuation",
        market=["US Market", "Nasdaq 100"],
        threshold="> 35",
        notes="Requires Nasdaq 100 fundamentals (configure data feed).",
    ),
    UnavailableIndicator(
        name="Price-to-Book",
        category="Valuation",
        market=["US Market", "S&P 500", "Nasdaq 100"],
        threshold="> 6-7 S&P / > 9 Nasdaq",
        notes="PB ratios need aggregated fundamentals data feed.",
    ),
    UnavailableIndicator(
        name="Price-to-Sales",
        category="Valuation",
        market=["US Market", "S&P 500", "Nasdaq 100"],
        threshold="> 6 S&P / > 10 Nasdaq",
        notes="Quarterly P/S requires S&P Global or Bloomberg API.",
    ),
    UnavailableIndicator(
        name="Retail Positioning",
        category="Sentiment",
        market=["US Market"],
        threshold="> 70%",
        notes="Requires AAII/Vanda or similar feed.",
    ),
    UnavailableIndicator(
        name="ETF Net Inflows Streak",
        category="Sentiment",
        market=["US Market"],
        threshold="> 20 days",
        notes="ETF flow data (e.g., QQQ/SPY) not yet scripted.",
    ),
    UnavailableIndicator(
        name="IPO Activity",
        category="Sentiment",
        market=["US Market"],
        threshold="Frothy",
        notes="Requires NASDAQ or Renaissance Capital dataset.",
    ),
]
