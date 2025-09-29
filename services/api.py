from __future__ import annotations

import os
from typing import Any, Dict, List, Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from common.logger import get_logger
from common.settings import settings
from common.utils import sanitize_column_name
from services import get_indicator_by_slug
from services.history import load_indicator_history
from services.output import read_latest_payload
from services.refresh import full_refresh, manual_refresh


logger = get_logger("services.api")
app = FastAPI(title="Market Indicator Service", version="1.0.0")
_scheduler: AsyncIOScheduler | None = None
REFRESH_CRON = os.getenv("REFRESH_CRON", settings.get("refresh.cron", "0 6 * * *"))


class RefreshRequest(BaseModel):
    mode: Literal["manual", "full"] = "manual"
    lookback_days: int = 365


def _enrich_indicator(item: Dict[str, object]) -> Dict[str, object]:
    enriched = dict(item)
    enriched.setdefault("slug", sanitize_column_name(str(item.get("name", ""))))
    return enriched


def _scheduled_manual_refresh() -> None:
    try:
        manual_refresh()
        logger.info("Scheduled manual refresh executed")
    except Exception as exc:  # pragma: no cover
        logger.exception("Scheduled manual refresh failed: %s", exc)


@app.on_event("startup")
async def startup_event() -> None:
    global _scheduler  # pylint: disable=global-statement
    _scheduler = AsyncIOScheduler(timezone="UTC")
    try:
        trigger = CronTrigger.from_crontab(REFRESH_CRON)
    except ValueError:
        logger.warning("Invalid cron expression '%s'; defaulting to 0 6 * * *", REFRESH_CRON)
        trigger = CronTrigger.from_crontab("0 6 * * *")
    _scheduler.add_job(_scheduled_manual_refresh, trigger)
    _scheduler.start()
    logger.info("Scheduler started with cron=%s", trigger)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


@app.get("/health")
def get_health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/summary")
def get_summary() -> Dict[str, object]:
    payload = read_latest_payload()
    if not payload:
        raise HTTPException(status_code=404, detail="No indicator run available")
    return {
        "generated_at": payload.get("generated_at"),
        "mode": payload.get("mode", "manual"),
        "summary": payload.get("summary", {}),
    }


@app.get("/indicators")
def list_indicators() -> Dict[str, Any]:
    payload = read_latest_payload()
    if not payload:
        raise HTTPException(status_code=404, detail="No indicator run available")
    indicators = [_enrich_indicator(item) for item in payload.get("indicators", [])]
    return {"generated_at": payload.get("generated_at"), "indicators": indicators}


@app.get("/indicators/{slug}")
def get_indicator(slug: str) -> Dict[str, object]:
    payload = read_latest_payload()
    if not payload:
        raise HTTPException(status_code=404, detail="No indicator run available")
    target_slug = slug.lower()
    for item in payload.get("indicators", []):
        enriched = _enrich_indicator(item)
        if enriched.get("slug") == target_slug:
            return enriched
    indicator = get_indicator_by_slug(target_slug)
    if indicator is None:
        raise HTTPException(status_code=404, detail=f"Indicator '{slug}' not found")
    raise HTTPException(status_code=404, detail=f"Indicator '{slug}' has no recorded run")


@app.get("/indicators/{slug}/history")
def get_indicator_history(slug: str) -> Dict[str, object]:
    history = load_indicator_history(slug.lower())
    if history is None:
        raise HTTPException(status_code=404, detail=f"History for '{slug}' not available")
    return history


@app.post("/refresh", status_code=202)
def trigger_refresh(request: RefreshRequest, background_tasks: BackgroundTasks) -> Dict[str, object]:
    mode = request.mode
    lookback_days = max(30, request.lookback_days)
    if mode == "manual":
        background_tasks.add_task(manual_refresh, lookback_days=lookback_days)
    else:
        background_tasks.add_task(full_refresh, lookback_days=lookback_days)
    logger.info("Refresh request accepted (mode=%s, lookback_days=%s)", mode, lookback_days)
    return {"status": "accepted", "mode": mode, "lookback_days": lookback_days}


