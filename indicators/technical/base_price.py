from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator


class PriceSeriesIndicator(BaseIndicator):
    """Base class for indicators relying on daily price history.

    Every run downloads each ticker's full history (``period="max"``: ^GSPC
    from 1927, ^NDX from 1985, ^VIX from 1990) and merges it over the stored
    rows. That backfills an indicator whose stored history is shorter, picks
    up vendor corrections, and costs one request per ticker per run because
    the fetcher shares downloads between indicators.
    """

    tickers: Dict[str, str] = {}
    price_field: str = "Adj Close"
    history_period: str = "max"

    def collect_full(self, fetcher: Optional[MarketDataFetcher] = None) -> pd.DataFrame:
        fetcher = fetcher or MarketDataFetcher()
        frames = []
        for market, ticker in self.tickers.items():
            df = fetcher.get_price_history(ticker, period=self.history_period)
            df = df.reset_index().rename(columns={"Date": "date"})
            df["ticker"] = ticker
            df["market"] = market
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    def collect_incremental(
        self, existing_clean: pd.DataFrame, fetcher: Optional[MarketDataFetcher] = None
    ) -> Optional[pd.DataFrame]:
        try:
            return self.collect_full(fetcher)
        except Exception as exc:  # yfinance raises a spread of types when Yahoo throttles
            # Stored history stays valid; the indicator reports from it until
            # the next run gets through.
            self.logger.warning("Price download failed; keeping stored history: %s", exc)
            return None

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
