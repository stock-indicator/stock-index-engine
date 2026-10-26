from __future__ import annotations

import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, model_validator

from common.logger import get_logger
from common.settings import settings
from common.utils import naive_utc, sanitize_column_name, utc_now
from indicators.sentiment.etf_fund_flow import record_fund_snapshots
from services import get_indicator_by_slug
from services.history import load_and_filter_history
from services.output import read_latest_payload
from services.refresh import full_refresh, manual_refresh


logger = get_logger("services.api")
app = FastAPI(title="Market Indicator Service", version="1.0.0")

# The read endpoints serve public data, so any origin may read them. Nothing
# authenticates with cookies (refresh uses a bearer token), so credentials
# stay off: with "*" origins they would let any site make credentialed calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    access_logger = get_logger("api.access")
    start_time = time.time()

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000

    client = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
    log_dict = {
        "log_type": "access",
        "request": {
            "method": request.method,
            "url": str(request.url),
            "client": client,
            "user_agent": request.headers.get("user-agent", "unknown")
        },
        "response": {
            "status_code": response.status_code
        },
        "duration_ms": process_time
    }
    
    access_logger.info(log_dict)
    
    return response


_scheduler: AsyncIOScheduler | None = None
REFRESH_CRON = os.getenv("REFRESH_CRON", settings.get("refresh.cron", "0 6 * * *"))
API_HOST = settings.get_api_host()
API_PORT = settings.get_api_port()

# POST /refresh can purge caches that cannot be re-downloaded (FINRA now
# answers 403), so only the server's owner may call it: the request must come
# from inside this container (refresh.sh on the host does `docker exec`) and
# carry REFRESH_TOKEN. Without the token the endpoint is off; the scheduler
# still runs.
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "").strip()
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
MIN_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 3650

# QQQ flows come from daily snapshots of Invesco's fund details, so a missed
# snapshot loses that day for good. Taking one every few hours means a restart
# or a transient error at refresh time costs nothing.
FUND_SNAPSHOT_INTERVAL_HOURS = 3
# Let a daily refresh that fires late (busy event loop, container restarting)
# still run instead of being dropped after APScheduler's 1 s default.
REFRESH_MISFIRE_GRACE_SECONDS = 3600
# On startup, catch up if the last refresh is older than this (the container
# was down at the scheduled time).
CATCH_UP_AFTER_HOURS = 26
# /health/data reports stale when the last refresh is older than this.
DATA_MAX_AGE_HOURS = 30

_bearer = HTTPBearer(auto_error=False)
# One refresh at a time: a full refresh deletes cache directories that a
# concurrent run may be reading from.
_refresh_lock = threading.Lock()


