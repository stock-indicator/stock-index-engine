from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, List

from common.logger import get_logger
from common.models import IndicatorResult
from services.models import IndicatorRun
from services.summary import build_summary


logger = get_logger("services.evaluator")


def _failure_result(indicator, exc: Exception) -> IndicatorResult:
    meta = indicator.metadata
    return IndicatorResult(
        name=meta.name,
        category=meta.category,
        markets=meta.markets,
        threshold=meta.threshold,
        status="unavailable",
        notes=f"Indicator failed: {exc}",
        raw_value=None,
        pure_value=None,
        topics=meta.topics,
        slug=indicator.slug,
    )


def evaluate_indicators(
    indicators: Iterable,
    *,
    fetcher,
    mode: str,
) -> IndicatorRun:
    results: List[IndicatorResult] = []
    for indicator in indicators:
        meta = indicator.metadata
        logger.info(
            "Evaluating indicator '%s' (%s)",
            meta.name,
            indicator.__class__.__name__,
        )
        try:
            result = indicator.evaluate(fetcher)
        except Exception as exc:  # pylint: disable=broad-except
            # Isolate failures per indicator: one broken data source is
            # reported as "unavailable" and must not abort the rest of the run.
            logger.exception("Indicator '%s' failed: %s", meta.name, exc)
            results.append(_failure_result(indicator, exc))
            continue
        if isinstance(result, list):
            for item in result:
                logger.info(
                    "Indicator '%s' completed with status=%s",
                    item.name,
                    item.status,
                )
            results.extend(result)
        else:
            logger.info(
                "Indicator '%s' completed with status=%s",
                result.name,
                result.status,
            )
            results.append(result)
    summary = build_summary(results)
    run = IndicatorRun(
        generated_at=datetime.now(UTC),
        mode=mode,
        results=results,
        summary=summary,
    )
    logger.info(
        "Run complete: total=%s triggered=%s available_total=%s available_triggered=%s",
        summary.get("total_total"),
        summary.get("triggered_total"),
        summary.get("total_available"),
        summary.get("triggered_available"),
    )
    return run
