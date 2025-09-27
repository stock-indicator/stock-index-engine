from __future__ import annotations

import pandas as pd

from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


class RetailPositioningIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Retail Positioning",
        category="Sentiment",
        threshold="> 70%",
        markets=["US Market"],
        topics=["Sentiment", "AAII"],
    )
    default_history_days = 365 * 3

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        path = resource_fetcher.ensure(
            "AAII-Sentiment-Survey",
            ttl_days=7,
            filename="sentiment.xls",
        )
        if path is None or not path.exists():
            return pd.DataFrame()
        return pd.read_excel(path, header=3)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None):
        return self.collect_full(fetcher)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(columns={"Date": "data_start_date"})
        required = ["data_start_date", "Bullish"]
        if not all(col in df.columns for col in required):
            return pd.DataFrame()
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date", "Bullish"])
        df = df.sort_values("data_start_date")
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())

        for col in ["Bullish", "Neutral", "Bearish"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                df[col] = df[col].apply(self._to_percent)

        columns = ["data_start_date", "data_end_date", "Bullish", "Neutral", "Bearish"]
        available = [col for col in columns if col in df.columns]
        return df[available]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty or "Bullish" not in clean_df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="AAII sentiment dataset empty.",
            )
        latest = clean_df.dropna(subset=["Bullish"]).iloc[-1]
        bullish_pct = float(latest["Bullish"])
        latest_date = latest["data_start_date"].date().isoformat()
        status = "high" if bullish_pct >= 70 else "normal"
        pure_value = [
            {"metric": "bullish_pct", "value": bullish_pct, "as_of": latest_date}
        ]
        for col in ["Neutral", "Bearish"]:
            if col in clean_df.columns and not pd.isna(latest.get(col)):
                pure_value.append({"metric": f"{col.lower()}_pct", "value": float(latest[col]), "as_of": latest_date})
        notes = (
            "Retail bullish sentiment extremely high"
            if status == "high"
            else "Retail bullish sentiment below 70% threshold"
        )
        return self.build_result(
            raw_value=f"AAII bullish: {bullish_pct:.1f}% (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes=notes,
        )

    @staticmethod
    def _to_percent(value: float) -> float:
        if pd.isna(value):
            return float("nan")
        value = float(value)
        return value * 100 if value <= 1 else value
