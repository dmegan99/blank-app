"""AI-powered command handlers: /brief, /nongaap, /x, /summarize, /thesis, /news."""

import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ContextTypes

from services.claude_client import ask_ai
from services.edgar import (
    get_quarterly_revenue, get_quarterly_margins,
    get_quarterly_profit, _format_fiscal_quarter,
)
from services.yfinance_client import get_stock_info, get_news
from utils.formatters import escape_html, fmt_millions, fmt_pct
from config import EDGAR_USER_AGENT, GEMINI_API_KEY, load_watchlist
from handlers.memory import get_full_context, auto_note

ET = ZoneInfo("America/New_York")


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


def _check_ai(update):
    """Check if AI is available, return error message if not."""
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY not configured"
    return None


async def _send_ai_response(update, title, prompt, system="", use_search=False):
    """Common pattern: send prompt to AI, handle errors, send response."""
    response = ask_ai(prompt, system=system, use_search=use_search)
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

_BRIEF_SLOTS = {
    # Keyword → (label, hour, description)
    "am":    ("Pre-Market", 7,  "pre-market"),
    "7am":   ("Pre-Market", 7,  "pre-market"),
    "7":     ("Pre-Market", 7,  "pre-market"),
    "pre":   ("Pre-Market", 7,  "pre-market"),
    "noon":  ("Midday", 12,     "midday"),
    "12pm":  ("Midday", 12,     "midday"),
    "12":    ("Midday", 12,     "midday"),
    "mid":   ("Midday", 12,     "midday"),
    "pm":    ("Closing", 17,    "end-of-day"),
    "5pm":   ("Closing", 17,    "end-of-day"),
    "5":     ("Closing", 17,    "end-of-day"),
    "close": ("Closing", 17,    "end-of-day"),
    "eod":   ("Closing", 17,    "end-of-day"),
}


