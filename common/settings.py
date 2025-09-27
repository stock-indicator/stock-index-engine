from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SETTINGS_PATH = Path("settings.json")
VAULT_PATH = Path("vault.key")


class Settings:
    """Centralized settings utility supporting env + JSON + vault secrets."""

    _instance: Optional["Settings"] = None

    def __init__(self, settings_path: Path = DEFAULT_SETTINGS_PATH, vault_path: Path = VAULT_PATH) -> None:
        self._settings_path = settings_path
        self._vault_path = vault_path
        self._cache: Dict[str, Any] = {}
        self._vault: Dict[str, str] = {}
        if settings_path.exists():
            try:
                self._cache = json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}
        if vault_path.exists():
            self._vault = self._load_vault(vault_path)

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        env_key = key.upper()
        if env_key in os.environ:
            return self._resolve(os.environ[env_key])
        value = self._cache.get(key, default)
        return self._resolve(value)

    def get_dict(self, key: str) -> Dict[str, Any]:
        value = self.get(key, {})
        return value if isinstance(value, dict) else {}

    def get_psql_connections(self) -> List[Dict[str, Any]]:
        conns = self.get("psql.connections", [])
        if not isinstance(conns, list):
            return []
        resolved: List[Dict[str, Any]] = []
        for conn in conns:
            if isinstance(conn, dict):
                resolved.append({k: self._resolve(v) for k, v in conn.items()})
        return resolved

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_vault(self, path: Path) -> Dict[str, str]:
        secrets: Dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            secrets[key.strip()] = value.strip()
        return secrets

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("@vault:"):
            secret_key = value[len("@vault:") :]
            return self._vault.get(secret_key, "")
        if isinstance(value, list):
            return [self._resolve(item) for item in value]
        if isinstance(value, dict):
            return {k: self._resolve(v) for k, v in value.items()}
        return value


settings = Settings.instance()
