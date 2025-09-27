from __future__ import annotations

import pandas as pd

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class CorporateProfitsToGDPIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Corporate Profits vs GDP",
        category="Macro",
        threshold="> 12%",
        markets=["US Market", "US Economy"],
        topics=["Macro", "Profits"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        gdp = fetcher.fetch_fred_series("GDP", observation_start="2000-01-01")
        profits = fetcher.fetch_fred_series("CPATAX", observation_start="2000-01-01")
        if gdp is None or profits is None or gdp.empty or profits.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to fetch GDP or corporate profits series from FRED.",
            )

        combined_index = gdp.index.intersection(profits.index)
        if combined_index.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No overlapping observations for GDP and corporate profits.",
            )

        gdp_vals = gdp.loc[combined_index].astype(float)
        profit_vals = profits.loc[combined_index].astype(float)

        ratio = (profit_vals / gdp_vals) * 100
        ratio = ratio.dropna()
        if ratio.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute corporate profit share due to missing data.",
            )

        latest_date = ratio.index[-1].to_period("Q").to_timestamp()
        latest_ratio = float(ratio.iloc[-1])
        latest_profit = float(profit_vals.loc[ratio.index[-1]])
        latest_gdp = float(gdp_vals.loc[ratio.index[-1]])

        status = "high" if latest_ratio > 12 else "normal"
        raw_value = (
            f"Corporate profits/GDP: {latest_ratio:.2f}% (profits={latest_profit:,.0f}, "
            f"GDP={latest_gdp:,.0f})"
        )
        pure_value = [
            {
                "metric": "corporate_profit_share_pct",
                "value": latest_ratio,
                "as_of": latest_date.date().isoformat(),
            },
            {
                "metric": "corporate_profits",
                "value": latest_profit,
            },
            {
                "metric": "gdp",
                "value": latest_gdp,
            },
        ]

        notes = (
            "Corporate profit share above 12% threshold"
            if status == "high"
            else "Corporate profit share below threshold"
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
