from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from common.models import IndicatorResult
from common.social.polymarket import DEFAULT_TOPIC, fetch_polymarket_odds
from indicators.base import IndicatorMetadata

from ._social_base import SnapshotIndicator


class RecessionOddsIndicator(SnapshotIndicator):
    """Market-implied probability of a US recession, from Polymarket."""

    metadata = IndicatorMetadata(
        name="Recession Odds",
        category="Sentiment",
        threshold=">= 35%",
        markets=["US Market"],
        topics=["Sentiment", "Macro"],
        description=(
            "Implied probability of the most-traded open Polymarket contract on a US "
            "recession. Complements the macro indicators rather than repeating them: "
            "FRED series say where the economy is, this says what money is betting "
            "happens next. Live odds only — Polymarket serves no historical vintage, so "
            "this series accumulates forward from first run and cannot be backfilled."
        ),
    )
    default_history_days = 365
    snapshot_columns = ("probability", "volume", "question", "end_date")

    #: Odds at or above which the crowd is pricing real recession risk rather
    #: than background noise.
    TRIGGER_PROBABILITY = 0.35

    #: Below this the crowd is pricing essentially no risk. Worth flagging in
    #: the notes as complacency, but it is not the threshold condition.
    COMPLACENCY_PROBABILITY = 0.10

    def fetch_snapshot(self) -> Dict[str, Any]:
        return fetch_polymarket_odds(topic=DEFAULT_TOPIC)

    def compute(self, clean_df: pd.DataFrame, fetcher: Any = None) -> IndicatorResult:
        if clean_df is None or clean_df.empty:
            return self._unavailable(
                "Polymarket unreachable and no readings stored yet."
            )

        latest = clean_df.iloc[-1]
        probability = float(latest["probability"])
        question = latest.get("question")
        latest_date = latest["data_start_date"]

        pure_value = [
            {"metric": "probability", "value": probability,
             "as_of": latest_date.isoformat()},
            {"metric": "question", "value": question},
            {"metric": "volume", "value": float(latest["volume"])},
            {"metric": "resolves", "value": latest.get("end_date")},
        ]

        if probability >= self.TRIGGER_PROBABILITY:
            status = "high"
            notes = (
                f"Prediction market prices a {probability * 100:.1f}% chance of "
                f"recession — elevated."
            )
        elif probability <= self.COMPLACENCY_PROBABILITY:
            status = "normal"
            notes = (
                f"Prediction market prices only a {probability * 100:.1f}% chance of "
                f"recession. Complacent, but not the overheating condition this "
                f"threshold tracks."
            )
        else:
            status = "normal"
            notes = f"Recession odds moderate at {probability * 100:.1f}%."

        return self.build_result(
            raw_value=(
                f"{probability * 100:.1f}% — {question} (as of {latest_date.date()})"
            ),
            pure_value=pure_value,
            status=status,
            notes=notes + self._staleness_note(latest_date),
        )
