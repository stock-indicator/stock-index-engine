from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from common.api_keys import load_api_keys
from common.config import OUTPUT_DIR
from common.fetchers import MarketDataFetcher
from common.logger import get_logger

from services import ALL_INDICATORS
from services.evaluator import evaluate_indicators
from services.history import generate_indicator_histories
from services.models import IndicatorRun
from services.output import persist_run


logger = get_logger("services.refresh")
RESOURCES_RAW_DIR = Path("resources/raw")
RESOURCES_CLEAN_DIR = Path("resources/clean")
RESOURCES_FILE_CACHE_DIR = Path("resources/files")


def _clear_indicator_cache(indicator) -> None:
    clean_path = indicator.clean_storage_path
    if clean_path.exists():
        clean_path.unlink()
    raw_dir = indicator.raw_storage_dir
    if raw_dir.exists():
        for child in raw_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


def _clear_global_resource_cache() -> None:
    if RESOURCES_FILE_CACHE_DIR.exists():
        shutil.rmtree(RESOURCES_FILE_CACHE_DIR, ignore_errors=True)
        RESOURCES_FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_directories() -> None:
    RESOURCES_RAW_DIR.mkdir(parents=True, exist_ok=True)
    RESOURCES_CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _run_cycle(
    *,
    indicators: Iterable,
    fetcher: MarketDataFetcher,
    mode: str,
    regenerate_history: bool,
    lookback_days: int,
) -> IndicatorRun:
    run = evaluate_indicators(indicators, fetcher=fetcher, mode=mode)
    persist_run(run)
    if regenerate_history:
        generate_indicator_histories(
            indicators=indicators,
            as_of=run.generated_at,
            lookback_days=lookback_days,
        )
    return run


def manual_refresh(
    *,
    indicators: Iterable = ALL_INDICATORS,
    lookback_days: int = 365,
    regenerate_history: bool = True,
) -> IndicatorRun:
    """Run incremental refresh using cached resources where possible."""

    indicators = list(indicators)
    logger.info("Starting manual refresh for %d indicators", len(indicators))
    load_api_keys()
    _ensure_directories()
    fetcher = MarketDataFetcher()
    run = _run_cycle(
        indicators=indicators,
        fetcher=fetcher,
        mode="manual",
        regenerate_history=regenerate_history,
        lookback_days=lookback_days,
    )
    logger.info(
        "Manual refresh completed at %s with mode=%s",
        run.generated_at.isoformat(timespec="seconds"),
        run.mode,
    )
    return run


def full_refresh(
    *,
    indicators: Iterable = ALL_INDICATORS,
    lookback_days: int = 365,
    regenerate_history: bool = True,
    purge_resource_cache: bool = True,
) -> IndicatorRun:
    """Force a full data refresh, replacing existing clean/raw caches."""

    indicators = list(indicators)
    logger.info("Starting full refresh for %d indicators", len(indicators))
    load_api_keys()
    _ensure_directories()
    for indicator in indicators:
        logger.info("Purging cached data for %s", indicator.metadata.name)
        _clear_indicator_cache(indicator)
    if purge_resource_cache:
        logger.info("Purging shared resource cache under %s", RESOURCES_FILE_CACHE_DIR)
        _clear_global_resource_cache()
    fetcher = MarketDataFetcher()
    run = _run_cycle(
        indicators=indicators,
        fetcher=fetcher,
        mode="full",
        regenerate_history=regenerate_history,
        lookback_days=lookback_days,
    )
    logger.info(
        "Full refresh completed at %s with mode=%s",
        run.generated_at.isoformat(timespec="seconds"),
        run.mode,
    )
    return run
