from __future__ import annotations

from typing import Optional

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.valuation.base_multpl import MultplIndicator


class SP500PEIndicator(MultplIndicator):
    metadata = IndicatorMetadata(
        name="Index PE",
        category="Valuation",
        threshold="> 35",
        markets=["US Market", "S&P 500"],
        topics=["Valuation"],
        description="Measures the Price-to-Earnings (PE) ratio for the S&P 500. A high PE ratio can indicate that the market is overvalued compared to corporate earnings.",
    )
    table_slug = "s-p-500-pe-ratio"

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="SP500 PE dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_value = float(latest["value"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if latest_value > 35 else "normal"
        pure_value = [
            {"metric": "pe_ratio", "value": latest_value, "as_of": latest_date}
        ]
        return self.build_result(
            raw_value=f"{latest_value:.2f} (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com monthly PE table.",
        )

    def status_for_value(self, value: float) -> Optional[str]:
        return "high" if value > 35 else "normal"
