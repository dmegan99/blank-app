"""AI-powered command handlers: /brief, /nongaap, /x."""

import re
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from services.claude_client import ask_ai
from utils.formatters import escape_html
from config import EDGAR_USER_AGENT, GEMINI_API_KEY


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate AI morning briefing."""
    if not GEMINI_API_KEY:
        await update.message.reply_text("❌ GEMINI_API_KEY not configured")
        return
    await update.message.reply_text("Generating morning briefing... (15-30s)")

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

    response = ask_ai(prompt, system=system)
    if not response:
        await update.message.reply_text("Failed to generate briefing. AI service may be unavailable.")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(
        f"📋 <b>Morning Briefing — {today}</b>\n\n{escape_html(response)}",
        parse_mode="HTML",
    )


async def nongaap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Non-GAAP metrics from latest 8-K via AI analysis."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /nongaap TICKER")
        return

    if not GEMINI_API_KEY:
        await update.message.reply_text("❌ GEMINI_API_KEY not configured")
        return
    await update.message.reply_text(f"Fetching latest 8-K for {ticker} and analyzing... (15-30s)")

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
        f"{filing_text[:6000]}"
    )

    response = ask_ai(prompt, system=system)
    if not response:
        await update.message.reply_text("Failed to analyze 8-K filing. AI service may be unavailable.")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(
        f"<b>{ticker} — Non-GAAP Metrics (Latest 8-K)</b>\n\n{escape_html(response)}",
        parse_mode="HTML",
    )


async def x_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """X/Twitter search with AI digest."""
    if not context.args:
        await update.message.reply_text("Usage: /x QUERY [hours]\nExample: /x SaaS 72")
        return

    args = list(context.args)
    hours = 72
    if len(args) > 1 and args[-1].isdigit():
        hours = int(args.pop())
    query = " ".join(args)

    if not GEMINI_API_KEY:
        await update.message.reply_text("❌ GEMINI_API_KEY not configured")
        return
    await update.message.reply_text(f"Analyzing X discourse for '{query}' ({hours}h window)... (15-30s)")

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

    response = ask_ai(prompt, system=system)
    if not response:
        await update.message.reply_text("Failed to generate X digest. AI returned no response.")
        return
    if response.startswith("[API Error") or response.startswith("[Error"):
        await update.message.reply_text(f"AI error: {response}")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    header = f"<b>{query} — X Signal Digest ({hours}h)</b>"
    await update.message.reply_text(f"{header}\n\n{escape_html(response)}", parse_mode="HTML")


def _fetch_latest_8k(ticker: str) -> str | None:
    """Fetch the latest 8-K filing text from EDGAR."""
    try:
        from utils.ticker_lookup import ticker_to_cik

        headers = {"User-Agent": EDGAR_USER_AGENT}
        cik = ticker_to_cik(ticker)
        if not cik:
            return None

        filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(filings_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form == "8-K" and i < len(accessions) and i < len(primary_docs):
                accession = accessions[i].replace("-", "")
                doc = primary_docs[i]
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}"
                doc_resp = requests.get(doc_url, headers=headers, timeout=20)
                if doc_resp.status_code == 200:
                    text = doc_resp.text
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text)
                    return text[:10000]
                break

        return None
    except Exception:
        return None
