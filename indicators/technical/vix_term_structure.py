from __future__ import annotations

import pandas as pd

from indicators.base import IndicatorMetadata
from indicators.signal_series import SignalSeriesIndicator


class VIXTermStructureIndicator(SignalSeriesIndicator):
    slug_override = "vix_term_structure"
    metadata = IndicatorMetadata(
        name="VIX Term Structure",
        category="Technical",
        threshold="High < 0.80 · Low > 1.00",
        markets=["US Market"],
        topics=["Volatility", "Sentiment"],
        description=(
            "Ratio of 30-day implied volatility (VIX) to 3-month implied volatility (VIX3M), from 2006. "
            "It normally sits below 1. A very low ratio means traders price no near-term risk at all; "
            "above 1 (backwardation) near-term fear exceeds longer-term fear, which marks panics and "
            "has sat near most major lows."
        ),
    )
    value_column = "vix_to_vix3m"
    detail_columns = ["vix", "vix3m"]
    high_below = 0.80
    low_above = 1.00
    decimals = 3
    stale_after_days = 7
    high_note = "Front-month volatility unusually cheap: complacency"
    low_note = "VIX above VIX3M (backwardation): near-term panic"
    normal_note = "Volatility curve in its usual contango"

    def collect_full(self, fetcher) -> pd.DataFrame:
        frame = pd.concat(
            {
                "vix": fetcher.get_price_history("^VIX")["Close"],
                "vix3m": fetcher.get_price_history("^VIX3M")["Close"],
            },
            axis=1,
        ).dropna()
        # yfinance reports 0.0 for some bars; those are gaps, not readings.
        frame = frame[(frame > 0).all(axis=1)]
        frame["vix_to_vix3m"] = frame["vix"] / frame["vix3m"]
        frame.index.name = "date"
        return frame.reset_index()
