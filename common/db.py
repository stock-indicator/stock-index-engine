from __future__ import annotations

import json
from typing import Dict, Optional

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from common.logger import get_logger
from common.settings import settings


logger = get_logger("db")


def get_psql_connection(name: Optional[str] = None) -> Optional[psycopg.Connection]:
    connections = settings.get_psql_connections()
    if not connections:
        return None
    target: Optional[Dict[str, str]] = None
    if name:
        for conn in connections:
            if conn.get("name") == name:
                target = conn
                break
        if target is None:
            # Falling through to connections[0] here would hand back a
            # different database than the caller asked for, and the caller
            # has no way to tell. Writing indicator data to the wrong
            # database is worse than not writing it at all.
            logger.warning(
                "No PostgreSQL connection named %r is configured (have: %s)",
                name,
                ", ".join(repr(c.get("name")) for c in connections) or "none",
            )
            return None
    else:
        target = connections[0]
    password = target.get("password")
    if not password:
        return None
    try:
        return psycopg.connect(
            host=target.get("host"),
            port=int(target.get("port", 5432)),
            dbname=target.get("database"),
            user=target.get("user"),
            password=password,
            row_factory=dict_row,
        )
    except Exception as exc:  # pragma: no cover
        # Postgres is optional: callers treat None as "no database" and fall
        # back to the CSV/JSON files, so an unreachable server is a warning
        # (no traceback), not a failed run.
        logger.warning("Failed to connect to PostgreSQL: %s", exc)
        return None


def upsert_indicator_dataframe(slug: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    conn = get_psql_connection()
    if conn is None:
        return
    table_name = "indicator_timeseries"
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        indicator_slug TEXT NOT NULL,
        data_start_date DATE,
        data_end_date DATE,
        payload JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (indicator_slug, data_start_date)
    )
    """
    try:
        with conn, conn.cursor() as cur:
            cur.execute(create_sql)
            rows = []
            for _, row in df.iterrows():
                start = _to_date(row.get("data_start_date"))
                end = _to_date(row.get("data_end_date"))
                payload = _row_to_payload(row)
                rows.append((slug, start, end, json.dumps(payload)))
            insert_sql = f"""
            INSERT INTO {table_name} (indicator_slug, data_start_date, data_end_date, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (indicator_slug, data_start_date)
            DO UPDATE SET
                data_end_date = excluded.data_end_date,
                payload = excluded.payload,
                created_at = NOW()
            """
            cur.executemany(insert_sql, rows)
    except Exception:  # pragma: no cover
        # Best-effort sink, same as the connection above: a failed write must
        # not fail the indicator run (the clean CSV is already on disk). A
        # SQL or serialization error is worth a traceback, unlike a connect
        # failure.
        logger.exception("Failed to upsert data for %s", slug)
    finally:
        conn.close()
        logger.debug("Closed database connection for %s", slug)


def _to_date(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"nat", "nan", ""}:
            return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            # An object with a missing or broken isoformat() is not fatal:
            # fall through to pandas parsing below.
            logger.debug("isoformat() failed for %s; falling back to pandas", type(value).__name__)
    try:
        parsed = pd.to_datetime(value)
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
    except Exception:
        # Anything pandas cannot parse is stored as a NULL date rather than
        # failing the whole batch over one malformed cell.
        return None


def _row_to_payload(row: pd.Series) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    for col, value in row.items():
        if col in {"data_start_date", "data_end_date"}:
            continue
        if isinstance(value, pd.Timestamp):
            payload[col] = value.isoformat()
        elif isinstance(value, (pd.Timedelta,)):
            payload[col] = value.total_seconds()
        elif isinstance(value, (pd.Series, pd.DataFrame)):
            payload[col] = value.to_dict()
        elif (
            isinstance(value, (float, int)) and pd.isna(value)
        ) or (
            isinstance(value, str) and value.strip().lower() in {"nat", "nan", ""}
        ):
            payload[col] = None
        else:
            payload[col] = value
    return payload
