"""Telegram Finance Bot — Main entry point.

Runs the Telegram bot alongside a lightweight HTTP server
so it can be deployed as a free Render Web Service.
"""

import logging
import threading
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram.ext import ApplicationBuilder, CommandHandler

from config import TELEGRAM_BOT_TOKEN
from handlers.basic import help_cmd, ping, chatid, status
from handlers.edgar import rev, margin, profit, bs
from handlers.finnhub_cmds import insider, inst
from handlers.valuation import val
from handlers.screen import screen
from handlers.ai import brief, nongaap, x_search, summarize, thesis, news
from handlers.portfolio import watchlist, portfolio
from handlers.analysis import compare, dcf, peers, earnings, dividend, alert
from handlers.memory import themes_cmd, note_cmd, feedback_cmd

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler so Render sees a live web service."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Finance bot is running")

    def log_message(self, format, *args):
        pass  # Suppress HTTP request logs


def start_health_server():
    """Start a background HTTP server for Render's health checks."""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server listening on port {port}")
    server.serve_forever()


def start_keep_alive():
    """Ping own Render URL every 14 minutes to prevent free-tier sleep."""
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set — keep-alive disabled")
        return
    ping_url = render_url.rstrip("/") + "/"
    logger.info(f"Keep-alive will ping {ping_url} every 14 minutes")
    while True:
        time.sleep(14 * 60)
        try:
            resp = requests.get(ping_url, timeout=10)
            logger.info(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set.")
        print("Set it in your .env file or as an environment variable.")
        print("See .env.example for required configuration.")
        return

    # Start health check server in background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Start self-ping to keep Render free tier awake
    keep_alive_thread = threading.Thread(target=start_keep_alive, daemon=True)
    keep_alive_thread.start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Basic commands
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("start", help_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("status", status))

    # SEC EDGAR commands
    app.add_handler(CommandHandler("rev", rev))
    app.add_handler(CommandHandler("margin", margin))
    app.add_handler(CommandHandler("profit", profit))
    app.add_handler(CommandHandler("bs", bs))

    # Finnhub commands
    app.add_handler(CommandHandler("insider", insider))
    app.add_handler(CommandHandler("inst", inst))

    # Valuation (yfinance + finnhub)
    app.add_handler(CommandHandler("val", val))

    # Technical screening
    app.add_handler(CommandHandler("screen", screen))

    # AI-powered commands (uses Gemini API)
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("nongaap", nongaap))
    app.add_handler(CommandHandler("x", x_search))
    app.add_handler(CommandHandler("summarize", summarize))
    app.add_handler(CommandHandler("thesis", thesis))
    app.add_handler(CommandHandler("news", news))

    # Analysis commands
    app.add_handler(CommandHandler("compare", compare))
    app.add_handler(CommandHandler("dcf", dcf))
    app.add_handler(CommandHandler("peers", peers))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CommandHandler("dividend", dividend))
    app.add_handler(CommandHandler("alert", alert))

    # Memory & intelligence
    app.add_handler(CommandHandler("themes", themes_cmd))
    app.add_handler(CommandHandler("note", note_cmd))
    app.add_handler(CommandHandler("feedback", feedback_cmd))

    # Watchlist & portfolio
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("portfolio", portfolio))

    logger.info("Bot starting... polling for messages")
    app.run_polling()


if __name__ == "__main__":
    main()
