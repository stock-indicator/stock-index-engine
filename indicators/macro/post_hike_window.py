from __future__ import annotations

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.macro.base_fred import FREDIndicator


class PostHikeWindowIndicator(FREDIndicator):
    metadata = IndicatorMetadata(
        name="Post-Hike Window",
        category="Macro",
        threshold="0-6 months",
        markets=["US Market"],
        topics=["Macro", "Policy"],
        description="Tracks the time elapsed since the last Federal Reserve rate hike. The period immediately following a rate hike can be a vulnerable time for markets.",
    )
    required_series = {
        "fed_funds": "FEDFUNDS",
    }

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty or "fed_funds" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series FEDFUNDS unavailable.",
            )
        df = clean_df.dropna(subset=["fed_funds"]).copy()
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No rate observations available.",
            )
        df = df.sort_values("data_start_date")
        df["fed_funds"] = df["fed_funds"].astype(float)
        series = df.set_index("data_start_date")["fed_funds"]
        changes = series.diff()
        hikes = changes[changes > 0]
        if hikes.empty:
            pure_value = [{"metric": "months_since_hike", "value": None}]
            return self.build_result(
                raw_value="No hikes in sample",
                pure_value=pure_value,
                status="normal",
                notes="No rate hikes detected in observation window.",
            )
        last_hike_date = hikes.index[-1]
        current_date = series.index[-1]
        months_since = (
            (current_date.year - last_hike_date.year) * 12
            + (current_date.month - last_hike_date.month)
        )
        status = "high" if months_since <= 6 else "normal"
        raw_value = (
            f"Months since last hike: {months_since} (hike on {last_hike_date.date().isoformat()})"
        )
        notes = (
            "Within 6 months of last rate hike"
            if status == "high"
            else "More than 6 months since last rate hike"
        )
        pure_value = [
            {"metric": "months_since_hike", "value": months_since},
            {"metric": "last_hike_date", "value": last_hike_date.date().isoformat()},
        ]
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
