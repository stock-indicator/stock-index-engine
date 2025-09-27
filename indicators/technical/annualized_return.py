from __future__ import annotations

from common.config import ANNUAL_RETURN_WINDOW, INDEX_TICKERS
from common.fetchers import MarketDataFetcher
from indicators.base import BaseIndicator, IndicatorMetadata


class AnnualizedReturnIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="12M Annualized Return",
        category="Technical",
        threshold="> 40%",
        markets=["US Market", "Nasdaq 100"],
        topics=["Technical", "Momentum"],
    )

    def evaluate(self, fetcher: MarketDataFetcher):
        ticker = INDEX_TICKERS["Nasdaq 100"]
        try:
            history = fetcher.get_price_history(ticker, period="max")
            adj_close = history["Adj Close"].dropna()
            if len(adj_close) <= ANNUAL_RETURN_WINDOW:
                raise ValueError("Insufficient history for 12-month return")
            current_price = adj_close.iat[-1]
            past_price = adj_close.iat[-ANNUAL_RETURN_WINDOW]
            annual_return = (current_price / past_price - 1) * 100
            status = "high" if annual_return > 40 else "normal"
            raw_value = f"{annual_return:.2f}%"
            pure_value = [
                {"market": "Nasdaq 100", "annualized_return_pct": annual_return}
            ]
            return self.build_result(
                raw_value=raw_value,
                pure_value=pure_value,
                status=status,
                notes="Trailing 252-trading-day return computed from adjusted close.",
            )
        except Exception as exc:  # pylint: disable=broad-except
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes=f"12M annualized return failed: {exc}",
            )
