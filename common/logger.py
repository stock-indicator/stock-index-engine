from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from common.settings import settings

_LOGGER_INITIALIZED = False


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

    fmt = cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    datefmt = cfg.get("datefmt", "%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on successive setup calls
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _LOGGER_INITIALIZED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
