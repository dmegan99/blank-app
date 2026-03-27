"""AI-powered command handlers: /brief, /nongaap, /x, /summarize, /thesis, /news."""

import re
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from services.claude_client import ask_ai
from services.edgar import (
    get_quarterly_revenue, get_quarterly_margins,
    get_quarterly_profit, _format_fiscal_quarter,
)
from services.yfinance_client import get_stock_info
from utils.formatters import escape_html, fmt_millions, fmt_pct
from config import EDGAR_USER_AGENT, GEMINI_API_KEY


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


def _check_ai(update):
    """Check if AI is available, return error message if not."""
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY not configured"
    return None


async def _send_ai_response(update, title, prompt, system=""):
    """Common pattern: send prompt to AI, handle errors, send response."""
    response = ask_ai(prompt, system=system)
    if not response:
        await update.message.reply_text("AI returned no response.")
        return
    if response.startswith("[API Error") or response.startswith("[Error"):
        await update.message.reply_text(f"AI error: {response}")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(
        f"<b>{title}</b>\n\n{escape_html(response)}",
        parse_mode="HTML",
    )


# --- /brief ---

async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate AI morning briefing."""
    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
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

    await _send_ai_response(update, f"📋 Morning Briefing — {today}", prompt, system)


# --- /nongaap ---

async def nongaap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Non-GAAP metrics from latest 8-K via AI analysis."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /nongaap TICKER")
        return

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
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

    await _send_ai_response(update, f"{ticker} — Non-GAAP Metrics (Latest 8-K)", prompt, system)


# --- /x ---

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

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
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

    await _send_ai_response(update, f"{query} — X Signal Digest ({hours}h)", prompt, system)


# --- /summarize ---

async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI summary combining revenue, margins, valuation into one view."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /summarize TICKER")
        return

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text(f"Building financial summary for {ticker}... (15-30s)")

    # Gather data from multiple sources
    data_parts = []

    # Revenue
    rev_data = get_quarterly_revenue(ticker, num_quarters=8)
    if rev_data:
        rev_lines = []
        for q in rev_data[:6]:
            label = _format_fiscal_quarter(q)
            rev_str = fmt_millions(q["val"])
            yoy = fmt_pct(q["yoy"]) if q.get("yoy") is not None else "N/A"
            rev_lines.append(f"  {label}: {rev_str} (YoY: {yoy})")
        data_parts.append("QUARTERLY REVENUE:\n" + "\n".join(rev_lines))

    # Margins
    margin_data = get_quarterly_margins(ticker, num_quarters=4)
    if margin_data and margin_data.get("quarters"):
        margin_lines = []
        for q in margin_data["quarters"][:4]:
            label = _format_fiscal_quarter(q)
            gm = f"{q['gross_margin']:.1f}%" if q.get("gross_margin") is not None else "N/A"
            om = f"{q['op_margin']:.1f}%" if q.get("op_margin") is not None else "N/A"
            nm = f"{q['net_margin']:.1f}%" if q.get("net_margin") is not None else "N/A"
            margin_lines.append(f"  {label}: Gross {gm} | Op {om} | Net {nm}")
        data_parts.append("QUARTERLY MARGINS:\n" + "\n".join(margin_lines))

    # Valuation from yfinance
    info = get_stock_info(ticker)
    if info:
        price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        pe = info.get("trailingPE")
        fwd_pe = info.get("forwardPE")
        mkt_cap = info.get("marketCap")
        rev_growth = info.get("revenueGrowth")

        val_lines = []
        if price:
            val_lines.append(f"  Price: ${price:.2f}")
        if mkt_cap:
            val_lines.append(f"  Market Cap: ${mkt_cap/1e9:.1f}B" if mkt_cap >= 1e9 else f"  Market Cap: ${mkt_cap/1e6:.0f}M")
        if pe:
            val_lines.append(f"  P/E (TTM): {pe:.1f}x")
        if fwd_pe:
            val_lines.append(f"  P/E (Fwd): {fwd_pe:.1f}x")
        if rev_growth is not None:
            val_lines.append(f"  Revenue Growth: {rev_growth*100:+.1f}%")
        if val_lines:
            data_parts.append("VALUATION:\n" + "\n".join(val_lines))

    if not data_parts:
        await update.message.reply_text(f"Could not fetch financial data for {ticker}")
        return

    data_block = "\n\n".join(data_parts)

    system = (
        "You are a senior equity research analyst. Provide a concise executive summary "
        "of a company's financial health based on the data provided. Cover:\n"
        "1. Revenue trajectory and growth quality\n"
        "2. Margin trends (expanding/contracting and why it matters)\n"
        "3. Valuation assessment (cheap/fair/expensive vs growth)\n"
        "4. Key takeaway in one sentence\n"
        "Be direct and specific. Use numbers from the data. Keep it under 300 words."
    )

    prompt = f"Provide an executive financial summary for {ticker} based on this data:\n\n{data_block}"

    await _send_ai_response(update, f"{ticker} — Financial Summary", prompt, system)


# --- /thesis ---

async def thesis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bull/bear case generated by AI."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /thesis TICKER")
        return

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text(f"Building bull/bear thesis for {ticker}... (15-30s)")

    # Gather financial context
    data_parts = []

    rev_data = get_quarterly_revenue(ticker, num_quarters=8)
    if rev_data:
        latest = rev_data[0]
        oldest = rev_data[-1]
        data_parts.append(f"Latest quarterly revenue: {fmt_millions(latest['val'])}")
        if latest.get("yoy") is not None:
            data_parts.append(f"YoY revenue growth: {fmt_pct(latest['yoy'])}")
        accel_count = sum(1 for q in rev_data if q.get("accel") == "↑")
        data_parts.append(f"Revenue accelerating in {accel_count}/{len(rev_data)} quarters")

    margin_data = get_quarterly_margins(ticker, num_quarters=4)
    if margin_data and margin_data.get("quarters"):
        q = margin_data["quarters"][0]
        if q.get("gross_margin") is not None:
            data_parts.append(f"Latest gross margin: {q['gross_margin']:.1f}%")
        if q.get("net_margin") is not None:
            data_parts.append(f"Latest net margin: {q['net_margin']:.1f}%")

    profit_data = get_quarterly_profit(ticker, num_quarters=4)
    if profit_data:
        if profit_data[0].get("yoy") is not None:
            data_parts.append(f"Net income YoY growth: {fmt_pct(profit_data[0]['yoy'])}")

    info = get_stock_info(ticker)
    if info:
        pe = info.get("trailingPE")
        fwd_pe = info.get("forwardPE")
        if pe:
            data_parts.append(f"P/E (TTM): {pe:.1f}x")
        if fwd_pe:
            data_parts.append(f"P/E (Fwd): {fwd_pe:.1f}x")

    context_str = "\n".join(data_parts) if data_parts else "No specific data available."

    system = (
        "You are a senior equity analyst writing an investment thesis. "
        "Present a balanced BULL CASE and BEAR CASE for the stock. "
        "For each case, provide 3-4 specific arguments with reasoning. "
        "End with a 'Key Risk' and 'Key Catalyst' section. "
        "Be specific and use the financial data provided. "
        "Format with clear headers: ## Bull Case, ## Bear Case, ## Key Risk, ## Key Catalyst"
    )

    prompt = (
        f"Write a bull/bear investment thesis for {ticker}.\n\n"
        f"Financial context:\n{context_str}\n\n"
        f"Provide specific, data-driven arguments for both sides."
    )

    await _send_ai_response(update, f"{ticker} — Investment Thesis", prompt, system)


# --- /news ---

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent news digest via AI."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /news TICKER")
        return

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text(f"Generating news digest for {ticker}... (15-30s)")

    # Get company name from yfinance
    info = get_stock_info(ticker)
    company_name = info.get("longName") or info.get("shortName") or ticker

    system = (
        "You are a financial news analyst. Provide a concise news digest covering "
        "the most important recent developments for this company. Cover:\n"
        "- Major business developments and announcements\n"
        "- Earnings highlights (if recent)\n"
        "- Analyst upgrades/downgrades\n"
        "- Industry trends affecting the company\n"
        "- Any regulatory or legal developments\n"
        "Be specific with dates and numbers. Format as bullet points. "
        "Flag anything that could materially move the stock."
    )

    prompt = (
        f"Provide a news digest for {company_name} ({ticker}) covering "
        f"the most recent and significant developments. "
        f"Focus on material, stock-moving news."
    )

    await _send_ai_response(update, f"{ticker} — News Digest", prompt, system)


# --- Helper ---

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
