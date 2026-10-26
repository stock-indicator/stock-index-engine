from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

from common.config import HTTP_HEADERS
from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from common.utils import naive_utc, naive_utc_from_timestamp, utc_now
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date

# CNN's graphdata endpoint serves history from a start date appended to the
# URL, back to the first trading day of 2021; earlier dates return HTTP 500.
BACKFILL_START = pd.Timestamp("2021-01-01")


class SmartVsDumbMoneyIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Smart vs Dumb Money",
        category="Sentiment",
        threshold="High ≥ 70 · Low < 25",
        markets=["US Market"],
        topics=["Sentiment"],
        description="Uses the CNN Fear & Greed Index as a proxy for \'dumb money\' sentiment. Extreme greed (a high index value) can be a contrarian signal, suggesting retail investors are over-exposed; extreme fear (below 25) has tended to come near lows.",
    )
    default_history_days = 365

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        latest = self._collect_latest()
        backfill = self._collect_backfill()
        return pd.concat([backfill, latest], ignore_index=True)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None):
        latest = self._collect_latest()
        earliest = pd.to_datetime(existing_clean["data_start_date"]).min()
        if pd.isna(earliest) or earliest > BACKFILL_START + pd.Timedelta(days=30):
            latest = pd.concat([self._collect_backfill(), latest], ignore_index=True)
        return latest

    def _collect_latest(self) -> pd.DataFrame:
        """The default feed: the latest reading plus about a year of history."""
        path = resource_fetcher.ensure(
            "CNN-Fear-and-Greed-Index-JSON",
            ttl_days=1,
            filename="cnn_fear_greed.json",
        )
        if path is None:
            return pd.DataFrame()
        return self._parse_json(Path(path).read_text(encoding="utf-8"))

    def _collect_backfill(self) -> pd.DataFrame:
        """History since ``BACKFILL_START``, the earliest date CNN serves.

        Only needed until the stored history reaches back that far; the
        default feed covers about a year.
        """
        base_url = resource_fetcher.get_url("CNN-Fear-and-Greed-Index-JSON")
        if not base_url:
            return pd.DataFrame()
        url = f"{base_url.rstrip('/')}/{BACKFILL_START.date().isoformat()}"
        try:
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()
            return self._parse_json(response.text)
        except (requests.RequestException, ValueError) as exc:
            self.logger.warning("Fear & Greed backfill from %s failed: %s", url, exc)
            return pd.DataFrame()

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        # One row per day: the backfill and the default feed overlap, and the
        # live reading is timestamped later on a day that already has a point.
        df["data_start_date"] = pd.to_datetime(df["as_of"], errors="coerce").dt.normalize()
        df = df.dropna(subset=["data_start_date", "fear_greed_index"])
        df = df.sort_values("data_start_date", kind="stable")
        df = df.drop_duplicates(subset="data_start_date", keep="last")
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
        status = self.status_for_value(latest_value)
        notes = {
            "high": "Dumb money confidence very high (index >= 70)",
            "low": "Extreme fear (index < 25)",
        }.get(status, "Fear & Greed index between the fear and greed bands")
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

    def status_for_value(self, value: float) -> Optional[str]:
        if value >= 70:
            return "high"
        if value < 25:
            return "low"
        return "normal"

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
