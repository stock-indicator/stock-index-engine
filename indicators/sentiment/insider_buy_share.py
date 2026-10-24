"""Insider Buy Share: how much insider money is buying versus selling.

Source: SEC Form 4 filings for S&P 500 issuers, fetched with edgartools.

Method
------
* Only open-market trades are counted: code P (purchase) and code S (sale).
  Grants (A), option exercises (M), tax withholding (F), gifts (G) and other
  non-discretionary codes are excluded.
* Equity swaps are excluded.
* Sell-to-cover sales are excluded. These are code-S sales that the footnotes
  describe as covering tax on vesting awards, so they say nothing about how the
  insider views the stock.
* Each trade is valued at shares x price. The daily buy and sell values are
  summed, then rolled over 30 and 90 calendar days.
* Buy share (%) = buy value / (buy value + sell value) x 100. A value of 50
  means buys and sales are equal in dollars. The scale is 0-100, like the AAII
  bullish percentage.
* Prices are sanity-checked. A few filings report a price 1000x too large
  (for example 1031414 instead of 1031.414), which would inflate the sell side
  badly. Trades priced above ``MAX_PLAUSIBLE_PRICE``, or more than
  ``PRICE_OUTLIER_RATIO`` away from the issuer's median price in the same
  window, are dropped.
* ``high`` means insiders are selling heavily: the 90-day buy share is at or
  below the bottom ``LOW_TAIL_QUANTILE`` of its own trailing year. A fixed
  cutoff does not work here. Insider buying is rare, so the typical reading sits
  near 2-3%, and a fixed 10% cutoff would be "high" almost every day. Heavy
  insider selling into strength is a market-top warning, the same reading as the
  other Sentiment indicators.

Universe: current S&P 500 members from the Wikipedia constituents table. To
track a custom set of tickers instead, set ``insider_buy_share.universe`` in
settings.json.

Form 4 filings are due within two business days of the trade, but late filings
happen. Each incremental run therefore re-reads the last
``REVISION_OVERLAP_DAYS`` of trade dates, so late filings are picked up.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from common.fetchers import fetch_sp500_constituents
from common.models import IndicatorResult
from common.sec_edgar import (
    load_cached_transactions,
    require_edgar_identity,
    resolve_ciks,
    sync_form4_filings,
)
from common.settings import settings
from indicators.base import BaseIndicator, IndicatorMetadata, compute_end_date


SHORT_WINDOW_DAYS = 30
LONG_WINDOW_DAYS = 90
REVISION_OVERLAP_DAYS = 30
MIN_TRADES_LONG_WINDOW = 30
# "high" when the 90-day buy share is at or below this quantile of its trailing year.
LOW_TAIL_QUANTILE = 0.10
THRESHOLD_LOOKBACK_DAYS = 365
THRESHOLD_MIN_DAYS = 180
MAX_PLAUSIBLE_PRICE = 100_000.0  # no S&P 500 share trades anywhere near this
PRICE_OUTLIER_RATIO = 100.0
# Trades footnoted as Rule 10b5-1 plans were set up in advance, so they say less
# about current views. They stay in by default. Flip this to measure without them.
EXCLUDE_10B5_1 = False

_VALUE_COLUMNS = ["buy_value_usd", "sell_value_usd", "buy_count", "sell_count"]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _round_or_none(value: float) -> Optional[float]:
    return None if pd.isna(value) else round(float(value), 2)


def _load_universe() -> Dict[int, str]:
    """Map issuer CIK to ticker. Configured tickers win over the S&P 500 list."""

    configured = settings.get("insider_buy_share.universe")
    if configured:
        return resolve_ciks(configured)
    constituents = fetch_sp500_constituents(ttl_days=30)
    if constituents is None or constituents.empty:
        return {}
    return dict(zip(constituents["cik"], constituents["symbol"]))


class InsiderBuyShareIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Insider Buy Share",
        category="Sentiment",
        threshold="Bottom 10% of past year",
        markets=["S&P 500"],
        topics=["Sentiment", "Insider"],
        description=(
            "Share of insider trading dollars that are purchases rather than sales, across "
            "S&P 500 companies, from SEC Form 4 filings. Grants, option exercises, tax "
            "withholding and sell-to-cover sales are excluded. Heavy insider selling into "
            "a rally has historically preceded market tops."
        ),
    )
    default_history_days = 365

    # ------------------------------------------------------------------
    # Data lifecycle
    # ------------------------------------------------------------------
    def collect_full(self, fetcher=None) -> pd.DataFrame:
        today = _today()
        # The 90-day rolling window needs trades from before the history window.
        start = today - timedelta(days=self.get_history_window_days() + LONG_WINDOW_DAYS)
        return self._collect(start, today)

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher=None):
        last_date = pd.to_datetime(existing_clean["data_start_date"]).max().date()
        start = last_date - timedelta(days=REVISION_OVERLAP_DAYS)
        raw = self._collect(start, _today())
        return raw if not raw.empty else None

    def _collect(self, start, end) -> pd.DataFrame:
        require_edgar_identity()
        universe = _load_universe()
        if not universe:
            self.logger.warning("No issuer universe available; skipping Form 4 collection")
            return pd.DataFrame()
        stats = sync_form4_filings(list(universe), start, end)
        self.logger.info(
            "Form 4 cache synced for %d issuers: fetched=%d failed=%d",
            len(universe),
            stats.fetched,
            stats.failed,
        )
        return load_cached_transactions(set(universe), start, end)

    def clean_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        trades = raw[raw["code"].isin(["P", "S"])]
        trades = trades[~trades["equity_swap"].astype(bool)]
        trades = trades[~((trades["code"] == "S") & trades["tax_related"].astype(bool))]
        if EXCLUDE_10B5_1:
            trades = trades[~trades["plan_10b5_1"].astype(bool)]
        prices = pd.to_numeric(trades["price"], errors="coerce")
        median_price = prices.groupby(trades["issuer_cik"]).transform("median")
        ratio = prices / median_price
        implausible = (prices > MAX_PLAUSIBLE_PRICE) | (ratio > PRICE_OUTLIER_RATIO) | (
            ratio < 1 / PRICE_OUTLIER_RATIO
        )
        implausible = implausible.fillna(True)
        if implausible.any():
            self.logger.warning("Dropped %d trades with implausible prices", int(implausible.sum()))
        trades = trades[~implausible]
        values = pd.to_numeric(trades["shares"], errors="coerce") * prices[trades.index]
        trades = trades.assign(value_usd=values)
        trades = trades[np.isfinite(trades["value_usd"]) & (trades["value_usd"] > 0)]
        if trades.empty:
            return pd.DataFrame()

        buys = (
            trades[trades["code"] == "P"]
            .groupby("transaction_date")
            .agg(buy_value_usd=("value_usd", "sum"), buy_count=("value_usd", "size"))
        )
        sells = (
            trades[trades["code"] == "S"]
            .groupby("transaction_date")
            .agg(sell_value_usd=("value_usd", "sum"), sell_count=("value_usd", "size"))
        )
        daily = buys.join(sells, how="outer").fillna(0.0).reset_index()
        daily["buy_count"] = daily["buy_count"].astype(int)
        daily["sell_count"] = daily["sell_count"].astype(int)
        daily["data_start_date"] = pd.to_datetime(daily["transaction_date"])
        daily = daily.sort_values("data_start_date").reset_index(drop=True)
        daily["data_end_date"] = compute_end_date(daily["data_start_date"].tolist())
        return daily[["data_start_date", "data_end_date", *_VALUE_COLUMNS]]

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    @staticmethod
    def _rolling(clean_df: pd.DataFrame) -> pd.DataFrame:
        """Daily frame with rolling 30d and 90d buy share, indexed by calendar day.

        ``complete`` is False for days where the 90-day window reaches before
        the earliest cached trade date, so those values are partial.
        """

        daily = clean_df.assign(data_start_date=pd.to_datetime(clean_df["data_start_date"]))
        daily = daily.set_index("data_start_date")[_VALUE_COLUMNS].astype(float).sort_index()
        daily = daily.groupby(level=0).sum()
        calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
        daily = daily.reindex(calendar, fill_value=0.0)

        frame = pd.DataFrame(index=calendar)
        for window in (SHORT_WINDOW_DAYS, LONG_WINDOW_DAYS):
            buy = daily["buy_value_usd"].rolling(window, min_periods=1).sum()
            sell = daily["sell_value_usd"].rolling(window, min_periods=1).sum()
            total = buy + sell
            frame[f"buy_share_{window}d_pct"] = (100 * buy / total).where(total > 0)
            frame[f"buy_value_{window}d_usd"] = buy
            frame[f"sell_value_{window}d_usd"] = sell
        frame["trades_90d"] = (daily["buy_count"] + daily["sell_count"]).rolling(
            LONG_WINDOW_DAYS, min_periods=1
        ).sum()
        frame["complete"] = frame.index >= calendar[0] + pd.Timedelta(days=LONG_WINDOW_DAYS - 1)
        share_complete = frame[f"buy_share_{LONG_WINDOW_DAYS}d_pct"].where(frame["complete"])
        frame["threshold_pct"] = share_complete.rolling(
            THRESHOLD_LOOKBACK_DAYS, min_periods=THRESHOLD_MIN_DAYS
        ).quantile(LOW_TAIL_QUANTILE)
        return frame

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df is None or clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No insider trades cached for the tracked universe.",
            )

        frame = self._rolling(clean_df)
        latest = frame.iloc[-1]
        as_of = frame.index[-1].date().isoformat()
        share_long = latest[f"buy_share_{LONG_WINDOW_DAYS}d_pct"]
        trades_long = int(latest["trades_90d"])

        if not latest["complete"]:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Less than {LONG_WINDOW_DAYS} days of Form 4 history cached.",
            )
        if pd.isna(share_long) or trades_long < MIN_TRADES_LONG_WINDOW:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Fewer than {MIN_TRADES_LONG_WINDOW} insider trades in the 90-day window.",
            )

        threshold = latest["threshold_pct"]
        if pd.isna(threshold):
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"Needs {THRESHOLD_MIN_DAYS} days of 90-day readings to set the low-tail threshold.",
            )

        share_short = latest[f"buy_share_{SHORT_WINDOW_DAYS}d_pct"]
        buy_long = float(latest[f"buy_value_{LONG_WINDOW_DAYS}d_usd"])
        sell_long = float(latest[f"sell_value_{LONG_WINDOW_DAYS}d_usd"])

        status = "high" if share_long <= threshold else "normal"
        notes = (
            f"Insiders are selling heavily: 90-day buy share is in the bottom "
            f"{LOW_TAIL_QUANTILE:.0%} of the past year"
            if status == "high"
            else f"Insider buy share is above the bottom {LOW_TAIL_QUANTILE:.0%} of the past year"
        )
        raw_value = (
            f"90d buy share: {share_long:.1f}% vs {threshold:.1f}% low-tail threshold "
            f"(buy ${buy_long / 1e6:,.0f}M, sell ${sell_long / 1e6:,.0f}M, as of {as_of})"
        )
        if not pd.isna(share_short):
            raw_value += f"; 30d: {share_short:.1f}%"
        pure_value = [
            {"metric": "buy_share_90d_pct", "value": round(float(share_long), 2), "as_of": as_of},
            {"metric": "low_tail_threshold_pct", "value": round(float(threshold), 2), "as_of": as_of},
            {"metric": "buy_value_90d_usd", "value": round(buy_long, 2), "as_of": as_of},
            {"metric": "sell_value_90d_usd", "value": round(sell_long, 2), "as_of": as_of},
            {"metric": "trades_90d", "value": trades_long, "as_of": as_of},
        ]
        if not pd.isna(share_short):
            pure_value.insert(
                1,
                {"metric": "buy_share_30d_pct", "value": round(float(share_short), 2), "as_of": as_of},
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
        frame = self._rolling(clean_df)
        frame = frame[frame["complete"]]
        cutoff = pd.Timestamp(as_of.date() - timedelta(days=lookback_days))
        frame = frame[frame.index >= cutoff]

        series: List[Dict[str, object]] = []
        for day, row in frame.iterrows():
            share = row[f"buy_share_{LONG_WINDOW_DAYS}d_pct"]
            threshold = row["threshold_pct"]
            if pd.isna(share) or pd.isna(threshold) or row["trades_90d"] < MIN_TRADES_LONG_WINDOW:
                continue
            series.append(
                {
                    "date": day.date().isoformat(),
                    "status": "high" if share <= threshold else "normal",
                    "summary_value": round(float(share), 2),
                    "details": {
                        "buy_share_90d_pct": round(float(share), 2),
                        "buy_share_30d_pct": _round_or_none(row[f"buy_share_{SHORT_WINDOW_DAYS}d_pct"]),
                        "low_tail_threshold_pct": round(float(threshold), 2),
                        "buy_value_90d_usd": round(float(row[f"buy_value_{LONG_WINDOW_DAYS}d_usd"]), 2),
                        "sell_value_90d_usd": round(float(row[f"sell_value_{LONG_WINDOW_DAYS}d_usd"]), 2),
                        "trades_90d": int(row["trades_90d"]),
                    },
                }
            )
        return series
