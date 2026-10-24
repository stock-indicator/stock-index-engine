"""Keyless public sentiment sources: Reddit, StockTwits, Polymarket.

Each module exposes a single ``fetch_*`` function returning a plain dict
snapshot of *right now*. None of these endpoints serves a historical vintage,
so the indicators built on them accumulate their series forward from the day
they are first run rather than backfilling. See the module docstrings.
"""

from .http import SourceUnavailable

__all__ = ["SourceUnavailable"]
