import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Dict, List

import pandas as pd
import numpy as np

from common.api_keys import load_api_keys
from common.config import OUTPUT_DIR
from common.fetchers import MarketDataFetcher
from common.models import IndicatorResult
from common.utils import sanitize_column_name
from indicators import ALL_INDICATORS


def _sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, (np.bool_, )):
        return bool(obj)
    if isinstance(obj, (np.integer, )):
        return int(obj)
    if isinstance(obj, (np.floating, )):
        return float(obj)
    if isinstance(obj, (pd.Timestamp, )):
        return obj.isoformat()
    return obj

def build_summary(results: List[IndicatorResult]) -> Dict[str, object]:
    triggered_total = sum(1 for r in results if r.status == "high")
    total_indicators = len(results)
    available = [r for r in results if r.status in {"high", "normal"}]
    triggered_available = sum(1 for r in available if r.status == "high")
    summary: Dict[str, object] = {
        "triggered_total": triggered_total,
        "total_total": total_indicators,
        "triggered_available": triggered_available,
        "total_available": len(available),
        "ratio_total": f"{triggered_total}/{total_indicators}",
        "ratio_available": (
            f"{triggered_available}/{len(available)}" if available else "0/0"
        ),
    }
    counts_by_category: Dict[str, Dict[str, int]] = {}
    for result in results:
        counts_by_category.setdefault(result.category, {
            "high": 0,
            "normal": 0,
            "unavailable": 0,
        })
        counts_by_category[result.category][result.status] += 1
    summary["by_category"] = counts_by_category
    return summary


def write_json(results: List[IndicatorResult], summary: Dict[str, object]) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summary,
        "indicators": [asdict(r) for r in results],
    }
    sanitized = _sanitize_for_json(payload)
    json_path = OUTPUT_DIR / "market_status.latest.json"
    json_path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")


def update_csv(results: List[IndicatorResult], summary: Dict[str, object]) -> None:
    csv_path = OUTPUT_DIR / "market_indicator_log.csv"
    row: Dict[str, object] = {
        "date": datetime.now(UTC).date().isoformat(),
        "triggered_available": summary["triggered_available"],
        "total_available": summary["total_available"],
        "triggered_total": summary["triggered_total"],
        "total_total": summary["total_total"],
    }
    for result in results:
        market_path = '__'.join(result.markets) if result.markets else 'unknown'
        col_name = sanitize_column_name(f"{market_path}_{result.name}")
        row[col_name] = result.status

    if csv_path.exists():
        existing = pd.read_csv(csv_path)
        existing = existing[existing["date"] != row["date"]]
        updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    else:
        updated = pd.DataFrame([row])
    updated.to_csv(csv_path, index=False)


def main() -> None:
    load_api_keys()
    fetcher = MarketDataFetcher()

    results: List[IndicatorResult] = []
    for indicator in ALL_INDICATORS:
        try:
            result = indicator.evaluate(fetcher)
        except Exception as exc:  # pylint: disable=broad-except
            meta = indicator.metadata
            results.append(
                IndicatorResult(
                    name=meta.name,
                    category=meta.category,
                    markets=meta.markets,
                    threshold=meta.threshold,
                    status="unavailable",
                    notes=f"Indicator failed: {exc}",
                    raw_value=None,
                    pure_value=None,
                    topics=meta.topics,
                )
            )
            continue
        if isinstance(result, list):
            results.extend(result)
        else:
            results.append(result)

    summary = build_summary(results)
    write_json(results, summary)
    update_csv(results, summary)

    print(f"JSON written to {OUTPUT_DIR / 'market_status.latest.json'}")
    print(f"CSV updated at {OUTPUT_DIR / 'market_indicator_log.csv'}")
    print(
        "Triggered indicators (available only): "
        f"{summary['ratio_available']}"
    )
    print(
        "Triggered indicators (all tracked): "
        f"{summary['ratio_total']}"
    )


if __name__ == "__main__":
    main()

