"""Daily auto-scan and smart alert engine.

Runs background jobs to:
1. Daily scan (6:30 AM ET): scan watchlist for overnight moves, news,
   compare against notes, auto-save observations, detect emerging themes.
2. Smart alerts (every 30 min): check for important developments that
   warrant proactive notification.

Designed to stay within free-tier limits:
- yfinance: ~30 calls per scan (no limit but be polite)
- Gemini: 2-3 calls per scan (free tier: 15/min, 1500/day)
- Finnhub: ~10 calls per scan (60/min free tier)
"""

import logging
import time
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    load_watchlist, load_themes, load_notes, save_notes,
    load_chat_ids, GEMINI_API_KEY, FINNHUB_API_KEY,
)
from services.claude_client import ask_ai
from services.yfinance_client import get_stock_info, get_news, get_price_history

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Track last scan to avoid double-runs
_last_daily_scan = None
_last_alert_check = None


def start_background_jobs(app):
    """Start all background job threads. Called from bot.py main()."""
    thread = threading.Thread(target=_scheduler_loop, args=(app,), daemon=True)
    thread.start()
    logger.info("Background scheduler started")


def _scheduler_loop(app):
    """Main scheduler: runs daily scan at 6:30 AM ET, alerts every 30 min."""
    global _last_daily_scan, _last_alert_check

    # Wait 60s after boot to let bot fully initialize
    time.sleep(60)
    logger.info("Background scheduler active")

    while True:
        try:
            now_et = datetime.now(ET)
            today_str = now_et.strftime("%Y-%m-%d")

            # Daily scan at 6:30 AM ET (run once per day)
            if (now_et.hour == 6 and now_et.minute >= 30 and now_et.minute < 35
                    and _last_daily_scan != today_str):
                logger.info("Starting daily auto-scan...")
                _last_daily_scan = today_str
                _run_async(app, _daily_scan(app))

            # Smart alert check every 30 minutes during market-relevant hours (6 AM - 8 PM ET)
            if 6 <= now_et.hour <= 20:
                check_key = f"{today_str}-{now_et.hour}-{now_et.minute // 30}"
                if _last_alert_check != check_key:
                    _last_alert_check = check_key
                    _run_async(app, _smart_alert_check(app))

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(60)  # Check every minute


