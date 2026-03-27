import os
import json
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_VERSION = "1.0.0"
BOT_BUILD_TIME = "2026-03-27"

EDGAR_USER_AGENT = "FinanceBot/1.0 (finance-bot@example.com)"
EDGAR_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FILINGS_URL = "https://efts.sec.gov/LATEST/search-index?q="

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")


def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
