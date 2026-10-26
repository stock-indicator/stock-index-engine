from __future__ import annotations

import pandas as pd

from indicators.base import IndicatorMetadata
from indicators.signal_series import TradingViewSeriesIndicator

AVERAGE_DAYS = 10


class EquityPutCallRatioIndicator(TradingViewSeriesIndicator):
    slug_override = "equity_put_call_ratio"
    metadata = IndicatorMetadata(
        name="Equity Put/Call Ratio",
        category="Sentiment",
        threshold="High < 0.60 · Low > 1.00 (10-day avg)",
        markets=["US Market"],
        topics=["Sentiment", "Options"],
        description=(
            "CBOE equity-only put volume divided by call volume (TradingView USI:PCCE, from 2007), "
            "averaged over 10 trading days. Few puts per call means traders chase upside without "
            "hedging, a contrarian warning; a spike above 1 shows the fear and hedging demand that "
            "tends to mark lows."
        ),
    )
    symbol = "USI:PCCE"
    value_column = "put_call_10d_avg"
    detail_columns = ["put_call_ratio"]
    high_below = 0.60
    low_above = 1.00
    decimals = 3
    stale_after_days = 7
    high_note = "Call buying far outpaces puts: complacent, one-sided positioning"
    low_note = "Puts outnumber calls: fear and heavy hedging"
    normal_note = "Put/call balance within its usual range"

    def collect_full(self, fetcher) -> pd.DataFrame:
        bars = fetcher.get_tradingview_bars(self.symbol)
        daily = bars.set_index("date")["close"].astype(float)
        frame = pd.DataFrame(
            {
                "put_call_ratio": daily,
                "put_call_10d_avg": daily.rolling(AVERAGE_DAYS, min_periods=AVERAGE_DAYS).mean(),
            }
        )
        frame.index.name = "date"
        return frame.reset_index()
