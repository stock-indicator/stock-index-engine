from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from common.api_keys import load_api_keys
from common.config import OUTPUT_DIR
from common.fetchers import MarketDataFetcher
from common.logger import get_logger
from common.utils import utc_now

from services import ALL_INDICATORS
from services.evaluator import evaluate_indicators
from services.history import generate_indicator_histories
from services.models import IndicatorRun
from services.output import persist_run


logger = get_logger("services.refresh")
RESOURCES_RAW_DIR = Path("resources/raw")
RESOURCES_CLEAN_DIR = Path("resources/clean")
RESOURCES_FILE_CACHE_DIR = Path("resources/files")


def _backup_clean_file(clean_path: Path) -> None:
    timestamp = utc_now().strftime('%Y%m%dT%H%M%S')
    backup_name = '{}.bak{}'.format(clean_path.name, timestamp)
    backup_path = clean_path.with_name(backup_name)
    clean_path.rename(backup_path)
    logger.info('Backed up clean data file from %s to %s', clean_path, backup_path)


def _clear_indicator_cache(indicator) -> None:
    clean_path = indicator.clean_storage_path
    if clean_path.exists():
        try:
            _backup_clean_file(clean_path)
        except Exception as exc:  # pragma: no cover
            # The backup is a courtesy. A full refresh has to rebuild this
            # file anyway, so a failed backup falls back to deleting it
            # rather than blocking the refresh.
            logger.warning('Failed to backup clean data at %s: %s', clean_path, exc)
            clean_path.unlink(missing_ok=True)
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


def _prepare_indicators(indicators: Iterable, indicator_slug: str | None) -> list:
    indicator_list = list(indicators)
    if indicator_slug is None:
        return indicator_list
    target_slug = indicator_slug.lower()
    selected = [indicator for indicator in indicator_list if indicator.slug == target_slug]
    if not selected:
        raise ValueError(f"Indicator '{indicator_slug}' not found")
    return selected


def _run_cycle(
    *,
    indicators: Iterable,
    fetcher: MarketDataFetcher,
    mode: str,
    regenerate_history: bool,
    lookback_days: int,
) -> IndicatorRun:
    indicators = list(indicators)
    partial = {i.slug for i in indicators} != {i.slug for i in ALL_INDICATORS}
    run = evaluate_indicators(indicators, fetcher=fetcher, mode=mode)
    # A subset run only replaces its own entries; the other indicators keep their
    # last reading and timestamp. The persisted run covers the whole snapshot.
    run = persist_run(run, partial=partial)
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
    indicator_slug: str | None = None,
) -> IndicatorRun:
    """Run incremental refresh using cached resources where possible."""

    indicators = _prepare_indicators(indicators, indicator_slug)
    logger.info("Starting manual refresh for %d indicator(s)", len(indicators))
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
    indicator_slug: str | None = None,
) -> IndicatorRun:
    """Force a full data refresh, replacing existing clean/raw caches for a specific indicator."""

    if indicator_slug is None:
        raise ValueError("indicator_slug is required for full refresh operations")
    indicators = _prepare_indicators(indicators, indicator_slug)
    logger.info("Starting full refresh for %d indicator(s)", len(indicators))
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

