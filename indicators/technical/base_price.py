from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from common.utils import utc_now
from indicators.base import BaseIndicator


class PriceSeriesIndicator(BaseIndicator):
    """Base class for indicators relying on daily price history."""

    tickers: Dict[str, str] = {}
    price_field: str = "Adj Close"

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        history_days = self.get_history_window_days()
        today = utc_now().date()
        start_date = today - timedelta(days=history_days + 30)
        end_date = today
        frames = []
        for market, ticker in self.tickers.items():
            df = yf.download(
                ticker,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="column",
            )
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                if ticker in df.columns.get_level_values(-1):
                    df = df.xs(ticker, axis=1, level=-1)
                else:
                    df = df.droplevel(0, axis=1)
            df = df.reset_index().rename(columns={"Date": "date"})
            df["ticker"] = ticker
            df["market"] = market
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None) -> Optional[pd.DataFrame]:
        if existing_clean.empty:
            return None
        last_dates = (
            existing_clean.groupby("ticker")["data_start_date"].max().dropna().to_dict()
        )
        frames = []
        end_date = utc_now().date()
        for market, ticker in self.tickers.items():
            last_date = last_dates.get(ticker)
            if last_date is None:
                start_date = end_date - timedelta(days=self.get_history_window_days())
            else:
                start_date = (pd.to_datetime(last_date).date() + timedelta(days=1))
            if start_date >= end_date:
                continue
            df = yf.download(
                ticker,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="column",
            )
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                if ticker in df.columns.get_level_values(-1):
                    df = df.xs(ticker, axis=1, level=-1)
                else:
                    df = df.droplevel(0, axis=1)
            df = df.reset_index().rename(columns={"Date": "date"})
            df["ticker"] = ticker
            df["market"] = market
            frames.append(df)
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(
            columns={
                "date": "data_start_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df = df.dropna(subset=["data_start_date", "adj_close"])
        df["data_end_date"] = df["data_start_date"]
        numeric_cols = ["open", "high", "low", "close", "adj_close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["ticker"] = df.get("ticker", "").astype(str)
        df["market"] = df.get("market", "").astype(str)
        columns = [
            "data_start_date",
            "data_end_date",
            "market",
            "ticker",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
        ]
        available = [col for col in columns if col in df.columns]
        return df[available]

    def prepare_price_series(self, clean_df: pd.DataFrame, field: str = "adj_close") -> Dict[str, pd.Series]:
        if clean_df.empty:
            return {}
        pivot = (
            clean_df.groupby(["data_start_date", "market"])[field]
            .last()
            .unstack("market")
            .sort_index()
        )
        return {
            market: pivot[market].dropna()
            for market in pivot.columns
            if market in self.metadata.markets
        }
