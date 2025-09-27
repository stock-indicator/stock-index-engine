from __future__ import annotations

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.valuation.base_multpl import MultplIndicator


class ShillerCAPEIndicator(MultplIndicator):
    metadata = IndicatorMetadata(
        name="CAPE Ratio",
        category="Valuation",
        threshold="> 35",
        markets=["US Market", "S&P 500"],
        topics=["Valuation", "Cycles"],
    )
    table_slug = "shiller-pe"

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Shiller CAPE dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_value = float(latest["value"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if latest_value > 35 else "normal"
        pure_value = [
            {"metric": "cape", "value": latest_value, "as_of": latest_date}
        ]
        return self.build_result(
            raw_value=f"{latest_value:.2f} (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com Shiller CAPE table.",
        )
