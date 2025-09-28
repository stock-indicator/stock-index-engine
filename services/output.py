from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from common.config import OUTPUT_DIR
from common.logger import get_logger
from common.models import IndicatorResult
from common.utils import sanitize_column_name
from services.models import IndicatorRun


logger = get_logger("services.output")
LATEST_JSON_PATH = OUTPUT_DIR / "market_status.latest.json"
LOG_CSV_PATH = OUTPUT_DIR / "market_indicator_log.csv"


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
    LATEST_JSON_PATH.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    logger.info("Wrote latest run snapshot to %s", LATEST_JSON_PATH)
    return LATEST_JSON_PATH


def _build_log_row(run: IndicatorRun) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "date": run.generated_at.date().isoformat(),
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "mode": run.mode,
        "triggered_available": run.summary.get("triggered_available"),
        "total_available": run.summary.get("total_available"),
        "triggered_total": run.summary.get("triggered_total"),
        "total_total": run.summary.get("total_total"),
    }
    for result in run.results:
        market_path = "__".join(result.markets) if result.markets else "unknown"
        column_name = sanitize_column_name(f"{market_path}_{result.name}")
        row[column_name] = result.status
    return row


def update_history_log(run: IndicatorRun) -> Path:
    row = _build_log_row(run)
    if LOG_CSV_PATH.exists():
        existing = pd.read_csv(LOG_CSV_PATH)
        if "date" in existing.columns:
            existing = existing[existing["date"] != row["date"]]
        updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True, sort=False)
    else:
        updated = pd.DataFrame([row])
    updated = updated.sort_values("date")
    updated.to_csv(LOG_CSV_PATH, index=False)
    logger.info("Updated history log at %s", LOG_CSV_PATH)
    return LOG_CSV_PATH


def persist_run(run: IndicatorRun) -> None:
    write_latest_run(run)
    update_history_log(run)


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
