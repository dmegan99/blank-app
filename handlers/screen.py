"""Technical screening handler: /screen."""

from telegram import Update
from telegram.ext import ContextTypes

from services.yfinance_client import screen_ticker
from utils.formatters import build_table, telegram_msg
from config import load_watchlist


async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Technical screening of US watchlist (RSI, MACD, Fibonacci)."""
    watchlist = load_watchlist()
    if not watchlist:
        await update.message.reply_text("❌ No watchlist configured. Add tickers to watchlist.json")
        return

    await update.message.reply_text(f"Screening {len(watchlist)} tickers... this may take a moment.")

    results = []
    for ticker in watchlist:
        result = screen_ticker(ticker)
        if result:
            results.append(result)

    if not results:
        await update.message.reply_text("No screening results available")
        return

    # Sort: tickers with signals first, then by RSI
    with_signals = [r for r in results if r["signals"]]
    without_signals = [r for r in results if not r["signals"]]
    with_signals.sort(key=lambda x: x.get("rsi") or 50)
    without_signals.sort(key=lambda x: x.get("rsi") or 50)

    # Build alert section for tickers with signals
    parts = []
    if with_signals:
        parts.append("⚡ SIGNALS DETECTED:")
        for r in with_signals:
            signals_str = ", ".join(r["signals"])
            parts.append(f"  {r['ticker']}: {signals_str}")
        parts.append("")

    # Summary table for all
    headers = ["Ticker", "Price", "RSI", "MACD", "vs52H", "SMA", "Vol"]
    rows = []
    all_results = with_signals + without_signals
    for r in all_results:
        rsi_str = f"{r['rsi']:.1f}" if r["rsi"] is not None else "N/A"
        macd_str = r.get("macd_cross", "N/A") if r.get("macd_cross") != "none" else "-"
        pct_high = f"{r['pct_from_high']:.1f}%"

        # SMA position: above/below 50 & 200
        sma_str = ""
        if r.get("sma50") and r.get("sma200"):
            above50 = r["price"] > r["sma50"]
            above200 = r["price"] > r["sma200"]
            if above50 and above200:
                sma_str = "▲▲"
            elif above200:
                sma_str = "—▲"
            elif above50:
                sma_str = "▲—"
            else:
                sma_str = "▼▼"
        elif r.get("sma50"):
            sma_str = "▲" if r["price"] > r["sma50"] else "▼"

        vol_str = f"{r['vol_ratio']:.1f}x" if r.get("vol_ratio") else "-"

        rows.append([r["ticker"], f"${r['price']:.2f}", rsi_str, macd_str, pct_high, sma_str, vol_str])

    table = build_table(headers, rows)

    body = "\n".join(parts) + table if parts else table
    msg = telegram_msg(f"Technical Screen — {len(results)}/{len(watchlist)} tickers", body)

    # Split message if too long (Telegram 4096 char limit)
    if len(msg) > 4000:
        # Send signals section separately
        if with_signals:
            alert_msg = telegram_msg("⚡ Screen Alerts", "\n".join(parts))
            await update.message.reply_text(alert_msg, parse_mode="HTML")

        table_msg = telegram_msg(f"Screen Summary — {len(results)} tickers", table)
        await update.message.reply_text(table_msg, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, parse_mode="HTML")
