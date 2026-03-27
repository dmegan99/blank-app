"""SEC EDGAR XBRL API client for financial data."""

import requests
from datetime import datetime
from config import EDGAR_USER_AGENT, EDGAR_BASE_URL
from utils.ticker_lookup import ticker_to_cik

HEADERS = {"User-Agent": EDGAR_USER_AGENT}

# Common XBRL taxonomy keys for different financial metrics
REVENUE_KEYS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]

COGS_KEYS = [
    "CostOfGoodsAndServicesSold",
    "CostOfRevenue",
    "CostOfGoodsSold",
    "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
]

OPERATING_INCOME_KEYS = [
    "OperatingIncomeLoss",
]

NET_INCOME_KEYS = [
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",
]

TOTAL_ASSETS_KEYS = ["Assets"]
TOTAL_LIABILITIES_KEYS = ["Liabilities", "LiabilitiesAndStockholdersEquity"]
STOCKHOLDERS_EQUITY_KEYS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
CASH_KEYS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsAndShortTermInvestments",
]
TOTAL_DEBT_KEYS = [
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtNoncurrent",
]
CAPEX_KEYS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
]
OPERATING_CASHFLOW_KEYS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]


def fetch_company_facts(ticker: str) -> dict | None:
    """Fetch full companyfacts JSON from EDGAR for a given ticker."""
    cik = ticker_to_cik(ticker)
    if not cik:
        return None

    url = f"{EDGAR_BASE_URL}/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _extract_quarterly_data(facts: dict, concept_keys: list, num_quarters: int = 12) -> list[dict]:
    """Extract quarterly data for given XBRL concept keys.

    Returns list of dicts with keys: end, val, form, fy, fp
    sorted by period end date descending.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for key in concept_keys:
        concept = us_gaap.get(key)
        if not concept:
            continue

        units = concept.get("units", {})
        # Financial values are typically in USD
        values = units.get("USD", [])
        if not values:
            continue

        # Filter for quarterly data (10-Q and 10-K filings)
        quarterly = []
        seen = set()
        for entry in values:
            form = entry.get("form", "")
            if form not in ("10-Q", "10-K"):
                continue

            start = entry.get("start")
            end = entry.get("end")
            if not start or not end:
                continue

            # Calculate period length in days to filter for quarters (~90 days)
            try:
                start_dt = datetime.strptime(start, "%Y-%m-%d")
                end_dt = datetime.strptime(end, "%Y-%m-%d")
                days = (end_dt - start_dt).days
            except ValueError:
                continue

            # Accept periods between 60 and 120 days (quarterly)
            if not (60 <= days <= 120):
                continue

            # Deduplicate by end date
            if end in seen:
                continue
            seen.add(end)

            quarterly.append({
                "end": end,
                "val": entry.get("val", 0),
                "form": form,
                "fy": entry.get("fy"),
                "fp": entry.get("fp", ""),
            })

        # Sort by end date descending
        quarterly.sort(key=lambda x: x["end"], reverse=True)
        return quarterly[:num_quarters]

    return []


def _extract_instant_data(facts: dict, concept_keys: list, num_periods: int = 12) -> list[dict]:
    """Extract instant (balance sheet) data for given XBRL concept keys.

    Returns list of dicts sorted by period end date descending.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for key in concept_keys:
        concept = us_gaap.get(key)
        if not concept:
            continue

        units = concept.get("units", {})
        values = units.get("USD", [])
        if not values:
            continue

        instant = []
        seen = set()
        for entry in values:
            form = entry.get("form", "")
            if form not in ("10-Q", "10-K"):
                continue

            end = entry.get("end")
            if not end or end in seen:
                continue
            seen.add(end)

            instant.append({
                "end": end,
                "val": entry.get("val", 0),
                "form": form,
                "fy": entry.get("fy"),
                "fp": entry.get("fp", ""),
            })

        instant.sort(key=lambda x: x["end"], reverse=True)
        return instant[:num_periods]

    return []


def get_quarterly_revenue(ticker: str, num_quarters: int = 12) -> list[dict]:
    """Get quarterly revenue data with QoQ, YoY, and acceleration."""
    facts = fetch_company_facts(ticker)
    if not facts:
        return []

    quarters = _extract_quarterly_data(facts, REVENUE_KEYS, num_quarters)
    if not quarters:
        return []

    return _add_growth_metrics(quarters)


def get_quarterly_margins(ticker: str, num_quarters: int = 12) -> dict:
    """Get quarterly revenue, COGS, operating income for margin calculation."""
    facts = fetch_company_facts(ticker)
    if not facts:
        return {}

    revenue = _extract_quarterly_data(facts, REVENUE_KEYS, num_quarters)
    cogs = _extract_quarterly_data(facts, COGS_KEYS, num_quarters)
    op_income = _extract_quarterly_data(facts, OPERATING_INCOME_KEYS, num_quarters)
    net_income = _extract_quarterly_data(facts, NET_INCOME_KEYS, num_quarters)

    if not revenue:
        return {}

    # Build a lookup by end date
    cogs_map = {d["end"]: d["val"] for d in cogs}
    op_map = {d["end"]: d["val"] for d in op_income}
    ni_map = {d["end"]: d["val"] for d in net_income}

    results = []
    for q in revenue:
        end = q["end"]
        rev_val = q["val"]
        cogs_val = cogs_map.get(end)
        op_val = op_map.get(end)
        ni_val = ni_map.get(end)

        gross_margin = ((rev_val - cogs_val) / rev_val * 100) if (cogs_val is not None and rev_val) else None
        op_margin = (op_val / rev_val * 100) if (op_val is not None and rev_val) else None
        net_margin = (ni_val / rev_val * 100) if (ni_val is not None and rev_val) else None

        results.append({
            "end": end,
            "fy": q.get("fy"),
            "fp": q.get("fp", ""),
            "revenue": rev_val,
            "gross_margin": gross_margin,
            "op_margin": op_margin,
            "net_margin": net_margin,
        })

    return {"quarters": results}


