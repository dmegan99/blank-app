"""Telegram Finance Bot — Main entry point."""

import logging
from telegram.ext import ApplicationBuilder, CommandHandler

from config import TELEGRAM_BOT_TOKEN
from handlers.basic import ping, chatid, status
from handlers.edgar import rev, margin, profit, bs
from handlers.finnhub_cmds import insider, inst
from handlers.valuation import val
from handlers.screen import screen
from handlers.ai import brief, nongaap, x_search

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set.")
        print("Set it in your .env file or as an environment variable.")
        print("See .env.example for required configuration.")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Basic commands
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

    # AI-powered commands (require ANTHROPIC_API_KEY)
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("nongaap", nongaap))
    app.add_handler(CommandHandler("x", x_search))

    logger.info("Bot starting... polling for messages")
    app.run_polling()


if __name__ == "__main__":
    main()
