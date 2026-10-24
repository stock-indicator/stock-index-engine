[中文](README.zh-CN.md)

# Stock Index Engine

## Overview

The Stock Index Engine is a Python-based tool for fetching, calculating, and evaluating a wide range of financial market indicators. It gathers data from various sources to create a comprehensive view of market health, covering valuation, sentiment, momentum, and macroeconomic factors. The engine's primary goal is to produce a consolidated "market status" report, which can be used for analysis and decision-making.

## Features

*   **Comprehensive Indicator Library:** Tracks over 20 key market indicators.
*   **Categorization:** Organizes indicators into four main categories: Valuation, Sentiment, Macroeconomic, and Technical.
*   **Data Fetching & Caching:** Downloads and caches data from various sources (e.g., FRED for economic data) to the `resources/` directory.
*   **Data Output:** Generates detailed historical data and a real-time summary in JSON and CSV formats in the `output/` directory.
*   **API Server:** Includes a FastAPI server to expose the data and trigger refreshes.
*   **Containerized:** Provides a Dockerfile for easy, self-contained deployment.

## How to Use

### 1. Configuration (API Keys)

Before running the engine, you must provide the necessary API keys.

1.  Create a file named `api.key` in the `stock-index-engine` directory.
2.  Add your keys in a `KEY=VALUE` format. For example:
    ```
    FRED_API_KEY=your_fred_api_key_here
    ANOTHER_API_KEY=your_other_key_here
    ```

The engine can also read keys from environment variables. If an environment variable and an `api.key` entry both exist for the same key, the environment variable will be used.

The Insider Buy Share indicator reads SEC EDGAR, which requires a contact identity on every request. Add one line to `api.key`, or set the variable in your environment:

```
EDGAR_IDENTITY="Your Name your.email@example.com"
```

Without it, only that indicator reports `unavailable`. The rest of the engine runs as before.

### 2. Running the Engine (Locally)

You can run the engine directly using Python.

```bash
# Install dependencies
pip install -r requirements.txt

# Run a full refresh, regenerating 365 days of history
python market_indicators.py --mode full --lookback-days 365

# Run an incremental refresh
python market_indicators.py --mode manual --lookback-days 365
```

### 3. Running the API Server

The included FastAPI server can be used to view data and trigger refreshes.

```bash
# Start the server
python services/api.py
```

*   Interactive docs will be available at `http://localhost:8000/docs`.
*   A Postman collection is available at `docs/postman_collection.json`.

## Insider Buy Share (SEC Form 4)

Insider Buy Share is a Sentiment indicator built from insider trades. It is the share of insider trading dollars that go to purchases rather than sales:

```
buy share (%) = buy value / (buy value + sell value) × 100
```

