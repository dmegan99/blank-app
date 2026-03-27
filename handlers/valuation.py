"""Valuation snapshot handler: /val."""

from telegram import Update
from telegram.ext import ContextTypes

from services.yfinance_client import get_stock_info, calculate_rsi, get_price_history
from services.finnhub_client import get_recommendation_trends, get_price_target
from utils.formatters import fmt_number, fmt_pct, fmt_multiplier, build_table, telegram_msg
from config import FINNHUB_API_KEY


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


async def val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Valuation snapshot with multiples, targets, consensus."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /val TICKER")
        return

    await update.message.reply_text(f"Fetching valuation data for {ticker}...")

    info = get_stock_info(ticker)
    if not info or not info.get("regularMarketPrice"):
        await update.message.reply_text(f"No data found for {ticker}")
        return

    price = info.get("regularMarketPrice") or info.get("currentPrice", 0)
    mkt_cap = info.get("marketCap", 0)
    ev = info.get("enterpriseValue", 0)
    beta = info.get("beta")
    avg_vol = info.get("averageDailyVolume10Day", 0)
    fye_month = info.get("lastFiscalYearEnd")
    high_52 = info.get("fiftyTwoWeekHigh", 0)
    low_52 = info.get("fiftyTwoWeekLow", 0)
    div_yield = info.get("dividendYield")

    # Get RSI
    hist = get_price_history(ticker, period="3mo")
    rsi = calculate_rsi(hist["Close"]) if not hist.empty else None

    # Multiples
    pe_trailing = info.get("trailingPE")
    pe_forward = info.get("forwardPE")
    pb = info.get("priceToBook")
    ps_trailing = info.get("priceToSalesTrailing12Months")
    ev_rev = info.get("enterpriseToRevenue")

    # EPS growth
    eps_trailing = info.get("trailingEps")
    eps_forward = info.get("forwardEps")
    eps_growth = None
    if eps_trailing and eps_forward and eps_trailing > 0:
        eps_growth = ((eps_forward - eps_trailing) / eps_trailing) * 100

    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None:
        rev_growth *= 100

    # Short interest
    short_pct = info.get("shortPercentOfFloat")
    if short_pct and short_pct < 1:
        short_pct *= 100
    shares_short = info.get("sharesShort", 0)
    short_ratio = info.get("shortRatio")
    float_shares = info.get("floatShares", 0)

    # Build header section
    mkt_cap_str = _fmt_large_number(mkt_cap)
    ev_str = _fmt_large_number(ev)
    adv_str = _fmt_large_number(avg_vol * price) if avg_vol and price else "N/A"

    header_lines = [
        f"Price: ${price:.2f} | Mkt Cap: {mkt_cap_str} | EV: {ev_str}",
        f"ADV: {adv_str} | Beta: {beta:.2f if beta else 'N/A'} | RSI(14): {rsi:.1f if rsi else 'N/A'}",
        f"52w: ${low_52:.2f} - ${high_52:.2f}",
    ]

    # Multiples table
    mult_headers = ["", "Trailing", "Forward"]
    mult_rows = [
        ["P/E", fmt_multiplier(pe_trailing), fmt_multiplier(pe_forward)],
        ["P/B", fmt_multiplier(pb), "N/A"],
        ["P/S", fmt_multiplier(ps_trailing), "N/A"],
        ["EV/Rev", fmt_multiplier(ev_rev), "N/A"],
    ]
    mult_table = build_table(mult_headers, mult_rows, alignments=['l', 'r', 'r'])

    # Growth
    growth_lines = []
    if div_yield is not None:
        growth_lines.append(f"Dividend Yield: {div_yield * 100:.1f}%")
    if eps_growth is not None:
        growth_lines.append(f"EPS Growth (Fwd/Trail): {eps_growth:+.1f}%")
    if rev_growth is not None:
        growth_lines.append(f"Rev Growth: {rev_growth:+.1f}%")

    # Short interest section
    short_lines = ["\nShort Interest:"]
    if short_pct is not None:
        short_lines.append(f"  Short % of Float: {short_pct:.1f}%")
    if shares_short:
        short_lines.append(f"  Shares Short: {shares_short / 1e6:.1f}M")
    if short_ratio:
        short_lines.append(f"  Days to Cover: {short_ratio:.1f}")
    if float_shares:
        short_lines.append(f"  Float: {float_shares / 1e6:.1f}M")

    # Analyst consensus from Finnhub
    consensus_line = ""
    if FINNHUB_API_KEY:
        recs = get_recommendation_trends(ticker)
        if recs:
            latest = recs[0]
            buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0) + latest.get("strongSell", 0)
            consensus_line = f"Consensus: {buy} Buy | {hold} Hold | {sell} Sell"

    # Assemble
    body_parts = [
        "\n".join(header_lines),
        "\nMultiples:",
        mult_table,
    ]
    if growth_lines:
        body_parts.append("\n" + "\n".join(growth_lines))
    if len(short_lines) > 1:
        body_parts.append("\n".join(short_lines))
    if consensus_line:
        body_parts.append("\n" + consensus_line)

    body = "\n".join(body_parts)
    msg = telegram_msg(f"{ticker} — Valuation Snapshot", body)
    await update.message.reply_text(msg, parse_mode="HTML")


def _fmt_large_number(value):
    """Format large numbers as $XXB or $XXM."""
    if not value:
        return "N/A"
    if value >= 1e12:
        return f"${value / 1e12:.1f}T"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"
