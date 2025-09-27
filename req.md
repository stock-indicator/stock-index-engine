# Project Requirements

## Objectives
- Track S&P 500 and Nasdaq 100 market-top warning indicators listed in `indicies.md`.
- Fetch required market, sentiment, and macro data on-demand (manual run for v0) and evaluate each indicator against its historical threshold.
- Produce a daily status JSON payload showing which indicators are in the "high" zone and a CSV log that records indicator hits per day (e.g., `RSI: 6/20` meaning 6 of 20 thresholds currently triggered).

## Tech Stack
- Language: Python 3.x.
- Core libraries: `pandas`, `yfinance`, `requests`, `python-dateutil` (time handling), optional `fredapi` for FRED series.
- Packaging: plain script for now with view to containerize (Docker) later.

## Data Sources & Coverage
- Price-derived metrics (RSI, MACD divergence, 200-day deviation, 12M annualized return, VIX) via Yahoo Finance / yfinance, plus custom calculations for technical indicators.
- Valuation metrics:
  - Index PE, PB, P/S, dividend yield via FRED (SP500), Multpl.com, or S&P Global CSVs (to be scripted if public endpoints permit; otherwise flagged for semi-manual input).
  - CAPE via Robert Shiller dataset or Multpl.com CSV download.
- Sentiment metrics:
  - Margin debt: FINRA monthly dataset (CSV download).
  - Retail positioning: AAII survey CSV/JSON (weekly), VandaTrack/JPM data currently assumed manual or requires subscription (flagged as backlog until access arranged).
  - ETF net inflow streaks: requires ETF.com or other feed; tentatively plan for scripted scrape if TOS allows, otherwise backlog.
  - IPO activity: Renaissance Capital / NASDAQ data (likely CSV scrape or manual import; backlog pending access method).
  - Smart vs Dumb Money: SentimenTrader is paid; for MVP mark as TBD or rely on CNN Fear & Greed as proxy if acceptable.
- Macro metrics via FRED (GS10, CPIAUCSL, T10Y2Y, FEDFUNDS) and BIS/World Bank for Credit-to-GDP (quarterly, may need manual download).

## Outputs
- JSON response: aggregated indicator status for the current run including raw value, threshold, status (`high`/`normal`), and optional commentary.
- CSV log: append-or-create daily row with date, indicator statuses, and counts of triggered indicators to support historical tracking.

## Workflow (v0)
1. One-shot Python script invoked manually.
2. Script fetches all available data, computes metrics, maps to thresholds, and writes JSON + CSV files.
3. Missing/paid data sources return placeholder status and are surfaced in the JSON for manual follow-up.
4. Automation (daily scheduler, Docker packaging) deferred to later iteration.

## Open Questions / Follow-ups
- Confirm acceptable proxies or alternative data feeds for metrics requiring paid sources (Smart vs Dumb Money, ETF flows, IPO activity, retail positioning beyond AAII).
- Decide storage location and filename conventions for the JSON and CSV outputs.
- Clarify whether indicator streaks (e.g., `6/20`) should be counted across categories or all indicators combined, and whether partial availability should affect the denominator.
- Determine tolerance for data latency on monthly/quarterly series when generating daily reports.