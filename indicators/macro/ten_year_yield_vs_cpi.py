from __future__ import annotations

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class TenYearYieldVsCPIIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="10Y Yield vs CPI",
        category="Macro",
        threshold="10Y < CPI",
        markets=["US Market"],
        topics=["Macro", "Rates"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        yields = fetcher.fetch_fred_series("GS10", observation_start="2000-01-01")
        cpi = fetcher.fetch_fred_series("CPIAUCSL", observation_start="2000-01-01")
        if yields is None or cpi is None or yields.empty or cpi.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FRED series GS10 or CPIAUCSL unavailable.",
            )
        cpi_yoy = (cpi.pct_change(12) * 100).dropna()
        if cpi_yoy.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to compute CPI YoY change (insufficient data).",
            )
        latest_cpi_date = cpi_yoy.index[-1]
        latest_cpi_yoy = float(cpi_yoy.iloc[-1])
        latest_yield_date = yields.index[-1]
        latest_yield = float(yields.iloc[-1])
        status = "high" if latest_yield < latest_cpi_yoy else "normal"
        notes = (
            "10Y yield below CPI YoY implies negative real rates"
            if status == "high"
            else "10Y yield above CPI YoY"
        )
        raw_value = (
            f"Yield: {latest_yield:.2f}% ({latest_yield_date.date().isoformat()}); "
            f"CPI YoY: {latest_cpi_yoy:.2f}% ({latest_cpi_date.date().isoformat()})"
        )
        pure_value = [
            {"metric": "10Y_yield_pct", "value": latest_yield},
            {"metric": "CPI_yoy_pct", "value": latest_cpi_yoy},
        ]
        return self.build_result(raw_value=raw_value, pure_value=pure_value, status=status, notes=notes)
