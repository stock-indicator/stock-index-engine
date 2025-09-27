import re
from typing import Dict


def summarize_values(values: Dict[str, float], unit: str = "") -> str:
    parts = [f"{label}: {val:.2f}{unit}" for label, val in values.items()]
    return "; ".join(parts)


def sanitize_column_name(name: str) -> str:
    base = name.lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_")
