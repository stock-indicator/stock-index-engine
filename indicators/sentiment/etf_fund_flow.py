from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from common.fetchers import resource_fetcher
from common.models import IndicatorResult
from common.utils import utc_now, write_text_atomic
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date

# A day's net flow is the change in shares outstanding times that day's NAV.
# On the 338 days that overlap the etf.com feed this indicator used before,
# that matches etf.com exactly (same values, same signs). etf.com closed its
# API to anonymous clients in 2026.
#
# State Street publishes SPY's full daily NAV history (download_url.conf key).
NAV_HISTORY_RESOURCES: Dict[str, str] = {"SPY": "SSGA-SPY-NAV-History"}
# Invesco only publishes the current day's NAV and shares outstanding for QQQ,
# so each run records a snapshot and flows come from consecutive snapshots.
FUND_DETAILS_RESOURCES: Dict[str, str] = {"QQQ": "INVESCO-QQQ-Fund-Details"}
# Outside resources/raw/<slug> and resources/files, so a full refresh, which
# purges both, cannot erase the only copy of past snapshots.
SNAPSHOT_DIR = Path("resources/snapshots")

USER_AGENT = "stock-index-engine/0.1 (market sentiment indicators)"
# A weekend plus a market holiday. A longer gap means missing data, and a
# streak must not be counted across it.
MAX_GAP_DAYS = 5
# A ticker whose newest flow is this much older than the newest flow overall
# is reported as stale instead of feeding the streak.
STALE_AFTER_DAYS = 7


class ETFFundFlowIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="ETF Net Inflows Streak",
        category="Sentiment",
        threshold="> 20",
        markets=["US Market"],
        topics=["Sentiment", "ETF"],
        description="Tracks the number of consecutive days of net inflows into SPY and QQQ. Daily flows are the change in shares outstanding times NAV, from State Street's and Invesco's published fund data. A long streak can indicate strong market conviction or potential overheating.",
    )
    tickers: List[str] = [*NAV_HISTORY_RESOURCES, *FUND_DETAILS_RESOURCES]
    default_history_days = 365

    def collect_full(self, fetcher) -> pd.DataFrame:
        end = utc_now().date()
        start = end - timedelta(days=self.get_history_window_days())
        return self._collect({ticker: start for ticker in self.tickers}, end)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher):
        if existing_clean is None or existing_clean.empty:
            return self.collect_full(fetcher)
        end = utc_now().date()
        default_start = end - timedelta(days=self.get_history_window_days())
        starts = {}
        for ticker in self.tickers:
            rows = existing_clean[existing_clean["ticker"] == ticker]
            if rows.empty:
                starts[ticker] = default_start
            else:
                starts[ticker] = pd.to_datetime(rows["data_start_date"].max()).date() + timedelta(days=1)
        data = self._collect(starts, end)
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

    def merge_clean_data(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        # One row per ticker per day. The base merge keys on the date alone,
        # which kept one ticker per day and silently dropped the other.
        combined = pd.concat([existing, new], ignore_index=True)
        combined["data_start_date"] = pd.to_datetime(combined["data_start_date"])
        combined = combined.drop_duplicates(subset=["ticker", "data_start_date"], keep="last")
        combined = combined.sort_values(["ticker", "data_start_date"]).reset_index(drop=True)
        combined["data_end_date"] = combined.groupby("ticker", group_keys=False)["data_start_date"].apply(
            lambda dates: pd.Series(compute_end_date(dates.tolist()), index=dates.index)
        )
        return combined

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if not clean_df.empty:
            clean_df = clean_df[clean_df["ticker"].isin(self.tickers)].copy()
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="ETF fund flow dataset empty.",
            )
        clean_df["data_start_date"] = pd.to_datetime(clean_df["data_start_date"])
        newest = clean_df["data_start_date"].max()
        streaks = {}
        latest_flows = {}
        stale = {}
        for ticker, group in clean_df.groupby("ticker"):
            group = group.sort_values("data_start_date")
            last_date = group["data_start_date"].iloc[-1]
            if (newest - last_date).days > STALE_AFTER_DAYS:
                stale[ticker] = last_date.date().isoformat()
                continue
            streak = 0
            newer_date = None
            for _, row in group.iloc[::-1].iterrows():
                if newer_date is not None and (newer_date - row["data_start_date"]).days > MAX_GAP_DAYS:
                    break
                if float(row["net_flow_musd"]) > 0:
                    streak += 1
                else:
                    break
                newer_date = row["data_start_date"]
            streaks[ticker] = streak
            latest_flows[ticker] = float(group.iloc[-1]["net_flow_musd"])
        if not streaks:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No ETF has recent flow data.",
            )
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
        pure_value += [
            {"ticker": ticker, "consecutive_inflow_days": None, "last_data_date": last}
            for ticker, last in stale.items()
        ]
        raw_value = "; ".join(
            [f"{ticker}: streak={streak} days" for ticker, streak in streaks.items()]
            + [f"{ticker}: no data since {last}" for ticker, last in stale.items()]
        )
        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value,
            status=status,
            notes=notes,
        )

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: int,
    ) -> Optional[List[Dict[str, object]]]:
        # One point per day: the summed flow of the ETFs reporting that day,
        # with each ETF's own flow in the details. The default series would
        # emit one point per row, i.e. two points on the same date.
        df = clean_df[clean_df["ticker"].isin(self.tickers)].copy()
        if df.empty:
            return None
        df["data_start_date"] = pd.to_datetime(df["data_start_date"])
        cutoff = pd.Timestamp(as_of.date() - timedelta(days=lookback_days))
        df = df[(df["data_start_date"] >= cutoff) & (df["data_start_date"] <= pd.Timestamp(as_of.date()))]
        if df.empty:
            return None
        wide = df.pivot_table(index="data_start_date", columns="ticker", values="net_flow_musd", aggfunc="last")
        history: List[Dict[str, object]] = []
        for ts, row in wide.iterrows():
            flows = {ticker: round(float(value), 2) for ticker, value in row.items() if pd.notna(value)}
            total = round(sum(flows.values()), 2)
            date_key = ts.date().isoformat()
            details: Dict[str, object] = {"total_net_flow_musd": total, "tickers": ",".join(flows)}
            details.update({f"{ticker.lower()}_net_flow_musd": value for ticker, value in flows.items()})
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": total,
                    "details": details,
                }
            )
        return history

    def _collect(self, starts: Dict[str, date], end: date) -> pd.DataFrame:
        frames = []
        for ticker in self.tickers:
            data = self._fetch_flows(ticker, starts[ticker], end)
            if data is not None:
                frames.append(data)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _fetch_flows(self, ticker: str, start: date, end: date) -> pd.DataFrame | None:
        if ticker in NAV_HISTORY_RESOURCES:
            nav = self._load_nav_history(ticker)
        else:
            # Record today's snapshot even when no flow is due yet, or the
            # next run would have nothing to diff against.
            self._record_snapshot(ticker)
            nav = self._load_snapshots(ticker)
        if nav is None or nav.empty or start > end:
            return None
        # Diff over all rows first, so the first day of the window still has
        # the previous day's share count to compare against.
        nav = nav.sort_values("as_of").reset_index(drop=True)
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

    def _load_nav_history(self, ticker: str) -> Optional[pd.DataFrame]:
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
        return nav

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

    @staticmethod
    def _snapshot_path(ticker: str) -> Path:
        return SNAPSHOT_DIR / f"{ticker.lower()}_fund_details.csv"

    def _load_snapshots(self, ticker: str) -> Optional[pd.DataFrame]:
        path = self._snapshot_path(ticker)
        if not path.exists():
            return None
        snapshots = pd.read_csv(path)
        snapshots["as_of"] = pd.to_datetime(snapshots["as_of"], errors="coerce")
        return snapshots.dropna(subset=["as_of", "nav", "shares"])

    def _record_snapshot(self, ticker: str) -> None:
        url = resource_fetcher.get_url(FUND_DETAILS_RESOURCES[ticker])
        if not url:
            self.logger.warning("No URL configured for %s fund details", ticker)
            return
        try:
            response = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self.logger.warning("Failed to fetch fund details for %s: %s", ticker, exc)
            return
        as_of = payload.get("effectiveBusinessDate")
        nav = payload.get("nav")
        shares = payload.get("sharesOutstanding")
        if not as_of or nav is None or shares is None:
            self.logger.warning("Fund details for %s lack date, NAV or shares: %r", ticker, payload)
            return
        snapshot = pd.DataFrame([{"as_of": as_of, "nav": float(nav), "shares": float(shares)}])
        existing = self._load_snapshots(ticker)
        if existing is not None:
            existing["as_of"] = existing["as_of"].dt.strftime("%Y-%m-%d")
            snapshot = pd.concat([existing, snapshot], ignore_index=True)
        # The API repeats the last business day over weekends and holidays.
        snapshot = snapshot.drop_duplicates(subset="as_of", keep="last").sort_values("as_of")
        write_text_atomic(self._snapshot_path(ticker), snapshot.to_csv(index=False))
        self.logger.info("Recorded %s fund details for %s", ticker, as_of)
