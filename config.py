import os
import json
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_VERSION = "2.0.0"
BOT_BUILD_TIME = "2026-03-28"

EDGAR_USER_AGENT = "FinanceBot/2.0 (finance-bot@example.com)"
EDGAR_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FILINGS_URL = "https://efts.sec.gov/LATEST/search-index?q="

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

_BASE_DIR = os.path.dirname(__file__)
WATCHLIST_FILE = os.path.join(_BASE_DIR, "watchlist.json")
THEMES_FILE = os.path.join(_BASE_DIR, "themes.json")
NOTES_FILE = os.path.join(_BASE_DIR, "notes.json")
FEEDBACK_FILE = os.path.join(_BASE_DIR, "feedback.json")


def _load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_watchlist():
    return _load_json(WATCHLIST_FILE, [])


def save_watchlist(tickers):
    _save_json(WATCHLIST_FILE, tickers)


def load_themes():
    """Load theme watchlist. Returns list of dicts: {name, description, tickers, added}."""
    return _load_json(THEMES_FILE, [])


def save_themes(themes):
    _save_json(THEMES_FILE, themes)


def load_notes():
    """Load notes. Returns dict: {subject: [{text, timestamp, source}]}."""
    return _load_json(NOTES_FILE, {})


def save_notes(notes):
    _save_json(NOTES_FILE, notes)


def load_feedback():
    """Load feedback entries. Returns list of dicts."""
    return _load_json(FEEDBACK_FILE, [])


def save_feedback(entries):
    _save_json(FEEDBACK_FILE, entries)
