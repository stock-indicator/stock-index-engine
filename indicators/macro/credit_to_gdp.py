from __future__ import annotations

import pandas as pd

from common.fetchers import resource_fetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class CreditToGDPIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Credit-to-GDP",
        category="Macro",
        threshold="> 350%",
        markets=["US Market", "US Economy"],
        topics=["Macro", "Leverage"],
    )

    def evaluate(self, fetcher):  # fetcher unused
        path = resource_fetcher.ensure(
            "BIS-Credit-to-GDP",
            ttl_days=180,
            filename="bis_credit_to_gdp.csv",
        )
        if path is None or not path.exists():
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to download BIS credit-to-GDP data.",
            )

        try:
            df = pd.read_csv(path)
        except Exception as exc:  # pylint: disable=broad-except
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Failed to read BIS credit data: {exc}",
            )

        df = df[(df["BORROWERS_CTY"] == "US") & (df["FREQ"] == "Q")]
        if df.empty or "OBS_VALUE" not in df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No US observations in BIS credit dataset.",
            )

        df = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
        df = df.dropna(subset=["OBS_VALUE"])
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="BIS credit dataset does not contain numeric observations.",
            )

        df["TIME_PERIOD"] = pd.PeriodIndex(df["TIME_PERIOD"], freq="Q").to_timestamp()
        df = df.sort_values("TIME_PERIOD")
        latest_row = df.iloc[-1]
        latest_ratio = float(latest_row["OBS_VALUE"])
        latest_date = latest_row["TIME_PERIOD"].date().isoformat()

        status = "high" if latest_ratio > 350 else "normal"
        raw_value = f"US credit-to-GDP ratio: {latest_ratio:.1f}% (as of {latest_date})"
        notes = (
            "Credit-to-GDP exceeds 350% threshold"
            if status == "high"
            else "Credit-to-GDP below threshold"
        )
        pure_value = [
            {
                "metric": "credit_to_gdp_pct",
                "value": latest_ratio,
                "as_of": latest_date,
            }
        ]
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
