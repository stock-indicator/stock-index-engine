from __future__ import annotations

from common.config import INDEX_TICKERS, ANNUAL_RETURN_WINDOW
from common.models import IndicatorResult
from indicators.base import IndicatorMetadata
from indicators.technical.base_price import PriceSeriesIndicator


class AnnualizedReturnIndicator(PriceSeriesIndicator):
    metadata = IndicatorMetadata(
        name="12M Annualized Return",
        category="Technical",
        threshold="> 40%",
        markets=["US Market", "Nasdaq 100"],
        topics=["Technical", "Momentum"],
    )
    tickers = {"Nasdaq 100": INDEX_TICKERS["Nasdaq 100"]}

    def compute(self, clean_df, fetcher) -> IndicatorResult:
        series_by_market = self.prepare_price_series(clean_df)
        series = series_by_market.get("Nasdaq 100")
        if series is None or series.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="No Nasdaq 100 price history available.",
            )

        if len(series) <= ANNUAL_RETURN_WINDOW:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="Insufficient history for 12-month return.",
            )

        current_price = float(series.iloc[-1])
        past_price = float(series.iloc[-ANNUAL_RETURN_WINDOW])
        annual_return = (current_price / past_price - 1) * 100
        status = "high" if annual_return > 40 else "normal"
        pure_value = [
            {
                "market": "Nasdaq 100",
                "annualized_return_pct": annual_return,
                "current_price": current_price,
                "price_252d_ago": past_price,
            }
        ]
        return self.build_result(
            raw_value=f"{annual_return:.2f}%",
            pure_value=pure_value,
            status=status,
            notes="Trailing 252-trading-day return computed from adjusted close.",
        )
