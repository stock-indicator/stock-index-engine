from pathlib import Path

# Shared configuration values and constants used across indicator modules.
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

INDEX_TICKERS = {
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
}

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_LOOKBACK = 90
MOVING_AVG_WINDOW = 200
ANNUAL_RETURN_WINDOW = 252  # trading days

FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}
