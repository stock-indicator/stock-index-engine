from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from common.models import IndicatorResult
from common.settings import settings

RESOURCES_DIR = Path("resources")
RAW_DATA_DIR = RESOURCES_DIR / "raw"
CLEAN_DATA_DIR = RESOURCES_DIR / "clean"
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class IndicatorMetadata:
    name: str
    category: str
    threshold: str
    markets: List[str]
    topics: List[str] = field(default_factory=list)


class BaseIndicator(ABC):
    """Base class defining standard data lifecycle for an indicator."""

    metadata: IndicatorMetadata
    default_schedule: str = "0 6 * * *"  # 每天早上六点
    default_history_days: int = 365

    def __init__(self) -> None:
        if not hasattr(self, "metadata"):
            raise ValueError("Indicator subclasses must define 'metadata'.")
        self.metadata = self.metadata  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Paths & identifiers
    # ------------------------------------------------------------------
    @property
    def slug(self) -> str:
        return self._sanitize(self.metadata.name)

    @property
    def raw_storage_dir(self) -> Path:
        path = RAW_DATA_DIR / self.slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def clean_storage_path(self) -> Path:
        path = CLEAN_DATA_DIR / f"{self.slug}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------
    def get_schedule(self) -> str:
        return settings.get_indicator_schedule(self.slug, self.default_schedule)

    def get_history_window_days(self) -> int:
        return settings.get_indicator_history_days(self.slug, self.default_history_days)

    # ------------------------------------------------------------------
    # Core lifecycle
    # ------------------------------------------------------------------
    def ensure_data(self, fetcher: Any) -> pd.DataFrame:
        clean_df = self.load_clean_data()
        if clean_df is None:
            raw_full = self.collect_full(fetcher)
            self._store_raw_snapshot(raw_full, tag="full")
            clean_df = self.clean_data(raw_full)
            self.store_clean_data(clean_df)  # overwrite
        else:
            raw_incremental = self.collect_incremental(clean_df, fetcher)
            if raw_incremental is not None:
                self._store_raw_snapshot(raw_incremental, tag="incremental")
                clean_incremental = self.clean_data(raw_incremental)
                clean_df = self.merge_clean_data(clean_df, clean_incremental)
                self.store_clean_data(clean_df)
        return clean_df

    def evaluate(self, fetcher: Any) -> IndicatorResult:
        clean_df = self.ensure_data(fetcher)
        result = self.compute(clean_df, fetcher)
        result.markets = self.metadata.markets
        result.topics = self.metadata.topics
        return result

    # ------------------------------------------------------------------
    # Abstract methods for subclasses
    # ------------------------------------------------------------------
    @abstractmethod
    def collect_full(self, fetcher: Any) -> Any:
        """Download a full history dataset (>= default history window)."""

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher: Any) -> Optional[Any]:
        """Download incremental updates since the last observation.

        Default implementation returns None (no incremental behaviour).
        """

        return None

    @abstractmethod
    def clean_data(self, raw: Any) -> pd.DataFrame:
        """Transform raw payload into standardized DataFrame."""

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

    def merge_clean_data(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        combined = pd.concat([existing, new], ignore_index=True)
        combined = combined.drop_duplicates(subset="data_start_date", keep="last")
        combined = combined.sort_values("data_start_date")
        return combined.reset_index(drop=True)

    @abstractmethod
    def compute(self, clean_df: pd.DataFrame, fetcher: Any) -> IndicatorResult:
        """Compute the final indicator result from cleaned data."""

    # ------------------------------------------------------------------
    # Data storage helpers
    # ------------------------------------------------------------------
    def store_clean_data(self, df: pd.DataFrame) -> None:
        df_to_store = df.copy()
        for column in ["data_start_date", "data_end_date"]:
            if column in df_to_store.columns:
                df_to_store[column] = pd.to_datetime(df_to_store[column]).dt.strftime("%Y-%m-%d")
        df_to_store.to_csv(self.clean_storage_path, index=False, encoding="utf-8")

    def load_clean_data(self) -> Optional[pd.DataFrame]:
        if not self.clean_storage_path.exists():
            return None
        try:
            df = pd.read_csv(self.clean_storage_path)
        except pd.errors.EmptyDataError:
            return None
        if df.empty:
            return None
        for column in ["data_start_date", "data_end_date"]:
            if column in df.columns:
                df[column] = pd.to_datetime(df[column], errors="coerce")
        return df

    def _store_raw_snapshot(self, data: Any, tag: str) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        if isinstance(data, pd.DataFrame):
            path = self.raw_storage_dir / f"{tag}_{timestamp}.csv"
            data.to_csv(path, index=False)
        elif isinstance(data, (list, dict)):
            path = self.raw_storage_dir / f"{tag}_{timestamp}.json"
            path.write_text(json.dumps(data, default=self._json_default), encoding="utf-8")
        else:
            path = self.raw_storage_dir / f"{tag}_{timestamp}.txt"
            path.write_text(str(data), encoding="utf-8")

    # ------------------------------------------------------------------
    # Optional database hook (placeholder)
    # ------------------------------------------------------------------
    def ingest_to_database(self) -> None:
        """Placeholder for future PostgreSQL ingestion."""

        raise NotImplementedError("Database ingestion not yet implemented.")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize(text: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")

    @staticmethod
    def _json_default(obj: Any) -> Any:
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        return str(obj)


def compute_end_date(index: pd.Index) -> List[pd.Timestamp]:
    """Given a sorted DatetimeIndex, compute interval end dates (exclusive)."""

    dates = pd.to_datetime(index)
    end_dates: List[pd.Timestamp] = []
    for i, start in enumerate(dates):
        if i + 1 < len(dates):
            next_start = dates[i + 1]
            end_dates.append(next_start - pd.Timedelta(days=1))
        else:
            end_dates.append(pd.NaT)
    return end_dates