def require_refresh_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> None:
    if not REFRESH_TOKEN:
        raise HTTPException(status_code=403, detail="Refresh is disabled on this server")
    # Requests proxied by the frontend arrive from its container, never from
    # loopback, so the public site cannot reach this even with the token.
    if request.client is None or request.client.host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="Refresh is only available on the server")
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(supplied.encode(), REFRESH_TOKEN.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _run_locked(task: Callable[..., object], **kwargs: object) -> None:
    """Run a refresh that already holds ``_refresh_lock``, then release it."""
    try:
        task(**kwargs)
    except Exception as exc:  # pragma: no cover
        logger.exception("Refresh failed: %s", exc)
    finally:
        _refresh_lock.release()


class RefreshRequest(BaseModel):
    mode: Literal["manual", "full"] = "manual"
    # Days of history to export; None exports everything in the clean data.
    lookback_days: Optional[int] = None
    indicator_slug: Optional[str] = None

    @model_validator(mode='before')
    def _validate_indicator(cls, data: Dict[str, object]) -> Dict[str, object]:
        if not isinstance(data, dict):
            return data
        slug = data.get('indicator_slug')
        if isinstance(slug, str):
            cleaned = sanitize_column_name(slug.strip())
            data['indicator_slug'] = cleaned or None
        if data.get('mode') == 'full' and not data.get('indicator_slug'):
            raise ValueError("indicator_slug is required when mode='full'")
        return data

def _enrich_indicator(item: Dict[str, object]) -> Dict[str, object]:
    enriched = dict(item)
    # Results carry their slug; older snapshots did not, so derive it from
    # the name as before (every indicator from then has a matching slug).
    if not enriched.get("slug"):
        enriched["slug"] = sanitize_column_name(str(item.get("name", "")))
    return enriched


def _scheduled_manual_refresh() -> None:
    if not _refresh_lock.acquire(blocking=False):
        logger.warning("Skipping scheduled refresh: another refresh is still running")
        return
    try:
        manual_refresh()
        logger.info("Scheduled manual refresh executed")
    except Exception as exc:  # pragma: no cover
        logger.exception("Scheduled manual refresh failed: %s", exc)
    finally:
        _refresh_lock.release()


def _scheduled_fund_snapshots() -> None:
    try:
        record_fund_snapshots()
    except Exception as exc:  # pragma: no cover
        logger.exception("Fund snapshot failed: %s", exc)


def _last_refresh_at() -> Optional[datetime]:
    payload = read_latest_payload()
    generated_at = payload.get("generated_at") if payload else None
    if not generated_at:
        return None
    try:
        return naive_utc(datetime.fromisoformat(str(generated_at)))
    except ValueError:
        return None


@app.on_event("startup")
async def startup_event() -> None:
    global _scheduler  # pylint: disable=global-statement
    _scheduler = AsyncIOScheduler(timezone="UTC")
    try:
        trigger = CronTrigger.from_crontab(REFRESH_CRON)
    except ValueError:
        logger.warning("Invalid cron expression '%s'; defaulting to 0 6 * * *", REFRESH_CRON)
        trigger = CronTrigger.from_crontab("0 6 * * *")
    _scheduler.add_job(
        _scheduled_manual_refresh,
        trigger,
        id="daily-refresh",
        misfire_grace_time=REFRESH_MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    now = datetime.now(timezone.utc)
    _scheduler.add_job(
        _scheduled_fund_snapshots,
        IntervalTrigger(hours=FUND_SNAPSHOT_INTERVAL_HOURS),
        id="fund-snapshots",
        next_run_time=now,
        coalesce=True,
        max_instances=1,
    )
    last_refresh = _last_refresh_at()
    if last_refresh is None or utc_now() - last_refresh > timedelta(hours=CATCH_UP_AFTER_HOURS):
        logger.warning("Last refresh at %s is overdue; running a catch-up refresh", last_refresh)
        # Give the server a minute to finish starting before the heavy run.
        _scheduler.add_job(_scheduled_manual_refresh, id="catch-up-refresh", next_run_time=now + timedelta(minutes=1))
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


@app.get("/health/data")
def get_data_health(response: Response) -> Dict[str, object]:
    """503 when the daily refresh or the SPY/QQQ flow data has stopped updating.

    Meant for an uptime monitor: /health only says the process is up, which is
    how an outage of the data itself once went unnoticed for months.
    """
    problems: List[str] = []
    last_refresh = _last_refresh_at()
    if last_refresh is None:
        problems.append("no refresh has completed")
    elif utc_now() - last_refresh > timedelta(hours=DATA_MAX_AGE_HOURS):
        problems.append(f"last refresh was at {last_refresh.isoformat(timespec='minutes')} UTC")
    payload = read_latest_payload() or {}
    etf = next(
        (
            item
            for item in map(_enrich_indicator, payload.get("indicators", []))
            if item.get("slug") == "etf_net_inflows_streak"
        ),
        None,
    )
    if etf is None or etf.get("status") == "unavailable":
        problems.append("ETF flows are unavailable")
    else:
        for entry in etf.get("pure_value") or []:
            if isinstance(entry, dict) and entry.get("consecutive_inflow_days") is None:
                problems.append(f"{entry.get('ticker')} flows have no data since {entry.get('last_data_date')}")
    response.status_code = 503 if problems else 200
    return {
        "status": "stale" if problems else "ok",
        "last_refresh": last_refresh.isoformat(timespec="seconds") if last_refresh else None,
        "problems": problems,
    }


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
def get_indicator_history(
    slug: str,
    lookback_days: Optional[int] = Query(None, ge=1, le=36500),
    max_points: Optional[int] = Query(None, ge=10, le=20000),
) -> Dict[str, object]:
    history = load_and_filter_history(slug.lower(), lookback_days, max_points)
    if history is None:
        raise HTTPException(status_code=404, detail=f"History for '{slug}' not available")
    return history


@app.post("/refresh", status_code=202, dependencies=[Depends(require_refresh_token)])
def trigger_refresh(request: RefreshRequest, background_tasks: BackgroundTasks) -> Dict[str, object]:
    mode = request.mode
    lookback_days = request.lookback_days
    if lookback_days is not None:
        lookback_days = min(max(MIN_LOOKBACK_DAYS, lookback_days), MAX_LOOKBACK_DAYS)
    indicator_slug = request.indicator_slug
    if indicator_slug and get_indicator_by_slug(indicator_slug) is None:
        raise HTTPException(status_code=404, detail=f"Indicator '{indicator_slug}' not found")
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A refresh is already running")
    task = manual_refresh if mode == "manual" else full_refresh
    background_tasks.add_task(_run_locked, task, lookback_days=lookback_days, indicator_slug=indicator_slug)
    logger.info("Refresh request accepted (mode=%s, lookback_days=%s, indicator=%s)", mode, lookback_days, indicator_slug or "all")
    return {"status": "accepted", "mode": mode, "lookback_days": lookback_days, "indicator_slug": indicator_slug}


if __name__ == "__main__":
    from uvicorn import run

    run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level=os.getenv('UVICORN_LOG_LEVEL', 'info'),
        access_log=False,  # Disable default access logger
    )