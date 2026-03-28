"""SEC EDGAR command handlers: /rev, /margin, /profit, /bs."""

from telegram import Update
from telegram.ext import ContextTypes

from services.edgar import (
    get_quarterly_revenue,
    get_quarterly_margins,
    get_quarterly_profit,
    get_balance_sheet,
    _format_fiscal_quarter,
)
from utils.formatters import fmt_millions, fmt_pct, build_table, telegram_msg


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Extract ticker from command arguments."""
    if not context.args:
        return None
    return context.args[0].upper()


async def rev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quarterly revenue from SEC EDGAR XBRL."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /rev TICKER")
        return

    await update.message.reply_text(f"Fetching revenue data for {ticker}...")

    quarters = get_quarterly_revenue(ticker)
    if not quarters:
        await update.message.reply_text(f"No revenue data found for {ticker}")
        return

    headers = ["Quarter", "Rev ($M)", "QoQ%", "YoY%", "Accel"]
    rows = []
    accel_up = 0
    accel_total = 0

    for q in quarters:
        quarter_label = _format_fiscal_quarter(q)
        rev_val = fmt_millions(q["val"], decimals=0)
        qoq = fmt_pct(q["qoq"]) if q["qoq"] is not None else "N/A"
        yoy = fmt_pct(q["yoy"]) if q["yoy"] is not None else "N/A"
        accel = q.get("accel", "")
        if accel == "↑":
            accel_up += 1
        if accel:
            accel_total += 1
        rows.append([quarter_label, rev_val, qoq, yoy, accel or ""])

    table = build_table(headers, rows)

    # Trend summary
    footer = ""
    if accel_total > 0:
        footer = f"\nTrend: YoY accelerating {accel_up} of last {accel_total} quarters"
        if accel_up > accel_total / 2:
            footer += "\n⚡ 2nd Derivative: Revenue growth ACCELERATING — recent YoY pace exceeding prior quarters"
        elif accel_up < accel_total / 2:
            footer += "\n📉 2nd Derivative: Revenue growth DECELERATING — YoY pace slowing"

    msg = telegram_msg(f"{ticker} — Quarterly Revenue (12Q)", table, footer)
    await update.message.reply_text(msg, parse_mode="HTML")


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quarterly margins from SEC EDGAR."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /margin TICKER")
        return

    await update.message.reply_text(f"Fetching margin data for {ticker}...")

    data = get_quarterly_margins(ticker)
    if not data or not data.get("quarters"):
        await update.message.reply_text(f"No margin data found for {ticker}")
        return

    headers = ["Quarter", "Rev ($M)", "Gross%", "Op%", "Net%"]
    rows = []

    for q in data["quarters"]:
        quarter_label = _format_fiscal_quarter(q)
        rev_val = fmt_millions(q["revenue"], decimals=0)
        gross = fmt_pct(q["gross_margin"], plus=False) if q["gross_margin"] is not None else "N/A"
        op = fmt_pct(q["op_margin"], plus=False) if q["op_margin"] is not None else "N/A"
        net = fmt_pct(q["net_margin"], plus=False) if q["net_margin"] is not None else "N/A"
        rows.append([quarter_label, rev_val, gross, op, net])

    table = build_table(headers, rows)
    msg = telegram_msg(f"{ticker} — Quarterly Margins", table)
    await update.message.reply_text(msg, parse_mode="HTML")


async def profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quarterly net income from SEC EDGAR."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /profit TICKER")
        return

    await update.message.reply_text(f"Fetching profit data for {ticker}...")

    quarters = get_quarterly_profit(ticker)
    if not quarters:
        await update.message.reply_text(f"No profit data found for {ticker}")
        return

    headers = ["Quarter", "Net Inc ($M)", "QoQ%", "YoY%", "Accel"]
    rows = []
    accel_up = 0
    accel_total = 0

    for q in quarters:
        quarter_label = _format_fiscal_quarter(q)
        ni_val = fmt_millions(q["val"], decimals=0)
        qoq = fmt_pct(q["qoq"]) if q["qoq"] is not None else "N/A"
        yoy = fmt_pct(q["yoy"]) if q["yoy"] is not None else "N/A"
        accel = q.get("accel", "")
        if accel == "↑":
            accel_up += 1
        if accel:
            accel_total += 1
        rows.append([quarter_label, ni_val, qoq, yoy, accel or ""])

    table = build_table(headers, rows)

    footer = ""
    if accel_total > 0:
        footer = f"\nTrend: YoY accelerating {accel_up} of last {accel_total} quarters"
        if accel_up > accel_total / 2:
            footer += "\n⚡ 2nd Derivative: Profit growth ACCELERATING — recent YoY pace exceeding prior quarters"
        elif accel_up < accel_total / 2:
            footer += "\n📉 2nd Derivative: Profit growth DECELERATING — YoY pace slowing"

    msg = telegram_msg(f"{ticker} — Quarterly Net Income (12Q)", table, footer)
    await update.message.reply_text(msg, parse_mode="HTML")


async def bs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Balance sheet & cash flow from SEC EDGAR."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /bs TICKER")
        return

    await update.message.reply_text(f"Fetching balance sheet for {ticker}...")

    data = get_balance_sheet(ticker)
    if not data or not data.get("periods"):
        await update.message.reply_text(f"No balance sheet data found for {ticker}")
        return

    headers = ["Period", "Assets", "Liab", "Equity", "Cash", "Debt", "FCF"]
    rows = []

    for p in data["periods"][:8]:
        period_label = _format_fiscal_quarter(p)
        rows.append([
            period_label,
            fmt_millions(p["assets"]) if p["assets"] else "N/A",
            fmt_millions(p["liabilities"]) if p["liabilities"] else "N/A",
            fmt_millions(p["equity"]) if p["equity"] else "N/A",
            fmt_millions(p["cash"]) if p["cash"] else "N/A",
            fmt_millions(p["debt"]) if p["debt"] else "N/A",
            fmt_millions(p["fcf"]) if p["fcf"] else "N/A",
        ])

    table = build_table(headers, rows)
    msg = telegram_msg(f"{ticker} — Balance Sheet & Cash Flow", table)
    await update.message.reply_text(msg, parse_mode="HTML")
