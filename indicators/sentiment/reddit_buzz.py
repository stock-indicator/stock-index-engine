from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from common.models import IndicatorResult
from common.social.reddit import DEFAULT_SUBREDDITS, fetch_reddit_velocity
from indicators.base import IndicatorMetadata

from ._social_base import SnapshotIndicator


class RetailBuzzVelocityIndicator(SnapshotIndicator):
    """How fast retail is posting about the market, versus its own history."""

    metadata = IndicatorMetadata(
        name="Retail Buzz Velocity",
        category="Sentiment",
        threshold=">= 90th percentile",
        markets=["US Market"],
        topics=["Sentiment"],
        description=(
            "Posting rate across r/wallstreetbets, r/stocks and r/investing, measured from "
            "the public Atom feed. Retail posting velocity spikes into euphoric tops and "
            "panic lows and goes quiet in between, so an extreme reading is a contrarian "
            "warning. Ranked against this indicator's own accumulated history rather than "
            "an absolute post count, because the baseline drifts with Reddit's own traffic."
        ),
    )
    default_history_days = 365
    snapshot_columns = ("posts_per_hour", "sample_size", "span_hours")

    #: Rank at or above which retail chatter counts as extreme.
    TRIGGER_PERCENTILE = 0.90

    def fetch_snapshot(self) -> Dict[str, Any]:
        return fetch_reddit_velocity(subreddits=DEFAULT_SUBREDDITS)

    def compute(self, clean_df: pd.DataFrame, fetcher: Any = None) -> IndicatorResult:
        if clean_df is None or clean_df.empty:
            return self._unavailable(
                "Reddit feed unreachable and no readings stored yet."
            )

        latest = clean_df.iloc[-1]
        velocity = float(latest["posts_per_hour"])
        latest_date = latest["data_start_date"]
        rank = self.percentile_rank(clean_df["posts_per_hour"], velocity)

        pure_value = [
            {"metric": "posts_per_hour", "value": velocity,
             "as_of": latest_date.isoformat()},
            {"metric": "percentile_rank", "value": rank},
            {"metric": "observations", "value": int(len(clean_df))},
        ]
        stale = self._staleness_note(latest_date)

        if rank is None:
            # Observed, just not yet rankable. "normal" keeps it inside the
            # summary's available set instead of reading as a failed fetch.
            return self.build_result(
                raw_value=f"{velocity:.1f} posts/hour (as of {latest_date.date()})",
                pure_value=pure_value,
                status="normal",
                notes=(
                    f"Building baseline: {len(clean_df)} of {self.MIN_HISTORY} readings "
                    f"needed before a percentile is meaningful." + stale
                ),
            )

        status = "high" if rank >= self.TRIGGER_PERCENTILE else "normal"
        notes = (
            f"Retail chatter in the top {(1 - rank) * 100:.0f}% of its own history "
            f"— crowded, contrarian warning."
            if status == "high"
            else f"Retail chatter at the {rank * 100:.0f}th percentile of its own history."
        )
        return self.build_result(
            raw_value=f"{velocity:.1f} posts/hour ({rank * 100:.0f}th pct, as of {latest_date.date()})",
            pure_value=pure_value,
            status=status,
            notes=notes + stale,
        )
