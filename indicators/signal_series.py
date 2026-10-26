from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from common.models import IndicatorResult
from common.utils import utc_now
from indicators.base import BaseIndicator, clip_to_window, compute_end_date


class SignalSeriesIndicator(BaseIndicator):
    """An indicator read from one numeric column against a high and a low band.

    ``high`` marks an overheated market (stretched valuations, complacency,
    overbought breadth) and ``low`` a washed-out one (cheap valuations,
    panic, oversold breadth). Each band is a bound in one direction, e.g.
    ``high_above = 80`` and ``low_below = 20``; leave a band unset to drop it.

    Subclasses implement ``collect_full`` returning a DataFrame with a
    ``date`` column, ``value_column`` and any ``detail_columns``. Sources are
    re-read in full every run and merged over the stored rows, so a failed
    download keeps the stored history and a longer download backfills it.
    """

    value_column: str = "value"
    detail_columns: List[str] = []
    high_above: Optional[float] = None
    high_below: Optional[float] = None
    low_above: Optional[float] = None
    low_below: Optional[float] = None
    unit: str = ""
    decimals: int = 2
    # The reading is reported unavailable once its newest observation is older
    # than this, so a broken source cannot pass a frozen value off as current.
    stale_after_days: Optional[int] = None
    high_note: str = ""
    low_note: str = ""
    normal_note: str = ""

    # ------------------------------------------------------------------
    # Data lifecycle
    # ------------------------------------------------------------------
    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher: Any) -> Optional[pd.DataFrame]:
        try:
            raw = self.collect_full(fetcher)
        except Exception as exc:  # sources raise a spread of network/parse errors
            self.logger.warning("Download failed; keeping stored history: %s", exc)
            return None
        return None if raw is None or raw.empty else raw

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(columns={"date": "data_start_date"}).copy()
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date", self.value_column])
        # Stable sort: when sources overlap, the one concatenated last wins.
        df = df.sort_values("data_start_date", kind="stable").drop_duplicates("data_start_date", keep="last")
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())
        columns = ["data_start_date", "data_end_date", self.value_column, *self.detail_columns]
        return df[[column for column in columns if column in df.columns]].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def status_for_value(self, value: float) -> Optional[str]:
        if self.high_above is not None and value > self.high_above:
            return "high"
        if self.high_below is not None and value < self.high_below:
            return "high"
        if self.low_above is not None and value > self.low_above:
            return "low"
        if self.low_below is not None and value < self.low_below:
            return "low"
        return "normal"

    def format_value(self, value: float) -> str:
        return f"{value:,.{self.decimals}f}{self.unit}"

    def compute(self, clean_df: pd.DataFrame, fetcher: Any) -> IndicatorResult:
        if clean_df is None or clean_df.empty or self.value_column not in clean_df.columns:
            return self.build_result(status="unavailable", notes="No data collected yet.")
        df = clean_df.dropna(subset=[self.value_column]).sort_values("data_start_date")
        if df.empty:
            return self.build_result(status="unavailable", notes="No data collected yet.")
        latest = df.iloc[-1]
        value = float(latest[self.value_column])
        as_of = pd.Timestamp(latest["data_start_date"]).date()
        pure_value: List[Dict[str, object]] = [
            {"metric": self.value_column, "value": value, "as_of": as_of.isoformat()}
        ]
        for column in self.detail_columns:
            detail = _to_python(latest.get(column))
            if detail is not None:
                pure_value.append({"metric": column, "value": detail})
        raw_value = f"{self.format_value(value)} (as of {as_of.isoformat()})"
        age_days = (utc_now().date() - as_of).days
        if self.stale_after_days is not None and age_days > self.stale_after_days:
            return self.build_result(
                status="unavailable",
                raw_value=raw_value,
                pure_value=pure_value,
                notes=f"No new data since {as_of.isoformat()}; the source may be down.",
            )
        status = self.status_for_value(value) or "normal"
        notes = {"high": self.high_note, "low": self.low_note}.get(status, self.normal_note)
        return self.build_result(status=status, raw_value=raw_value, pure_value=pure_value, notes=notes)

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: Optional[int],
    ) -> Optional[List[Dict[str, object]]]:
        df = clean_df.dropna(subset=[self.value_column]).set_index("data_start_date").sort_index()
        df = clip_to_window(df, as_of, lookback_days)
        columns = [column for column in [self.value_column, *self.detail_columns] if column in df.columns]
        history: List[Dict[str, object]] = []
        for ts, row in df[columns].iterrows():
            date_key = ts.date().isoformat()
            details = {column: _to_python(row[column]) for column in columns}
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": details[self.value_column],
                    "details": {key: value for key, value in details.items() if value is not None},
                }
            )
        return history


class TradingViewSeriesIndicator(SignalSeriesIndicator):
    """A signal series read from the daily closes of one TradingView symbol."""

    symbol: str = ""

    def collect_full(self, fetcher: Any) -> pd.DataFrame:
        bars = fetcher.get_tradingview_bars(self.symbol)
        return pd.DataFrame({"date": bars["date"], self.value_column: bars["close"].astype(float)})


def _to_python(value: Any) -> Any:
    """Plain JSON-friendly value, or ``None`` for missing data."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        # Sources report float noise (18.63999938964844); 6 decimals is
        # beyond any input's precision and keeps history files small.
        return None if pd.isna(value) else round(float(value), 6)
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, str):
        return value
    return None if pd.isna(value) else value
