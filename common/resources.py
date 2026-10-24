from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, Optional

import requests

from .config import HTTP_HEADERS
from .logger import get_logger
from .utils import naive_utc_from_timestamp, utc_now

RESOURCE_BASE_DIR = Path("resources/files")
DOWNLOAD_CONFIG = Path("resources/download_url.conf")


LOGGER = get_logger("resources")


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
        self.logger = LOGGER.getChild("fetcher")
        self.logger.debug(
            "Initializing ResourceFetcher (base_dir=%s, config_path=%s)",
            self.base_dir,
            self.config_path,
        )
        self._urls = self._load_urls()

    def _load_urls(self) -> Dict[str, str]:
        urls: Dict[str, str] = {}
        if not self.config_path.exists():
            self.logger.debug("Resource config not found at %s", self.config_path)
            return urls

        pattern = re.compile(r"^([^#=]+)\s*=\s*\"(.+?)\"\s*$")
        for line in self.config_path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if match:
                key, value = match.groups()
                urls[key.strip()] = value.strip()
        self.logger.debug("Loaded %d resource URLs", len(urls))
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
            # Both branches must stay naive UTC: max() compares their results.
            match = dated_pattern.match(path.name)
            if match:
                try:
                    return dt.datetime.strptime(match.group(1), "%Y%m%d")
                except ValueError:
                    pass
            return naive_utc_from_timestamp(path.stat().st_mtime)

        return max(candidates, key=sort_key)

    def ensure(
        self,
        key: str,
        *,
        ttl_days: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> Optional[Path]:
        self.logger.debug(
            "Ensuring resource %s (ttl_days=%s, filename=%s)",
            key,
            ttl_days,
            filename,
        )
        url = self.get_url(key)
        if not url:
            self.logger.warning("No URL configured for resource %s", key)
            return None

        folder = self.base_dir / key
        folder.mkdir(parents=True, exist_ok=True)

        base_filename = filename or Path(url).name
        latest = self._latest_file(folder, base_filename)

        if ttl_days is not None and latest is not None:
            age = utc_now() - naive_utc_from_timestamp(latest.stat().st_mtime)
            if age <= dt.timedelta(days=ttl_days):
                self.logger.info(
                    "Using cached resource %s at %s (age=%s)",
                    key,
                    latest,
                    age,
                )
                return latest
        elif ttl_days is None and latest is not None:
            self.logger.info("Using cached resource %s at %s", key, latest)
            return latest

        timestamp = utc_now().strftime("%Y%m%d")
        base_path = Path(base_filename)
        dated_filename = f"{base_path.stem}_{timestamp}{base_path.suffix}"
        target = folder / dated_filename

        if target.exists():
            self.logger.info("Reusing existing download for resource %s at %s", key, target)
            return target

        try:
            response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.warning("Failed to download resource %s: %s", key, exc)
            if latest is not None:
                self.logger.info("Falling back to cached resource %s at %s", key, latest)
            return latest if latest is not None else None

        target.write_bytes(response.content)
        self.logger.info("Downloaded resource %s to %s", key, target)
        return target
