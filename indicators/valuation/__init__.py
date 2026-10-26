from .excess_cape_yield import ExcessCAPEYieldIndicator
from .market_cap_ratios import BuffettIndicator, TobinsQIndicator
from .shiller_cape import ShillerCAPEIndicator
from .sp500_dividend_yield import SP500DividendYieldIndicator
from .sp500_pe import SP500PEIndicator
from .sp500_price_to_book import SP500PriceToBookIndicator
from .sp500_price_to_sales import SP500PriceToSalesIndicator

VALUATION_INDICATORS = [
    SP500PEIndicator(),
    SP500DividendYieldIndicator(),
    ShillerCAPEIndicator(),
    SP500PriceToBookIndicator(),
    SP500PriceToSalesIndicator(),
    BuffettIndicator(),
    TobinsQIndicator(),
    ExcessCAPEYieldIndicator(),
]
