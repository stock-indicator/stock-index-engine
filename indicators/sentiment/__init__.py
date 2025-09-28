from .aaii_retail import RetailPositioningIndicator
from .etf_fund_flow import ETFFundFlowIndicator
from .fear_greed import SmartVsDumbMoneyIndicator
from .ipo_activity import IPOActivityIndicator
from .margin_debt import MarginDebtIndicator

SENTIMENT_INDICATORS = [
    MarginDebtIndicator(),
    RetailPositioningIndicator(),
    ETFFundFlowIndicator(),
    IPOActivityIndicator(),
    SmartVsDumbMoneyIndicator(),
]
