from __future__ import annotations

import os
import re
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from .config import FRED_API_BASE, HTTP_HEADERS
from .resources import ResourceFetcher

resource_fetcher = ResourceFetcher()


class MarketDataFetcher:
    """Cache-friendly helpers for pulling price history and macro series."""

    def __init__(self) -> None:
        self._price_cache: Dict[str, pd.DataFrame] = {}

    def get_price_history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        if ticker not in self._price_cache:
            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
            )
            if df.empty:
                raise ValueError(f"No price history returned for {ticker}")
            if isinstance(df.columns, pd.MultiIndex):
                try:
                    df = df.xs(ticker, axis=1, level="Ticker")
                except (KeyError, ValueError):
                    df = df.droplevel(-1, axis=1)
            self._price_cache[ticker] = df
        return self._price_cache[ticker]

    def fetch_fred_series(
        self, series_id: str, observation_start: Optional[str] = None
    ) -> Optional[pd.Series]:
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            return None
        params = {
            "api_key": api_key,
            "series_id": series_id,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start
        try:
            response = requests.get(
                FRED_API_BASE, params=params, timeout=10, headers=HTTP_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        observations = response.json().get("observations", [])
        if not observations:
            return None
        data = {}
        for obs in observations:
            value = obs.get("value")
            if value in {None, "."}:
                continue
            try:
                data[obs["date"]] = float(value)
            except ValueError:
                continue
        if not data:
            return None
        series = pd.Series(data, dtype="float64")
        series.index = pd.to_datetime(series.index)
        return series.sort_index()


def fetch_multpl_value(slug: str) -> Optional[Tuple[str, float]]:
    """Scrape the latest value from multpl.com tables."""

    url = f"https://www.multpl.com/{slug}/table/by-month"
    try:
        response = requests.get(url, timeout=10, headers=HTTP_HEADERS)
        response.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        return None
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None
    cells = rows[1].find_all("td")
    if len(cells) < 2:
        return None
    date_text = cells[0].get_text(strip=True)
    value_text = cells[1].get_text(strip=True)
    value_clean = re.sub(r"[^0-9+\-.]", "", value_text)
    if not value_clean:
        return None
    try:
        value = float(value_clean)
    except ValueError:
        return None
    return date_text, value


def fetch_finra_margin_table(ttl_days: int = 60) -> Optional[pd.DataFrame]:
    """Return the FINRA margin statistics as a DataFrame, using local cache when possible."""

    path = resource_fetcher.ensure(
        "FINRA-Margin_Statistics",
        ttl_days=ttl_days,
        filename="margin-statistics.xlsx",
    )
    if path is None or not path.exists():
        return None

    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df.columns = [str(col).strip() for col in df.columns]
    if "Year-Month" in df.columns:
        df = df.dropna(subset=["Year-Month"])
        try:
            df["Year-Month"] = pd.to_datetime(df["Year-Month"], format="%Y-%m")
        except (ValueError, TypeError):
            df["Year-Month"] = pd.to_datetime(df["Year-Month"], errors="coerce")
    return df
