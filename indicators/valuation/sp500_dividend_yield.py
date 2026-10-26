from __future__ import annotations

from typing import Optional

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.valuation.base_multpl import MultplIndicator


class SP500DividendYieldIndicator(MultplIndicator):
    metadata = IndicatorMetadata(
        name="Dividend Yield",
        category="Valuation",
        threshold="< 1.2%",
        markets=["US Market", "S&P 500"],
        topics=["Valuation", "Income"],
        description="Shows the S&P 500\'s dividend per share as a percentage of the index\'s price. A very low yield can suggest that market valuations are expensive relative to corporate payouts.",
    )
    table_slug = "s-p-500-dividend-yield"

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Dividend yield dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_value = float(latest["value"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if latest_value < 1.2 else "normal"
        pure_value = [
            {"metric": "dividend_yield_pct", "value": latest_value, "as_of": latest_date}
        ]
        return self.build_result(
            raw_value=f"{latest_value:.2f}% (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes="Source: multpl.com dividend yield table.",
        )

    def status_for_value(self, value: float) -> Optional[str]:
        return "high" if value < 1.2 else "normal"
