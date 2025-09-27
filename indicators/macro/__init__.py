from .corporate_profits_vs_gdp import CorporateProfitsToGDPIndicator
from .credit_to_gdp import CreditToGDPIndicator
from .post_hike_window import PostHikeWindowIndicator
from .ten_year_yield_vs_cpi import TenYearYieldVsCPIIndicator
from .yield_curve_duration import YieldCurveDurationIndicator

MACRO_INDICATORS = [
    TenYearYieldVsCPIIndicator(),
    YieldCurveDurationIndicator(),
    PostHikeWindowIndicator(),
    CorporateProfitsToGDPIndicator(),
    CreditToGDPIndicator(),
]
