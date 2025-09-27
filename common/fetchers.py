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
from .logger import get_logger

resource_fetcher = ResourceFetcher()


LOGGER = get_logger("fetchers")
FRED_LOGGER = LOGGER.getChild("fred")
MULTPL_LOGGER = LOGGER.getChild("multpl")
FINRA_LOGGER = LOGGER.getChild("finra")


class MarketDataFetcher:
    """Cache-friendly helpers for pulling price history and macro series."""

    def __init__(self) -> None:
        self._price_cache: Dict[str, pd.DataFrame] = {}
        self.logger = LOGGER.getChild("market_data")

    def get_price_history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        if ticker not in self._price_cache:
            self.logger.info("Downloading price history for %s (period=%s)", ticker, period)
            try:
                df = yf.download(
                    ticker,
                    period=period,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                )
            except Exception as exc:
                self.logger.error("Price history download failed for %s: %s", ticker, exc)
                raise
            if df.empty:
                self.logger.warning("No price history returned for %s (period=%s)", ticker, period)
                raise ValueError(f"No price history returned for {ticker}")
            if isinstance(df.columns, pd.MultiIndex):
                try:
                    df = df.xs(ticker, axis=1, level="Ticker")
                except (KeyError, ValueError):
                    df = df.droplevel(-1, axis=1)
            self._price_cache[ticker] = df
            self.logger.debug("Cached price history for %s with %d rows", ticker, len(df))
        else:
            self.logger.debug("Returning cached price history for %s", ticker)
        return self._price_cache[ticker]

    def fetch_fred_series(
        self, series_id: str, observation_start: Optional[str] = None
    ) -> Optional[pd.Series]:
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            FRED_LOGGER.warning("FRED API key missing; skipping series %s", series_id)
            return None
        params = {
            "api_key": api_key,
            "series_id": series_id,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start
        FRED_LOGGER.info(
            "Requesting FRED series %s (observation_start=%s)",
            series_id,
            observation_start or "default",
        )
        try:
            response = requests.get(
                FRED_API_BASE, params=params, timeout=10, headers=HTTP_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            FRED_LOGGER.warning("FRED request failed for %s: %s", series_id, exc)
            return None
        observations = response.json().get("observations", [])
        if not observations:
            FRED_LOGGER.warning("FRED response for %s contained no observations", series_id)
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
            FRED_LOGGER.warning("FRED series %s contained only invalid data", series_id)
            return None
        series = pd.Series(data, dtype="float64")
        series.index = pd.to_datetime(series.index)
        FRED_LOGGER.info(
            "Fetched FRED series %s with %d observations",
            series_id,
            len(series),
        )
        return series.sort_index()


def fetch_multpl_value(slug: str) -> Optional[Tuple[str, float]]:
    """Scrape the latest value from multpl.com tables."""

    url = f"https://www.multpl.com/{slug}/table/by-month"
    MULTPL_LOGGER.info("Fetching multpl.com table for %s", slug)
    try:
        response = requests.get(url, timeout=10, headers=HTTP_HEADERS)
        response.raise_for_status()
    except requests.RequestException as exc:
        MULTPL_LOGGER.warning("multpl.com request failed for %s: %s", slug, exc)
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        MULTPL_LOGGER.warning("No table found in multpl.com response for %s", slug)
        return None
    rows = table.find_all("tr")
    if len(rows) < 2:
        MULTPL_LOGGER.warning("Table rows missing in multpl.com response for %s", slug)
        return None
    cells = rows[1].find_all("td")
    if len(cells) < 2:
        MULTPL_LOGGER.warning("Table cells missing in multpl.com response for %s", slug)
        return None
    date_text = cells[0].get_text(strip=True)
    value_text = cells[1].get_text(strip=True)
    value_clean = re.sub(r"[^0-9+\-.]", "", value_text)
    if not value_clean:
        MULTPL_LOGGER.warning("Unable to parse value for %s from multpl.com", slug)
        return None
    try:
        value = float(value_clean)
    except ValueError as exc:
        MULTPL_LOGGER.warning("Invalid numeric value for %s from multpl.com: %s", slug, exc)
        return None
    MULTPL_LOGGER.info("Fetched multpl.com value for %s: %s on %s", slug, value, date_text)
    return date_text, value


def fetch_finra_margin_table(ttl_days: int = 60) -> Optional[pd.DataFrame]:
    """Return the FINRA margin statistics as a DataFrame, using local cache when possible."""

    FINRA_LOGGER.info("Ensuring FINRA margin statistics (ttl_days=%s)", ttl_days)
    path = resource_fetcher.ensure(
        "FINRA-Margin_Statistics",
        ttl_days=ttl_days,
        filename="margin-statistics.xlsx",
    )
    if path is None or not path.exists():
        FINRA_LOGGER.warning("FINRA margin statistics unavailable after ensure()")
        return None

    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception as exc:
        FINRA_LOGGER.warning("Failed to read FINRA margin statistics %s: %s", path, exc)
        return None

    if df is None or df.empty:
        FINRA_LOGGER.warning("FINRA margin statistics empty at %s", path)
        return None

    df.columns = [str(col).strip() for col in df.columns]
    if "Year-Month" in df.columns:
        df = df.dropna(subset=["Year-Month"])
        try:
            df["Year-Month"] = pd.to_datetime(df["Year-Month"], format="%Y-%m")
        except (ValueError, TypeError):
            df["Year-Month"] = pd.to_datetime(df["Year-Month"], errors="coerce")
    FINRA_LOGGER.info(
        "Loaded FINRA margin statistics with %d rows and %d columns",
        len(df),
        len(df.columns),
    )
    return df
