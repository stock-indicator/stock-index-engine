from __future__ import annotations

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.macro.base_fred import FREDIndicator


class YieldCurveDurationIndicator(FREDIndicator):
    metadata = IndicatorMetadata(
        name="Yield Curve Duration",
        category="Macro",
        threshold="> 12 months",
        markets=["US Market"],
        topics=["Macro", "Yield Curve"],
        description="Tracks the consecutive duration of a yield curve inversion (10-year vs 2-year Treasury). Prolonged inversions have historically been a leading indicator of recessions.",
    )
    required_series = {
        "spread_pct": "T10Y2Y",
    }

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty or "spread_pct" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series T10Y2Y unavailable.",
            )
        df = clean_df.dropna(subset=["spread_pct"]).copy()
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Spread dataset empty after cleaning.",
            )
        df = df.sort_values("data_start_date")
        latest_row = df.iloc[-1]
        latest_value = float(latest_row["spread_pct"])
        latest_date = latest_row["data_start_date"].date().isoformat()
        if latest_value >= 0:
            pure_value = [
                {"metric": "spread_pct", "value": latest_value, "as_of": latest_date},
                {"metric": "inversion_months", "value": 0.0},
            ]
            return self.build_result(
                raw_value=f"Spread {latest_value:.2f}% (as of {latest_date})",
                pure_value=pure_value,
                status="normal",
                notes="Yield curve not inverted currently.",
            )

        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        spread_series = df.set_index("data_start_date")["spread_pct"].astype(float)
        negative_mask = spread_series < 0
        if not negative_mask.any():
            months = 0.0
        else:
            last_negative_date = negative_mask[negative_mask].index[-1]
            contiguous_negative = spread_series[last_negative_date:]
            first_non_negative = contiguous_negative[contiguous_negative >= 0]
            if not first_non_negative.empty:
                months = 0.0
            else:
                first_negative_date = contiguous_negative.index[0]
                months = (last_negative_date - first_negative_date).days / 30.4375
        status = "high" if months >= 12 else "normal"
        raw_value = (
            f"Spread {latest_value:.2f}% (as of {latest_date}); current inversion ~{months:.1f} months"
        )
        notes = (
            "Yield curve inverted for over 12 months"
            if status == "high"
            else "Yield curve inversion duration below 12 months"
        )
        pure_value = [
            {"metric": "spread_pct", "value": latest_value, "as_of": latest_date},
            {"metric": "inversion_months", "value": months, "as_of": latest_date},
        ]
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
