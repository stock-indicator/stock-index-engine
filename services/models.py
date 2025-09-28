from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from common.models import IndicatorResult


@dataclass
class IndicatorRun:
    """Container describing a completed indicator evaluation cycle."""

    generated_at: datetime
    mode: str
    results: List[IndicatorResult]
    summary: Dict[str, Any]
