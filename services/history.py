from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from common.config import OUTPUT_DIR
from common.db import get_psql_connection
from common.logger import get_logger
from common.utils import sanitize_column_name
from services.output import LOG_CSV_PATH, sanitize_for_json


logger = get_logger("services.history")
HISTORY_DIR = OUTPUT_DIR / "history"


def _strip_source_fields(value):
    if isinstance(value, dict):
        return {k: _strip_source_fields(v) for k, v in value.items() if "source" not in k.lower()}
    if isinstance(value, list):
        return [_strip_source_fields(item) for item in value]
    return value


def _build_alias_map(indicators: Iterable) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for indicator in indicators:
        slug = indicator.slug
        aliases = {slug, sanitize_column_name(indicator.metadata.name)}
        markets = [sanitize_column_name(market) for market in indicator.metadata.markets]
        if markets:
            aliases.add("_".join(markets + [slug]))
            for market_alias in markets:
                aliases.add(f"{market_alias}_{slug}")
        for alias in aliases:
            if alias:
                alias_map[alias] = slug
    return alias_map


def generate_indicator_histories(
    *,
    indicators: Iterable,
    as_of: datetime,
    lookback_days: int,
) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    indicators = list(indicators)
    alias_map = _build_alias_map(indicators)
    status_lookup = _load_status_history(
        as_of=as_of,
        lookback_days=lookback_days,
        alias_map=alias_map,
    )
    for indicator in indicators:
        slug = indicator.slug
        clean_df = indicator.load_clean_data()
        if clean_df is None or clean_df.empty:
            logger.debug("No clean data available for %s; skipping history export", slug)
            continue
        status_map = status_lookup.get(slug, {})
        custom_series = indicator.build_history_series(
            clean_df=clean_df,
            status_map=status_map,
            as_of=as_of,
            lookback_days=lookback_days,
        )
        if custom_series is not None:
            series = _append_status_only_entries(custom_series, status_map)
            series.sort(key=lambda item: item["date"])
        else:
            series = _build_series(
                indicator_slug=slug,
                clean_df=clean_df,
                status_map=status_map,
                as_of=as_of,
                lookback_days=lookback_days,
            )
        payload = {
            "indicator": slug,
            "display_name": indicator.metadata.name,
            "category": indicator.metadata.category,
            "markets": indicator.metadata.markets,
            "topics": indicator.metadata.topics,
            "threshold": indicator.metadata.threshold,
            "updated_at": as_of.isoformat(timespec="seconds"),
            "series": series,
        }
        _write_history_file(slug, payload)
        _upsert_history_to_db(slug, series)


def load_indicator_history(slug: str) -> Optional[Dict[str, object]]:
    path = HISTORY_DIR / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover
        logger.warning("Failed to parse history file %s: %s", path, exc)
        return None


def _write_history_file(slug: str, payload: Dict[str, object]) -> None:
    path = HISTORY_DIR / f"{slug}.json"
    path.write_text(json.dumps(sanitize_for_json(payload), indent=2), encoding="utf-8")
    logger.info("Wrote history series for %s to %s", slug, path)


