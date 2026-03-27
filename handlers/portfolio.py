"""Watchlist and portfolio command handlers: /watchlist, /portfolio."""

import json
from telegram import Update
from telegram.ext import ContextTypes

from services.yfinance_client import get_stock_info, get_price_history
from utils.formatters import build_table, telegram_msg
from config import WATCHLIST_FILE, load_watchlist


def _save_watchlist(tickers: list):
    """Save the watchlist to file."""
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(tickers, f, indent=2)


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage watchlist: /watchlist, /watchlist add TICKER, /watchlist remove TICKER."""
    args = list(context.args) if context.args else []
    current = load_watchlist()

    # No args — show current watchlist
    if not args:
        if not current:
            await update.message.reply_text("Watchlist is empty. Use /watchlist add TICKER")
            return
        msg = telegram_msg(
            f"Watchlist — {len(current)} tickers",
            "  ".join(current),
            "\nUse /watchlist add TICKER or /watchlist remove TICKER",
        )
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    action = args[0].lower()
    tickers = [t.upper() for t in args[1:]]

    if action == "add":
        if not tickers:
            await update.message.reply_text("Usage: /watchlist add TICKER1 TICKER2 ...")
            return
        added = []
        for t in tickers:
            if t not in current:
                current.append(t)
                added.append(t)
        _save_watchlist(current)
        if added:
            await update.message.reply_text(f"✅ Added: {', '.join(added)}\nWatchlist: {len(current)} tickers")
        else:
            await update.message.reply_text(f"Already in watchlist: {', '.join(tickers)}")

    elif action in ("remove", "rm", "del", "delete"):
        if not tickers:
            await update.message.reply_text("Usage: /watchlist remove TICKER1 TICKER2 ...")
            return
        removed = []
        for t in tickers:
            if t in current:
                current.remove(t)
                removed.append(t)
        _save_watchlist(current)
        if removed:
            await update.message.reply_text(f"🗑 Removed: {', '.join(removed)}\nWatchlist: {len(current)} tickers")
        else:
            await update.message.reply_text(f"Not in watchlist: {', '.join(tickers)}")

    else:
        # Treat the action as a ticker to add (shorthand: /watchlist AAPL)
        ticker = action.upper()
        if ticker not in current:
            current.append(ticker)
            _save_watchlist(current)
            await update.message.reply_text(f"✅ Added {ticker}\nWatchlist: {len(current)} tickers")
        else:
            await update.message.reply_text(f"{ticker} already in watchlist")


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track a portfolio with current prices and returns.

    Usage: /portfolio AAPL NVDA MSFT
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /portfolio TICKER1 TICKER2 ...\n"
            "Example: /portfolio AAPL NVDA MSFT GOOGL"
        )
        return

    tickers = [t.upper() for t in context.args]
    if len(tickers) > 15:
        await update.message.reply_text("Max 15 tickers at a time")
        return

    await update.message.reply_text(f"Fetching portfolio data for {len(tickers)} tickers...")

    headers = ["Ticker", "Price", "Day%", "5D%", "1M%", "YTD%"]
    rows = []
    errors = []

    for ticker in tickers:
        try:
            info = get_stock_info(ticker)
            price = (
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
            )

            if not price:
                # Try from history
                hist = get_price_history(ticker, period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])

            if not price:
                errors.append(ticker)
                continue

            # Get returns from history
            hist = get_price_history(ticker, period="1y")
            if hist.empty or len(hist) < 2:
                rows.append([ticker, f"${price:.2f}", "N/A", "N/A", "N/A", "N/A"])
                continue

            close = hist["Close"]
            current = float(close.iloc[-1])

            # Day change
            day_ret = _calc_return(close, 1)

            # 5-day change
            five_d_ret = _calc_return(close, 5)

            # 1-month change (~21 trading days)
            one_m_ret = _calc_return(close, 21)

            # YTD - find first trading day of current year
            ytd_ret = None
            current_year = close.index[-1].year
            year_data = close[close.index.year == current_year]
            if len(year_data) > 1:
                ytd_start = float(year_data.iloc[0])
                ytd_ret = ((current - ytd_start) / ytd_start) * 100

            rows.append([
                ticker,
                f"${current:.2f}",
                _fmt_ret(day_ret),
                _fmt_ret(five_d_ret),
                _fmt_ret(one_m_ret),
                _fmt_ret(ytd_ret),
            ])

        except Exception:
            errors.append(ticker)

    if not rows:
        await update.message.reply_text("Could not fetch data for any tickers")
        return

    table = build_table(headers, rows)

    footer = ""
    if errors:
        footer = f"\n⚠️ No data: {', '.join(errors)}"

    msg = telegram_msg(f"Portfolio — {len(rows)} tickers", table, footer)
    await update.message.reply_text(msg, parse_mode="HTML")


def _calc_return(close, days):
    """Calculate return over N trading days."""
    if len(close) <= days:
        return None
    current = float(close.iloc[-1])
    past = float(close.iloc[-1 - days])
    return ((current - past) / past) * 100


def _fmt_ret(value):
    """Format a return percentage."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"