def _run_async(app, coro):
    """Run an async coroutine from a sync thread."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(coro)
        loop.close()
    except Exception as e:
        logger.error(f"Async runner error: {e}")


async def _send_to_all(app, text: str, parse_mode: str = None):
    """Send a message to all registered chat IDs."""
    chat_ids = load_chat_ids()
    for cid in chat_ids:
        try:
            await app.bot.send_message(chat_id=cid, text=text, parse_mode=parse_mode)
        except Exception as e:
            logger.warning(f"Failed to send to {cid}: {e}")


# ═══════════════════════════════════════════════════════════════════
#  DAILY SCAN — runs once at 6:30 AM ET
# ═══════════════════════════════════════════════════════════════════

async def _daily_scan(app):
    """Full daily scan: price moves, news, note comparisons, theme detection."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    watchlist = load_watchlist()
    notes = load_notes()

    if not watchlist:
        return

    logger.info(f"Daily scan: {len(watchlist)} tickers")

    # ── 1. Check overnight price moves ──
    movers = []
    for ticker in watchlist:
        try:
            hist = get_price_history(ticker, period="5d")
            if hist is None or hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            chg_pct = ((last - prev) / prev) * 100

            if abs(chg_pct) >= 3.0:  # 3%+ move is notable
                movers.append({
                    "ticker": ticker,
                    "price": last,
                    "change": chg_pct,
                })

                # Auto-note significant moves
                note_text = f"Moved {chg_pct:+.1f}% to ${last:.2f}"
                _auto_save_note(ticker, note_text, "daily_scan")

        except Exception as e:
            logger.debug(f"Scan price error {ticker}: {e}")
        time.sleep(0.3)  # Be polite to yfinance

    # ── 2. Scan news for top movers + first 8 watchlist tickers ──
    scan_tickers = list(set(
        [m["ticker"] for m in movers] + watchlist[:8]
    ))[:12]  # Cap at 12 to stay in free tier

    all_headlines = {}
    for ticker in scan_tickers:
        try:
            hl = get_news(ticker, max_items=5)
            if hl:
                all_headlines[ticker] = hl
        except Exception:
            pass
        time.sleep(0.2)

    # ── 3. Compare news against notes — find contradictions ──
    contradiction_alerts = []
    if GEMINI_API_KEY and all_headlines and notes:
        # Build a compact summary for AI analysis
        news_block = []
        notes_block = []

        for ticker, headlines in list(all_headlines.items())[:8]:
            hl_text = "; ".join(h["title"] for h in headlines[:3])
            news_block.append(f"{ticker}: {hl_text}")

            if ticker in notes and notes[ticker]:
                recent_notes = [n["text"] for n in notes[ticker][-3:]]
                notes_block.append(f"{ticker}: {' | '.join(recent_notes)}")

        if news_block and notes_block:
            prompt = (
                f"Today is {today}. Compare these NEWS headlines against the user's PRIOR NOTES.\n\n"
                f"NEWS:\n" + "\n".join(news_block) + "\n\n"
                f"PRIOR NOTES:\n" + "\n".join(notes_block) + "\n\n"
                f"For each ticker where news CONTRADICTS or SIGNIFICANTLY UPDATES a prior note, "
                f"output a line: TICKER: what changed and why it matters.\n"
                f"If nothing contradicts, reply 'ALL_CONSISTENT'.\n"
                f"Be brief — one line per contradiction max."
            )

            try:
                result = ask_ai(prompt, system="Be extremely concise. One line per finding.",
                                use_search=False)
                if result and "ALL_CONSISTENT" not in result:
                    for line in result.strip().split("\n"):
                        line = line.strip()
                        if line and ":" in line:
                            contradiction_alerts.append(line)
                            # Auto-note the contradiction
                            parts = line.split(":", 1)
                            _auto_save_note(parts[0].strip(), f"[CHANGE] {parts[1].strip()}",
                                            "contradiction_scan")
            except Exception as e:
                logger.warning(f"Contradiction check error: {e}")

    # ── 4. Emerging themes scan (1 Gemini call) ──
    emerging_themes = ""
    if GEMINI_API_KEY and all_headlines:
        themes = load_themes()
        existing_names = ", ".join(t["name"] for t in themes) if themes else "none"

        hl_summary = "\n".join(
            f"{t}: " + "; ".join(h["title"] for h in hl[:2])
            for t, hl in list(all_headlines.items())[:10]
        )

        try:
            result = ask_ai(
                f"Today is {today}. Headlines across watchlist:\n{hl_summary}\n\n"
                f"Currently tracked themes: {existing_names}\n\n"
                f"Are there any NEW emerging investment themes visible in these headlines "
                f"that aren't already tracked? Reply with theme names and 1-sentence why, "
                f"or 'NONE_NEW' if nothing notable. Max 3 themes.",
                system="Be extremely concise. One line per theme.",
                use_search=True,
            )
            if result and "NONE_NEW" not in result:
                emerging_themes = result.strip()
        except Exception:
            pass

    # ── 5. Build daily digest and send ──
    digest_parts = [f"🤖 Daily Auto-Scan — {today} 6:30 AM ET\n"]

    if movers:
        digest_parts.append("📊 Significant Moves:")
        for m in sorted(movers, key=lambda x: abs(x["change"]), reverse=True):
            emoji = "🟢" if m["change"] > 0 else "🔴"
            digest_parts.append(f"  {emoji} {m['ticker']}: ${m['price']:.2f} ({m['change']:+.1f}%)")

    if contradiction_alerts:
        digest_parts.append("\n⚠️ Note Conflicts Detected:")
        for c in contradiction_alerts:
            digest_parts.append(f"  {c}")

    if emerging_themes:
        digest_parts.append(f"\n🔍 Emerging Themes:\n  {emerging_themes}")

    # Summary stats
    total_notes = sum(len(v) for v in load_notes().values())
    digest_parts.append(f"\n📝 Memory: {total_notes} notes across {len(load_notes())} subjects")

    if len(digest_parts) > 1:  # More than just the header
        msg = "\n".join(digest_parts)
        await _send_to_all(app, msg)
        logger.info("Daily scan digest sent")
    else:
        logger.info("Daily scan: nothing notable to report")


