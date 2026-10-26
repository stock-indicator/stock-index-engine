from __future__ import annotations

import pandas as pd

from indicators.base import IndicatorMetadata
from indicators.signal_series import SignalSeriesIndicator
from indicators.valuation.base_multpl import MultplIndicator, fetch_multpl_table

# Months of CPI used for the trailing inflation that turns the nominal 10-year
# yield into a real one, as in Shiller's definition.
INFLATION_MONTHS = 120
# A CAPE reading pairs with the latest real yield at most this old. Monthly
# FRED data lands up to ~6 weeks after the month it describes.
REAL_YIELD_MAX_AGE = pd.Timedelta(days=70)


class ExcessCAPEYieldIndicator(SignalSeriesIndicator):
    slug_override = "excess_cape_yield"
    metadata = IndicatorMetadata(
        name="Excess CAPE Yield",
        category="Valuation",
        threshold="High < 1% · Low > 7%",
        markets=["US Market", "S&P 500"],
        topics=["Valuation", "Rates"],
        description=(
            "Robert Shiller's excess CAPE yield, from 1957: the S&P 500's cyclically adjusted earnings "
            "yield (1 / CAPE) minus the real 10-year Treasury yield (10-year yield less trailing "
            "10-year CPI inflation). It is the extra return stocks offer over inflation-protected "
            "bonds. Below 1% stocks pay almost nothing for their risk, as in 1968 and 1999-2000; "
            "above 7% they were priced for strong returns, as in 1974-82 and 2009."
        ),
    )
    value_column = "excess_cape_yield_pct"
    detail_columns = ["cape", "cape_yield_pct", "real_10y_yield_pct"]
    high_below = 1.0
    low_above = 7.0
    unit = "%"
    decimals = 2
    stale_after_days = 10
    high_note = "Stocks offer almost no premium over real bond yields"
    low_note = "Stocks offer a wide premium over real bond yields"
    normal_note = "Equity premium over real bond yields within its usual range"

    def collect_full(self, fetcher) -> pd.DataFrame:
        cape = fetch_multpl_table("shiller-pe", period="by-month")
        if cape.empty:
            raise RuntimeError("multpl.com returned no CAPE table")
        cape["date"] = pd.to_datetime(cape["date"], errors="coerce")
        cape["cape"] = cape["value"].map(MultplIndicator._parse_value)
        cape = cape.dropna(subset=["date", "cape"]).sort_values("date")[["date", "cape"]]

        gs10 = fetcher.fetch_fred_series("GS10")
        cpi = fetcher.fetch_fred_series("CPIAUCSL")
        if gs10 is None or cpi is None:
            raise RuntimeError("FRED series GS10 or CPIAUCSL unavailable")
        inflation = ((cpi / cpi.shift(INFLATION_MONTHS)) ** (12 / INFLATION_MONTHS) - 1) * 100
        real = (gs10 - inflation.reindex(gs10.index)).dropna()
        real = pd.DataFrame({"date": real.index, "real_10y_yield_pct": real.values}).sort_values("date")

        frame = pd.merge_asof(cape, real, on="date", direction="backward", tolerance=REAL_YIELD_MAX_AGE)
        frame["cape_yield_pct"] = 100 / frame["cape"]
        frame["excess_cape_yield_pct"] = frame["cape_yield_pct"] - frame["real_10y_yield_pct"]
        return frame.dropna(subset=["excess_cape_yield_pct"])
