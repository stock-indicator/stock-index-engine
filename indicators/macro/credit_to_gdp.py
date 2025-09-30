from __future__ import annotations

import pandas as pd

from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


class CreditToGDPIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Credit-to-GDP",
        category="Macro",
        threshold="> 350%",
        markets=["US Market", "US Economy"],
        topics=["Macro", "Leverage"],
        description="Tracks the ratio of total credit to the private non-financial sector relative to Gross Domestic Product (GDP). It is a key measure of economy-wide leverage.",
    )
    default_history_days = 365 * 5  # BIS 数据按季度

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        path = resource_fetcher.ensure(
            "BIS-Credit-to-GDP",
            ttl_days=180,
            filename="bis_credit_to_gdp.csv",
        )
        if path is None or not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None) -> pd.DataFrame:
        return self.collect_full(fetcher)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        df = raw[(raw["BORROWERS_CTY"] == "US") & (raw["FREQ"] == "Q")]
        if df.empty:
            return pd.DataFrame()
        df = df[["TIME_PERIOD", "OBS_VALUE"]].copy()
        df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
        df = df.dropna(subset=["OBS_VALUE"])
        if df.empty:
            return pd.DataFrame()
        df["data_start_date"] = pd.PeriodIndex(df["TIME_PERIOD"], freq="Q").to_timestamp()
        df = df.sort_values("data_start_date")
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())
        df = df.rename(columns={"OBS_VALUE": "credit_to_gdp_pct"})
        df["source"] = "BIS WS_CREDIT_GAP"
        return df[["data_start_date", "data_end_date", "credit_to_gdp_pct", "source"]]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="BIS credit dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_ratio = float(latest["credit_to_gdp_pct"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if latest_ratio > 350 else "normal"
        notes = (
            "Credit-to-GDP exceeds 350% threshold"
            if status == "high"
            else "Credit-to-GDP below threshold"
        )
        pure_value = [
            {"metric": "credit_to_gdp_pct", "value": latest_ratio, "as_of": latest_date}
        ]
        return self.build_result(
            raw_value=f"US credit-to-GDP ratio: {latest_ratio:.1f}% (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
