"""Analysis command handlers: /compare, /dcf, /peers, /earnings, /dividend, /alert."""

import json
import threading
import time
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from services.yfinance_client import get_stock_info, get_price_history
from services.finnhub_client import get_eps_estimates, get_recommendation_trends, get_price_target
from services.edgar import get_quarterly_revenue, get_quarterly_profit
from config import FINNHUB_API_KEY
from utils.formatters import build_table, telegram_msg, fmt_pct, fmt_millions

logger = logging.getLogger(__name__)

# ── In-memory price alerts ──────────────────────────────────────────
# Structure: {chat_id: [{"ticker": "AAPL", "target": 150.0, "direction": "above/below"}]}
_alerts: dict[int, list[dict]] = {}
_alert_thread_started = False


def _get_ticker(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if not context.args:
        return None
    return context.args[0].upper()


def _safe_get(info, *keys, default=None):
    for key in keys:
        val = info.get(key)
        if val is not None:
            return val
    return default


def _fmt_large(value):
    if not value:
        return "N/A"
    if value >= 1e12:
        return f"${value / 1e12:.1f}T"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


# ── /compare ────────────────────────────────────────────────────────

async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Side-by-side comparison of two tickers."""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /compare TICKER1 TICKER2")
        return

    t1, t2 = context.args[0].upper(), context.args[1].upper()
    await update.message.reply_text(f"Comparing {t1} vs {t2}...")

    info1 = get_stock_info(t1)
    info2 = get_stock_info(t2)

    if not info1 and not info2:
        await update.message.reply_text("Could not fetch data for either ticker")
        return

    def _row(label, key1, key2, fmt="num"):
        v1 = _safe_get(info1, *key1) if isinstance(key1, tuple) else _safe_get(info1, key1)
        v2 = _safe_get(info2, *key2) if isinstance(key2, tuple) else _safe_get(info2, key2)
        if fmt == "large":
            return [label, _fmt_large(v1), _fmt_large(v2)]
        elif fmt == "pct":
            s1 = f"{v1 * 100:.1f}%" if v1 is not None else "N/A"
            s2 = f"{v2 * 100:.1f}%" if v2 is not None else "N/A"
            return [label, s1, s2]
        elif fmt == "mult":
            s1 = f"{v1:.1f}x" if v1 is not None else "N/A"
            s2 = f"{v2:.1f}x" if v2 is not None else "N/A"
            return [label, s1, s2]
        else:
            s1 = f"{v1:.2f}" if isinstance(v1, (int, float)) else str(v1 or "N/A")
            s2 = f"{v2:.2f}" if isinstance(v2, (int, float)) else str(v2 or "N/A")
            return [label, s1, s2]

    price1 = _safe_get(info1, "regularMarketPrice", "currentPrice", "previousClose", default=0)
    price2 = _safe_get(info2, "regularMarketPrice", "currentPrice", "previousClose", default=0)

    headers = ["Metric", t1, t2]
    rows = [
        ["Price", f"${price1:.2f}" if price1 else "N/A", f"${price2:.2f}" if price2 else "N/A"],
        _row("Mkt Cap", "marketCap", "marketCap", "large"),
        _row("P/E (Fwd)", "forwardPE", "forwardPE", "mult"),
        _row("P/E (Trail)", "trailingPE", "trailingPE", "mult"),
        _row("P/S", "priceToSalesTrailing12Months", "priceToSalesTrailing12Months", "mult"),
        _row("P/B", "priceToBook", "priceToBook", "mult"),
        _row("EV/Rev", "enterpriseToRevenue", "enterpriseToRevenue", "mult"),
        _row("Rev Growth", "revenueGrowth", "revenueGrowth", "pct"),
        _row("Gross Margin", "grossMargins", "grossMargins", "pct"),
        _row("Op Margin", "operatingMargins", "operatingMargins", "pct"),
        _row("Net Margin", "profitMargins", "profitMargins", "pct"),
        _row("ROE", "returnOnEquity", "returnOnEquity", "pct"),
        _row("Beta", "beta", "beta"),
        _row("Div Yield", ("dividendYield",), ("dividendYield",), "pct"),
    ]

    # 52-week performance
    try:
        h1 = get_price_history(t1, period="1y")
        h2 = get_price_history(t2, period="1y")
        if not h1.empty and not h2.empty:
            ret1 = ((h1["Close"].iloc[-1] - h1["Close"].iloc[0]) / h1["Close"].iloc[0]) * 100
            ret2 = ((h2["Close"].iloc[-1] - h2["Close"].iloc[0]) / h2["Close"].iloc[0]) * 100
            rows.append(["52w Return", f"{ret1:+.1f}%", f"{ret2:+.1f}%"])
    except Exception:
        pass

    table = build_table(headers, rows, alignments=['l', 'r', 'r'])
    msg = telegram_msg(f"{t1} vs {t2} — Comparison", table)
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /dcf ────────────────────────────────────────────────────────────

async def dcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick discounted cash flow estimate."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /dcf TICKER")
        return

    await update.message.reply_text(f"Running DCF for {ticker}...")

    info = get_stock_info(ticker)
    if not info:
        await update.message.reply_text(f"No data found for {ticker}")
        return

    # Get FCF from yfinance
    fcf = _safe_get(info, "freeCashflow")
    shares = _safe_get(info, "sharesOutstanding")
    price = _safe_get(info, "regularMarketPrice", "currentPrice", "previousClose", default=0)
    rev_growth = _safe_get(info, "revenueGrowth")
    mkt_cap = _safe_get(info, "marketCap", default=0)

    if not fcf or not shares or not price:
        await update.message.reply_text(
            f"Insufficient data for DCF on {ticker}. Need FCF and shares outstanding."
        )
        return

    fcf_per_share = fcf / shares
    base_growth = (rev_growth * 100) if rev_growth else 10.0
    # Cap growth assumptions
    growth_high = min(base_growth * 1.2, 40)
    growth_base = min(base_growth, 30)
    growth_low = max(base_growth * 0.6, 2)

    terminal_growth = 3.0  # perpetual growth
    discount_rate = 10.0   # WACC assumption

    scenarios = {}
    for label, growth in [("Bull", growth_high), ("Base", growth_base), ("Bear", growth_low)]:
        pv_sum = 0
        proj_fcf = fcf_per_share
        for year in range(1, 11):
            # Decay growth rate toward terminal over 10 years
            yr_growth = growth - (growth - terminal_growth) * (year - 1) / 9
            proj_fcf *= (1 + yr_growth / 100)
            pv_sum += proj_fcf / ((1 + discount_rate / 100) ** year)

        # Terminal value
        terminal_val = proj_fcf * (1 + terminal_growth / 100) / (discount_rate / 100 - terminal_growth / 100)
        pv_terminal = terminal_val / ((1 + discount_rate / 100) ** 10)
        fair_value = pv_sum + pv_terminal
        upside = ((fair_value - price) / price) * 100

        scenarios[label] = {
            "growth": growth,
            "fair_value": fair_value,
            "upside": upside,
        }

    # Build output
    lines = [
        f"Price: ${price:.2f} | FCF/Share: ${fcf_per_share:.2f}",
        f"Base Growth: {base_growth:.1f}% | Discount: {discount_rate:.0f}%",
        f"Terminal Growth: {terminal_growth:.0f}%",
        "",
    ]

    headers = ["Scenario", "Growth", "Fair Val", "Upside"]
    rows = []
    for label in ["Bull", "Base", "Bear"]:
        s = scenarios[label]
        rows.append([
            label,
            f"{s['growth']:.1f}%",
            f"${s['fair_value']:.2f}",
            f"{s['upside']:+.1f}%",
        ])

    table = build_table(headers, rows, alignments=['l', 'r', 'r', 'r'])
    lines.append(table)
    lines.append("")

    # Margin of safety
    base_fv = scenarios["Base"]["fair_value"]
    if base_fv > price:
        mos = ((base_fv - price) / base_fv) * 100
        lines.append(f"Margin of Safety (Base): {mos:.1f}%")
    else:
        premium = ((price - base_fv) / base_fv) * 100
        lines.append(f"⚠️ Trading at {premium:.1f}% PREMIUM to Base DCF")

    lines.append("\n⚠️ Simplified 10yr DCF — use as directional guide only")

    body = "\n".join(lines)
    msg = telegram_msg(f"{ticker} — DCF Valuation", body)
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /peers ──────────────────────────────────────────────────────────

async def peers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find and compare peer companies."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /peers TICKER")
        return

    await update.message.reply_text(f"Finding peers for {ticker}...")

    info = get_stock_info(ticker)
    if not info:
        await update.message.reply_text(f"No data found for {ticker}")
        return

    # yfinance doesn't have a direct peers endpoint, but we can use sector + industry
    sector = info.get("sector", "")
    industry = info.get("industry", "")
    mkt_cap = _safe_get(info, "marketCap", default=0)

    # Common peer mappings for popular sectors
    _PEER_MAP = {
        "AAPL": ["MSFT", "GOOGL", "SAMSUNG", "DELL", "HPQ"],
        "MSFT": ["AAPL", "GOOGL", "ORCL", "CRM", "ADBE"],
        "GOOGL": ["META", "MSFT", "AMZN", "SNAP", "PINS"],
        "AMZN": ["WMT", "SHOP", "EBAY", "TGT", "BABA"],
        "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "MU"],
        "META": ["GOOGL", "SNAP", "PINS", "TWTR", "TTD"],
        "TSLA": ["F", "GM", "RIVN", "LCID", "NIO"],
        "AMD": ["NVDA", "INTC", "QCOM", "AVGO", "MU"],
        "NFLX": ["DIS", "WBD", "PARA", "CMCSA", "ROKU"],
        "JPM": ["BAC", "GS", "MS", "WFC", "C"],
        "V": ["MA", "PYPL", "SQ", "AXP", "FIS"],
        "UNH": ["CVS", "CI", "ELV", "HUM", "CNC"],
        "LLY": ["JNJ", "PFE", "ABBV", "MRK", "NVO"],
        "CRM": ["ORCL", "NOW", "WDAY", "HUBS", "ADBE"],
    }

    peer_tickers = _PEER_MAP.get(ticker, [])

    # If not in map, try to get from yfinance recommendations or use industry
    if not peer_tickers:
        try:
            stock = __import__("yfinance").Ticker(ticker)
            # Some yfinance versions have recommendations_summary or similar
            recs = getattr(stock, "recommendations", None)
            # Fallback: just note we couldn't find peers
        except Exception:
            pass

    if not peer_tickers:
        await update.message.reply_text(
            f"No peer mapping for {ticker}.\n"
            f"Sector: {sector}\nIndustry: {industry}\n\n"
            f"Try: /compare {ticker} TICKER2"
        )
        return

    # Fetch data for target + peers
    all_tickers = [ticker] + peer_tickers[:5]
    headers = ["Ticker", "MktCap", "P/E", "P/S", "Margin", "Growth", "52wRet"]
    rows = []

    for t in all_tickers:
        try:
            ti = get_stock_info(t) if t != ticker else info
            if not ti:
                continue

            mc = _fmt_large(_safe_get(ti, "marketCap", default=0))
            pe = _safe_get(ti, "forwardPE")
            ps = _safe_get(ti, "priceToSalesTrailing12Months")
            margin = _safe_get(ti, "profitMargins")
            growth = _safe_get(ti, "revenueGrowth")

            pe_s = f"{pe:.1f}x" if pe else "N/A"
            ps_s = f"{ps:.1f}x" if ps else "N/A"
            m_s = f"{margin * 100:.0f}%" if margin else "N/A"
            g_s = f"{growth * 100:.0f}%" if growth else "N/A"

            # 52w return
            ret_s = "N/A"
            try:
                h = get_price_history(t, period="1y")
                if not h.empty and len(h) > 20:
                    ret = ((h["Close"].iloc[-1] - h["Close"].iloc[0]) / h["Close"].iloc[0]) * 100
                    ret_s = f"{ret:+.0f}%"
            except Exception:
                pass

            marker = "→" if t == ticker else " "
            rows.append([f"{marker}{t}", mc, pe_s, ps_s, m_s, g_s, ret_s])
        except Exception:
            continue

    if not rows:
        await update.message.reply_text("Could not fetch peer data")
        return

    table = build_table(headers, rows, alignments=['l', 'r', 'r', 'r', 'r', 'r', 'r'])

    footer = f"\nSector: {sector}\nIndustry: {industry}"
    msg = telegram_msg(f"{ticker} — Peer Comparison", table, footer)
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /earnings ───────────────────────────────────────────────────────

async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upcoming earnings date + EPS surprise history."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /earnings TICKER")
        return

    await update.message.reply_text(f"Fetching earnings data for {ticker}...")

    import yfinance as yf
    stock = yf.Ticker(ticker)

    lines = []

    # Upcoming earnings date
    try:
        cal = stock.calendar
        if cal is not None:
            if isinstance(cal, dict):
                earn_date = cal.get("Earnings Date")
                if isinstance(earn_date, list) and earn_date:
                    lines.append(f"Next Earnings: {earn_date[0]}")
                elif earn_date:
                    lines.append(f"Next Earnings: {earn_date}")
            elif hasattr(cal, "iloc"):
                lines.append(f"Next Earnings: {cal.iloc[0, 0] if len(cal) > 0 else 'N/A'}")
    except Exception:
        pass

    # EPS history from yfinance
    try:
        earnings_hist = stock.earnings_history
        if earnings_hist is not None and not earnings_hist.empty:
            lines.append("")
            headers = ["Quarter", "Est", "Actual", "Surprise"]
            rows = []
            for _, row in earnings_hist.tail(8).iterrows():
                q_date = str(row.get("Quarter", ""))[:10]
                est = row.get("epsEstimate")
                act = row.get("epsActual")
                surp = row.get("surprisePercent")

                est_s = f"${est:.2f}" if est is not None else "N/A"
                act_s = f"${act:.2f}" if act is not None else "N/A"
                surp_s = f"{surp:+.1f}%" if surp is not None else "N/A"
                rows.append([q_date, est_s, act_s, surp_s])

            if rows:
                table = build_table(headers, rows, alignments=['l', 'r', 'r', 'r'])
                lines.append(table)
    except Exception:
        pass

    # Try quarterly earnings from yfinance
    if len(lines) <= 1:
        try:
            qe = stock.quarterly_earnings
            if qe is not None and not qe.empty:
                lines.append("\nQuarterly Earnings:")
                headers = ["Quarter", "Revenue", "Earnings"]
                rows = []
                for idx, row in qe.tail(8).iterrows():
                    rev = row.get("Revenue", 0)
                    earn = row.get("Earnings", 0)
                    rows.append([
                        str(idx),
                        f"${rev / 1e9:.1f}B" if rev else "N/A",
                        f"${earn / 1e9:.1f}B" if earn else "N/A",
                    ])
                if rows:
                    table = build_table(headers, rows, alignments=['l', 'r', 'r'])
                    lines.append(table)
        except Exception:
            pass

    # Finnhub EPS estimates for upcoming quarters
    if FINNHUB_API_KEY:
        try:
            eps_est = get_eps_estimates(ticker)
            if eps_est:
                lines.append("\nUpcoming EPS Estimates:")
                for e in eps_est[:4]:
                    period = e.get("period", "?")
                    avg = e.get("epsAvg")
                    high = e.get("epsHigh")
                    low = e.get("epsLow")
                    n = e.get("numberAnalysts", 0)
                    if avg is not None:
                        range_s = f" (${low:.2f}-${high:.2f})" if low is not None and high is not None else ""
                        lines.append(f"  {period}: ${avg:.2f}{range_s} [{n} est]")
        except Exception:
            pass

    if not lines:
        await update.message.reply_text(f"No earnings data found for {ticker}")
        return

    body = "\n".join(lines)
    msg = telegram_msg(f"{ticker} — Earnings", body)
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /dividend ───────────────────────────────────────────────────────

async def dividend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dividend history and safety metrics."""
    ticker = _get_ticker(context)
    if not ticker:
        await update.message.reply_text("Usage: /dividend TICKER")
        return

    await update.message.reply_text(f"Fetching dividend data for {ticker}...")

    info = get_stock_info(ticker)
    if not info:
        await update.message.reply_text(f"No data found for {ticker}")
        return

    div_yield = _safe_get(info, "dividendYield", "trailingAnnualDividendYield")
    div_rate = _safe_get(info, "dividendRate", "trailingAnnualDividendRate")
    payout_ratio = _safe_get(info, "payoutRatio")
    ex_date = _safe_get(info, "exDividendDate")
    price = _safe_get(info, "regularMarketPrice", "currentPrice", "previousClose", default=0)
    eps = _safe_get(info, "trailingEps")
    fcf = _safe_get(info, "freeCashflow")
    shares = _safe_get(info, "sharesOutstanding")

    if not div_yield and not div_rate:
        await update.message.reply_text(f"{ticker} does not appear to pay a dividend.")
        return

    lines = []
    if price:
        lines.append(f"Price: ${price:.2f}")
    if div_rate:
        lines.append(f"Annual Dividend: ${div_rate:.2f}/share")
    if div_yield:
        lines.append(f"Dividend Yield: {div_yield * 100:.2f}%")
    if payout_ratio is not None:
        lines.append(f"Payout Ratio: {payout_ratio * 100:.1f}%")
        if payout_ratio < 0.4:
            lines.append("  → Very safe payout")
        elif payout_ratio < 0.6:
            lines.append("  → Moderate payout")
        elif payout_ratio < 0.8:
            lines.append("  → Elevated payout")
        else:
            lines.append("  → ⚠️ High payout — watch for cuts")

    # FCF payout ratio (more reliable)
    if fcf and shares and div_rate:
        fcf_per_share = fcf / shares
        fcf_payout = div_rate / fcf_per_share if fcf_per_share > 0 else None
        if fcf_payout is not None:
            lines.append(f"FCF Payout Ratio: {fcf_payout * 100:.1f}%")

    if ex_date:
        if isinstance(ex_date, (int, float)):
            ex_str = datetime.fromtimestamp(ex_date).strftime("%Y-%m-%d")
        else:
            ex_str = str(ex_date)
        lines.append(f"Ex-Dividend Date: {ex_str}")

    # EPS coverage
    if eps and div_rate and eps > 0:
        coverage = eps / div_rate
        lines.append(f"EPS Coverage: {coverage:.1f}x")

    # Dividend history from yfinance
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        divs = stock.dividends
        if divs is not None and not divs.empty:
            recent = divs.tail(8)
            lines.append("\nRecent Dividends:")
            headers = ["Date", "Amount"]
            rows = []
            for date, amount in recent.items():
                rows.append([str(date.date()), f"${amount:.4f}"])
            table = build_table(headers, rows, alignments=['l', 'r'])
            lines.append(table)

            # Growth: compare last year total vs prior year
            yearly = divs.resample('YE').sum()
            if len(yearly) >= 2:
                last_yr = float(yearly.iloc[-1])
                prev_yr = float(yearly.iloc[-2])
                if prev_yr > 0:
                    div_growth = ((last_yr - prev_yr) / prev_yr) * 100
                    lines.append(f"\nYoY Dividend Growth: {div_growth:+.1f}%")

            # Streak: consecutive years of paying dividends
            yearly_paid = yearly[yearly > 0]
            lines.append(f"Years Paying Dividends: {len(yearly_paid)}")
    except Exception:
        pass

    body = "\n".join(lines)
    msg = telegram_msg(f"{ticker} — Dividend Analysis", body)
    await update.message.reply_text(msg, parse_mode="HTML")


# ── /alert ──────────────────────────────────────────────────────────

async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set price alerts: /alert TICKER PRICE, /alert list, /alert clear."""
    global _alert_thread_started

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/alert TICKER PRICE — alert when price crosses target\n"
            "/alert list — show active alerts\n"
            "/alert clear — remove all alerts"
        )
        return

    chat_id = update.effective_chat.id

    # /alert list
    if context.args[0].lower() == "list":
        user_alerts = _alerts.get(chat_id, [])
        if not user_alerts:
            await update.message.reply_text("No active alerts. Use /alert TICKER PRICE")
            return
        lines = []
        for a in user_alerts:
            lines.append(f"  {a['ticker']} {a['direction']} ${a['target']:.2f}")
        body = "\n".join(lines)
        msg = telegram_msg(f"Active Alerts ({len(user_alerts)})", body)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # /alert clear
    if context.args[0].lower() == "clear":
        removed = len(_alerts.get(chat_id, []))
        _alerts[chat_id] = []
        await update.message.reply_text(f"Cleared {removed} alert(s)")
        return

    # /alert TICKER PRICE
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /alert TICKER PRICE")
        return

    ticker = context.args[0].upper()
    try:
        target_price = float(context.args[1].replace("$", ""))
    except ValueError:
        await update.message.reply_text("Invalid price. Usage: /alert AAPL 150")
        return

    # Get current price to determine direction
    info = get_stock_info(ticker)
    current = _safe_get(info, "regularMarketPrice", "currentPrice", "previousClose")
    if not current:
        try:
            hist = get_price_history(ticker, period="5d")
            if not hist.empty:
                current = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    if not current:
        await update.message.reply_text(f"Could not get current price for {ticker}")
        return

    direction = "above" if target_price > current else "below"

    if chat_id not in _alerts:
        _alerts[chat_id] = []

    _alerts[chat_id].append({
        "ticker": ticker,
        "target": target_price,
        "direction": direction,
        "created": datetime.now().isoformat(),
    })

    await update.message.reply_text(
        f"Alert set: {ticker} → ${target_price:.2f} "
        f"(currently ${current:.2f}, alert when {direction})\n"
        f"Checking every 5 minutes."
    )

    # Start background checker if not already running
    if not _alert_thread_started:
        _alert_thread_started = True
        app = context.application
        thread = threading.Thread(target=_alert_checker_loop, args=(app,), daemon=True)
        thread.start()


def _alert_checker_loop(app):
    """Background loop that checks price alerts every 5 minutes."""
    import asyncio

    while True:
        time.sleep(300)  # 5 minutes
        try:
            _check_alerts_sync(app)
        except Exception as e:
            logger.warning(f"Alert checker error: {e}")


def _check_alerts_sync(app):
    """Check all alerts and send notifications for triggered ones."""
    import asyncio

    triggered = []

    for chat_id, alerts_list in list(_alerts.items()):
        remaining = []
        for a in alerts_list:
            try:
                info = get_stock_info(a["ticker"])
                current = _safe_get(
                    info, "regularMarketPrice", "currentPrice", "previousClose"
                )
                if not current:
                    remaining.append(a)
                    continue

                hit = False
                if a["direction"] == "above" and current >= a["target"]:
                    hit = True
                elif a["direction"] == "below" and current <= a["target"]:
                    hit = True

                if hit:
                    triggered.append((chat_id, a, current))
                else:
                    remaining.append(a)
            except Exception:
                remaining.append(a)

        _alerts[chat_id] = remaining

    # Send notifications
    for chat_id, a, current in triggered:
        msg = (
            f"🔔 PRICE ALERT: {a['ticker']}\n"
            f"Target: ${a['target']:.2f} ({a['direction']})\n"
            f"Current: ${current:.2f}"
        )
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(app.bot.send_message(chat_id=chat_id, text=msg))
            loop.close()
        except Exception as e:
            logger.warning(f"Failed to send alert: {e}")
