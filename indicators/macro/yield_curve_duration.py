from __future__ import annotations

from datetime import timedelta

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class YieldCurveDurationIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Yield Curve Duration",
        category="Macro",
        threshold="> 12 months",
        markets=["US Market"],
        topics=["Macro", "Yield Curve"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        spread = fetcher.fetch_fred_series("T10Y2Y", observation_start="2000-01-01")
        if spread is None or spread.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series T10Y2Y unavailable.",
            )
        spread = spread.dropna()
        latest_value = float(spread.iloc[-1])
        latest_date = spread.index[-1]
        if latest_value >= 0:
            raw_value = f"Spread {latest_value:.2f}% (as of {latest_date.date().isoformat()})"
            pure_value = [
                {"metric": "spread_pct", "value": latest_value},
                {"metric": "inversion_months", "value": 0.0},
            ]
            return self.build_result(
                raw_value=raw_value,
                pure_value=pure_value,
                status="normal",
                notes="Yield curve not inverted currently.",
            )

        non_negative = spread[spread >= 0]
        if non_negative.empty:
            inversion_start = spread.index[0]
        else:
            prior_non_negative = non_negative.index[non_negative.index < latest_date]
            inversion_start = (
                prior_non_negative[-1] + timedelta(days=1)
                if len(prior_non_negative) > 0
                else spread.index[0]
            )
        duration_days = max((latest_date - inversion_start).days, 0)
        duration_months = duration_days / 30.4375
        status = "high" if duration_months >= 12 else "normal"
        raw_value = (
            f"Spread {latest_value:.2f}% (as of {latest_date.date().isoformat()}); "
            f"current inversion ~{duration_months:.1f} months"
        )
        notes = (
            "Yield curve inverted for over 12 months"
            if status == "high"
            else "Yield curve inversion duration below 12 months"
        )
        pure_value = [
            {"metric": "spread_pct", "value": latest_value},
            {"metric": "inversion_months", "value": duration_months},
        ]
        return self.build_result(raw_value=raw_value, pure_value=pure_value, status=status, notes=notes)
