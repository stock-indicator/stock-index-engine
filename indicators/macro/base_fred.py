from __future__ import annotations

from datetime import timedelta
from typing import Dict

import pandas as pd

from common.utils import utc_now
from indicators.base import BaseIndicator, compute_end_date


class FREDIndicator(BaseIndicator):
    required_series: Dict[str, str] = {}
    # Every run re-downloads this window and merges it, so a long window both
    # keeps each series' full history (GS10 from 1953, T10Y2Y from 1976) and
    # backfills an indicator that was built with a shorter one.
    default_history_days = 365 * 100

    def collect_full(self, fetcher) -> pd.DataFrame:
        start = utc_now() - timedelta(days=self.get_history_window_days() + 120)
        combined = None
        for alias, series_id in self.required_series.items():
            series = fetcher.fetch_fred_series(series_id, observation_start=start.strftime("%Y-%m-%d"))
            if series is None or series.empty:
                continue
            series = series.astype(float)
            df = series.to_frame(name=alias)
            combined = df if combined is None else combined.join(df, how="outer")
        if combined is None or combined.empty:
            return pd.DataFrame()
        combined = combined.sort_index()
        combined.index.name = "date"
        return combined.reset_index()

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher):
        # 简化：直接重新抓取全集，merge 时会去重
        return self.collect_full(fetcher)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        df["data_start_date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        df = df.sort_values("data_start_date")
        end_dates = compute_end_date(df["data_start_date"].tolist())
        df["data_end_date"] = end_dates
        return df.drop(columns=["date"])
