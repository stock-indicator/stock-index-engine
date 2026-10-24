import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


def summarize_values(values: Dict[str, float], unit: str = "") -> str:
    parts = [f"{label}: {val:.2f}{unit}" for label, val in values.items()]
    return "; ".join(parts)


def sanitize_column_name(name: str) -> str:
    base = name.lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_")


_REPLACE_ATTEMPTS = 20


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` so readers never observe a partial file.

    The content goes to a sibling temp file first and is then renamed over the
    target. ``text`` is encoded as-is (no newline translation), so callers that
    already control their line endings, like ``DataFrame.to_csv``, keep them.

    On Windows the rename fails with ``PermissionError`` while another process
    has the target open for reading, so it is retried briefly before giving up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(text.encode(encoding))
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(1, _REPLACE_ATTEMPTS + 1):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS:
                    raise
                time.sleep(min(0.025 * attempt, 0.1))
    finally:
        tmp_path.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# Naive-UTC timestamps
#
# The clean-data layer stores naive ``datetime64`` values that are UTC by
# convention. Mixing an aware datetime into the same column makes
# ``pd.to_datetime(..., errors="coerce")`` coerce that row to NaT, which a
# following ``dropna`` silently removes -- the newest reading can vanish
# without an error. So these helpers return *naive* UTC on purpose; do not
# "fix" them to return aware datetimes.
# ----------------------------------------------------------------------
def utc_now() -> datetime:
    """Current time as a naive UTC datetime (replacement for ``utcnow()``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive_utc(value: datetime) -> datetime:
    """Normalize a datetime to naive UTC.

    Aware values are converted to UTC and stripped of tzinfo. Naive values are
    assumed to already be UTC and are returned unchanged.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def naive_utc_from_timestamp(timestamp: float) -> datetime:
    """Naive UTC datetime for a POSIX timestamp (replacement for ``utcfromtimestamp()``)."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
