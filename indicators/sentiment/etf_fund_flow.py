from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

import cloudscraper
import pandas as pd

from common.models import IndicatorResult
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


class ETFFundFlowIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="ETF Net Inflows Streak",
        category="Sentiment",
        threshold="> 20",
        markets=["US Market"],
        topics=["Sentiment", "ETF"],
        description="Tracks the number of consecutive days of net inflows into major index ETFs (e.g., SPY, QQQ). A long streak can indicate strong market conviction or potential overheating.",
    )
    tickers: List[str] = ["QQQ", "SPY"]
    default_history_days = 365

    def collect_full(self, fetcher) -> pd.DataFrame:
        end = datetime.utcnow().date()
        start = end - timedelta(days=self.get_history_window_days())
        frames = []
        for ticker in self.tickers:
            data = self._fetch_flows(ticker, start, end)
            if data is not None:
                frames.append(data)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher):
        if existing_clean is None or existing_clean.empty:
            return self.collect_full(fetcher)
        last_date = pd.to_datetime(existing_clean["data_start_date"].max()).date()
        start = last_date + timedelta(days=1)
        end = datetime.utcnow().date()
        if start > end:
            return None
        frames = []
        for ticker in self.tickers:
            data = self._fetch_flows(ticker, start, end)
            if data is not None:
                frames.append(data)
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        df["data_start_date"] = pd.to_datetime(df["as_of"], errors="coerce")
        df = df.dropna(subset=["data_start_date", "net_flow"])
        df = df.sort_values(["ticker", "data_start_date"])
        df["data_end_date"] = compute_end_date(df["data_start_date"].tolist())
        df = df.rename(columns={"net_flow": "net_flow_musd"})
        return df[["data_start_date", "data_end_date", "ticker", "net_flow_musd", "aggregated_flows"]]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="ETF fund flow dataset empty.",
            )
        streaks = {}
        latest_flows = {}
        for ticker, group in clean_df.groupby("ticker"):
            group = group.sort_values("data_start_date")
            streak = 0
            for _, row in group.iloc[::-1].iterrows():
                value = float(row["net_flow_musd"])
                if value > 0:
                    streak += 1
                else:
                    break
            streaks[ticker] = streak
            latest_flows[ticker] = float(group.iloc[-1]["net_flow_musd"])
        status = "high" if any(streak >= 20 for streak in streaks.values()) else "normal"
        notes = (
            "At least one ETF shows >20 days consecutive inflows"
            if status == "high"
            else "ETF inflow streak below 20-day threshold"
        )
        pure_value = [
            {
                "ticker": ticker,
                "consecutive_inflow_days": streak,
                "latest_flow_musd": latest_flows.get(ticker),
            }
            for ticker, streak in streaks.items()
        ]
        raw_value = "; ".join(
            f"{ticker}: streak={streak} days" for ticker, streak in streaks.items()
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )

    def _fetch_flows(self, ticker: str, start, end) -> pd.DataFrame | None:
        if start > end:
            return None
        scraper = cloudscraper.create_scraper()
        fmt = "%Y%m%d"
        url = (
            "https://api-prod.etf.com/v2/tool/fund-flows"
            f"?tickers={ticker}&startDate={start.strftime(fmt)}&endDate={end.strftime(fmt)}"
        )
        try:
            resp = scraper.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # pragma: no cover
            print(f"[ETF] Failed to fetch fund flows for {ticker}: {exc}")
            return None
        if not payload:
            return None
        record = payload[0]
        flows = record.get("flows", [])
        if not flows:
            return None
        rows = []
        for item in flows:
            rows.append(
                {
                    "ticker": ticker,
                    "as_of": item.get("asOf"),
                    "net_flow": item.get("value", 0.0),
                    "aggregated_flows": record.get("aggregated_flows"),
                }
            )
        return pd.DataFrame(rows)
