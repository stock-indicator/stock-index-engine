from __future__ import annotations

from typing import Dict, List

from common.models import IndicatorResult

# "high" flags an overheated market, "low" a washed-out one. Older indicators
# only ever report "high" or "normal".
STATUSES = ("high", "low", "normal", "unavailable")


def build_summary(results: List[IndicatorResult]) -> Dict[str, object]:
    triggered_total = sum(1 for r in results if r.status == "high")
    total_indicators = len(results)
    available = [r for r in results if r.status in {"high", "low", "normal"}]
    triggered_available = sum(1 for r in available if r.status == "high")
    low_available = sum(1 for r in available if r.status == "low")
    summary: Dict[str, object] = {
        "triggered_total": triggered_total,
        "total_total": total_indicators,
        "triggered_available": triggered_available,
        "total_available": len(available),
        "low_available": low_available,
        "ratio_total": f"{triggered_total}/{total_indicators}" if total_indicators else "0/0",
        "ratio_available": (
            f"{triggered_available}/{len(available)}" if available else "0/0"
        ),
    }
    counts_by_category: Dict[str, Dict[str, int]] = {}
    for result in results:
        counts = counts_by_category.setdefault(result.category, {status: 0 for status in STATUSES})
        # An unexpected status counts as unavailable rather than raising and
        # failing the whole run's summary.
        status = result.status if result.status in counts else "unavailable"
        counts[status] += 1
    summary["by_category"] = counts_by_category
    return summary