def _parse_brief_slot(args):
    """Parse time slot from args. Returns (label, slot_desc) or defaults based on current ET."""
    if args:
        key = args[0].lower().replace(":", "")
        slot = _BRIEF_SLOTS.get(key)
        if slot:
            return slot[0], slot[2]

    # Auto-detect based on current Eastern time
    et_hour = datetime.now(ET).hour
    if et_hour < 10:
        return "Pre-Market", "pre-market"
    elif et_hour < 14:
        return "Midday", "midday"
    else:
        return "Closing", "end-of-day"


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Market briefing: /brief [am|noon|pm]. Uses real-time data via web search."""
    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
        return

    label, slot_desc = _parse_brief_slot(context.args)
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    time_str = now_et.strftime("%I:%M %p ET")

    await update.message.reply_text(f"Generating {label} briefing... (15-30s)")

    # Fetch watchlist headlines to ground the briefing
    watchlist = load_watchlist()
    watchlist_context = ""
    if watchlist:
        top_tickers = watchlist[:10]
        all_hl = []
        for t in top_tickers:
            hl = get_news(t, max_items=3)
            if hl:
                lines = [f"{t}:"]
                for h in hl:
                    pub = h.get("published", "")[:10] if h.get("published") else ""
                    lines.append(f"  - [{pub}] {h['title']}")
                all_hl.append("\n".join(lines))
        if all_hl:
            watchlist_context = "\n\nWATCHLIST HEADLINES:\n" + "\n".join(all_hl)

    # Fetch broad market data
    market_data = ""
    try:
        from services.yfinance_client import get_price_history
        indices = {"SPY": "S&P 500", "QQQ": "Nasdaq", "DIA": "Dow", "IWM": "Russell 2K",
                   "TLT": "20Y Bond", "GLD": "Gold", "USO": "Oil", "VIX": "VIX"}
        mkt_lines = []
        for sym, name in indices.items():
            try:
                hist = get_price_history(sym, period="5d")
                if not hist.empty and len(hist) >= 2:
                    last = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2])
                    chg = ((last - prev) / prev) * 100
                    mkt_lines.append(f"  {name} ({sym}): {last:.2f} ({chg:+.2f}%)")
            except Exception:
                pass
        if mkt_lines:
            market_data = "\n\nMARKET DATA:\n" + "\n".join(mkt_lines)
    except Exception:
        pass

    slot_instructions = {
        "pre-market": (
            "This is a PRE-MARKET briefing (7 AM ET). Focus on:\n"
            "- Overnight futures and global market moves (Asia, Europe)\n"
            "- Pre-market movers and why they're moving\n"
            "- Key economic data releases scheduled today\n"
            "- Earnings reports before the open\n"
            "- Geopolitical developments overnight affecting markets\n"
            "- Setup: what to watch for at the open"
        ),
        "midday": (
            "This is a MIDDAY briefing (12 PM ET). Focus on:\n"
            "- Morning session recap: what moved and why\n"
            "- Sector rotation and leadership/laggards\n"
            "- Any breaking news or intraday developments\n"
            "- Volume and breadth observations\n"
            "- Key levels being tested (S&P, Nasdaq)\n"
            "- What to watch into the close"
        ),
        "end-of-day": (
            "This is an END-OF-DAY briefing (5 PM ET). Focus on:\n"
            "- Full session recap: major indices performance\n"
            "- Biggest winners and losers with reasons\n"
            "- Earnings reports after the close\n"
            "- Key macro takeaways from the day\n"
            "- After-hours movers\n"
            "- Setup: what to watch for tomorrow"
        ),
    }

    system = (
        f"You are a concise, professional Wall Street market analyst. "
        f"Today is {today}, current time is {time_str}. "
        f"{slot_instructions.get(slot_desc, '')}\n\n"
        f"IMPORTANT: Use the real-time market data, news headlines, and web search results "
        f"provided to give accurate, current information. Do NOT rely on training data for "
        f"recent events. If you're unsure about something, say so. "
        f"Use bullet points. Include tickers. Keep it scannable and actionable."
    )

    # Pull memory context (themes + notes)
    memory_ctx = get_full_context(tickers=watchlist[:10])
    memory_block = f"\n\n{memory_ctx}" if memory_ctx else ""

    prompt = (
        f"Generate a {slot_desc} market briefing for {today} ({time_str}).\n\n"
        f"Search the web for the latest financial news, market moves, economic data, "
        f"and corporate events as of right now.\n"
        f"{market_data}"
        f"{watchlist_context}"
        f"{memory_block}\n\n"
        f"Combine the above real data with your web search results into a concise, "
        f"actionable briefing. Include specific numbers, prices, and percentages.\n"
        f"If any of the ACTIVE THEMES above are relevant to today's news, highlight them. "
        f"If you notice EMERGING THEMES not yet tracked, flag them at the end."
    )

    await _send_ai_response(
        update, f"📋 {label} Briefing — {today} {time_str}", prompt, system,
        use_search=True
    )


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

    today = datetime.now(ET).strftime("%Y-%m-%d")

    system = (
        f"You are a financial analyst specializing in non-GAAP metrics. Today is {today}. "
        f"Extract and present: Non-GAAP EPS, Adjusted EBITDA, Adjusted Operating Income, "
        f"Free Cash Flow, Adjusted Revenue, and other key non-GAAP metrics. "
        f"Present as a clean table. Note significant reconciliation items. "
        f"Supplement with web search for the latest earnings release if the filing text is incomplete."
    )

    prompt = (
        f"Analyze this 8-K filing excerpt for {ticker} and extract all non-GAAP metrics:\n\n"
        f"{filing_text[:6000]}\n\n"
        f"Also search the web for {ticker}'s most recent earnings release for additional non-GAAP data."
    )

    await _send_ai_response(
        update, f"{ticker} — Non-GAAP Metrics (Latest 8-K)", prompt, system,
        use_search=True
    )


# --- /x ---

async def x_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """X/Twitter search with AI digest. Uses web search for real-time data."""
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

    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    time_str = now_et.strftime("%I:%M %p ET")

    await update.message.reply_text(f"Searching X/web for '{query}' ({hours}h)... (15-30s)")

    system = (
        f"You are a financial intelligence analyst. Today is {today}, {time_str}. "
        f"You produce Signal Digests by searching the web for recent X/Twitter posts, "
        f"financial news, and social media sentiment about a given topic.\n\n"
        f"Format your output with:\n"
        f"- Sentiment score (1-5)\n"
        f"- Material news & catalysts (from real sources — cite URLs or sources)\n"
        f"- Sentiment balance (bullish vs bearish with ratio)\n"
        f"- Notable accounts and their positions\n"
        f"- Emerging narratives\n"
        f"- Volume & velocity assessment\n"
        f"- Key disagreements\n"
        f"Use headers. Mention specific account handles. "
        f"IMPORTANT: Use your web search to find REAL, CURRENT posts and discussions "
        f"from today ({today}) or the last {hours} hours. Do not fabricate posts or handles."
    )

    # Memory context for X search
    x_memory = get_full_context(ticker=query.upper() if len(query.split()) == 1 else None)
    mem_block = f"\n\n{x_memory}" if x_memory else ""

    prompt = (
        f"Search the web for recent X/Twitter posts, discussions, and financial commentary "
        f"about '{query}' from the last {hours} hours (as of {today} {time_str}).\n\n"
        f"Search for: '{query} site:x.com OR site:twitter.com' and "
        f"'{query} stock sentiment {today}'\n\n"
        f"{mem_block}\n"
        f"Create a Signal Digest with real, sourced information. "
        f"Focus on financial/investment-relevant discussions. "
        f"If you can't find specific X posts, use other financial news sources and note that. "
        f"If any of the user's prior notes or themes are relevant, reference how sentiment "
        f"compares to their existing thesis."
    )

    await _send_ai_response(
        update, f"{query} — X Signal Digest ({hours}h)", prompt, system,
        use_search=True
    )


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

    today = datetime.now(ET).strftime("%Y-%m-%d")

    system = (
        f"You are a senior equity research analyst. Today is {today}. "
        f"Provide a concise executive summary of a company's financial health "
        f"based on the data provided AND any recent developments you can find via web search. Cover:\n"
        f"1. Revenue trajectory and growth quality\n"
        f"2. Margin trends (expanding/contracting and why it matters)\n"
        f"3. Valuation assessment (cheap/fair/expensive vs growth)\n"
        f"4. Recent news/catalysts that could change the outlook\n"
        f"5. Key takeaway in one sentence\n"
        f"Use the hard data provided below, supplemented by real-time web search. Keep under 400 words."
    )

    memory_ctx = get_full_context(ticker=ticker)
    mem_block = f"\n\n{memory_ctx}" if memory_ctx else ""

    prompt = (
        f"Provide an executive financial summary for {ticker} based on this data:\n\n{data_block}"
        f"{mem_block}\n\n"
        f"Also search the web for any recent news, analyst actions, or developments for {ticker} "
        f"as of {today} that could affect the outlook.\n"
        f"If the user has prior notes on this ticker, note what has CHANGED since their last observation."
    )

    await _send_ai_response(update, f"{ticker} — Financial Summary", prompt, system, use_search=True)


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

    today = datetime.now(ET).strftime("%Y-%m-%d")

    system = (
        f"You are a senior equity analyst. Today is {today}. "
        f"Write an investment thesis using the financial data provided AND real-time web search. "
        f"Present a balanced BULL CASE and BEAR CASE.\n"
        f"For each case, provide 3-4 specific arguments with reasoning.\n"
        f"End with 'Key Risk' and 'Key Catalyst' sections.\n"
        f"IMPORTANT: Incorporate recent news, analyst actions, competitive developments, "
        f"and earnings commentary found via web search. Cite sources where possible.\n"
        f"Format: ## Bull Case, ## Bear Case, ## Key Risk, ## Key Catalyst"
    )

    memory_ctx = get_full_context(ticker=ticker)
    mem_block = f"\n\n{memory_ctx}" if memory_ctx else ""

    prompt = (
        f"Write a bull/bear investment thesis for {ticker}.\n\n"
        f"Financial context:\n{context_str}"
        f"{mem_block}\n\n"
        f"Search the web for recent analyst reports, news, and competitive developments "
        f"for {ticker} as of {today}. Incorporate real findings into both bull and bear cases.\n"
        f"If the user has prior notes or tracked themes, weave those into the thesis."
    )

    await _send_ai_response(update, f"{ticker} — Investment Thesis", prompt, system, use_search=True)


# --- /news ---

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent news digest via AI. Supports /news TICKER or /news watchlist."""
    if not context.args:
        await update.message.reply_text("Usage: /news TICKER  or  /news watchlist")
        return

    err = _check_ai(update)
    if err:
        await update.message.reply_text(err)
        return

    # Check if user wants watchlist news
    if context.args[0].lower() == "watchlist":
        await _news_watchlist(update)
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"Fetching news for {ticker}... (15-30s)")

    info = get_stock_info(ticker)
    company_name = info.get("longName") or info.get("shortName") or ticker

    # Fetch real headlines from yfinance
    headlines = get_news(ticker, max_items=15)
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    time_str = now_et.strftime("%I:%M %p ET")

    headlines_text = ""
    if headlines:
        lines = []
        for h in headlines:
            pub = h.get("published", "")[:10] if h.get("published") else ""
            lines.append(f"- [{pub}] {h['title']} ({h['publisher']})")
        headlines_text = "\n".join(lines)

    system = (
        f"You are a financial news analyst. Today is {today}, {time_str}. "
        f"Analyze the provided news headlines AND search the web for additional "
        f"recent news about this company. For each key story:\n"
        f"- Explain what happened and why it matters for the stock\n"
        f"- Note the potential impact (bullish/bearish/neutral)\n"
        f"- Flag anything that could materially move the stock with ⚠️\n"
        f"IMPORTANT: Supplement yfinance headlines with real-time web search results. "
        f"Prioritize news from TODAY ({today}). Be concise."
    )

    memory_ctx = get_full_context(ticker=ticker)
    mem_block = f"\n\n{memory_ctx}" if memory_ctx else ""

    prompt = (
        f"Here are news headlines for {company_name} ({ticker}) from yfinance:\n\n"
        f"{headlines_text or '(no headlines from yfinance)'}"
        f"{mem_block}\n\n"
        f"Now search the web for the latest news about {company_name} ({ticker}) "
        f"as of {today}. Combine all sources into a concise news digest. "
        f"Focus on what matters most for the stock.\n"
        f"If the user has prior notes, flag anything that CONTRADICTS or CONFIRMS their thesis."
    )

    await _send_ai_response(update, f"{ticker} — News Digest", prompt, system, use_search=True)