def get_quarterly_profit(ticker: str, num_quarters: int = 12) -> list[dict]:
    """Get quarterly net income data with growth metrics."""
    facts = fetch_company_facts(ticker)
    if not facts:
        return []

    quarters = _extract_quarterly_data(facts, NET_INCOME_KEYS, num_quarters)
    if not quarters:
        return []

    return _add_growth_metrics(quarters)


def get_balance_sheet(ticker: str, num_periods: int = 8) -> dict:
    """Get balance sheet and cash flow data."""
    facts = fetch_company_facts(ticker)
    if not facts:
        return {}

    assets = _extract_instant_data(facts, TOTAL_ASSETS_KEYS, num_periods)
    liabilities = _extract_instant_data(facts, TOTAL_LIABILITIES_KEYS, num_periods)
    equity = _extract_instant_data(facts, STOCKHOLDERS_EQUITY_KEYS, num_periods)
    cash = _extract_instant_data(facts, CASH_KEYS, num_periods)
    debt = _extract_instant_data(facts, TOTAL_DEBT_KEYS, num_periods)
    capex = _extract_quarterly_data(facts, CAPEX_KEYS, num_periods)
    op_cf = _extract_quarterly_data(facts, OPERATING_CASHFLOW_KEYS, num_periods)

    if not assets:
        return {}

    # Build lookups
    liab_map = {d["end"]: d["val"] for d in liabilities}
    eq_map = {d["end"]: d["val"] for d in equity}
    cash_map = {d["end"]: d["val"] for d in cash}
    debt_map = {d["end"]: d["val"] for d in debt}
    capex_map = {d["end"]: d["val"] for d in capex}
    opcf_map = {d["end"]: d["val"] for d in op_cf}

    results = []
    for a in assets:
        end = a["end"]
        opcf_val = opcf_map.get(end)
        capex_val = capex_map.get(end)
        fcf = (opcf_val - capex_val) if (opcf_val is not None and capex_val is not None) else None

        results.append({
            "end": end,
            "fy": a.get("fy"),
            "fp": a.get("fp", ""),
            "assets": a["val"],
            "liabilities": liab_map.get(end),
            "equity": eq_map.get(end),
            "cash": cash_map.get(end),
            "debt": debt_map.get(end),
            "op_cashflow": opcf_val,
            "capex": capex_val,
            "fcf": fcf,
        })

    return {"periods": results}


def _add_growth_metrics(quarters: list[dict]) -> list[dict]:
    """Add QoQ%, YoY%, and acceleration indicators to quarterly data."""
    result = []
    for i, q in enumerate(quarters):
        entry = dict(q)
        val = q["val"]

        # QoQ growth
        if i + 1 < len(quarters) and quarters[i + 1]["val"]:
            prev_val = quarters[i + 1]["val"]
            entry["qoq"] = ((val - prev_val) / abs(prev_val)) * 100 if prev_val != 0 else None
        else:
            entry["qoq"] = None

        # YoY growth
        if i + 4 < len(quarters) and quarters[i + 4]["val"]:
            yoy_val = quarters[i + 4]["val"]
            entry["yoy"] = ((val - yoy_val) / abs(yoy_val)) * 100 if yoy_val != 0 else None
        else:
            entry["yoy"] = None

        # Acceleration (is YoY growth increasing vs prior quarter's YoY?)
        entry["accel"] = None
        if entry["yoy"] is not None and i + 1 < len(quarters):
            # Check next (older) quarter's YoY
            older_q_idx = i + 1
            if older_q_idx + 4 < len(quarters) and quarters[older_q_idx + 4]["val"]:
                older_val = quarters[older_q_idx]["val"]
                older_yoy_val = quarters[older_q_idx + 4]["val"]
                older_yoy = ((older_val - older_yoy_val) / abs(older_yoy_val)) * 100 if older_yoy_val != 0 else None
                if older_yoy is not None:
                    entry["accel"] = "↑" if entry["yoy"] > older_yoy else "↓"

        result.append(entry)

    return result


def _format_fiscal_quarter(entry: dict) -> str:
    """Format fiscal quarter label like 'Q3 FY25'."""
    fp = entry.get("fp", "")
    fy = entry.get("fy")
    if fp and fy:
        # fp is like "Q1", "Q2", etc. fy is the fiscal year
        fy_short = str(fy)[-2:] if fy else ""
        return f"{fp} FY{fy_short}"
    # Fallback to end date
    return entry.get("end", "")[:7]
