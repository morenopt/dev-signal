"""
Telegram Bot for dev-signal agent.

Private bot that:
- Receives messages and routes them to the appropriate agent
- Sends daily trend alerts (triggered by Cloud Scheduler)
- Provides inline keyboards for approve/reject/mix actions
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_CHAT_ID = int(os.environ.get("TELEGRAM_OWNER_CHAT_ID", "0"))


def _is_owner(update: Update) -> bool:
    """Check if the message is from the bot owner."""
    return update.effective_chat.id == OWNER_CHAT_ID


async def cmd_start(update: Update, context) -> None:
    """Handle /start command."""
    if not _is_owner(update):
        await update.message.reply_text("This bot is private.")
        return
    await update.message.reply_text(
        "Hey! I'm your dev-signal assistant.\n\n"
        "Commands:\n"
        "/trends - Get today's trending topics\n"
        "/promote <url> - Generate promotion drafts\n"
        "Or just send me a message and I'll route it to the right agent."
    )


async def cmd_trends(update: Update, context) -> None:
    """Handle /trends command — trigger trend_scanner."""
    if not _is_owner(update):
        return
    await update.message.reply_text("Scanning trends across 400+ sources...")
    # This will be called by the FastAPI route handler which has agent access
    context.application.bot_data["pending_action"] = {
        "chat_id": update.effective_chat.id,
        "action": "trends",
        "query": " ".join(context.args) if context.args else "",
    }


async def cmd_promote(update: Update, context) -> None:
    """Handle /promote <url> command — trigger growth_promoter."""
    if not _is_owner(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /promote <dev.to URL>")
        return
    url = context.args[0]
    await update.message.reply_text(f"Generating promotion drafts for:\n{url}")
    context.application.bot_data["pending_action"] = {
        "chat_id": update.effective_chat.id,
        "action": "promote",
        "url": url,
    }


async def handle_message(update: Update, context) -> None:
    """Handle free-text messages — route to agent."""
    if not _is_owner(update):
        return
    text = update.message.text
    await update.message.reply_text("Processing...")
    context.application.bot_data["pending_action"] = {
        "chat_id": update.effective_chat.id,
        "action": "chat",
        "text": text,
    }


async def handle_callback(update: Update, context) -> None:
    """Handle inline keyboard button presses."""
    if not _is_owner(update):
        return
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "write:1", "skip", "mix:1,3"
    action, _, payload = data.partition(":")

    if action == "write":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Starting blog draft for trend #{payload}...")
        context.application.bot_data["pending_action"] = {
            "chat_id": update.effective_chat.id,
            "action": "write_trend",
            "trend_index": payload,
        }
    elif action == "mix":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Mixing trends #{payload} into a post...")
        context.application.bot_data["pending_action"] = {
            "chat_id": update.effective_chat.id,
            "action": "mix_trends",
            "trend_indices": payload,
        }
    elif action == "skip":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Skipped. See you tomorrow!")


def build_trends_keyboard(num_trends: int) -> InlineKeyboardMarkup:
    """Build inline keyboard for trend selection."""
    buttons = []
    # Individual write buttons
    row = [
        InlineKeyboardButton(f"Write #{i+1}", callback_data=f"write:{i+1}")
        for i in range(min(num_trends, 5))
    ]
    buttons.append(row)
    # Mix and skip
    buttons.append([
        InlineKeyboardButton("Mix top 2", callback_data="mix:1,2"),
        InlineKeyboardButton("Skip all", callback_data="skip:"),
    ])
    return InlineKeyboardMarkup(buttons)


def format_trends_message(trends_text: str) -> str:
    """Format trend scanner output for Telegram (markdown)."""
    # Truncate if too long for Telegram (4096 char limit)
    if len(trends_text) > 3800:
        trends_text = trends_text[:3800] + "\n\n... (truncated)"
    return trends_text


def create_bot_application() -> Application | None:
    """Create and configure the Telegram bot application."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")
        return None

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CommandHandler("promote", cmd_promote))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
