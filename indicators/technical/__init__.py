from .annualized_return import AnnualizedReturnNasdaqIndicator, AnnualizedReturnSP500Indicator
from .breadth import Nasdaq100Above200DMAIndicator, SP500Above200DMAIndicator
from .deviation_200dma import Price200DMANasdaqIndicator, Price200DMASP500Indicator
from .macd_divergence import MACDNasdaqIndicator, MACDSP500Indicator
from .rsi import RSINasdaq100Indicator, RSISP500Indicator
from .vix import VIXLevelIndicator
from .vix_term_structure import VIXTermStructureIndicator

TECHNICAL_INDICATORS = [
    RSISP500Indicator(),
    RSINasdaq100Indicator(),
    MACDSP500Indicator(),
    MACDNasdaqIndicator(),
    Price200DMASP500Indicator(),
    Price200DMANasdaqIndicator(),
    AnnualizedReturnSP500Indicator(),
    AnnualizedReturnNasdaqIndicator(),
    VIXLevelIndicator(),
    VIXTermStructureIndicator(),
    SP500Above200DMAIndicator(),
    Nasdaq100Above200DMAIndicator(),
]
