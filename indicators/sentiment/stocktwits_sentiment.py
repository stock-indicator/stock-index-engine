from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from common.models import IndicatorResult
from common.social.stocktwits import DEFAULT_SYMBOLS, fetch_stocktwits_sentiment
from indicators.base import IndicatorMetadata

from ._social_base import SnapshotIndicator


class SocialBullBearIndicator(SnapshotIndicator):
    """Retail bull/bear balance from self-labelled StockTwits messages."""

    metadata = IndicatorMetadata(
        name="Social Bull-Bear Ratio",
        category="Sentiment",
        threshold=">= 0.75",
        markets=["US Market"],
        topics=["Sentiment"],
        description=(
            "Share of self-labelled StockTwits messages on SPY and QQQ tagged Bullish. "
            "Posters label their own messages, so this is a directional sentiment read "
            "with no model in the loop to drift or tune. Retail skews structurally "
            "bullish, so the signal is in the extremes: crowded optimism above 0.75 is a "
            "contrarian warning, and capitulation below 0.30 has historically marked "
            "washout lows."
        ),
    )
    default_history_days = 365
    snapshot_columns = ("bull_ratio", "bullish", "bearish", "labelled", "total")

    #: Crowded-optimism trigger. Retail's resting state on StockTwits sits well
    #: above a neutral 0.50, so the threshold is set where the reading stops
    #: being ordinary enthusiasm.
    EUPHORIA_RATIO = 0.75

    #: Capitulation. Reported in the notes rather than as its own status --
    #: the engine's summary counts only "high" as triggered, so inventing a
    #: third status would drop this indicator out of the available set.
    CAPITULATION_RATIO = 0.30

    def fetch_snapshot(self) -> Dict[str, Any]:
        return fetch_stocktwits_sentiment(symbols=DEFAULT_SYMBOLS)

    def compute(self, clean_df: pd.DataFrame, fetcher: Any = None) -> IndicatorResult:
        if clean_df is None or clean_df.empty:
            return self._unavailable(
                "StockTwits streams unreachable and no readings stored yet."
            )

        latest = clean_df.iloc[-1]
        ratio = float(latest["bull_ratio"])
        bullish = int(latest["bullish"])
        bearish = int(latest["bearish"])
        labelled = int(latest["labelled"])
        latest_date = latest["data_start_date"]

        pure_value = [
            {"metric": "bull_ratio", "value": ratio, "as_of": latest_date.isoformat()},
            {"metric": "bullish", "value": bullish},
            {"metric": "bearish", "value": bearish},
            {"metric": "labelled", "value": labelled},
            {"metric": "percentile_rank",
             "value": self.percentile_rank(clean_df["bull_ratio"], ratio)},
        ]

        if ratio >= self.EUPHORIA_RATIO:
            status = "high"
            notes = (
                f"Retail crowded long: {ratio * 100:.1f}% of {labelled} labelled "
                f"messages are bullish — contrarian warning."
            )
        elif ratio <= self.CAPITULATION_RATIO:
            status = "normal"
            notes = (
                f"Retail capitulation: only {ratio * 100:.1f}% of {labelled} labelled "
                f"messages are bullish. Historically a washout condition, not an "
                f"overheating one, so the threshold is not triggered."
            )
        else:
            status = "normal"
            notes = (
                f"Retail bull/bear balance ordinary at {ratio * 100:.1f}% bullish "
                f"across {labelled} labelled messages."
            )

        return self.build_result(
            raw_value=(
                f"{ratio * 100:.1f}% bullish ({bullish}B/{bearish}S of {labelled} "
                f"labelled, as of {latest_date.date()})"
            ),
            pure_value=pure_value,
            status=status,
            notes=notes + self._staleness_note(latest_date),
        )