def _load_status_history(*, as_of: datetime, lookback_days: int, alias_map: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    if not LOG_CSV_PATH.exists():
        return {}
    try:
        df = pd.read_csv(LOG_CSV_PATH)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to read history log: %s", exc)
        return {}
    if df.empty or "date" not in df.columns:
        return {}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    cutoff = (as_of - timedelta(days=lookback_days)).date()
    df = df[df["date"].dt.date >= cutoff]
    status_lookup: Dict[str, Dict[str, str]] = {}
    for column in df.columns:
        if column in {"date", "generated_at", "mode", "triggered_available", "total_available", "triggered_total", "total_total"}:
            continue
        slug = _match_column_to_slug(column, alias_map)
        if not slug:
            continue
        for _, row in df.iterrows():
            date_value = row["date"]
            if pd.isna(date_value):
                continue
            status = row[column]
            if isinstance(status, float) and np.isnan(status):
                continue
            date_key = pd.Timestamp(date_value).date().isoformat()
            status_lookup.setdefault(slug, {})[date_key] = str(status)
    return status_lookup


def _match_column_to_slug(column: str, alias_map: Dict[str, str]) -> Optional[str]:
    normalized = column.strip().lower()
    for alias, slug in alias_map.items():
        if normalized == alias or normalized.endswith(f"_{alias}"):
            return slug
    return None


def _build_series(
    *,
    indicator_slug: str,
    clean_df: pd.DataFrame,
    status_map: Dict[str, str],
    as_of: datetime,
    lookback_days: int,
) -> List[Dict[str, object]]:
    df = clean_df.copy()
    if "data_start_date" in df.columns:
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        cutoff_ts = pd.Timestamp(as_of.date() - timedelta(days=lookback_days))
        upper_ts = pd.Timestamp(as_of.date())
        df = df[(df["data_start_date"] >= cutoff_ts) & (df["data_start_date"] <= upper_ts)]
        df = df.sort_values("data_start_date")
    elif "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        cutoff_ts = pd.Timestamp(as_of.date() - timedelta(days=lookback_days))
        upper_ts = pd.Timestamp(as_of.date())
        df = df[(df["date"] >= cutoff_ts) & (df["date"] <= upper_ts)]
        df = df.sort_values("date")
    else:
        df = df.reset_index(drop=True)
    series: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        date_value = row.get("data_start_date") or row.get("date")
        if pd.isna(date_value):
            continue
        date_ts = pd.Timestamp(date_value)
        if date_ts.date() > as_of.date():
            continue
        date_key = date_ts.date().isoformat()
        details = _row_to_details(row)
        summary_value = _extract_summary_value(details)
        series.append(
            {
                "date": date_key,
                "status": status_map.get(date_key),
                "summary_value": summary_value,
                "details": details,
            }
        )
    details_template = series[-1]["details"].copy() if series else None
    series = _append_status_only_entries(series, status_map, details_template=details_template)
    series.sort(key=lambda item: item["date"])
    return series


def _append_status_only_entries(series: List[Dict[str, object]], status_map: Dict[str, str], *, details_template: Optional[Dict[str, object]] = None) -> List[Dict[str, object]]:
    if not status_map:
        return series
    existing_dates = {item.get("date") for item in series}
    template = details_template or {}
    for status_date, status_value in status_map.items():
        if status_date in existing_dates:
            continue
        details = template.copy() if isinstance(template, dict) else {}
        series.append(
            {"date": status_date, "status": status_value, "summary_value": None, "details": details}
        )
    return series



def _row_to_details(row: pd.Series) -> Dict[str, object]:
    details: Dict[str, object] = {}
    for column, value in row.items():
        if column in {"data_start_date", "data_end_date", "date"}:
            continue
        if isinstance(value, float) and np.isnan(value):
            continue
        if isinstance(value, pd.Timestamp):
            details[column] = value.isoformat()
        elif hasattr(value, "isoformat"):
            try:
                details[column] = value.isoformat()
            except Exception:  # pragma: no cover
                details[column] = str(value)
        else:
            details[column] = value
    return details


def _extract_summary_value(details: Dict[str, object]) -> Optional[float]:
    preferred_keys = [
        "indicator_value",
        "value",
        "score",
        "ratio",
        "deviation_pct",
        "annualized_return_pct",
        "macd",
        "rsi",
        "reading",
    ]
    for key in preferred_keys:
        value = details.get(key)
        numeric = _coerce_numeric(value)
        if numeric is not None:
            return numeric
    for value in details.values():
        numeric = _coerce_numeric(value)
        if numeric is not None:
            return numeric
    return None


def _coerce_numeric(value) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and np.isnan(value):
            return None
        return float(value)
    try:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            if not stripped:
                return None
            return float(stripped)
    except ValueError:
        return None
    return None


def _upsert_history_to_db(slug: str, series: List[Dict[str, object]]) -> None:
    if not series:
        return
    conn = get_psql_connection()
    if conn is None:
        return
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS indicator_history_series (
        indicator_slug TEXT NOT NULL,
        as_of_date DATE NOT NULL,
        status TEXT,
        summary_value DOUBLE PRECISION,
        details JSONB,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (indicator_slug, as_of_date)
    )
    """
    insert_sql = """
    INSERT INTO indicator_history_series (indicator_slug, as_of_date, status, summary_value, details)
    VALUES (%s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (indicator_slug, as_of_date)
    DO UPDATE SET
        status = EXCLUDED.status,
        summary_value = EXCLUDED.summary_value,
        details = EXCLUDED.details,
        updated_at = NOW()
    """
    rows = []
    for item in series:
        stripped_details = _strip_source_fields(item.get("details", {}))
        details_payload = sanitize_for_json(stripped_details)
        rows.append(
            (
                slug,
                item.get("date"),
                item.get("status"),
                _coerce_numeric(item.get("summary_value")),
                json.dumps(details_payload),
            )
        )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(create_table_sql)
            cur.executemany(insert_sql, rows)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to upsert history for %s: %s", slug, exc)
    finally:
        conn.close()

