import os
from pathlib import Path
from typing import Optional

DEFAULT_KEY_FILES = ["api.key", "keys.txt"]


def load_api_keys(path: Optional[Path] = None) -> None:
    """Populate known API keys from a simple KEY=VALUE file."""

    candidate_paths = []
    if path is not None:
        candidate_paths.append(Path(path))
    else:
        candidate_paths.extend(Path(p) for p in DEFAULT_KEY_FILES)

    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip().upper()
            value = value.strip()
            if not value:
                continue
            if key == "FRED":
                os.environ.setdefault("FRED_API_KEY", value)
            else:
                os.environ.setdefault(key, value)
        break
