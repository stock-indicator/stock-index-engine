from __future__ import annotations

import json
from pathlib import Path

from common.fetchers import resource_fetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class SmartVsDumbMoneyIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Smart vs Dumb Money",
        category="Sentiment",
        threshold="> 70",
        markets=["US Market"],
        topics=["Sentiment"],
    )

    def evaluate(self, fetcher):  # fetcher unused
        path = resource_fetcher.ensure(
            "CNN-Fear-and-Greed-Index-JSON",
            ttl_days=1,
            filename="cnn_fear_greed.json",
        )
        if path is None or not Path(path).exists():
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to download CNN Fear & Greed index.",
            )

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Failed to parse CNN Fear & Greed JSON: {exc}",
            )

        if "fear_and_greed" in data:
            latest_entry = data["fear_and_greed"]
            latest_value = float(latest_entry.get("score"))
            latest_date = latest_entry.get("timestamp") or latest_entry.get("date") or "unknown"
        else:
            series_list = list(data.get("data", {}).values())
            if not series_list:
                return self.build_result(
                    raw_value=None,
                    pure_value=None,
                    status="unavailable",
                    notes="CNN Fear & Greed JSON missing data series.",
                )

            primary_series = series_list[0].get("series")
            if not primary_series:
                return self.build_result(
                    raw_value=None,
                    pure_value=None,
                    status="unavailable",
                    notes="CNN Fear & Greed JSON missing primary series.",
                )

            fear_greed_points = primary_series[0]
            if not fear_greed_points:
                return self.build_result(
                    raw_value=None,
                    pure_value=None,
                    status="unavailable",
                    notes="CNN Fear & Greed primary series empty.",
                )

            latest_date, latest_value_str = fear_greed_points[-1]
            try:
                latest_value = float(latest_value_str)
            except ValueError:
                return self.build_result(
                    raw_value=None,
                    pure_value=None,
                    status="unavailable",
                    notes="CNN Fear & Greed latest observation is not numeric.",
                )

        status = "high" if latest_value >= 70 else "normal"
        raw_value = f"Fear & Greed index: {latest_value:.1f} (as of {latest_date})"
        pure_value = [
            {
                "metric": "fear_greed_index",
                "value": latest_value,
                "as_of": latest_date,
            }
        ]
        notes = (
            "Dumb money confidence very high (index >= 70)"
            if status == "high"
            else "Fear & Greed index below exuberance threshold"
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
