from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from common.config import (
    INDEX_TICKERS,
    MACD_FAST,
    MACD_LOOKBACK,
    MACD_SIGNAL,
    MACD_SLOW,
)
from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


def _compute_macd(prices: pd.Series) -> pd.DataFrame:
    ema_fast = prices.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = prices.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": histogram})


class BaseMACDDivergenceIndicator(PriceSeriesIndicator):
    market_label: str
    tickers: Dict[str, str]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        series_map = self.prepare_price_series(clean_df)
        del fetcher
        series = series_map.get(self.market_label)
        if series is None or series.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"No price history available for {self.market_label}.",
            )

        macd_df = _compute_macd(series).dropna()
        if macd_df.empty or len(macd_df) < MACD_LOOKBACK:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Insufficient data to compute MACD divergence for {self.market_label}.",
            )

        price_window = series.iloc[-MACD_LOOKBACK:]
        macd_window = macd_df["macd"].iloc[-MACD_LOOKBACK:]
        price_new_high = bool(series.iloc[-1] >= price_window.max() * 0.999)
        macd_new_high = bool(macd_df["macd"].iloc[-1] >= macd_window.max() * 0.999)
        divergence = price_new_high and not macd_new_high

        latest_macd = float(macd_df["macd"].iloc[-1])
        latest_signal = float(macd_df["signal"].iloc[-1])
        latest_hist = float(macd_df["hist"].iloc[-1])
        latest_price = float(series.iloc[-1])

        status = "high" if divergence else "normal"
        note = f"MACD divergence check for {self.market_label}"
        if divergence:
            note += "; price made new high without MACD confirmation"
        else:
            note += "; no bearish divergence detected"

        details_entry = {
            "market": self.market_label,
            "indicator_value": latest_macd,
            "macd": latest_macd,
            "signal": latest_signal,
            "hist": latest_hist,
            "price": latest_price,
            "price_new_high": price_new_high,
            "macd_new_high": macd_new_high,
            "divergence": divergence,
        }

        raw_value = (
            f"price_new_high={price_new_high}; macd_new_high={macd_new_high}; macd={latest_macd:.2f}"
        )

        return self.build_result(
            raw_value=raw_value,
            pure_value=[details_entry],
            status=status,
            notes=note,
        )

    def build_history_series(
        self,
        clean_df: pd.DataFrame,
        *,
        status_map: Dict[str, str],
        as_of: datetime,
        lookback_days: int,
    ) -> Optional[List[Dict[str, object]]]:
        series_map = self.prepare_price_series(clean_df)
        series = series_map.get(self.market_label)
        if series is None or series.empty:
            return None

        cutoff_date = as_of.date() - timedelta(days=lookback_days)
        upper_date = as_of.date()
        series = series[(series.index.date >= cutoff_date) & (series.index.date <= upper_date)]
        if series.empty:
            return None

        macd_df = _compute_macd(series).dropna()
        macd_df = macd_df[(macd_df.index.date >= cutoff_date) & (macd_df.index.date <= upper_date)]
        if macd_df.empty:
            return None

        aligned_prices = series.reindex(macd_df.index)
        price_roll_max = aligned_prices.rolling(window=MACD_LOOKBACK).max()
        macd_roll_max = macd_df["macd"].rolling(window=MACD_LOOKBACK).max()
        price_new_high_series = aligned_prices >= (price_roll_max * 0.999)
        macd_new_high_series = macd_df["macd"] >= (macd_roll_max * 0.999)
        divergence_series = price_new_high_series & (~macd_new_high_series)

        history: List[Dict[str, object]] = []
        for ts, row in macd_df.iterrows():
            date_key = ts.date().isoformat()
            details = {
                "market": self.market_label,
                "indicator_value": float(row["macd"]),
                "macd": float(row["macd"]),
                "signal": float(row["signal"]),
                "hist": float(row["hist"]),
                "price": float(aligned_prices.loc[ts]),
                "price_new_high": bool(price_new_high_series.loc[ts]),
                "macd_new_high": bool(macd_new_high_series.loc[ts]),
                "divergence": bool(divergence_series.loc[ts]),
            }
            history.append(
                {
                    "date": date_key,
                    "status": status_map.get(date_key),
                    "summary_value": float(row["macd"]),
                    "details": details,
                }
            )

        history.sort(key=lambda item: item["date"])
        return history


class MACDSP500Indicator(BaseMACDDivergenceIndicator):
    market_label = "S&P 500"
    slug_override = "macd_divergence_s_p_500"
    metadata = IndicatorMetadata(
        name="MACD Divergence (S&P 500)",
        category="Technical",
        threshold="Bearish divergence",
        markets=[market_label],
        topics=["Technical", "Trend"],
        description="Identifies a bearish divergence where the index price reaches a new high but the MACD indicator fails to confirm with a new high of its own, signaling weakening momentum.",
    )
    tickers = {market_label: INDEX_TICKERS["S&P 500"]}


class MACDNasdaqIndicator(BaseMACDDivergenceIndicator):
    market_label = "Nasdaq 100"
    slug_override = "macd_divergence_nasdaq_100"
    metadata = IndicatorMetadata(
        name="MACD Divergence (Nasdaq 100)",
        category="Technical",
        threshold="Bearish divergence",
        markets=[market_label],
        topics=["Technical", "Trend"],
    )
    tickers = {market_label: INDEX_TICKERS["Nasdaq 100"]}
