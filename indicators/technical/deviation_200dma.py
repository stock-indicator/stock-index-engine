from __future__ import annotations

from typing import Dict

from common.config import INDEX_TICKERS, MOVING_AVG_WINDOW
from common.fetchers import MarketDataFetcher
from common.utils import summarize_values
from indicators.base import BaseIndicator, IndicatorMetadata


class Price200DMADeviationIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="Price vs 200DMA",
        category="Technical",
        threshold="> 25%",
        markets=["US Market", "S&P 500", "Nasdaq 100"],
        topics=["Technical", "Trend"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        values: Dict[str, float] = {}
        missing: Dict[str, str] = {}
        for market, ticker in INDEX_TICKERS.items():
            try:
                history = fetcher.get_price_history(ticker, period="5y")
                adj_close = history["Adj Close"].dropna()
                ma = adj_close.rolling(window=MOVING_AVG_WINDOW).mean()
                latest_ma = ma.iat[-1]
                if latest_ma != latest_ma:  # NaN check
                    raise ValueError("Insufficient data for 200DMA")
                deviation = (adj_close.iat[-1] - latest_ma) / latest_ma * 100
                values[market] = float(deviation)
            except Exception as exc:  # pylint: disable=broad-except
                missing[market] = str(exc)

        if not values:
            note = "200DMA deviation failed for all indices: " + "; ".join(
                f"{k} ({v})" for k, v in missing.items()
            )
            return self.build_result(raw_value=None, pure_value=None, status="unavailable", notes=note)

        status = "high" if any(val > 25 for val in values.values()) else "normal"
        note_suffix = ""
        if missing:
            note_suffix = "; missing: " + "; ".join(f"{k} ({v})" for k, v in missing.items())

        pure_value = [
            {"market": market, "deviation_pct": float(value)}
            for market, value in values.items()
        ]

        return self.build_result(
            raw_value=summarize_values(values, unit="%"),
            pure_value=pure_value,
            status=status,
            notes="Deviation from 200-day moving average" + note_suffix,
        )
