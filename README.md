# Stock Index Indicators

Service toolkit for evaluating market indicators, persisting results, and exposing them via a FastAPI application.

## Requirements
- Python 3.12+
- pip / virtualenv (recommended)
- PostgreSQL endpoint if you want to persist clean & history datasets (`settings.json` controls credentials)
- Docker (optional) for containerised deployment

## Setup
1. Clone the repository and enter the project directory.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Provide API keys or other secrets via environment variables or `vault.key` as required by the indicator fetchers.

## Running Indicator Refreshes
Use the CLI wrapper to trigger manual or full refresh cycles.

```bash
# Incremental refresh, regenerating 365 days of history
python market_indicators.py --mode manual --lookback-days 365

# Cache-busting refresh, deleting raw/clean caches first
python market_indicators.py --mode full --lookback-days 365

# Skip history exports (useful for quick CLI checks)
python market_indicators.py --mode manual --skip-history
```

- `--keep-resource-cache` prevents `full` mode from clearing `resources/files` (shared downloads).
- Each run writes to `output/market_status.latest.json`, updates `output/market_indicator_log.csv`, regenerates `output/history/*.json`, and upserts to PostgreSQL (`indicator_timeseries`, `indicator_history_series`). Source-related fields are stripped before DB insertion.

## Running the API Server
The FastAPI service wraps refresh hooks and history files.

```bash
uvicorn services.api:app --host 0.0.0.0 --port 8000
```

- Interactive docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Postman collection: import `docs/postman_collection.json` and update the `baseUrl` variable if you deploy elsewhere.
- Automatic scheduler: set `REFRESH_CRON` (default `0 6 * * *`) to control the background manual refresh cadence.
- POST `/refresh` triggers manual/full refreshes asynchronously.

Detailed endpoint descriptions live in [`docs/api.md`](docs/api.md).

## Docker
Build and run the containerised service if you prefer a self-contained deployment.

```bash
# Build image
docker build -t stock-index-service .

# Run container with persistent output folder and custom cron
docker run \
  -p 8000:8000 \
  -e REFRESH_CRON="0 */6 * * *" \
  -v $(pwd)/output:/app/output \
  stock-index-service
```

Mount `output/` to retain JSON/CSV history outside the container. Provide API keys through `-e` env vars or Docker secrets as needed.

## Database Notes
- `indicator_timeseries` stores clean indicator datasets (handled inside each indicator via `upsert_indicator_dataframe`).
- `indicator_history_series` stores per-day status snapshots taken from history files. Fields containing "source" are dropped before insert to avoid persisting provenance URLs if you do not want them in the database.
- Remove or adjust `_upsert_history_to_db` in `services/history.py` if you want to disable database writes entirely.

## Tests
Automated tests are not included yet. Once tests are added, run them with:
```bash
pytest
```
Consider adding integration tests that exercise `manual_refresh` and the API endpoints.

## Logs & Outputs
- Structured logs live under `logs/` (see `market_indicators.log`).
- Latest run snapshot: `output/market_status.latest.json`.
- Daily log: `output/market_indicator_log.csv`.
- History JSON: `output/history/{slug}.json` (one file per indicator).

## Project Structure
- `common/` – shared utilities, config, DB helpers.
- `indicators/` – indicator implementations.
- `services/` – orchestration layer (refresh, evaluation, API, history, exports).
- `resources/` – cached raw & clean datasets.
- `output/` – generated reports and history series.
- `docs/api.md` – REST API reference.
