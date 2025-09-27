from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

from common.models import IndicatorResult


@dataclass
class IndicatorMetadata:
    name: str
    category: str
    threshold: str
    markets: List[str]
    topics: List[str] = field(default_factory=list)


class BaseIndicator(ABC):
    """Abstract base class for all indicators."""

    metadata: IndicatorMetadata

    def __init__(self) -> None:
        if not hasattr(self, "metadata"):
            raise ValueError("Indicator subclasses must define 'metadata'.")

    @abstractmethod
    def evaluate(self, fetcher) -> IndicatorResult:
        """Produce the indicator result."""

    def build_result(
        self,
        *,
        status: str,
        notes: str,
        raw_value: Optional[str] = None,
        pure_value: Optional[List[Any]] = None,
        markets: Optional[List[str]] = None,
        threshold: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> IndicatorResult:
        meta = self.metadata
        return IndicatorResult(
            name=meta.name,
            category=meta.category,
            markets=markets or meta.markets,
            threshold=threshold or meta.threshold,
            status=status,
            notes=notes,
            raw_value=raw_value,
            pure_value=pure_value,
            topics=topics if topics is not None else meta.topics,
        )
