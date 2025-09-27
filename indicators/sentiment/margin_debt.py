from __future__ import annotations

import pandas as pd

from common.fetchers import fetch_finra_margin_table
from indicators.base import BaseIndicator, IndicatorMetadata

MARGIN_DEBT_COLUMN = "Debit Balances in Customers' Securities Margin Accounts"


class MarginDebtIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Margin Debt",
        category="Sentiment",
        threshold="New high",
        markets=["US Market"],
        topics=["Sentiment", "Leverage"],
    )

    def evaluate(self, fetcher):  # fetcher unused
        table = fetch_finra_margin_table()
        if table is None or table.empty or MARGIN_DEBT_COLUMN not in table.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to retrieve FINRA margin statistics.",
            )

        df = table.dropna(subset=[MARGIN_DEBT_COLUMN]).copy()
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="FINRA margin dataset missing debt column.",
            )

        if "Year-Month" in df.columns:
            df = df.dropna(subset=["Year-Month"])
            df = df.sort_values("Year-Month")
        latest_row = df.iloc[-1]
        latest_value = float(latest_row[MARGIN_DEBT_COLUMN])
        peak_value = float(df[MARGIN_DEBT_COLUMN].max())

        tolerance = max(peak_value * 0.001, 1.0)
        status = "high" if latest_value >= peak_value - tolerance else "normal"

        latest_date = (
            latest_row["Year-Month"].date().isoformat()
            if "Year-Month" in latest_row and not pd.isna(latest_row["Year-Month"])
            else "latest"
        )
        peak_date = "unknown"
        if "Year-Month" in df.columns:
            peak_dates = df.loc[
                df[MARGIN_DEBT_COLUMN] == peak_value, "Year-Month"
            ].dropna()
            if not peak_dates.empty:
                peak_date = peak_dates.iloc[-1].date().isoformat()

        notes = (
            "Latest margin debt at record high"
            if status == "high"
            else "Below historical peak"
        )
        raw_value = (
            f"{latest_value:,.0f} (latest: {latest_date}); "
            f"peak: {peak_value:,.0f} (as of {peak_date})"
        )
        pure_value = [
            {"metric": "latest_margin_debt", "value": latest_value, "as_of": latest_date},
            {"metric": "peak_margin_debt", "value": peak_value, "as_of": peak_date},
        ]
        return self.build_result(raw_value=raw_value, pure_value=pure_value, status=status, notes=notes)
