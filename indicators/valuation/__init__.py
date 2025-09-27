from .shiller_cape import ShillerCAPEIndicator
from .sp500_dividend_yield import SP500DividendYieldIndicator
from .sp500_pe import SP500PEIndicator

VALUATION_INDICATORS = [
    SP500PEIndicator(),
    SP500DividendYieldIndicator(),
    ShillerCAPEIndicator(),
]
