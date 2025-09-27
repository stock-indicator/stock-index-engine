from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_SETTINGS_PATH = Path("settings.json")


class Settings:
    """Centralized settings utility supporting env overrides and JSON fallback."""

    _instance: Optional["Settings"] = None

    def __init__(self, settings_path: Path = DEFAULT_SETTINGS_PATH) -> None:
        self._settings_path = settings_path
        self._cache: Dict[str, Any] = {}
        if settings_path.exists():
            try:
                self._cache = json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        env_key = key.upper()
        if env_key in os.environ:
            return os.environ[env_key]
        return self._cache.get(key, default)

    def get_dict(self, key: str) -> Dict[str, Any]:
        value = self.get(key, {})
        if isinstance(value, dict):
            return value
        return {}

    def get_indicator_schedule(self, indicator_slug: str, default: str) -> str:
        env_key = f"INDICATOR_{indicator_slug.upper()}_SCHEDULE"
        if env_key in os.environ:
            return os.environ[env_key]
        schedules = self.get_dict("indicator_schedules")
        return schedules.get(indicator_slug, default)

    def get_indicator_history_days(self, indicator_slug: str, default: int) -> int:
        env_key = f"INDICATOR_{indicator_slug.upper()}_HISTORY_DAYS"
        if env_key in os.environ:
            try:
                return int(os.environ[env_key])
            except ValueError:
                return default
        history = self.get_dict("indicator_history_days")
        value = history.get(indicator_slug)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


settings = Settings.instance()
