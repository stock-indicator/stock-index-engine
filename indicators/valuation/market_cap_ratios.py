from __future__ import annotations

import pandas as pd

from common.models import IndicatorResult
from indicators.base import IndicatorMetadata, compute_end_date
from indicators.signal_series import SignalSeriesIndicator

# Federal Reserve Z.1 Financial Accounts, via FRED. Market value of the
# equity of US nonfinancial corporations, in millions of dollars.
EQUITIES_SERIES = "NCBEILQ027S"
# Recent estimates scale the latest quarter by this index's move since then.
PRICE_TICKER = "^GSPC"


class Z1EquityRatioIndicator(SignalSeriesIndicator):
    """Corporate equity market value (Fed Z.1) over a quarterly denominator.

    Z.1 is quarterly and published about ten weeks after each quarter ends,
    so days after the latest quarter carry an estimate: that quarter's ratio
    scaled by the S&P 500's move since its last close. Estimates are replaced
    by the actual figure once Z.1 publishes it.
    """

    denominator_series: str = ""
    detail_columns = ["estimated"]
    stale_after_days = 200

    def ratio(self, equities_musd: pd.Series, denominator: pd.Series) -> pd.Series:
        raise NotImplementedError

    def collect_full(self, fetcher) -> pd.DataFrame:
        equities = fetcher.fetch_fred_series(EQUITIES_SERIES)
        denominator = fetcher.fetch_fred_series(self.denominator_series)
        if equities is None or denominator is None:
            raise RuntimeError(f"FRED series {EQUITIES_SERIES} or {self.denominator_series} unavailable")
        quarterly = pd.concat({"equities": equities, "denominator": denominator}, axis=1).dropna()
        # Z.1 levels are end-of-quarter values that FRED dates on the quarter's
        # first day; date them at the quarter end they describe.
        quarterly.index = quarterly.index + pd.offsets.QuarterEnd(0)
        actual = pd.DataFrame(
            {self.value_column: self.ratio(quarterly["equities"], quarterly["denominator"]), "estimated": False}
        )
        frames = [actual]
        try:
            prices = fetcher.get_price_history(PRICE_TICKER)["Close"].dropna()
        except Exception as exc:  # yfinance throttling must not cost the quarterly data
            self.logger.warning("No %s prices for the estimate after the last quarter: %s", PRICE_TICKER, exc)
            prices = None
        if prices is not None:
            last_quarter = actual.index[-1]
            base = prices[prices.index <= last_quarter]
            after = prices[prices.index > last_quarter]
            if not base.empty and not after.empty:
                scaled = actual[self.value_column].iloc[-1] * after / base.iloc[-1]
                frames.append(pd.DataFrame({self.value_column: scaled, "estimated": True}))
        frame = pd.concat(frames)
        frame.index.name = "date"
        return frame.reset_index()

    def merge_clean_data(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        combined = super().merge_clean_data(existing, new)
        estimated = combined["estimated"].astype(str).str.lower() == "true"
        latest_actual = combined.loc[~estimated, "data_start_date"].max()
        if pd.notna(latest_actual):
            # Estimates up to the latest published quarter are superseded.
            combined = combined[~(estimated & (combined["data_start_date"] <= latest_actual))].copy()
            combined["data_end_date"] = compute_end_date(combined["data_start_date"].tolist())
        return combined.reset_index(drop=True)

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        result = super().compute(clean_df, fetcher)
        if result.status in {"high", "low", "normal"}:
            ordered = clean_df.sort_values("data_start_date")
            estimated = ordered["estimated"].astype(str).str.lower() == "true"
            last_quarter = ordered.loc[~estimated, "data_start_date"].max()
            if bool(estimated.iloc[-1]) and pd.notna(last_quarter):
                result.notes = (
                    f"{result.notes}. Estimated from the S&P 500's move since the latest "
                    f"Fed Z.1 quarter ({pd.Timestamp(last_quarter).date().isoformat()})."
                )
        return result


class BuffettIndicator(Z1EquityRatioIndicator):
    slug_override = "buffett_indicator"
    metadata = IndicatorMetadata(
        name="Buffett Indicator",
        category="Valuation",
        threshold="High > 150% · Low < 60%",
        markets=["US Market"],
        topics=["Valuation", "Cycles"],
        description=(
            "Market value of US corporate equity divided by GDP, from 1947 (Fed Z.1 nonfinancial "
            "corporate equities over nominal GDP). Warren Buffett called it probably the best single "
            "measure of where valuations stand. It peaked near 160% in 2000 and 220% in 2021; below "
            "60% stocks were cheap, as in 1974-82."
        ),
    )
    denominator_series = "GDP"
    value_column = "market_cap_to_gdp_pct"
    high_above = 150.0
    low_below = 60.0
    unit = "%"
    decimals = 1
    high_note = "Stock market value far above the size of the economy"
    low_note = "Stock market value low relative to the economy"
    normal_note = "Market value to GDP within its historical range"

    def ratio(self, equities_musd: pd.Series, denominator: pd.Series) -> pd.Series:
        # Equities in millions, GDP in billions (annualized rate).
        return equities_musd / 1000 / denominator * 100


class TobinsQIndicator(Z1EquityRatioIndicator):
    slug_override = "tobins_q"
    metadata = IndicatorMetadata(
        name="Tobin's Q",
        category="Valuation",
        threshold="High > 1.4 · Low < 0.5",
        markets=["US Market"],
        topics=["Valuation", "Cycles"],
        description=(
            "Market value of US nonfinancial corporations' equity divided by their net worth, from "
            "1945 (Fed Z.1). Above 1 the market prices companies above what it would cost to rebuild "
            "them. Peaks: 1.5 in 1968 and 2000; troughs near 0.3 in 1982."
        ),
    )
    denominator_series = "TNWMVBSNNCB"
    value_column = "q_ratio"
    high_above = 1.4
    low_below = 0.5
    decimals = 2
    high_note = "Equity valued far above the replacement cost of corporate assets"
    low_note = "Equity valued below the replacement cost of corporate assets"
    normal_note = "Q ratio within its historical range"

    def ratio(self, equities_musd: pd.Series, denominator: pd.Series) -> pd.Series:
        return equities_musd / denominator
