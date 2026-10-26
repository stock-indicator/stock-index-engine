from __future__ import annotations

import re

import pandas as pd
import requests
from bs4 import BeautifulSoup

from indicators.base import BaseIndicator, compute_end_date

MULTPL_BASE_URL = "https://www.multpl.com"


def fetch_multpl_table(table_slug: str, period: str = "by-quarter") -> pd.DataFrame:
    """Raw ``date``/``value`` text cells of a multpl.com history table, newest first.

    The first row is multpl's estimate for the current day; the rest are
    one row per month (or quarter).
    """
    url = f"{MULTPL_BASE_URL}/{table_slug}/table/{period}"
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if table is None:
        return pd.DataFrame()
    tbody = table.find("tbody") or table
    rows = []
    for tr in tbody.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) >= 2:
            rows.append(cols[:2])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["date", "value"])


class MultplIndicator(BaseIndicator):
    table_slug: str = ""

    def collect_full(self, fetcher=None) -> pd.DataFrame:
        return fetch_multpl_table(self.table_slug)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        df["data_start_date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        df["value"] = df["value"].apply(self._parse_value)
        df = df.dropna(subset=["value"])
        df = df.sort_values("data_start_date")
        end_dates = compute_end_date(df["data_start_date"].tolist())
        df["data_end_date"] = end_dates
        df["source_url"] = f"{MULTPL_BASE_URL}/{self.table_slug}"
        return df[["data_start_date", "data_end_date", "value"]]

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None):
        # Multpl 不提供增量接口，直接重新抓取全集后由 merge 去重
        return self.collect_full()

    @staticmethod
    def _parse_value(value: str) -> float:
        cleaned = re.sub(r"[^0-9.+-]", "", value)
        if not cleaned:
            return float("nan")
        try:
            return float(cleaned)
        except ValueError:
            return float("nan")

    def merge_clean_data(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        combined = super().merge_clean_data(existing, new)
        return combined.drop_duplicates(subset="data_start_date", keep="last")
