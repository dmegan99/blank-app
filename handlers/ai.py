"""AI-powered command handlers: /brief, /nongaap, /x."""

import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from services.claude_client import ask_claude
from services.edgar import fetch_company_facts, HEADERS
from utils.formatters import escape_html
from config import ANTHROPIC_API_KEY, EDGAR_USER_AGENT


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate Claude Opus morning briefing."""
    if not ANTHROPIC_API_KEY:
        await update.message.reply_text("❌ ANTHROPIC_API_KEY not configured")
        return

    await update.message.reply_text("Generating morning briefing... (30-60s)")

    today = datetime.now().strftime("%Y-%m-%d")

    system = (
        "You are a concise financial analyst. Generate a morning market briefing. "
        "Cover: key overnight moves, macro events, notable earnings, sector rotations, "
        "and any significant geopolitical developments affecting markets. "
        "Use bullet points and keep it scannable. Include relevant tickers where applicable."
    )

    prompt = (
        f"Generate a morning market briefing for {today}. "
        f"Cover the most important market developments, overnight futures, "
        f"key economic data releases, and notable corporate events. "
        f"Format it as a clean, readable briefing suitable for a Telegram message."
    )

    response = ask_claude(prompt, system=system, max_tokens=2000)
    if not response:
        await update.message.reply_text("Failed to generate briefing")
        return

    # Truncate if needed for Telegram's 4096 char limit
    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(f"📋 <b>Morning Briefing — {today}</b>\n\n{escape_html(response)}", parse_mode="HTML")


async def nongaap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Non-GAAP metrics from latest 8-K via Claude analysis."""
    if not ANTHROPIC_API_KEY:
        await update.message.reply_text("❌ ANTHROPIC_API_KEY not configured")
        return

    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /nongaap TICKER")
        return

    await update.message.reply_text(f"Fetching latest 8-K for {ticker} and analyzing with Claude... (30-60s)")

    # Fetch recent 8-K filing text from EDGAR full-text search
    filing_text = _fetch_latest_8k(ticker)
    if not filing_text:
        await update.message.reply_text(f"Could not find recent 8-K filing for {ticker}")
        return

    system = (
        "You are a financial analyst specializing in extracting non-GAAP metrics from earnings releases. "
        "Extract and present the following if available: "
        "Non-GAAP EPS, Adjusted EBITDA, Adjusted Operating Income, Free Cash Flow, "
        "Adjusted Revenue, and any other key non-GAAP metrics the company reports. "
        "Present as a clean table. Note any significant reconciliation items."
    )

    prompt = (
        f"Analyze this 8-K filing excerpt for {ticker} and extract all non-GAAP metrics:\n\n"
        f"{filing_text[:8000]}"
    )

    response = ask_claude(prompt, system=system, max_tokens=2000)
    if not response:
        await update.message.reply_text("Failed to analyze 8-K filing")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(
        f"<b>{ticker} — Non-GAAP Metrics (Latest 8-K)</b>\n\n{escape_html(response)}",
        parse_mode="HTML"
    )


async def x_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """X/Twitter search with AI digest."""
    if not ANTHROPIC_API_KEY:
        await update.message.reply_text("❌ ANTHROPIC_API_KEY not configured")
        return

    if not context.args:
        await update.message.reply_text("Usage: /x QUERY [hours]\nExample: /x SaaS 72")
        return

    # Parse query and optional hours
    args = list(context.args)
    hours = 72
    if len(args) > 1 and args[-1].isdigit():
        hours = int(args.pop())
    query = " ".join(args)

    await update.message.reply_text(f"Searching X for '{query}' ({hours}h window)... (30-60s)")

    system = (
        "You are a financial intelligence analyst who synthesizes social media discussions into actionable briefings. "
        "You produce Signal Digests from X/Twitter posts. Format your output with:\n"
        "- Sentiment score (1-5)\n"
        "- Material news & catalysts\n"
        "- Sentiment balance (bullish vs bearish breakdown with ratio)\n"
        "- Notable accounts and their positions\n"
        "- Emerging narratives\n"
        "- Volume & velocity assessment\n"
        "- Key disagreements\n"
        "Use markdown headers. Mention specific account handles where relevant. "
        "Be specific about follower counts and engagement metrics where available."
    )

    prompt = (
        f"Create an X/Twitter Signal Digest for the query '{query}' covering the last {hours} hours. "
        f"Based on your knowledge, analyze what the current discourse on X/Twitter looks like around this topic. "
        f"Focus on financial/investment-relevant discussions. "
        f"Identify key accounts, sentiment shifts, and actionable signals. "
        f"Format as a comprehensive signal digest."
    )

    response = ask_claude(prompt, system=system, max_tokens=3000)
    if not response:
        await update.message.reply_text("Failed to generate X digest")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    header = f"<b>{query} — X Signal Digest ({hours}h)</b>"
    await update.message.reply_text(f"{header}\n\n{escape_html(response)}", parse_mode="HTML")


def _fetch_latest_8k(ticker: str) -> str | None:
    """Fetch the latest 8-K filing text from EDGAR full-text search."""
    try:
        # Use EDGAR EFTS (full-text search) to find recent 8-K filings
        search_url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'"{ticker}"',
            "dateRange": "custom",
            "forms": "8-K",
            "startdt": "2024-01-01",
        }
        headers = {"User-Agent": EDGAR_USER_AGENT}

        # Try the filing search API
        search_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=8-K"
        resp = requests.get(search_url, headers=headers, timeout=15)

        # Fallback: use the companyfacts to at least get the company info
        # and construct a search for 8-K filings
        from utils.ticker_lookup import ticker_to_cik
        cik = ticker_to_cik(ticker)
        if not cik:
            return None

        # Fetch recent filings list
        filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(filings_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        # Find the most recent 8-K
        for i, form in enumerate(forms):
            if form == "8-K" and i < len(accessions) and i < len(primary_docs):
                accession = accessions[i].replace("-", "")
                doc = primary_docs[i]
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}"
                doc_resp = requests.get(doc_url, headers=headers, timeout=20)
                if doc_resp.status_code == 200:
                    # Strip HTML tags roughly for plain text
                    text = doc_resp.text
                    # Basic HTML stripping
                    import re
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text)
                    return text[:10000]  # Limit to 10k chars
                break

        return None
    except Exception:
        return None
