from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from common.utils import naive_utc, naive_utc_from_timestamp, utc_now
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


class SmartVsDumbMoneyIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Smart vs Dumb Money",
        category="Sentiment",
        threshold="> 70",
        markets=["US Market"],
        topics=["Sentiment"],
        description="Uses the CNN Fear & Greed Index as a proxy for \'dumb money\' sentiment. Extreme greed (a high index value) can be a contrarian signal, suggesting retail investors are over-exposed.",
    )
    default_history_days = 365

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        path = resource_fetcher.ensure(
            "CNN-Fear-and-Greed-Index-JSON",
            ttl_days=1,
            filename="cnn_fear_greed.json",
        )
        if path is None:
            return pd.DataFrame()
        return self._parse_json(Path(path).read_text(encoding="utf-8"))

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None):
        return self.collect_full(fetcher)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        df["data_start_date"] = pd.to_datetime(df["as_of"], errors="coerce")
        df = df.dropna(subset=["data_start_date", "fear_greed_index"])
        df = df.sort_values("data_start_date")
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())
        df = df.rename(columns={"fear_greed_index": "index_value"})
        return df[["data_start_date", "data_end_date", "index_value", "rating"]]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="CNN Fear & Greed dataset empty.",
            )
        latest = clean_df.iloc[-1]
        latest_value = float(latest["index_value"])
        latest_date = latest["data_start_date"].isoformat()
        status = "high" if latest_value >= 70 else "normal"
        notes = (
            "Dumb money confidence very high (index >= 70)"
            if status == "high"
            else "Fear & Greed index below exuberance threshold"
        )
        pure_value = [
            {"metric": "fear_greed_index", "value": latest_value, "as_of": latest_date},
            {"metric": "rating", "value": latest.get("rating")},
        ]
        return self.build_result(
            raw_value=f"Fear & Greed index: {latest_value:.1f} (as of {latest_date})",
            pure_value=pure_value,
            status=status,
            notes=notes,
        )

    def _parse_json(self, text: str) -> pd.DataFrame:
        data = json.loads(text)
        if "fear_and_greed" in data:
            latest_entry = data["fear_and_greed"]
            latest_ts = latest_entry.get("timestamp")
            if latest_ts:
                latest_dt = naive_utc(
                    datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
                )
            else:
                latest_dt = utc_now()
            rows = self._collect_historical(data)
            rows.append({
                "as_of": latest_dt,
                "fear_greed_index": latest_entry.get("score"),
                "rating": latest_entry.get("rating"),
            })
            return pd.DataFrame(rows)
        if "data" in data:
            series_list = list(data["data"].values())
            if not series_list or "series" not in series_list[0]:
                return pd.DataFrame()
            primary_series = series_list[0]["series"][0]
            rows = [
                {
                    "as_of": naive_utc(datetime.fromisoformat(date)),
                    "fear_greed_index": float(value),
                    "rating": None,
                }
                for date, value in primary_series
            ]
            return pd.DataFrame(rows)
        return pd.DataFrame()

    def _collect_historical(self, payload: dict) -> List[dict]:
        rows: List[dict] = []
        historical = payload.get("fear_and_greed_historical", {})
        data = historical.get("data", [])
        for item in data:
            timestamp_ms = item.get("x")
            value = item.get("y")
            rating = item.get("rating")
            if timestamp_ms is None or value is None:
                continue
            rows.append({
                "as_of": naive_utc_from_timestamp(timestamp_ms / 1000),
                "fear_greed_index": float(value),
                "rating": rating,
            })
        return rows
