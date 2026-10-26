from __future__ import annotations

import pandas as pd

from common.tradingview import TradingViewError
from indicators.base import IndicatorMetadata
from indicators.signal_series import SignalSeriesIndicator

SERIES_ID = "BAMLH0A0HYM2"


class HighYieldSpreadIndicator(SignalSeriesIndicator):
    slug_override = "high_yield_spread"
    metadata = IndicatorMetadata(
        name="High-Yield Credit Spread",
        category="Macro",
        threshold="High < 3.0% · Low > 7.0%",
        markets=["US Market"],
        topics=["Macro", "Credit"],
        description=(
            "ICE BofA US High Yield option-adjusted spread over Treasuries, from 1996. Spreads this "
            "tight mean lenders charge almost nothing for default risk, a late-cycle sign of "
            "complacency; above 7% credit is under stress, as it was at every major equity low "
            "since 1996."
        ),
    )
    value_column = "hy_oas_pct"
    high_below = 3.0
    low_above = 7.0
    unit = "%"
    decimals = 2
    stale_after_days = 10
    high_note = "Junk-bond spreads near record tights: credit priced for perfection"
    low_note = "Junk-bond spreads above 7%: credit stress"
    normal_note = "Junk-bond spreads within their usual range"

    def collect_full(self, fetcher) -> pd.DataFrame:
        # FRED's API serves only the last three years of ICE series, so the
        # history comes from TradingView's mirror of the same FRED series.
        # FRED's own rows go last and win on overlapping dates.
        frames = []
        try:
            bars = fetcher.get_tradingview_bars(f"FRED:{SERIES_ID}")
            frames.append(pd.DataFrame({"date": bars["date"], self.value_column: bars["close"]}))
        except TradingViewError as exc:
            self.logger.warning("TradingView history unavailable, using FRED's recent data only: %s", exc)
        recent = fetcher.fetch_fred_series(SERIES_ID)
        if recent is not None and not recent.empty:
            frames.append(pd.DataFrame({"date": recent.index, self.value_column: recent.values}))
        if not frames:
            raise RuntimeError("Neither TradingView nor FRED returned high-yield spreads")
        return pd.concat(frames, ignore_index=True)
