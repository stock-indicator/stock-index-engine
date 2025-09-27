from __future__ import annotations

import pandas as pd

from common.fetchers import fetch_finra_margin_table
from common.models import IndicatorResult
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


class MarginDebtIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Margin Debt",
        category="Sentiment",
        threshold="New high",
        markets=["US Market"],
        topics=["Sentiment", "Leverage"],
    )
    default_history_days = 365 * 5

    def collect_full(self, fetcher) -> pd.DataFrame:
        df = fetch_finra_margin_table(ttl_days=90)
        return df if df is not None else pd.DataFrame()

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(
            columns={
                "Year-Month": "data_start_date",
                "Debit Balances in Customers' Securities Margin Accounts": "margin_debt",
                "Free Credit Balances in Customers' Cash Accounts": "cash_balances",
                "Free Credit Balances in Customers' Securities Margin Accounts": "margin_credit",
            }
        )
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date", "margin_debt"])
        df = df.sort_values("data_start_date")
        end_dates = compute_end_date(df["data_start_date"].tolist())
        df["data_end_date"] = end_dates
        numeric_cols = ["margin_debt", "cash_balances", "margin_credit"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[[
            "data_start_date",
            "data_end_date",
            "margin_debt",
            "cash_balances",
            "margin_credit",
        ]]

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher):
        return self.collect_full(fetcher)

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to retrieve FINRA margin statistics.",
            )

        latest = clean_df.dropna(subset=["margin_debt"]).iloc[-1]
        latest_value = float(latest["margin_debt"])
        latest_date = latest["data_start_date"].date().isoformat()
        peak_value = float(clean_df["margin_debt"].max())
        peak_row = clean_df.loc[clean_df["margin_debt"].idxmax()]
        peak_date = peak_row["data_start_date"].date().isoformat()

        tolerance = max(peak_value * 0.001, 1.0)
        status = "high" if latest_value >= peak_value - tolerance else "normal"
        notes = (
            "Latest margin debt at record high"
            if status == "high"
            else "Below historical peak"
        )
        raw_value = (
            f"{latest_value:,.0f} (latest: {latest_date}); peak: {peak_value:,.0f} (as of {peak_date})"
        )
        pure_value = [
            {"metric": "latest_margin_debt", "value": latest_value, "as_of": latest_date},
            {"metric": "peak_margin_debt", "value": peak_value, "as_of": peak_date},
        ]
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
