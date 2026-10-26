from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata, clip_to_window
from indicators.macro.base_fred import FREDIndicator


class TenYearYieldVsCPIIndicator(FREDIndicator):
    metadata = IndicatorMetadata(
        name="10Y Yield vs CPI",
        category="Macro",
        threshold="10Y < CPI",
        markets=["US Market"],
        topics=["Macro", "Rates"],
        description="Compares the 10-year Treasury yield to the year-over-year Consumer Price Index (CPI). When the yield is below CPI, it indicates negative real rates, which can influence investor behavior.",
    )
    required_series = {
        "ten_year_yield_pct": "GS10",
        "cpi": "CPIAUCSL",
    }

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: Optional[int],
    ) -> Optional[List[Dict[str, object]]]:
        # Plot the real rate (yield minus CPI YoY), which is what the status
        # tests; the generic series would plot the bare 10Y yield.
        df = clean_df.dropna(subset=["ten_year_yield_pct", "cpi"]).set_index("data_start_date").sort_index()
        cpi_yoy = df["cpi"].pct_change(periods=12) * 100
        real = pd.DataFrame({"yield": df["ten_year_yield_pct"], "cpi_yoy": cpi_yoy}).dropna()
        real = clip_to_window(real, as_of, lookback_days)
        history: List[Dict[str, object]] = []
        for ts, row in real.iterrows():
            spread = float(row["yield"] - row["cpi_yoy"])
            history.append(
                {
                    "date": ts.date().isoformat(),
                    "status": status_map.get(ts.date().isoformat()),
                    "summary_value": spread,
                    "details": {
                        "real_rate_pct": spread,
                        "ten_year_yield_pct": float(row["yield"]),
                        "cpi_yoy_pct": float(row["cpi_yoy"]),
                    },
                }
            )
        return history

    def status_for_value(self, value: float) -> Optional[str]:
        return "high" if value < 0 else "normal"

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        if clean_df.empty or "ten_year_yield_pct" not in clean_df.columns or "cpi" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series GS10 or CPIAUCSL unavailable.",
            )
        df = clean_df.dropna(subset=["ten_year_yield_pct", "cpi"]).copy()
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute CPI YoY change.",
            )
        df = df.set_index("data_start_date")
        cpi_yoy = df["cpi"].pct_change(periods=12) * 100
        cpi_yoy = cpi_yoy.dropna()
        if cpi_yoy.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute CPI YoY change (insufficient data).",
            )
        latest_date = cpi_yoy.index[-1]
        latest_cpi_yoy = float(cpi_yoy.iloc[-1])
        ten_year_series = df["ten_year_yield_pct"].astype(float)
        latest_yield = float(ten_year_series.loc[latest_date])
        status = "high" if latest_yield < latest_cpi_yoy else "normal"
        notes = (
            "10Y yield below CPI YoY implies negative real rates"
            if status == "high"
            else "10Y yield above CPI YoY"
        )
        raw_value = (
            f"Yield: {latest_yield:.2f}% ({latest_date.date().isoformat()}); "
            f"CPI YoY: {latest_cpi_yoy:.2f}% ({latest_date.date().isoformat()})"
        )
        pure_value = [
            {"metric": "10Y_yield_pct", "value": latest_yield, "as_of": latest_date.date().isoformat()},
            {"metric": "CPI_yoy_pct", "value": latest_cpi_yoy, "as_of": latest_date.date().isoformat()},
        ]
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
