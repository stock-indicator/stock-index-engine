from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata, clip_to_window
from indicators.macro.base_fred import FREDIndicator


class CorporateProfitsToGDPIndicator(FREDIndicator):
    metadata = IndicatorMetadata(
        name="Corporate Profits vs GDP",
        category="Macro",
        threshold="> 12%",
        markets=["US Market", "US Economy"],
        topics=["Macro", "Profits"],
        description="Measures corporate profits as a percentage of GDP. Historically high levels can indicate unsustainable profit margins and potential reversions.",
    )
    required_series = {
        "gdp": "GDP",
        "corporate_profits": "CPATAX",
    }

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: Optional[int],
    ) -> Optional[List[Dict[str, object]]]:
        # Plot the profit share itself; the generic series would plot GDP,
        # the first numeric column.
        df = clean_df.dropna(subset=["gdp", "corporate_profits"]).copy()
        if df.empty:
            return None
        df = df.set_index("data_start_date").sort_index()
        share = clip_to_window(df["corporate_profits"] / df["gdp"] * 100, as_of, lookback_days)
        return [
            {
                "date": ts.date().isoformat(),
                "status": status_map.get(ts.date().isoformat()),
                "summary_value": float(value),
                "details": {
                    "corporate_profit_share_pct": float(value),
                    "corporate_profits": float(df.at[ts, "corporate_profits"]),
                    "gdp": float(df.at[ts, "gdp"]),
                },
            }
            for ts, value in share.items()
        ]

    def status_for_value(self, value: float) -> Optional[str]:
        return "high" if value > 12 else "normal"

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty or "gdp" not in clean_df.columns or "corporate_profits" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to fetch GDP or corporate profits series from FRED.",
            )
        df = clean_df.dropna(subset=["gdp", "corporate_profits"]).copy()
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute corporate profit share due to missing data.",
            )
        df = df.sort_values("data_start_date")
        df["profit_share_pct"] = (df["corporate_profits"].astype(float) / df["gdp"].astype(float)) * 100
        df = df.dropna(subset=["profit_share_pct"])
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute corporate profit share due to missing data.",
            )
        latest = df.iloc[-1]
        latest_ratio = float(latest["profit_share_pct"])
        latest_date = latest["data_start_date"].date().isoformat()
        latest_profit = float(latest["corporate_profits"])
        latest_gdp = float(latest["gdp"])
        status = "high" if latest_ratio > 12 else "normal"
        raw_value = (
            f"Corporate profits/GDP: {latest_ratio:.2f}% (profits={latest_profit:,.0f}, GDP={latest_gdp:,.0f})"
        )
        pure_value = [
            {"metric": "corporate_profit_share_pct", "value": latest_ratio, "as_of": latest_date},
            {"metric": "corporate_profits", "value": latest_profit, "as_of": latest_date},
            {"metric": "gdp", "value": latest_gdp, "as_of": latest_date},
        ]
        notes = (
            "Corporate profit share above 12% threshold"
            if status == "high"
            else "Corporate profit share below threshold"
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
