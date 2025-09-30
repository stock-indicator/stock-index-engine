from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class IndicatorResult:
    name: str
    category: str
    markets: List[str]
    threshold: str
    status: str
    notes: str
    raw_value: Optional[str] = None
    pure_value: Optional[List[Any]] = None
    topics: List[str] = field(default_factory=list)
    description: Optional[str] = None

