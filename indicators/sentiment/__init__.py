from .aaii_retail import RetailPositioningIndicator
from .etf_fund_flow import ETFFundFlowIndicator
from .fear_greed import SmartVsDumbMoneyIndicator
from .insider_buy_share import InsiderBuyShareIndicator
from .ipo_activity import IPOActivityIndicator
from .margin_debt import MarginDebtIndicator
from .polymarket_risk import RecessionOddsIndicator
from .put_call_ratio import EquityPutCallRatioIndicator
from .reddit_buzz import RetailBuzzVelocityIndicator
from .stocktwits_sentiment import SocialBullBearIndicator

SENTIMENT_INDICATORS = [
    MarginDebtIndicator(),
    RetailPositioningIndicator(),
    ETFFundFlowIndicator(),
    IPOActivityIndicator(),
    SmartVsDumbMoneyIndicator(),
    InsiderBuyShareIndicator(),
    RetailBuzzVelocityIndicator(),
    SocialBullBearIndicator(),
    RecessionOddsIndicator(),
    EquityPutCallRatioIndicator(),
]
