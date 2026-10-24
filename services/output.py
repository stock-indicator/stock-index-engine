from __future__ import annotations

import json
import threading
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from common.config import OUTPUT_DIR
from common.logger import get_logger
from common.models import IndicatorResult
from common.utils import sanitize_column_name, write_text_atomic
from services.models import IndicatorRun
from services.summary import build_summary


logger = get_logger("services.output")
LATEST_JSON_PATH = OUTPUT_DIR / "market_status.latest.json"
LOG_CSV_PATH = OUTPUT_DIR / "market_indicator_log.csv"

_RESULT_FIELDS = {f.name for f in fields(IndicatorResult)}
# Serializes the read-merge-write in persist_run between threads of one process
# (scheduler and POST /refresh share the API process). Writes stay atomic across
# processes, but two processes finishing in the same instant can still lose one update.
_PERSIST_LOCK = threading.Lock()


def sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def write_latest_run(run: IndicatorRun) -> Path:
    payload = {
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "mode": run.mode,
        "summary": run.summary,
        "indicators": [asdict(result) for result in run.results],
    }
    sanitized = sanitize_for_json(payload)
    write_text_atomic(LATEST_JSON_PATH, json.dumps(sanitized, indent=2))
    logger.info("Wrote latest run snapshot to %s", LATEST_JSON_PATH)
    return LATEST_JSON_PATH


def _build_log_row(run: IndicatorRun, results: List[IndicatorResult]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "date": run.generated_at.date().isoformat(),
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "mode": run.mode,
        "triggered_available": run.summary.get("triggered_available"),
        "total_available": run.summary.get("total_available"),
        "triggered_total": run.summary.get("triggered_total"),
        "total_total": run.summary.get("total_total"),
    }
    for result in results:
        market_path = "__".join(result.markets) if result.markets else "unknown"
        column_name = sanitize_column_name(f"{market_path}_{result.name}")
        row[column_name] = result.status
    return row


def update_history_log(
    run: IndicatorRun, *, refreshed: Optional[List[IndicatorResult]] = None
) -> Path:
    """Upsert the log row for ``run``'s date.

    ``run`` carries the aggregate columns. ``refreshed`` is set for a partial
    refresh: only those indicators' status columns are written, and the rest of
    that day's existing row is kept instead of being replaced.
    """
    row = _build_log_row(run, run.results if refreshed is None else refreshed)
    if LOG_CSV_PATH.exists():
        existing = pd.read_csv(LOG_CSV_PATH)
        if "date" in existing.columns:
            if refreshed is not None:
                same_day = existing[existing["date"] == row["date"]]
                if not same_day.empty:
                    row = {**same_day.iloc[-1].dropna().to_dict(), **row}
            existing = existing[existing["date"] != row["date"]]
        updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True, sort=False)
    else:
        updated = pd.DataFrame([row])
    updated = updated.sort_values("date")
    write_text_atomic(LOG_CSV_PATH, updated.to_csv(index=False))
    logger.info("Updated history log at %s", LOG_CSV_PATH)
    return LOG_CSV_PATH


def _stamp(results: List[IndicatorResult], generated_at: datetime) -> List[IndicatorResult]:
    stamp = generated_at.isoformat(timespec="seconds")
    return [replace(result, updated_at=stamp) for result in results]


def _load_previous_results() -> List[IndicatorResult]:
    """Readings from the current snapshot, each carrying its own ``updated_at``.

    Snapshots written before per-record timestamps existed have none; every
    entry in them was produced by the run that wrote the file, so they inherit
    its ``generated_at``.
    """
    payload = read_latest_payload()
    if not payload:
        return []
    written_at = payload.get("generated_at")
    results: List[IndicatorResult] = []
    for item in payload.get("indicators", []):
        try:
            result = IndicatorResult(**{k: v for k, v in item.items() if k in _RESULT_FIELDS})
        except (AttributeError, TypeError):
            logger.warning("Dropping unreadable entry from previous snapshot: %r", item)
            continue
        if not result.updated_at:
            result.updated_at = written_at
        results.append(result)
    return results


def _merge_into_snapshot(run: IndicatorRun) -> IndicatorRun:
    """Overlay a partial run on the current snapshot and recompute the summary.

    Entries are matched by indicator name. Replaced entries keep their position,
    new ones are appended, and untouched ones are carried over as they were.
    """
    fresh = {result.name: result for result in _stamp(run.results, run.generated_at)}
    previous = _load_previous_results()
    if not previous:
        logger.warning(
            "No previous snapshot to merge into; the snapshot will hold only the %d refreshed "
            "indicator(s) until the next complete refresh",
            len(fresh),
        )
    merged = [fresh.pop(old.name, old) for old in previous]
    merged.extend(fresh.values())
    return replace(run, results=merged, summary=build_summary(merged))


def persist_run(run: IndicatorRun, *, partial: bool = False) -> IndicatorRun:
    """Write ``run`` to the latest snapshot and the history log.

    A complete run replaces the snapshot. A ``partial`` run (a single-indicator
    refresh) only replaces its own entries; the rest keep their previous
    reading and timestamp. Returns the run as persisted, whose results and
    summary cover the whole snapshot.
    """
    with _PERSIST_LOCK:
        if partial:
            snapshot = _merge_into_snapshot(run)
        else:
            snapshot = replace(run, results=_stamp(run.results, run.generated_at))
        write_latest_run(snapshot)
        update_history_log(snapshot, refreshed=run.results if partial else None)
    return snapshot


def read_latest_payload() -> Optional[Dict[str, Any]]:
    if not LATEST_JSON_PATH.exists():
        return None
    try:
        return json.loads(LATEST_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover
        logger.warning("Failed to read latest payload: %s", exc)
        return None


def read_latest_run() -> Optional[IndicatorRun]:
    payload = read_latest_payload()
    if not payload:
        return None
    try:
        generated_at = datetime.fromisoformat(payload["generated_at"]).astimezone(UTC)
    except (KeyError, ValueError):
        generated_at = datetime.now(UTC)
    mode = payload.get("mode", "manual")
    indicators_payload = payload.get("indicators", [])
    results = [IndicatorResult(**item) for item in indicators_payload]
    summary = payload.get("summary", {})
    return IndicatorRun(
        generated_at=generated_at,
        mode=mode,
        results=results,
        summary=summary,
    )


def serialize_indicator_result(result: IndicatorResult) -> Dict[str, Any]:
    return sanitize_for_json(asdict(result))


def serialize_run(run: IndicatorRun) -> Dict[str, Any]:
    payload = {
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "mode": run.mode,
        "summary": run.summary,
        "indicators": [serialize_indicator_result(r) for r in run.results],
    }
    return sanitize_for_json(payload)
