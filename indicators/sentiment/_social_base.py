"""Shared lifecycle for indicators whose source only serves a live reading.

Reddit, StockTwits and Polymarket all answer "what is it right now" and offer
no historical vintage. That breaks the assumption behind ``collect_full`` in
:class:`~indicators.base.BaseIndicator`, which elsewhere downloads a whole
history on first run.

These indicators instead accumulate their own series: every refresh appends
one dated snapshot, and ``merge_clean_data`` (dedupe on ``data_start_date``,
keep last) collapses repeat runs on the same day. The practical consequence
is that a fresh checkout starts with a single data point and the series grows
one row per day from there -- it cannot be backfilled, and
``--lookback-days 365`` will not conjure a year of history for them.

The alternative would be to record today's live reading against past dates,
which would put information into a backtest that nobody could have had at the
time. A short honest series beats a long fabricated one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from common.social.http import SourceUnavailable
from indicators.base import BaseIndicator, compute_end_date


class SnapshotIndicator(BaseIndicator):
    """An indicator fed by one live reading per refresh."""

    #: Columns carried from the snapshot dict into the clean frame, in order.
    #: The first is the indicator's primary value.
    snapshot_columns: tuple = ()

    def fetch_snapshot(self) -> Dict[str, Any]:
        """Return one live reading. Raises SourceUnavailable when it fails."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def collect_full(self, fetcher: Any = None) -> pd.DataFrame:
        try:
            return pd.DataFrame([self.fetch_snapshot()])
        except SourceUnavailable as exc:
            self.logger.warning("Snapshot unavailable on first run: %s", exc)
            return pd.DataFrame()

    def collect_incremental(
        self, existing_clean: pd.DataFrame, fetcher: Any = None
    ) -> Optional[pd.DataFrame]:
        try:
            return pd.DataFrame([self.fetch_snapshot()])
        except SourceUnavailable as exc:
            # None means "no update", which leaves the stored series intact.
            # An outage must not append a row: a reading we failed to take is
            # not a reading of zero, and writing one would turn every network
            # blip into a permanent bearish data point.
            self.logger.warning("Snapshot unavailable; series left unchanged: %s", exc)
            return None

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        # Collapse to date granularity so repeat runs on one day dedupe to the
        # latest reading rather than piling up intraday rows.
        df["data_start_date"] = pd.to_datetime(
            df["as_of"], errors="coerce", utc=True
        ).dt.tz_localize(None).dt.normalize()
        columns = [c for c in self.snapshot_columns if c in df.columns]
        df = df.dropna(subset=["data_start_date", columns[0]] if columns else ["data_start_date"])
        if df.empty:
            return pd.DataFrame()
        df = df.sort_values("data_start_date")
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())
        return df[["data_start_date", "data_end_date", *columns]]

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------
    def _unavailable(self, reason: str):
        return self.build_result(
            raw_value=None,
            pure_value=None,
            status="unavailable",
            notes=reason,
        )

    @staticmethod
    def _staleness_note(latest_date: pd.Timestamp) -> str:
        """A note when the newest stored reading is not from today.

        A stale series means recent refreshes could not reach the source, and
        the headline value is older than it looks.
        """
        age_days = (datetime.now(timezone.utc).date() - latest_date.date()).days
        if age_days <= 1:
            return ""
        return f" Latest reading is {age_days} days old; source may be unreachable."

    @staticmethod
    def percentile_rank(series: pd.Series, value: float) -> Optional[float]:
        """Where ``value`` sits within ``series``, as a 0-1 rank.

        Returns None when the series is too short to rank against. These
        sources have no history to calibrate against on day one, and a
        percentile off five observations is not a percentile.
        """
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if len(clean) < SnapshotIndicator.MIN_HISTORY:
            return None
        return float((clean <= value).sum() / len(clean))

    #: Observations needed before a percentile is meaningful. Roughly a month
    #: of daily readings.
    MIN_HISTORY = 30
