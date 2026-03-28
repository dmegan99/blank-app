"""Memory & intelligence handlers: /themes, /note, /feedback, /themes scan."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ContextTypes

from services.claude_client import ask_ai
from services.yfinance_client import get_stock_info, get_news
from utils.formatters import escape_html, telegram_msg, build_table
from config import (
    load_themes, save_themes,
    load_notes, save_notes,
    load_feedback, save_feedback,
    load_watchlist,
    GEMINI_API_KEY,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT BUILDER — feeds notes + themes into AI prompts
# ═══════════════════════════════════════════════════════════════════

def get_context_for_ticker(ticker: str, max_notes: int = 5) -> str:
    """Build context string from stored notes for a ticker."""
    notes = load_notes()
    key = ticker.upper()
    entries = notes.get(key, [])
    if not entries:
        return ""

    recent = entries[-max_notes:]
    lines = [f"YOUR PRIOR NOTES ON {key}:"]
    for n in recent:
        ts = n.get("timestamp", "?")[:10]
        src = n.get("source", "manual")
        lines.append(f"  [{ts}|{src}] {n['text']}")
    return "\n".join(lines)


def get_context_for_themes(relevant_tickers: list = None) -> str:
    """Build context string from active themes, optionally filtered by tickers."""
    themes = load_themes()
    if not themes:
        return ""

    lines = ["ACTIVE THEMES YOU ARE TRACKING:"]
    for t in themes:
        tickers = t.get("tickers", [])
        # If filtering, only include themes that overlap with requested tickers
        if relevant_tickers:
            overlap = set(tickers) & set(relevant_tickers)
            if not overlap and tickers:
                continue
        desc = t.get("description", "")
        ticker_str = ", ".join(tickers) if tickers else "broad"
        lines.append(f"  • {t['name']} [{ticker_str}]: {desc}")
    return "\n".join(lines) if len(lines) > 1 else ""


def get_full_context(ticker: str = None, tickers: list = None) -> str:
    """Get combined notes + themes context for AI prompts."""
    parts = []

    if ticker:
        tc = get_context_for_ticker(ticker)
        if tc:
            parts.append(tc)

    if tickers:
        for t in tickers[:5]:  # limit to avoid prompt bloat
            tc = get_context_for_ticker(t)
            if tc:
                parts.append(tc)

    theme_ctx = get_context_for_themes(
        [ticker] if ticker else (tickers or [])
    )
    if theme_ctx:
        parts.append(theme_ctx)

    # Add feedback patterns
    feedback = load_feedback()
    if feedback:
        patterns = [f.get("pattern", "") for f in feedback[-5:] if f.get("pattern")]
        if patterns:
            parts.append("LEARNED PREFERENCES:\n  " + "\n  ".join(patterns))

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
#  /themes — manage theme watchlist
# ═══════════════════════════════════════════════════════════════════

async def themes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage theme watchlist.

    /themes — list active themes
    /themes add NAME — add a new theme
    /themes add NAME | description | TICK1,TICK2 — full add
    /themes remove NAME — remove a theme
    /themes scan — AI scan for emerging themes
    """
    args = list(context.args) if context.args else []
    current = load_themes()

    # /themes — list all
    if not args:
        if not current:
            await update.message.reply_text(
                "No themes tracked yet.\n\n"
                "Add one:\n"
                "/themes add AI Infrastructure\n"
                "/themes add Rate Cuts | Fed policy impact on growth | AAPL,MSFT,GOOGL"
            )
            return

        lines = []
        for i, t in enumerate(current, 1):
            tickers = ", ".join(t.get("tickers", [])) or "broad"
            desc = t.get("description", "")[:60]
            lines.append(f"{i}. {t['name']}")
            if desc:
                lines.append(f"   {desc}")
            lines.append(f"   Tickers: {tickers}")

        body = "\n".join(lines)
        msg = telegram_msg(f"Theme Watchlist — {len(current)} themes", body,
                           "\n/themes add NAME | desc | TICK1,TICK2\n/themes remove NAME\n/themes scan")
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    action = args[0].lower()

    # /themes scan — AI emerging themes
    if action == "scan":
        await _themes_scan(update)
        return

    # /themes info NAME — show theme details + related notes
    if action == "info":
        theme_name = " ".join(args[1:]).lower()
        if not theme_name:
            await update.message.reply_text("Usage: /themes info Theme Name")
            return

        theme = None
        for t in current:
            if t["name"].lower() == theme_name:
                theme = t
                break

        # Partial match fallback
        if not theme:
            for t in current:
                if theme_name in t["name"].lower():
                    theme = t
                    break

        if not theme:
            await update.message.reply_text(f"Theme '{theme_name}' not found. Use /themes to list.")
            return

        # Combine explicit theme tickers + watchlist tickers
        explicit_tickers = theme.get("tickers", [])
        watchlist_tickers = load_watchlist()
        all_related = list(dict.fromkeys(explicit_tickers + watchlist_tickers))

        lines = [
            f"Name: {theme['name']}",
            f"Description: {theme.get('description', 'none')}",
            f"Tickers: {', '.join(explicit_tickers) or 'auto from watchlist'}",
            f"Added: {theme.get('added', '?')[:10]}",
        ]

        # Pull notes for theme tickers, then scan all watchlist notes for keyword matches
        notes = load_notes()
        theme_keywords = theme["name"].lower().split() + theme.get("description", "").lower().split()
        # Filter out short/common words
        theme_keywords = [w for w in theme_keywords if len(w) > 3 and w not in
                          {"with", "from", "that", "this", "they", "their", "about", "across"}]

        note_lines = []
        shown_tickers = set()

        # First: notes for explicit tickers
        for ticker in explicit_tickers:
            entries = notes.get(ticker, [])
            if entries:
                shown_tickers.add(ticker)
                note_lines.append(f"\n{ticker} ({len(entries)} notes):")
                for n in entries[-5:]:
                    ts = n["timestamp"][:10]
                    src = n.get("source", "manual")
                    note_lines.append(f"  [{ts}|{src}] {n['text'][:80]}")

        # Second: scan all notes for keyword matches (auto-linking)
        for subject, entries in notes.items():
            if subject in shown_tickers:
                continue
            # Check if any notes mention theme keywords
            relevant = []
            for n in entries[-10:]:
                text_lower = n["text"].lower()
                if any(kw in text_lower for kw in theme_keywords):
                    relevant.append(n)
            if relevant:
                shown_tickers.add(subject)
                note_lines.append(f"\n{subject} ({len(relevant)} related):")
                for n in relevant[-3:]:
                    ts = n["timestamp"][:10]
                    src = n.get("source", "manual")
                    note_lines.append(f"  [{ts}|{src}] {n['text'][:80]}")

        # Third: notes keyed by theme name itself
        theme_key = theme["name"].upper()
        theme_notes = notes.get(theme_key, [])
        if theme_notes:
            note_lines.append(f"\n📋 Theme-level notes ({len(theme_notes)}):")
            for n in theme_notes[-5:]:
                ts = n["timestamp"][:10]
                src = n.get("source", "manual")
                note_lines.append(f"  [{ts}|{src}] {n['text'][:80]}")

        if note_lines:
            lines.append("\n📝 Related Notes:")
            lines.extend(note_lines)
        else:
            lines.append("\nNo notes yet. Save with:")
            lines.append(f"  /note {explicit_tickers[0] if explicit_tickers else 'TICKER'} your observation")
            lines.append(f"  /note {theme_key} theme-level note")

        body = "\n".join(lines)
        msg = telegram_msg(f"Theme: {theme['name']}", body)

        # Split if too long
        if len(msg) > 4000:
            msg = msg[:3950] + "\n[truncated]</pre>"

        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # /themes add
    if action == "add":
        raw = " ".join(args[1:])
        if not raw:
            await update.message.reply_text(
                "Usage: /themes add Theme Name\n"
                "Or: /themes add Theme Name | description | TICK1,TICK2"
            )
            return

        parts = [p.strip() for p in raw.split("|")]
        name = parts[0]
        description = parts[1] if len(parts) > 1 else ""
        tickers = [t.strip().upper() for t in parts[2].split(",")] if len(parts) > 2 else []

        # Check duplicate
        for t in current:
            if t["name"].lower() == name.lower():
                await update.message.reply_text(f"Theme '{name}' already exists.")
                return

        current.append({
            "name": name,
            "description": description,
            "tickers": tickers,
            "added": datetime.now(ET).isoformat(),
        })
        save_themes(current)
        await update.message.reply_text(
            f"✅ Added theme: {name}\n"
            + (f"Description: {description}\n" if description else "")
            + (f"Tickers: {', '.join(tickers)}" if tickers else "No specific tickers (broad theme)")
        )
        return

    # /themes edit NAME | new description | NEW,TICKERS
    if action == "edit":
        raw = " ".join(args[1:])
        if not raw:
            await update.message.reply_text(
                "Usage: /themes edit Theme Name | new description | TICK1,TICK2\n"
                "Use - to keep existing value:\n"
                "/themes edit AI Infra | - | NVDA,AMD,TSM  (keep desc, change tickers)\n"
                "/themes edit AI Infra | new desc | -  (change desc, keep tickers)\n"
                "/themes edit AI Infra | new desc | NVDA,AMD  (change both)"
            )
            return

        parts = [p.strip() for p in raw.split("|")]
        search_name = parts[0].strip().lower()

        theme = None
        for t in current:
            if t["name"].lower() == search_name:
                theme = t
                break

        if not theme:
            # Try partial match
            for t in current:
                if search_name in t["name"].lower():
                    theme = t
                    break

        if not theme:
            await update.message.reply_text(f"Theme '{parts[0]}' not found. Use /themes to list.")
            return

        changes = []
        if len(parts) > 1 and parts[1].strip() != "-" and parts[1].strip():
            theme["description"] = parts[1].strip()
            changes.append(f"Description: {theme['description']}")

        if len(parts) > 2 and parts[2].strip() != "-" and parts[2].strip():
            theme["tickers"] = [t.strip().upper() for t in parts[2].split(",") if t.strip()]
            changes.append(f"Tickers: {', '.join(theme['tickers'])}")

        # Allow renaming: /themes edit OLD NAME | new desc | tickers | NEW NAME
        if len(parts) > 3 and parts[3].strip():
            old_name = theme["name"]
            theme["name"] = parts[3].strip()
            changes.append(f"Renamed: {old_name} → {theme['name']}")

        if not changes:
            await update.message.reply_text("Nothing changed. Use | to separate fields:\n/themes edit Name | description | TICKERS")
            return

        save_themes(current)
        await update.message.reply_text(f"✅ Updated theme:\n" + "\n".join(changes))
        return

    # /themes remove
    if action in ("remove", "rm", "del", "delete"):
        name = " ".join(args[1:]).lower()
        if not name:
            await update.message.reply_text("Usage: /themes remove Theme Name")
            return
        before = len(current)
        current = [t for t in current if t["name"].lower() != name]
        save_themes(current)
        if len(current) < before:
            await update.message.reply_text(f"🗑 Removed theme: {name}")
        else:
            await update.message.reply_text(f"Theme '{name}' not found.")
        return

    # Shorthand: /themes Some Theme Name → add it
    name = " ".join(args)
    current.append({
        "name": name,
        "description": "",
        "tickers": [],
        "added": datetime.now(ET).isoformat(),
    })
    save_themes(current)
    await update.message.reply_text(f"✅ Added theme: {name}")


