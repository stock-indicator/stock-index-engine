from __future__ import annotations

from indicators.base import IndicatorMetadata
from indicators.signal_series import TradingViewSeriesIndicator


class BaseAbove200DMAIndicator(TradingViewSeriesIndicator):
    value_column = "pct_above_200dma"
    high_above = 80.0
    low_below = 20.0
    unit = "%"
    decimals = 1
    stale_after_days = 7
    high_note = "Over 80% of members above their 200-day average: broad, overbought rally"
    low_note = "Under 20% of members above their 200-day average: washed-out market"
    normal_note = "Breadth between the overbought and washed-out bands"


class SP500Above200DMAIndicator(BaseAbove200DMAIndicator):
    slug_override = "stocks_above_200dma_s_p_500"
    metadata = IndicatorMetadata(
        name="Stocks Above 200DMA (S&P 500)",
        category="Technical",
        threshold="High > 80% · Low < 20%",
        markets=["S&P 500"],
        topics=["Technical", "Breadth"],
        description=(
            "Share of S&P 500 members trading above their own 200-day moving average (TradingView "
            "INDEX:S5TH, from 1990). Above 80% the rally is broad and stretched; below 20% selling "
            "has reached nearly every stock, which is where durable lows tend to form."
        ),
    )
    symbol = "INDEX:S5TH"


class Nasdaq100Above200DMAIndicator(BaseAbove200DMAIndicator):
    slug_override = "stocks_above_200dma_nasdaq_100"
    metadata = IndicatorMetadata(
        name="Stocks Above 200DMA (Nasdaq 100)",
        category="Technical",
        threshold="High > 80% · Low < 20%",
        markets=["Nasdaq 100"],
        topics=["Technical", "Breadth"],
        description=(
            "Share of Nasdaq 100 members trading above their own 200-day moving average (TradingView "
            "INDEX:NDTH, from 2006). A narrow rally, with the index near highs but this reading "
            "falling, shows fewer stocks carrying the market."
        ),
    )
    symbol = "INDEX:NDTH"
