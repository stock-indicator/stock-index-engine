from __future__ import annotations

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class PostHikeWindowIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Post-Hike Window",
        category="Macro",
        threshold="0-6 months",
        markets=["US Market"],
        topics=["Macro", "Policy"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        fed_funds = fetcher.fetch_fred_series("FEDFUNDS", observation_start="2000-01-01")
        if fed_funds is None or fed_funds.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series FEDFUNDS unavailable.",
            )
        fed_funds = fed_funds.dropna()
        changes = fed_funds.diff()
        last_hike_dates = changes[changes > 0].index
        if last_hike_dates.empty:
            return self.build_result(
                raw_value="No hikes in sample",
                pure_value=[{"metric": "months_since_hike", "value": None}],
                status="normal",
                notes="No rate hikes detected in observation window.",
            )
        last_hike_date = last_hike_dates[-1]
        current_date = fed_funds.index[-1]
        months_since = (
            (current_date.year - last_hike_date.year) * 12
            + (current_date.month - last_hike_date.month)
        )
        status = "high" if months_since <= 6 else "normal"
        raw_value = (
            f"Months since last hike: {months_since} (hike on {last_hike_date.date().isoformat()})"
        )
        notes = (
            "Within 6 months of last rate hike"
            if status == "high"
            else "More than 6 months since last rate hike"
        )
        pure_value = [
            {"metric": "months_since_hike", "value": months_since},
            {"metric": "last_hike_date", "value": last_hike_date.date().isoformat()},
        ]
        return self.build_result(raw_value=raw_value, pure_value=pure_value, status=status, notes=notes)