# ═══════════════════════════════════════════════════════════════════
#  SMART ALERTS — check every 30 min for important developments
# ═══════════════════════════════════════════════════════════════════

async def _smart_alert_check(app):
    """Quick check for developments that warrant immediate notification."""
    now_et = datetime.now(ET)
    watchlist = load_watchlist()

    if not watchlist:
        return

    alerts = []

    # ── Check for big intraday moves (>5%) ──
    for ticker in watchlist[:15]:
        try:
            info = get_stock_info(ticker)
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

            if price and prev_close and prev_close > 0:
                chg = ((price - prev_close) / prev_close) * 100
                if abs(chg) >= 5.0:
                    emoji = "🚀" if chg > 0 else "💥"
                    alerts.append(
                        f"{emoji} {ticker}: ${price:.2f} ({chg:+.1f}%) — big intraday move"
                    )
                    _auto_save_note(ticker, f"Big move {chg:+.1f}% to ${price:.2f}", "smart_alert")
        except Exception:
            pass
        time.sleep(0.2)

    # ── Check for breaking news on top tickers (limit to 5 to conserve API) ──
    notes = load_notes()
    for ticker in watchlist[:5]:
        try:
            headlines = get_news(ticker, max_items=3)
            if not headlines:
                continue

            # Check if any headline mentions earnings, FDA, merger, acquisition, etc.
            high_impact_keywords = [
                "earnings", "beat", "miss", "guidance", "downgrade", "upgrade",
                "FDA", "merger", "acquisition", "buyout", "layoff", "restructur",
                "investigation", "lawsuit", "recall", "bankruptcy", "dividend cut",
                "stock split", "CEO", "resign", "fired",
            ]

            for h in headlines[:3]:
                title_lower = h["title"].lower()
                for kw in high_impact_keywords:
                    if kw in title_lower:
                        # Check we haven't already alerted this (use title hash)
                        note_key = f"[ALERT] {h['title'][:80]}"
                        existing = notes.get(ticker, [])
                        already_noted = any(n["text"].startswith("[ALERT]") and
                                            h["title"][:40] in n["text"]
                                            for n in existing[-10:])
                        if not already_noted:
                            alerts.append(f"📰 {ticker}: {h['title']}")
                            _auto_save_note(ticker, note_key, "breaking_news")
                        break
        except Exception:
            pass
        time.sleep(0.2)

    # Send alerts if any
    if alerts:
        msg = "🔔 Smart Alert\n\n" + "\n".join(alerts)
        await _send_to_all(app, msg)
        logger.info(f"Smart alert sent: {len(alerts)} items")


# ═══════════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════════

def _auto_save_note(subject: str, text: str, source: str):
    """Save a note without async (for background threads)."""
    try:
        notes = load_notes()
        subject = subject.upper()
        if subject not in notes:
            notes[subject] = []

        # Avoid duplicate recent notes
        recent = notes[subject][-5:] if notes[subject] else []
        if any(n["text"] == text for n in recent):
            return

        notes[subject].append({
            "text": text,
            "timestamp": datetime.now(ET).isoformat(),
            "source": source,
        })

        # Keep max 50 per subject
        if len(notes[subject]) > 50:
            notes[subject] = notes[subject][-50:]

        save_notes(notes)
    except Exception as e:
        logger.warning(f"Auto-note save error: {e}")
