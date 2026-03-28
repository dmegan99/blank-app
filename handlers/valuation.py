"""Valuation snapshot handler: /val."""

import traceback
from telegram import Update
from telegram.ext import ContextTypes

from services.yfinance_client import get_stock_info, calculate_rsi, get_price_history
from services.finnhub_client import (
    get_recommendation_trends, get_price_target,
    get_eps_estimates, get_revenue_estimates,
)
from utils.formatters import fmt_number, fmt_pct, fmt_multiplier, build_table, telegram_msg
from config import FINNHUB_API_KEY


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


def _safe_get(info, *keys, default=None):
    """Try multiple keys, return first non-None value."""
    for key in keys:
        val = info.get(key)
        if val is not None:
            return val
    return default


async def val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Valuation snapshot with multiples, targets, consensus."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /val TICKER")
        return

    await update.message.reply_text(f"Fetching valuation data for {ticker}...")

    try:
        info = get_stock_info(ticker)
    except Exception as e:
        await update.message.reply_text(f"Error fetching data: {e}")
        return

    if not info:
        await update.message.reply_text(f"No data found for {ticker}")
        return

    # Try multiple keys for price — yfinance versions vary
    price = _safe_get(info, "regularMarketPrice", "currentPrice",
                      "regularMarketPreviousClose", "previousClose", default=0)

    if not price:
        # Fallback: get price from history
        try:
            hist = get_price_history(ticker, period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    if not price:
        await update.message.reply_text(f"No price data found for {ticker}")
        return

    mkt_cap = _safe_get(info, "marketCap", default=0)
    ev = _safe_get(info, "enterpriseValue", default=0)
    beta = _safe_get(info, "beta")
    avg_vol = _safe_get(info, "averageDailyVolume10Day", "averageVolume10days",
                        "averageVolume", default=0)
    high_52 = _safe_get(info, "fiftyTwoWeekHigh", default=0)
    low_52 = _safe_get(info, "fiftyTwoWeekLow", default=0)
    div_yield = _safe_get(info, "dividendYield", "trailingAnnualDividendYield")

    # Get RSI
    rsi = None
    try:
        hist = get_price_history(ticker, period="3mo")
        if not hist.empty:
            rsi = calculate_rsi(hist["Close"])
    except Exception:
        pass

    # Multiples
    pe_trailing = _safe_get(info, "trailingPE")
    pe_forward = _safe_get(info, "forwardPE")
    pb = _safe_get(info, "priceToBook")
    ps_trailing = _safe_get(info, "priceToSalesTrailing12Months")
    ev_rev = _safe_get(info, "enterpriseToRevenue")

    # EPS growth
    eps_trailing = _safe_get(info, "trailingEps")
    eps_forward = _safe_get(info, "forwardEps")
    eps_growth = None
    if eps_trailing and eps_forward and eps_trailing > 0:
        eps_growth = ((eps_forward - eps_trailing) / eps_trailing) * 100

    rev_growth = _safe_get(info, "revenueGrowth")
    if rev_growth is not None:
        rev_growth *= 100

    # Short interest
    short_pct = _safe_get(info, "shortPercentOfFloat")
    if short_pct and short_pct < 1:
        short_pct *= 100
    shares_short = _safe_get(info, "sharesShort", default=0)
    short_ratio = _safe_get(info, "shortRatio")
    float_shares = _safe_get(info, "floatShares", default=0)

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

    # Analyst consensus + price target + EPS estimates from Finnhub
    consensus_line = ""
    target_line = ""
    eps_lines = []
    if FINNHUB_API_KEY:
        try:
            recs = get_recommendation_trends(ticker)
            if recs:
                latest = recs[0]
                buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
                hold = latest.get("hold", 0)
                sell = latest.get("sell", 0) + latest.get("strongSell", 0)
                consensus_line = f"Consensus: {buy} Buy | {hold} Hold | {sell} Sell"
        except Exception:
            pass

        try:
            pt = get_price_target(ticker)
            if pt and pt.get("targetMean"):
                low = pt.get("targetLow", 0)
                mean = pt.get("targetMean", 0)
                high = pt.get("targetHigh", 0)
                upside = ((mean - price) / price * 100) if price else 0
                target_line = (
                    f"Price Target: ${low:.0f} / ${mean:.0f} / ${high:.0f} "
                    f"(Low/Mean/High) → {upside:+.1f}%"
                )
        except Exception:
            pass

        try:
            eps_est = get_eps_estimates(ticker)
            if eps_est:
                eps_lines.append("\nEPS Estimates:")
                for e in eps_est[:4]:
                    period = e.get("period", "?")
                    est = e.get("epsAvg")
                    high_e = e.get("epsHigh")
                    low_e = e.get("epsLow")
                    num = e.get("numberAnalysts", 0)
                    if est is not None:
                        eps_lines.append(
                            f"  {period}: ${est:.2f} "
                            f"(${low_e:.2f}-${high_e:.2f}, {num} analysts)"
                            if low_e is not None and high_e is not None
                            else f"  {period}: ${est:.2f} ({num} analysts)"
                        )
        except Exception:
            pass

    # PEG ratio
    peg_line = ""
    if pe_forward and eps_growth and eps_growth > 0:
        peg = pe_forward / eps_growth
        peg_line = f"PEG Ratio: {peg:.2f}"

    # Assemble
    body_parts = [
        "\n".join(header_lines),
        "\nMultiples:",
        mult_table,
    ]
    if growth_lines:
        body_parts.append("\n" + "\n".join(growth_lines))
    if peg_line:
        body_parts.append(peg_line)
    if len(short_lines) > 1:
        body_parts.append("\n".join(short_lines))
    if consensus_line:
        body_parts.append("\n" + consensus_line)
    if target_line:
        body_parts.append(target_line)
    if eps_lines:
        body_parts.append("\n".join(eps_lines))

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
