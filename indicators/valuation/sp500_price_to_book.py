from __future__ import annotations

from typing import Optional

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.valuation.base_multpl import MultplIndicator


class SP500PriceToBookIndicator(MultplIndicator):
    metadata = IndicatorMetadata(
        name="Price-to-Book",
        category="Valuation",
        threshold="> 6",
        markets=["US Market", "S&P 500"],
        topics=["Valuation"],
        description="Compares the S&P 500\'s market value to its book value. A high Price-to-Book (P/B) ratio can suggest the market is trading at a significant premium to its net asset value.",
    )
    table_slug = "s-p-500-price-to-book"

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="S&P 500 price-to-book dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_value = float(latest["value"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if latest_value > 6 else "normal"
        pure_value = [
            {"metric": "price_to_book", "value": latest_value, "as_of": latest_date}
        ]
        return self.build_result(
            raw_value=f"{latest_value:.2f} (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes="",
        )

    def status_for_value(self, value: float) -> Optional[str]:
        return "high" if value > 6 else "normal"
