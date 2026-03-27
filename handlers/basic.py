"""Basic bot commands: /ping, /chatid, /status."""

import time
from telegram import Update
from telegram.ext import ContextTypes

from config import BOT_VERSION, BOT_BUILD_TIME, FINNHUB_API_KEY, load_watchlist

_START_TIME = time.time()


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

    services = []
    services.append(f"  SEC EDGAR:  ✅ (no key needed)")
    services.append(f"  Finnhub:    {'✅' if FINNHUB_API_KEY else '❌ (no key)'}")
    services.append(f"  DuckDuckGo: ✅ (no key needed)")

    msg = (
        f"<b>Bot Status</b>\n"
        f"<pre>"
        f"Version:   {BOT_VERSION}\n"
        f"Built:     {BOT_BUILD_TIME}\n"
        f"Uptime:    {uptime_str}\n"
        f"Watchlist: {len(watchlist)} tickers\n"
        f"\nServices:\n"
        + "\n".join(services)
        + f"</pre>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")
