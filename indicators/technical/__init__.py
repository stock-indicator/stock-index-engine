from .annualized_return import AnnualizedReturnIndicator
from .deviation_200dma import Price200DMADeviationIndicator
from .macd_divergence import MACDDivergenceIndicator
from .rsi import RSIIndicator
from .vix import VIXLevelIndicator

TECHNICAL_INDICATORS = [
    RSIIndicator(),
    MACDDivergenceIndicator(),
    Price200DMADeviationIndicator(),
    AnnualizedReturnIndicator(),
    VIXLevelIndicator(),
]
