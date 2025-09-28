"""Service-layer utilities for market indicator workflows."""

from indicators import ALL_INDICATORS

INDICATOR_BY_SLUG = {indicator.slug: indicator for indicator in ALL_INDICATORS}

def get_indicator_by_slug(slug: str):
    return INDICATOR_BY_SLUG.get(slug)

__all__ = ["ALL_INDICATORS", "INDICATOR_BY_SLUG", "get_indicator_by_slug"]
