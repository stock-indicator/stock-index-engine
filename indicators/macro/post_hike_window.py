from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata, clip_to_window
from indicators.macro.base_fred import FREDIndicator

# Before the FOMC published a target (September 1982), a hike is a rise of at
# least this much in the monthly effective rate. The monthly average drifts by
# a few basis points without any policy move, so smaller rises are noise.
EFFECTIVE_RATE_HIKE_PCT = 0.25
WINDOW_MONTHS = 6


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
        # The FOMC's target: a single rate until December 2008, then the
        # upper bound of the target range.
        "target_pct": "DFEDTAR",
        "target_upper_pct": "DFEDTARU",
    }

    @staticmethod
    def _hike_dates(clean_df: pd.DataFrame) -> pd.DatetimeIndex:
        """Dates of rate hikes: target increases, or large effective-rate rises before targets existed."""
        df = clean_df.set_index("data_start_date").sort_index()
        hikes: List[pd.Timestamp] = []
        target_start = None
        if {"target_pct", "target_upper_pct"} <= set(df.columns):
            target = df["target_upper_pct"].combine_first(df["target_pct"]).dropna()
            if not target.empty:
                target_start = target.index[0]
                hikes.extend(target.index[target.diff() > 0])
        effective = df["fed_funds"].dropna()
        if target_start is not None:
            effective = effective[effective.index < target_start]
        hikes.extend(effective.index[effective.diff() >= EFFECTIVE_RATE_HIKE_PCT])
        return pd.DatetimeIndex(sorted(hikes))

    @staticmethod
    def _months_between(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
        return (later.year - earlier.year) * 12 + (later.month - earlier.month)

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: Optional[int],
    ) -> Optional[List[Dict[str, object]]]:
        rates = clean_df.dropna(subset=["fed_funds"]).set_index("data_start_date").sort_index()["fed_funds"]
        rates = clip_to_window(rates.astype(float), as_of, lookback_days)
        if rates.empty:
            return None
        hikes = self._hike_dates(clean_df)
        history: List[Dict[str, object]] = []
        for month, rate in rates.items():
            # A hike any time in the month counts for that month.
            prior = hikes[hikes <= month + pd.offsets.MonthEnd(0)]
            months = self._months_between(month, prior[-1]) if len(prior) else None
            date_key = month.date().isoformat()
            rule_status = "high" if months is not None and months <= WINDOW_MONTHS else "normal"
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key) or rule_status,
                    "summary_value": float(rate),
                    "details": {"fed_funds_pct": float(rate), "months_since_hike": months},
                }
            )
        return history

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty or "fed_funds" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series FEDFUNDS unavailable.",
            )
        hikes = self._hike_dates(clean_df)
        if hikes.empty:
            pure_value = [{"metric": "months_since_hike", "value": None}]
            return self.build_result(
                raw_value="No hikes in sample",
                pure_value=pure_value,
                status="normal",
                notes="No rate hikes detected in observation window.",
            )
        last_hike_date = hikes[-1]
        current_date = pd.Timestamp(clean_df["data_start_date"].max())
        months_since = self._months_between(current_date, last_hike_date)
        status = "high" if months_since <= WINDOW_MONTHS else "normal"
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
