"""Finnhub command handlers: /insider, /inst."""

from telegram import Update
from telegram.ext import ContextTypes

from services.finnhub_client import (
    get_insider_transactions,
    get_institutional_ownership,
    get_fund_ownership,
)
from utils.formatters import fmt_number, build_table, telegram_msg
from config import FINNHUB_API_KEY


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


async def insider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Insider transactions (12 months) via Finnhub."""
    if not FINNHUB_API_KEY:
        await update.message.reply_text("❌ FINNHUB_API_KEY not configured")
        return

    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /insider TICKER")
        return

    await update.message.reply_text(f"Fetching insider transactions for {ticker}...")

    txns = get_insider_transactions(ticker)
    if not txns:
        await update.message.reply_text(f"No insider transactions found for {ticker}")
        return

    # Summarize by transaction type
    buys = [t for t in txns if t.get("transactionType") in ("P - Purchase", "P")]
    sells = [t for t in txns if t.get("transactionType") in ("S - Sale", "S", "S - Sale+OE")]

    total_bought = sum(t.get("share", 0) or 0 for t in buys)
    total_sold = sum(abs(t.get("share", 0) or 0) for t in sells)
    total_buy_value = sum((t.get("share", 0) or 0) * (t.get("price", 0) or 0) for t in buys)
    total_sell_value = sum(abs(t.get("share", 0) or 0) * (t.get("price", 0) or 0) for t in sells)

    summary = (
        f"Total Transactions: {len(txns)}\n"
        f"Buys:  {len(buys)} txns | {fmt_number(total_bought, prefix='')} shares | {fmt_number(total_buy_value)}\n"
        f"Sells: {len(sells)} txns | {fmt_number(total_sold, prefix='')} shares | {fmt_number(total_sell_value)}\n"
    )

    # Recent transactions table (top 15)
    headers = ["Date", "Name", "Type", "Shares", "Price"]
    rows = []
    for t in txns[:15]:
        name = (t.get("name") or "Unknown")[:18]
        tx_type = "BUY" if "P" in (t.get("transactionType") or "") else "SELL"
        shares = fmt_number(abs(t.get("share", 0) or 0), prefix="")
        price = fmt_number(t.get("price", 0) or 0, prefix="$", decimals=2)
        date = (t.get("transactionDate") or "")[:10]
        rows.append([date, name, tx_type, shares, price])

    table = build_table(headers, rows, alignments=['l', 'l', 'l', 'r', 'r'])

    body = summary + "\nRecent Transactions:\n" + table
    msg = telegram_msg(f"{ticker} — Insider Transactions (12M)", body)
    await update.message.reply_text(msg, parse_mode="HTML")


async def inst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Institutional & fund ownership via Finnhub."""
    if not FINNHUB_API_KEY:
        await update.message.reply_text("❌ FINNHUB_API_KEY not configured")
        return

    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /inst TICKER")
        return

    await update.message.reply_text(f"Fetching institutional ownership for {ticker}...")

    institutions = get_institutional_ownership(ticker)
    funds = get_fund_ownership(ticker)

    if not institutions and not funds:
        await update.message.reply_text(f"No ownership data found for {ticker}")
        return

    parts = []

    if institutions:
        headers = ["Holder", "Shares (M)", "% Out", "Change%"]
        rows = []
        for inst_entry in institutions[:10]:
            name = (inst_entry.get("name") or "Unknown")[:25]
            shares = f"{(inst_entry.get('share', 0) or 0) / 1e6:.1f}"
            pct = f"{(inst_entry.get('percentage', 0) or 0) * 100:.1f}%"
            change = f"{(inst_entry.get('change', 0) or 0) / 1e6:+.1f}M"
            rows.append([name, shares, pct, change])

        parts.append("Institutional Holders (Top 10):\n" + build_table(headers, rows, alignments=['l', 'r', 'r', 'r']))

    if funds:
        headers = ["Fund", "Shares (M)", "% Out", "Change%"]
        rows = []
        for f in funds[:10]:
            name = (f.get("name") or "Unknown")[:25]
            shares = f"{(f.get('share', 0) or 0) / 1e6:.1f}"
            pct = f"{(f.get('percentage', 0) or 0) * 100:.1f}%"
            change = f"{(f.get('change', 0) or 0) / 1e6:+.1f}M"
            rows.append([name, shares, pct, change])

        parts.append("\nFund Holders (Top 10):\n" + build_table(headers, rows, alignments=['l', 'r', 'r', 'r']))

    body = "\n".join(parts)
    msg = telegram_msg(f"{ticker} — Institutional & Fund Ownership", body)
    await update.message.reply_text(msg, parse_mode="HTML")
