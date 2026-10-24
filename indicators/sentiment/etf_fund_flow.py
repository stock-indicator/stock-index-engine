from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

import pandas as pd

from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from common.utils import utc_now
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date

# Issuer NAV history files (download_url.conf keys) that publish daily shares
# outstanding. A day's net flow is the change in shares outstanding times that
# day's NAV. On the 338 days that overlap the etf.com feed this indicator used
# before, the result matches etf.com exactly (same values, same signs). etf.com
# closed that API to anonymous clients in 2026, and Invesco publishes no such
# file for QQQ, so QQQ is no longer tracked; its older rows stay in the clean
# CSV but are left out of the computation.
NAV_HISTORY_RESOURCES: Dict[str, str] = {"SPY": "SSGA-SPY-NAV-History"}


class ETFFundFlowIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="ETF Net Inflows Streak",
        category="Sentiment",
        threshold="> 20",
        markets=["US Market"],
        topics=["Sentiment", "ETF"],
        description="Tracks the number of consecutive days of net inflows into SPY, the largest S&P 500 ETF. Daily flows are the change in shares outstanding times NAV, from State Street's published NAV history. A long streak can indicate strong market conviction or potential overheating.",
    )
    tickers: List[str] = list(NAV_HISTORY_RESOURCES)
    default_history_days = 365

    def collect_full(self, fetcher) -> pd.DataFrame:
        end = utc_now().date()
        start = end - timedelta(days=self.get_history_window_days())
        return self._collect(start, end)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher):
        if existing_clean is None or existing_clean.empty:
            return self.collect_full(fetcher)
        tracked = existing_clean[existing_clean["ticker"].isin(self.tickers)]
        if tracked.empty:
            return self.collect_full(fetcher)
        last_date = pd.to_datetime(tracked["data_start_date"].max()).date()
        start = last_date + timedelta(days=1)
        end = utc_now().date()
        if start > end:
            return None
        data = self._collect(start, end)
        return None if data.empty else data

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
        if not clean_df.empty:
            clean_df = clean_df[clean_df["ticker"].isin(self.tickers)]
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

    def _collect(self, start: date, end: date) -> pd.DataFrame:
        frames = []
        for ticker in self.tickers:
            data = self._fetch_flows(ticker, start, end)
            if data is not None:
                frames.append(data)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _fetch_flows(self, ticker: str, start: date, end: date) -> pd.DataFrame | None:
        if start > end:
            return None
        path = resource_fetcher.ensure(
            NAV_HISTORY_RESOURCES[ticker],
            ttl_days=1,
            filename=f"navhist-{ticker.lower()}.xlsx",
        )
        if path is None or not path.exists():
            self.logger.warning("NAV history for %s unavailable", ticker)
            return None
        try:
            nav = self._read_nav_history(path)
        except Exception as exc:  # pragma: no cover
            # A malformed or truncated workbook must not fail the run; with no
            # data at all the indicator reports "unavailable".
            self.logger.warning("Failed to read NAV history for %s at %s: %s", ticker, path, exc)
            return None
        if nav is None:
            self.logger.warning("NAV history for %s at %s has no Date/NAV/Shares table", ticker, path)
            return None
        # Diff over the whole file first, so the first day of the window still
        # has the previous day's share count to compare against.
        nav["net_flow"] = nav["shares"].diff() * nav["nav"] / 1_000_000
        window = nav[(nav["as_of"].dt.date >= start) & (nav["as_of"].dt.date <= end)]
        window = window.dropna(subset=["net_flow"])
        if window.empty:
            return None
        return pd.DataFrame(
            {
                "ticker": ticker,
                "as_of": window["as_of"].dt.strftime("%Y-%m-%d"),
                "net_flow": window["net_flow"].round(2),
                "aggregated_flows": round(float(window["net_flow"].sum()), 2),
            }
        )

    @staticmethod
    def _read_nav_history(path) -> pd.DataFrame | None:
        """Read the Date / NAV / Shares Outstanding table below the fund header."""
        raw = pd.read_excel(path, header=None)
        header_rows = raw.index[raw[0].astype(str).str.strip().eq("Date")]
        if header_rows.empty:
            return None
        header_at = header_rows[0]
        table = raw.iloc[header_at + 1 :].copy()
        table.columns = [str(col).strip() for col in raw.iloc[header_at]]
        if not {"Date", "NAV", "Shares Outstanding"}.issubset(table.columns):
            return None
        nav = pd.DataFrame(
            {
                "as_of": pd.to_datetime(table["Date"], format="%d-%b-%Y", errors="coerce"),
                # Some older rows hold "-" instead of a number.
                "nav": pd.to_numeric(table["NAV"], errors="coerce"),
                "shares": pd.to_numeric(table["Shares Outstanding"], errors="coerce"),
            }
        )
        return nav.dropna().sort_values("as_of").reset_index(drop=True)
