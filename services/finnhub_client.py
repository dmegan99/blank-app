"""Finnhub API client wrapper."""

import requests
from datetime import datetime, timedelta
from config import FINNHUB_API_KEY, FINNHUB_BASE_URL


def _get(endpoint: str, params: dict = None) -> dict | list | None:
    """Make a GET request to Finnhub API."""
    if not FINNHUB_API_KEY:
        return None

    if params is None:
        params = {}
    params["token"] = FINNHUB_API_KEY

    url = f"{FINNHUB_BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_insider_transactions(ticker: str, months: int = 12) -> list[dict]:
    """Get insider transactions for the past N months."""
    to_date = datetime.now()
    from_date = to_date - timedelta(days=months * 30)

    data = _get("stock/insider-transactions", {
        "symbol": ticker.upper(),
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
    })

    if not data or "data" not in data:
        return []

    return data["data"]


def get_institutional_ownership(ticker: str) -> list[dict]:
    """Get institutional/fund ownership."""
    data = _get("stock/ownership", {"symbol": ticker.upper(), "limit": 20})
    if not data:
        return []
    return data if isinstance(data, list) else []


def get_fund_ownership(ticker: str) -> list[dict]:
    """Get fund ownership data."""
    data = _get("stock/fund-ownership", {"symbol": ticker.upper(), "limit": 20})
    if not data:
        return []
    return data if isinstance(data, list) else []


def get_recommendation_trends(ticker: str) -> list[dict]:
    """Get analyst recommendation trends."""
    data = _get("stock/recommendation", {"symbol": ticker.upper()})
    if not data:
        return []
    return data if isinstance(data, list) else []


def get_price_target(ticker: str) -> dict | None:
    """Get analyst price target consensus."""
    data = _get("stock/price-target", {"symbol": ticker.upper()})
    return data if data else None


def get_eps_estimates(ticker: str) -> list[dict]:
    """Get EPS estimates/revisions."""
    data = _get("stock/eps-estimate", {"symbol": ticker.upper(), "freq": "quarterly"})
    if not data or "data" not in data:
        return []
    return data["data"]


def get_revenue_estimates(ticker: str) -> list[dict]:
    """Get revenue estimates."""
    data = _get("stock/revenue-estimate", {"symbol": ticker.upper(), "freq": "quarterly"})
    if not data or "data" not in data:
        return []
    return data["data"]