async def _themes_scan(update: Update):
    """AI scan for emerging themes across watchlist and news."""
    if not GEMINI_API_KEY:
        await update.message.reply_text("❌ GEMINI_API_KEY not configured")
        return

    await update.message.reply_text("Scanning for emerging themes... (30-60s)")

    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    # Gather headlines from watchlist
    watchlist = load_watchlist()
    all_headlines = []
    for ticker in watchlist[:15]:
        headlines = get_news(ticker, max_items=3)
        if headlines:
            lines = [f"{ticker}:"]
            for h in headlines:
                lines.append(f"  - {h['title']}")
            all_headlines.append("\n".join(lines))

    headlines_block = "\n".join(all_headlines) if all_headlines else "(no headlines available)"

    # Current themes for comparison
    current_themes = load_themes()
    existing = ", ".join(t["name"] for t in current_themes) if current_themes else "none"

    # Notes for context
    notes = load_notes()
    notes_summary = ""
    if notes:
        subjects = list(notes.keys())[:10]
        notes_summary = f"Subjects with existing notes: {', '.join(subjects)}"

    system = (
        f"You are a thematic investment analyst. Today is {today}. "
        f"Your job is to identify EMERGING investment themes by analyzing news across "
        f"multiple companies and sectors. Look for:\n"
        f"- Patterns appearing across multiple tickers\n"
        f"- New regulatory/policy shifts\n"
        f"- Technology inflection points\n"
        f"- Supply chain or geopolitical shifts\n"
        f"- Sector rotation signals\n"
        f"- Sentiment shifts on social media\n\n"
        f"The user is already tracking these themes: {existing}\n"
        f"Focus on NEW themes they might be missing.\n\n"
        f"For each emerging theme:\n"
        f"1. Theme name (short, memorable)\n"
        f"2. Why it's emerging NOW (specific catalysts)\n"
        f"3. Affected tickers\n"
        f"4. Potential impact (high/medium/low)\n"
        f"5. Suggested action: add to watchlist? deeper research?\n\n"
        f"Identify 3-5 themes. Be specific, not generic."
    )

    prompt = (
        f"Analyze these recent headlines from my watchlist and search the web for "
        f"broader market themes emerging as of {today}:\n\n"
        f"WATCHLIST HEADLINES:\n{headlines_block}\n\n"
        f"{notes_summary}\n\n"
        f"Search the web for today's biggest market themes, sector trends, and "
        f"emerging narratives. Identify 3-5 NEW emerging themes I should pay attention to."
    )

    response = ask_ai(prompt, system=system, use_search=True)
    if not response or response.startswith("["):
        await update.message.reply_text(f"AI error: {response or 'no response'}")
        return

    if len(response) > 3900:
        response = response[:3900] + "\n\n[truncated]"

    await update.message.reply_text(
        f"<b>🔍 Emerging Themes Scan — {today}</b>\n\n{escape_html(response)}",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════
#  /note — memory system
# ═══════════════════════════════════════════════════════════════════

async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage notes/memory.

    /note SUBJECT your note text — save a note
    /note SUBJECT — view notes for a subject
    /note list — list all subjects with notes
    /note clear SUBJECT — clear notes for a subject
    """
    args = list(context.args) if context.args else []
    notes = load_notes()

    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "/note NVDA margins expanding rapidly\n"
            "/note NVDA — view notes\n"
            "/note list — list all subjects\n"
            "/note clear NVDA — clear notes"
        )
        return

    # /note list
    if args[0].lower() == "list":
        if not notes:
            await update.message.reply_text("No notes yet. Use /note SUBJECT your note text")
            return
        lines = []
        for subject, entries in notes.items():
            latest = entries[-1]["timestamp"][:10] if entries else "?"
            lines.append(f"  {subject}: {len(entries)} notes (latest: {latest})")
        body = "\n".join(lines)
        msg = telegram_msg(f"Notes — {len(notes)} subjects", body)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # /note clear SUBJECT
    if args[0].lower() == "clear":
        subject = args[1].upper() if len(args) > 1 else None
        if not subject:
            await update.message.reply_text("Usage: /note clear SUBJECT")
            return
        if subject in notes:
            count = len(notes[subject])
            del notes[subject]
            save_notes(notes)
            await update.message.reply_text(f"🗑 Cleared {count} notes for {subject}")
        else:
            await update.message.reply_text(f"No notes found for {subject}")
        return

    subject = args[0].upper()

    # /note SUBJECT (view)
    if len(args) == 1:
        entries = notes.get(subject, [])
        if not entries:
            await update.message.reply_text(f"No notes for {subject}. Add one:\n/note {subject} your observation here")
            return
        lines = []
        for n in entries[-10:]:  # last 10
            ts = n["timestamp"][:16]
            src = n.get("source", "manual")
            lines.append(f"[{ts}|{src}]\n  {n['text']}")
        body = "\n".join(lines)
        msg = telegram_msg(f"{subject} — Notes ({len(entries)} total)", body)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # /note SUBJECT text... — save new note
    note_text = " ".join(args[1:])
    now = datetime.now(ET)

    if subject not in notes:
        notes[subject] = []

    new_entry = {
        "text": note_text,
        "timestamp": now.isoformat(),
        "source": "manual",
    }

    # Check for contradictions with existing notes
    contradiction_note = ""
    if notes[subject] and GEMINI_API_KEY:
        existing_texts = [n["text"] for n in notes[subject][-5:]]
        existing_block = "\n".join(f"  - {t}" for t in existing_texts)
        check_prompt = (
            f"EXISTING NOTES for {subject}:\n{existing_block}\n\n"
            f"NEW NOTE: {note_text}\n\n"
            f"Does the new note CONTRADICT or significantly UPDATE any existing notes? "
            f"If yes, briefly explain what changed (1-2 sentences). If no, reply 'consistent'."
        )
        check = ask_ai(check_prompt, system="You are a concise analyst. Be brief.")
        if check and "consistent" not in check.lower():
            contradiction_note = f"\n\n⚠️ Change detected: {check}"

    notes[subject].append(new_entry)
    save_notes(notes)

    count = len(notes[subject])
    await update.message.reply_text(
        f"📝 Note saved for {subject} ({count} total){contradiction_note}"
    )


async def auto_note(subject: str, text: str, source: str = "auto"):
    """Programmatically save a note (called by other handlers)."""
    notes = load_notes()
    if subject not in notes:
        notes[subject] = []

    notes[subject].append({
        "text": text,
        "timestamp": datetime.now(ET).isoformat(),
        "source": source,
    })

    # Keep max 50 notes per subject
    if len(notes[subject]) > 50:
        notes[subject] = notes[subject][-50:]

    save_notes(notes)


# ═══════════════════════════════════════════════════════════════════
#  /feedback — learning loop
# ═══════════════════════════════════════════════════════════════════

async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record feedback to improve responses.

    /feedback good — last response was good
    /feedback bad too verbose — last response was bad, with reason
    /feedback prefer bullet points over paragraphs
    /feedback list — view recorded feedback
    /feedback clear — clear all feedback
    """
    args = list(context.args) if context.args else []
    entries = load_feedback()

    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "/feedback good — thumbs up last response\n"
            "/feedback bad reason — flag issue\n"
            "/feedback prefer X over Y — set preference\n"
            "/feedback list — view all feedback\n"
            "/feedback clear — reset"
        )
        return

    action = args[0].lower()

    if action == "list":
        if not entries:
            await update.message.reply_text("No feedback recorded yet.")
            return
        lines = []
        for f in entries[-15:]:
            ts = f.get("timestamp", "?")[:10]
            typ = f.get("type", "?")
            txt = f.get("text", "")[:50]
            lines.append(f"  [{ts}] {typ}: {txt}")
        body = "\n".join(lines)
        msg = telegram_msg(f"Feedback — {len(entries)} entries", body)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if action == "clear":
        save_feedback([])
        await update.message.reply_text("🗑 All feedback cleared.")
        return

    now = datetime.now(ET)

    if action == "good":
        entry = {
            "type": "positive",
            "text": " ".join(args[1:]) if len(args) > 1 else "good response",
            "timestamp": now.isoformat(),
            "pattern": "",
        }
    elif action == "bad":
        reason = " ".join(args[1:]) if len(args) > 1 else "unspecified"
        # Try to extract a preference pattern from the reason
        pattern = ""
        if GEMINI_API_KEY and len(reason) > 5:
            pat = ask_ai(
                f"The user gave negative feedback: '{reason}'. "
                f"Extract a SHORT actionable preference rule (e.g., 'Use bullet points, not paragraphs' "
                f"or 'Keep responses under 200 words'). Reply with JUST the rule, nothing else.",
                system="Extract a 1-sentence preference rule."
            )
            if pat and not pat.startswith("["):
                pattern = pat.strip()

        entry = {
            "type": "negative",
            "text": reason,
            "timestamp": now.isoformat(),
            "pattern": pattern,
        }
    elif action == "prefer":
        preference = " ".join(args[1:])
        entry = {
            "type": "preference",
            "text": preference,
            "timestamp": now.isoformat(),
            "pattern": preference,
        }
    else:
        # Treat everything as a general preference
        preference = " ".join(args)
        entry = {
            "type": "preference",
            "text": preference,
            "timestamp": now.isoformat(),
            "pattern": preference,
        }

    entries.append(entry)

    # Keep max 100 feedback entries
    if len(entries) > 100:
        entries = entries[-100:]

    save_feedback(entries)

    response = f"✅ Feedback recorded: {entry['type']}"
    if entry.get("pattern"):
        response += f"\nLearned: {entry['pattern']}"
    await update.message.reply_text(response)


# ═══════════════════════════════════════════════════════════════════
#  /scan — trigger manual scan
# ═══════════════════════════════════════════════════════════════════

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger the daily auto-scan."""
    await update.message.reply_text("Running manual scan... (30-60s)")

    from services.daily_scan import _daily_scan
    try:
        await _daily_scan(context.application)
        await update.message.reply_text("✅ Scan complete — check above for results.")
    except Exception as e:
        await update.message.reply_text(f"Scan error: {e}")