async def _news_watchlist(update: Update):
    """Generate a combined news digest for the entire watchlist."""
    tickers = load_watchlist()
    if not tickers:
        await update.message.reply_text("Watchlist is empty. Use /watchlist add TICKER")
        return

    await update.message.reply_text(
        f"Fetching news for {len(tickers)} watchlist tickers... (30-60s)"
    )

    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    time_str = now_et.strftime("%I:%M %p ET")

    # Fetch real headlines for each ticker
    all_headlines = []
    for ticker in tickers:
        headlines = get_news(ticker, max_items=5)
        if headlines:
            lines = [f"\n{ticker}:"]
            for h in headlines:
                pub = h.get("published", "")[:10] if h.get("published") else ""
                lines.append(f"  - [{pub}] {h['title']} ({h['publisher']})")
            all_headlines.append("\n".join(lines))

    headlines_block = "\n".join(all_headlines) if all_headlines else ""
    ticker_list = ", ".join(tickers)

    system = (
        f"You are a financial news analyst covering a portfolio of stocks. "
        f"Today is {today}, {time_str}. "
        f"Analyze the provided headlines AND search the web for additional breaking news. "
        f"For each company with notable news:\n"
        f"- Use the ticker as a header\n"
        f"- Summarize the 1-2 most important stories and their stock impact\n"
        f"- Flag anything material with ⚠️\n"
        f"Skip tickers with no notable news. "
        f"End with 'Market-Wide Themes' covering trends affecting multiple names. "
        f"Prioritize TODAY's ({today}) news. Be concise."
    )

    prompt = (
        f"Here are recent news headlines for my watchlist:\n{headlines_block or '(limited headlines)'}\n\n"
        f"Also search the web for breaking news about these watchlist tickers: {ticker_list}\n\n"
        f"Provide a consolidated news digest as of {today} {time_str}. "
        f"Focus on the most material stories. Skip tickers with routine/non-material news."
    )

    await _send_ai_response(
        update, f"Watchlist News — {len(tickers)} tickers", prompt, system,
        use_search=True
    )


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
