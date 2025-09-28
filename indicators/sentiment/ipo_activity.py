from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from common.fetchers import fetch_renaissance_ipo_stats
from common.models import IndicatorResult
from indicators.base import BaseIndicator, IndicatorMetadata


class IPOActivityIndicator(BaseIndicator):
    metadata = IndicatorMetadata(
        name="IPO Activity",
        category="Sentiment",
        threshold="Frothy",
        markets=["US Market"],
        topics=["Sentiment", "IPO"],
    )
    default_history_days = 365 * 10

    def collect_full(self, fetcher) -> Any:
        data = fetch_renaissance_ipo_stats(ttl_days=1)
        return data if data is not None else {}

    def collect_incremental(self, existing_clean: pd.DataFrame, fetcher) -> Any:
        return self.collect_full(fetcher)

    def clean_data(self, raw: Any) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame()

        annual = raw.get("annual", []) if isinstance(raw, dict) else []
        monthly = raw.get("monthly", []) if isinstance(raw, dict) else []
        as_of_value = raw.get("as_of") if isinstance(raw, dict) else None
        as_of_ts = pd.to_datetime(as_of_value, errors="coerce") if as_of_value else pd.NaT

        rows = []

        for record in annual:
            year = record.get("year")
            if year is None:
                continue
            try:
                year_int = int(year)
            except (TypeError, ValueError):
                continue
            start = pd.Timestamp(year=year_int, month=1, day=1)
            end = pd.Timestamp(year=year_int, month=12, day=31)
            rows.append(
                {
                    "period_type": "annual",
                    "period_label": str(year_int),
                    "data_start_date": start,
                    "data_end_date": end,
                    "ipo_count": record.get("ipo_count"),
                    "proceeds_billion": record.get("proceeds_billion"),
                    "as_of": as_of_ts,
                }
            )

        for record in monthly:
            year = record.get("year")
            month = record.get("month")
            if year is None or month is None:
                continue
            try:
                year_int = int(year)
                month_int = int(month)
            except (TypeError, ValueError):
                continue
            if month_int < 1 or month_int > 12:
                continue
            start = pd.Timestamp(year=year_int, month=month_int, day=1)
            end = start + pd.offsets.MonthEnd(0)
            rows.append(
                {
                    "period_type": "monthly",
                    "period_label": f"{year_int}-{month_int:02d}",
                    "data_start_date": start,
                    "data_end_date": end,
                    "ipo_count": record.get("ipo_count"),
                    "proceeds_billion": None,
                    "as_of": as_of_ts,
                }
            )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["data_start_date"] = pd.to_datetime(df["data_start_date"], errors="coerce")
        df["data_end_date"] = pd.to_datetime(df["data_end_date"], errors="coerce")
        df["ipo_count"] = pd.to_numeric(df["ipo_count"], errors="coerce")
        if "proceeds_billion" in df.columns:
            df["proceeds_billion"] = pd.to_numeric(df["proceeds_billion"], errors="coerce")
        df["as_of"] = pd.to_datetime(df["as_of"], errors="coerce")
        df = df.dropna(subset=["data_start_date"])
        df = df.sort_values(["data_start_date", "period_type"]).reset_index(drop=True)
        return df[
            [
                "period_type",
                "period_label",
                "data_start_date",
                "data_end_date",
                "ipo_count",
                "proceeds_billion",
                "as_of",
            ]
        ]

    def compute(self, clean_df: pd.DataFrame, fetcher) -> IndicatorResult:
        if clean_df.empty:
            return self.build_result(
                raw_value=None,
                pure_value=None,
                status="unavailable",
                notes="IPO dataset empty.",
            )

        df = clean_df.copy()
        df["ipo_count"] = pd.to_numeric(df["ipo_count"], errors="coerce")
        df["proceeds_billion"] = pd.to_numeric(df["proceeds_billion"], errors="coerce")

        as_of_series = df["as_of"].dropna()
        as_of_ts: Optional[pd.Timestamp] = as_of_series.iloc[-1] if not as_of_series.empty else None
        as_of_str = as_of_ts.date().isoformat() if as_of_ts is not None else "unknown"

        annual_df = (
            df[df["period_type"] == "annual"].dropna(subset=["ipo_count"]).sort_values("data_start_date")
        )
        monthly_df = (
            df[df["period_type"] == "monthly"].dropna(subset=["ipo_count"]).sort_values("data_start_date")
        )

        trailing_count: Optional[float] = None
        trailing_months = 0
        trailing_start = trailing_end = None
        if not monthly_df.empty:
            if as_of_ts is not None:
                monthly_df = monthly_df[monthly_df["data_start_date"] <= as_of_ts]
            if not monthly_df.empty:
                trailing_window = monthly_df.tail(12)
                trailing_months = len(trailing_window)
                trailing_count = float(trailing_window["ipo_count"].sum())
                trailing_start = trailing_window.iloc[0]["data_start_date"].date().isoformat()
                trailing_end = trailing_window.iloc[-1]["data_start_date"].date().isoformat()

        last_full_year_row = None
        current_year_row = None
        if not annual_df.empty:
            if as_of_ts is not None:
                current_year = as_of_ts.year
                completed_mask = annual_df["data_start_date"].dt.year < current_year
                completed_years = annual_df[completed_mask]
                if not completed_years.empty:
                    last_full_year_row = completed_years.iloc[-1]
                current_year_rows = annual_df[annual_df["data_start_date"].dt.year == current_year]
                if not current_year_rows.empty:
                    current_year_row = current_year_rows.iloc[-1]
            if last_full_year_row is None:
                last_full_year_row = annual_df.iloc[-1]

        mania_threshold_count = 200
        mania_threshold_proceeds = 100.0
        mania = False
        reasons = []

        def as_int(value: Optional[float]) -> Optional[int]:
            if value is None or pd.isna(value):
                return None
            return int(round(float(value)))

        def as_float(value: Optional[float]) -> Optional[float]:
            if value is None or pd.isna(value):
                return None
            return float(value)

        trailing_count_int = as_int(trailing_count)
        if trailing_count_int is not None and trailing_months >= 12 and trailing_count_int >= mania_threshold_count:
            mania = True
            reasons.append(
                f"12M IPO count {trailing_count_int} >= {mania_threshold_count}"
            )

        last_full_year_count = None
        last_full_year_proceeds = None
        last_full_year_label = None
        if last_full_year_row is not None:
            last_full_year_count = as_int(last_full_year_row.get("ipo_count"))
            last_full_year_proceeds = as_float(last_full_year_row.get("proceeds_billion"))
            last_full_year_label = last_full_year_row["period_label"]
            if last_full_year_count is not None and last_full_year_count >= mania_threshold_count:
                mania = True
                reasons.append(
                    f"{last_full_year_label} IPO count {last_full_year_count} >= {mania_threshold_count}"
                )
            if (
                last_full_year_proceeds is not None
                and last_full_year_proceeds >= mania_threshold_proceeds
            ):
                mania = True
                reasons.append(
                    f"{last_full_year_label} proceeds ${last_full_year_proceeds:.1f}B >= {mania_threshold_proceeds}B"
                )

        current_year_count = None
        if current_year_row is not None:
            current_year_count = as_int(current_year_row.get("ipo_count"))

        status = "high" if mania else "normal"
        if mania:
            notes = "IPO market running hot; " + "; ".join(reasons)
        else:
            notes = "IPO activity below mania threshold"
            if trailing_months and trailing_months < 12:
                notes += f" (only {trailing_months} months of data)"

        raw_parts = []
        if trailing_count_int is not None:
            window_label = (
                f"{trailing_start} to {trailing_end}"
                if trailing_start and trailing_end
                else "last available months"
            )
            raw_parts.append(f"Trailing 12M IPOs ({window_label}): {trailing_count_int}")
        if last_full_year_count is not None:
            if last_full_year_proceeds is not None:
                raw_parts.append(
                    f"{last_full_year_label} IPOs: {last_full_year_count} (${last_full_year_proceeds:.1f}B)"
                )
            else:
                raw_parts.append(f"{last_full_year_label} IPOs: {last_full_year_count}")
        if current_year_count is not None and as_of_ts is not None:
            raw_parts.append(f"{as_of_ts.year} YTD IPOs: {current_year_count}")
        raw_value = "; ".join(raw_parts) if raw_parts else None

        pure_value = []
        if trailing_count_int is not None:
            pure_value.append(
                {
                    "metric": "trailing_12m_ipo_count",
                    "value": trailing_count_int,
                    "window_start": trailing_start,
                    "window_end": trailing_end,
                    "as_of": as_of_str,
                }
            )
        if last_full_year_count is not None:
            pure_value.append(
                {
                    "metric": "last_full_year_ipo_count",
                    "value": last_full_year_count,
                    "year": last_full_year_label,
                    "proceeds_billion": last_full_year_proceeds,
                }
            )
        if current_year_count is not None and as_of_ts is not None:
            pure_value.append(
                {
                    "metric": "current_year_ipo_count",
                    "value": current_year_count,
                    "year": as_of_ts.year,
                }
            )

        return self.build_result(
            raw_value=raw_value,
            pure_value=pure_value or None,
            status=status,
            notes=notes,
        )
