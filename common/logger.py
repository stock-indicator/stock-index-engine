from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from common.settings import settings

_LOGGER_INITIALIZED = False


class _JsonFormatter(logging.Formatter):
    """Lightweight JSON formatter to avoid external dependency."""

    _RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def __init__(
        self,
        *,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        static_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(datefmt=datefmt)
        self._static_fields = static_fields or {}
        self._field_names = self._extract_fields(fmt) if fmt else []

    @staticmethod
    def _extract_fields(fmt: str) -> Iterable[str]:
        fields: list[str] = []
        cursor = 0
        while True:
            start = fmt.find("%(", cursor)
            if start == -1:
                break
            end = fmt.find(")s", start)
            if end == -1:
                break
            name = fmt[start + 2 : end]
            if name and name not in fields:
                fields.append(name)
            cursor = end + 2
        return fields

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            return {str(k): _JsonFormatter._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_JsonFormatter._to_jsonable(item) for item in value]
        return repr(value)

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self._format_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
        }
        payload.update(self._static_fields)

        # honour explicit fmt tokens when configured
        for field in self._field_names:
            if field == "asctime":
                payload[field] = payload["timestamp"]
            elif hasattr(record, field):
                payload[field] = self._to_jsonable(getattr(record, field))

        if isinstance(record.msg, Mapping):
            payload.update(self._to_jsonable(record.msg))
        else:
            message = record.getMessage()
            if message:
                payload.setdefault("message", message)

        extras = {
            key: self._to_jsonable(value)
            for key, value in record.__dict__.items()
            if key not in self._RESERVED_ATTRS and not key.startswith("_")
        }
        if extras:
            payload.update(extras)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)

    def _format_timestamp(self, record: logging.LogRecord) -> str:
        if self.datefmt:
            return datetime.fromtimestamp(record.created).strftime(self.datefmt)
        return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()


def setup_logging() -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    cfg = settings.get_dict("logging")
    level_name = str(cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_dir = Path(cfg.get("directory", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / cfg.get("filename", "market_indicators.log")

    # Use a JSON formatter, adding a static field for the log type
    fmt = cfg.get("format", "%(asctime)s %(name)s %(levelname)s %(message)s")
    datefmt = cfg.get("datefmt", "%Y-%m-%d %H:%M:%S")
    formatter = _JsonFormatter(
        fmt=fmt,
        datefmt=datefmt,
        static_fields={"log_type": "application"},
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on successive setup calls
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _LOGGER_INITIALIZED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
