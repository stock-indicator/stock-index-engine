from __future__ import annotations

import pandas as pd

from common.fetchers import resource_fetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class RetailPositioningIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Retail Positioning",
        category="Sentiment",
        threshold="> 70%",
        markets=["US Market"],
        topics=["Sentiment", "AAII"],
    )

    def evaluate(self, fetcher):  # fetcher unused
        path = resource_fetcher.ensure(
            "AAII-Sentiment-Survey",
            ttl_days=7,
            filename="sentiment.xls",
        )
        if path is None:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Unable to download AAII sentiment survey.",
            )

        try:
            df = pd.read_excel(path, header=3)
        except Exception as exc:  # pylint: disable=broad-except
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Failed to read AAII sentiment file: {exc}",
            )

        if "Date" not in df.columns or "Bullish" not in df.columns:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="AAII sentiment format unexpected (missing Date/Bullish columns).",
            )

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Bullish"])
        if df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="AAII sentiment dataset has no valid rows.",
            )

        df = df.sort_values("Date")
        latest = df.iloc[-1]
        latest_date = latest["Date"].date().isoformat()

        def to_pct(value: float) -> float:
            if value is None:
                return float("nan")
            value = float(value)
            return value * 100 if value <= 1 else value

        bullish_pct = to_pct(latest.get("Bullish"))
        neutral_pct = to_pct(latest.get("Neutral")) if "Neutral" in df.columns else None
        bearish_pct = to_pct(latest.get("Bearish")) if "Bearish" in df.columns else None

        if pd.isna(bullish_pct):
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Latest AAII bullish percentage missing.",
            )

        status = "high" if bullish_pct >= 70 else "normal"
        raw_value = f"AAII bullish: {bullish_pct:.1f}% (as of {latest_date})"
        pure_value = [
            {"metric": "bullish_pct", "value": bullish_pct, "as_of": latest_date},
        ]
        if neutral_pct is not None and not pd.isna(neutral_pct):
            pure_value.append({"metric": "neutral_pct", "value": neutral_pct, "as_of": latest_date})
        if bearish_pct is not None and not pd.isna(bearish_pct):
            pure_value.append({"metric": "bearish_pct", "value": bearish_pct, "as_of": latest_date})

        notes = (
            "Retail bullish sentiment extremely high"
            if status == "high"
            else "Retail bullish sentiment below 70% threshold"
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )
