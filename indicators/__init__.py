from .macro import MACRO_INDICATORS
from .placeholders import PLACEHOLDER_INDICATORS
from .sentiment import SENTIMENT_INDICATORS
from .technical import TECHNICAL_INDICATORS
from .valuation import VALUATION_INDICATORS


def _unique_by_name(indicators):
    """Keep the first instance of each indicator name so real implementations win."""
    seen = set()
    unique = []
    for indicator in indicators:
        name = indicator.metadata.name
        if name in seen:
            continue
        seen.add(name)
        unique.append(indicator)
    return unique


ALL_INDICATORS = _unique_by_name([
    *TECHNICAL_INDICATORS,
    *VALUATION_INDICATORS,
    *MACRO_INDICATORS,
    *SENTIMENT_INDICATORS,
    *PLACEHOLDER_INDICATORS,
])
