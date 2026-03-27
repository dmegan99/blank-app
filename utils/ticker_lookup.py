"""Ticker to CIK mapping for SEC EDGAR lookups."""

import requests
from config import EDGAR_USER_AGENT, EDGAR_TICKERS_URL

_TICKER_CIK_CACHE = {}


def _load_ticker_map():
    """Fetch and cache the ticker→CIK mapping from SEC."""
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE:
        return _TICKER_CIK_CACHE

    headers = {"User-Agent": EDGAR_USER_AGENT}
    resp = requests.get(EDGAR_TICKERS_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    for entry in data.values():
        ticker = entry["ticker"].upper()
        cik = str(entry["cik_str"])
        _TICKER_CIK_CACHE[ticker] = cik

    return _TICKER_CIK_CACHE


def ticker_to_cik(ticker: str) -> str | None:
    """Convert a ticker symbol to a CIK number (zero-padded to 10 digits)."""
    mapping = _load_ticker_map()
    cik = mapping.get(ticker.upper())
    if cik is None:
        return None
    return cik.zfill(10)
