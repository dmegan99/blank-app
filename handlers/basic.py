"""Basic bot commands: /ping, /chatid, /status."""

import time
from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_VERSION, BOT_BUILD_TIME, FINNHUB_API_KEY, GEMINI_API_KEY, load_watchlist, load_themes, load_notes

_START_TIME = time.time()


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands."""
    msg = (
        "<b>Available Commands</b>\n\n"
        "<b>Basics</b>\n"
        "/help           — Show this message\n"
        "/ping           — Health check\n"
        "/chatid         — Current chat ID\n"
        "/status         — Bot version &amp; services\n\n"
        "<b>SEC EDGAR (no key needed)</b>\n"
        "/rev TICKER     — Quarterly revenue (12Q)\n"
        "/margin TICKER  — Quarterly margins\n"
        "/profit TICKER  — Quarterly net income\n"
        "/bs TICKER      — Balance sheet &amp; cash flow\n\n"
        "<b>Finnhub (needs API key)</b>\n"
        "/insider TICKER — Insider transactions (12M)\n"
        "/inst TICKER    — Institutional ownership\n\n"
        "<b>Valuation &amp; Screening</b>\n"
        "/val TICKER     — Valuation snapshot + EPS est\n"
        "/screen         — Technical screen (watchlist)\n"
        "/compare T1 T2  — Side-by-side comparison\n"
        "/dcf TICKER     — Quick DCF valuation\n"
        "/peers TICKER   — Peer company comparison\n\n"
        "<b>Earnings &amp; Dividends</b>\n"
        "/earnings TICKER — Earnings dates + surprises\n"
        "/dividend TICKER — Dividend history &amp; safety\n\n"
        "<b>AI-Powered (Gemini)</b>\n"
        "/brief [am|noon|pm] — Market briefing\n"
        "/nongaap TICKER — Non-GAAP from latest 8-K\n"
        "/x QUERY [hrs]  — X/Twitter signal digest\n"
        "/summarize TICKER — Full financial summary\n"
        "/thesis TICKER  — Bull/bear investment thesis\n"
        "/news TICKER    — Recent news digest\n"
        "/news watchlist — News for all watchlist\n\n"
        "<b>Memory &amp; Intelligence</b>\n"
        "/themes         — View theme watchlist\n"
        "/themes add NAME — Track a theme\n"
        "/themes scan    — AI scan for emerging themes\n"
        "/note TICKER text — Save a note/observation\n"
        "/note TICKER    — View notes\n"
        "/note list      — All subjects with notes\n"
        "/feedback good/bad — Help bot learn\n\n"
        "<b>Portfolio &amp; Alerts</b>\n"
        "/watchlist      — View watchlist\n"
        "/watchlist add TICKER — Add to watchlist\n"
        "/watchlist remove TICKER — Remove\n"
        "/portfolio T1 T2 ... — Portfolio tracker\n"
        "/alert TICKER PRICE — Set price alert\n"
        "/alert list     — View active alerts\n"
        "/alert clear    — Clear all alerts\n"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Health check."""
    await update.message.reply_text("pong")


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return the current chat ID."""
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status information."""
    uptime_secs = int(time.time() - _START_TIME)
    hours, remainder = divmod(uptime_secs, 3600)
    minutes, secs = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {secs}s"

    watchlist = load_watchlist()
    themes = load_themes()
    notes = load_notes()

    services = []
    services.append(f"  SEC EDGAR:  ✅ (no key needed)")
    services.append(f"  Finnhub:    {'✅' if FINNHUB_API_KEY else '❌ (no key)'}")
    services.append(f"  Gemini AI:  {'✅' if GEMINI_API_KEY else '❌ (no key)'}")

    msg = (
        f"<b>Bot Status</b>\n"
        f"<pre>"
        f"Version:   {BOT_VERSION}\n"
        f"Built:     {BOT_BUILD_TIME}\n"
        f"Uptime:    {uptime_str}\n"
        f"Watchlist: {len(watchlist)} tickers\n"
        f"Themes:    {len(themes)} tracked\n"
        f"Notes:     {sum(len(v) for v in notes.values())} across {len(notes)} subjects\n"
        f"\nServices:\n"
        + "\n".join(services)
        + f"</pre>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")
