from .aaii_retail import RetailPositioningIndicator
from .fear_greed import SmartVsDumbMoneyIndicator
from .margin_debt import MarginDebtIndicator

SENTIMENT_INDICATORS = [
    MarginDebtIndicator(),
    RetailPositioningIndicator(),
    SmartVsDumbMoneyIndicator(),
]