*   **Source:** SEC Form 4 filings, read with [edgartools](https://edgartools.readthedocs.io/en/latest/insider-filings/).
*   **Universe:** Current S&P 500 members, taken from the constituents table on Wikipedia and cached for 30 days. To track your own tickers instead, add `"insider_buy_share.universe": ["AAPL", "MSFT"]` to `settings.json`.
*   **Counted trades:** Open-market purchases (code `P`) and open-market sales (code `S`). Grants, option exercises, tax withholding, gifts and equity swaps are excluded. Sell-to-cover sales are also excluded: sales that the filing footnotes describe as covering tax on vesting awards.
*   **Windows:** Daily buy and sell values are rolled over 30 and 90 calendar days. The 90-day reading sets the status.
*   **Status:** `high` when the 90-day buy share sits in the bottom 10% of its own trailing year, which means insiders are selling heavily relative to their recent norm. A fixed cutoff does not work here: insider buying is rare, the typical 90-day reading sits near 2–3%, and a fixed 10% line would read `high` almost every day. Heavy insider selling into a rally has historically come before market tops. The status is `unavailable` until 180 days of 90-day readings exist, or while the window holds fewer than 30 trades.
*   **Caveats:** The measure is dollar-weighted, so one large purchase can move the reading. Prices are sanity-checked: a trade priced above $100,000 a share, or more than 100× away from the issuer's median price in the window, is dropped. Some filings report prices 1000× too large (1031414 instead of 1031.414). Left in, those few filings added about $83B of false sell volume in the first build. Rule 10b5-1 sales stay in by default. Set `EXCLUDE_10B5_1 = True` in `indicators/sentiment/insider_buy_share.py` to drop them. Each incremental run re-reads the last 30 days of trade dates, so late filings are picked up.

### Cache and first-run cost

Each Form 4 accession is parsed once and saved as `resources/raw/sec_form4/filings/<accession>.json`. An accession number never changes once filed, so this cache cannot go stale. A full refresh of this indicator clears its own clean data but keeps the Form 4 cache. An interrupted run resumes from the files already on disk.

The first build downloads every S&P 500 Form 4 in the window. That is tens of thousands of filings. SEC allows about 9 requests per second, so expect the first build to take roughly an hour. Later runs list each company's filings and download only the new accessions. To force a full re-download, delete `resources/raw/sec_form4/`.

```bash
# Build the Form 4 cache and the indicator history (re-run to resume after an interruption)
python market_indicators.py --mode full --indicator insider_buy_share --keep-resource-cache --lookback-days 365
```

`--mode full` requires `--indicator`. Use `--mode manual` to refresh every indicator together.

## Social & Prediction-Market Sentiment

Three Sentiment indicators built on keyless public endpoints — no API key, no account, no OAuth:

| Indicator | Source | Triggers (`high`) when |
|---|---|---|
| Retail Buzz Velocity | Reddit Atom feed | posting rate >= 90th percentile of its own history |
| Social Bull-Bear Ratio | StockTwits symbol stream | >= 75% of self-labelled messages bullish |
| Recession Odds | Polymarket Gamma API | implied probability >= 35% |

**These three cannot be backfilled.** None of the sources serves a historical
vintage, so each accumulates one row per day from the day you first run it —
`--lookback-days 365` does not apply to them. Recording today's live reading
against past dates would put information into a backtest that nobody could
have had at the time, so it is not offered.

Retail Buzz Velocity reports `normal` with a "building baseline" note until it
has 30 observations, because a percentile off five readings is not a percentile.

Metric definitions, failure handling and tuning knobs are in
[docs/social-sentiment.md](docs/social-sentiment.md).

## Docker Deployment

For a self-contained deployment, you can use Docker.

```bash
# 1. Build the image (APP_UID should own the mounted directories on the host)
docker build --build-arg APP_UID="$(id -u)" -t stock-index-engine .

# 2. Run the container
docker run \
  -p 127.0.0.1:8000:8000 \
  -e FRED_API_KEY="your_fred_api_key_here" \
  -e EDGAR_IDENTITY="Your Name your.email@example.com" \
  -e REFRESH_TOKEN="a long random string" \
  -v /local/path/to/output:/app/output \
  -v /local/path/to/resources:/app/resources \
  stock-index-engine
```

*   Use the `-e` flag to pass API keys as environment variables.
*   `POST /refresh` only works from inside the container and with `REFRESH_TOKEN` (sent as `Authorization: Bearer <token>`), e.g. `docker exec` into it and call `http://127.0.0.1:8000/refresh`. Leave the token unset to turn the endpoint off; the daily scheduler still runs.
*   The container runs as a non-root user (`APP_UID`, default 10001), so the mounted directories must be writable by that uid.
*   Mount a local directory to `/app/output` to persist the generated reports.
*   Mount `/app/resources` as well so the SEC Form 4 cache survives container restarts. Without that mount, every new container repeats the first build.

## Output Files

The engine generates the following files in the `output/` directory:

*   `market_status.latest.json`: A snapshot of the latest evaluation for all indicators.
*   `history/{indicator_slug}.json`: A series of historical data points for each individual indicator.
*   `market_indicator_log.csv`: A log of indicator values over time.

## Project Structure

- `common/` – Shared utilities and configuration helpers.
- `indicators/` – Implementations for all market indicators.
- `services/` – Orchestration layer (refresh, evaluation, API, history, exports).
- `resources/` – Cached raw & clean datasets.
- `output/` – Generated reports and history series.
- `docs/` – API documentation, indicator notes and Postman collections.
