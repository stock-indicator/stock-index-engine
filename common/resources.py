from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, Optional

import requests

from .config import HTTP_HEADERS

RESOURCE_BASE_DIR = Path("resources/files")
DOWNLOAD_CONFIG = Path("resources/download_url.conf")


class ResourceFetcher:
    """Manage local cached resources with optional auto-download."""

    def __init__(
        self,
        base_dir: Path = RESOURCE_BASE_DIR,
        config_path: Path = DOWNLOAD_CONFIG,
    ) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_path
        self._urls = self._load_urls()

    def _load_urls(self) -> Dict[str, str]:
        urls: Dict[str, str] = {}
        if not self.config_path.exists():
            return urls

        pattern = re.compile(r"^([^#=]+)\s*=\s*\"(.+?)\"\s*$")
        for line in self.config_path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if match:
                key, value = match.groups()
                urls[key.strip()] = value.strip()
        return urls

    def get_url(self, key: str) -> Optional[str]:
        return self._urls.get(key)

    def _latest_file(self, folder: Path, base_filename: str) -> Optional[Path]:
        if not folder.exists():
            return None

        base_path = Path(base_filename)
        stem = base_path.stem
        suffix = base_path.suffix
        dated_pattern = re.compile(rf"^{re.escape(stem)}_(\d{{8}}){re.escape(suffix)}$")

        candidates = list(folder.glob(f"{stem}_*{suffix}"))
        base_file = folder / base_filename
        if base_file.exists():
            candidates.append(base_file)

        if not candidates:
            return None

        def sort_key(path: Path) -> dt.datetime:
            match = dated_pattern.match(path.name)
            if match:
                try:
                    return dt.datetime.strptime(match.group(1), "%Y%m%d")
                except ValueError:
                    pass
            return dt.datetime.utcfromtimestamp(path.stat().st_mtime)

        return max(candidates, key=sort_key)

    def ensure(
        self,
        key: str,
        *,
        ttl_days: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> Optional[Path]:
        url = self.get_url(key)
        if not url:
            return None

        folder = self.base_dir / key
        folder.mkdir(parents=True, exist_ok=True)

        base_filename = filename or Path(url).name
        latest = self._latest_file(folder, base_filename)

        if ttl_days is not None and latest is not None:
            age = dt.datetime.utcnow() - dt.datetime.utcfromtimestamp(latest.stat().st_mtime)
            if age <= dt.timedelta(days=ttl_days):
                return latest
        elif ttl_days is None and latest is not None:
            return latest

        timestamp = dt.datetime.utcnow().strftime("%Y%m%d")
        base_path = Path(base_filename)
        dated_filename = f"{base_path.stem}_{timestamp}{base_path.suffix}"
        target = folder / dated_filename

        if target.exists():
            return target

        try:
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()
        except requests.RequestException:
            return latest if latest is not None else None

        target.write_bytes(response.content)
        return target
