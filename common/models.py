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
    # ISO-8601 time this reading was produced. Stamped when the snapshot is
    # written, and carried over unchanged for indicators a partial refresh skips.
    updated_at: Optional[str] = None
    # The indicator's slug, which names its history file. Snapshots written
    # before this field existed lack it; the API then derives it from the name.
    slug: Optional[str] = None

