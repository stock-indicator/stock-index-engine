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

## Docker Deployment

For a self-contained deployment, you can use Docker.

```bash
# 1. Build the image
docker build -t stock-index-engine .

# 2. Run the container
docker run \
  -p 8000:8000 \
  -e FRED_API_KEY="your_fred_api_key_here" \
  -v /local/path/to/output:/app/output \
  stock-index-engine
```

*   Use the `-e` flag to pass API keys as environment variables.
*   Mount a local directory to `/app/output` to persist the generated reports.

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
- `docs/` – API documentation and Postman collections.
