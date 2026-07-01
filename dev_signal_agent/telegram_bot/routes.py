"""
FastAPI routes for Telegram bot integration.

- POST /telegram/webhook — receives Telegram updates via webhook
- POST /telegram/cron/trends — triggered by Cloud Scheduler for daily trends

Architecture note:
  The Telegram bot uses a direct ADK Runner with VertexAiSessionService +
  VertexAiMemoryBankService for persistence.  This is the same Agent Engine
  backend used by the ADK Web UI (configured in fast_api_app.py), so
  sessions and memory are shared and survive Cloud Run scale-to-zero.
"""

import os
import asyncio
import logging
from datetime import date
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Response
from telegram import Update, Bot
from telegram.constants import ParseMode

from google.adk.runners import Runner
from google.genai import types as genai_types

from dev_signal_agent.telegram_bot.bot import (
    create_bot_application,
    TELEGRAM_BOT_TOKEN,
    OWNER_CHAT_ID,
    build_trends_keyboard,
    format_trends_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

# Webhook secret — Telegram sends this in X-Telegram-Bot-Api-Secret-Token header
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "dev-signal-webhook-7x9k2m")

# Lazy-initialized singletons
_bot_app = None
_bot: Bot | None = None
_runner: Runner | None = None

# Service URIs — injected by fast_api_app.py via configure_services()
_session_service_uri: str | None = None
_memory_service_uri: str | None = None

APP_NAME = "dev_signal_agent"
USER_ID = "telegram_owner"


def configure_services(session_uri: str | None, memory_uri: str | None):
    """Called by fast_api_app.py to share Agent Engine URIs with this module.

    This avoids circular imports and ensures Telegram uses the SAME
    persistent backend as the ADK Web UI.
    """
    global _session_service_uri, _memory_service_uri
    _session_service_uri = session_uri
    _memory_service_uri = memory_uri
    logger.info(
        "Telegram services configured — session=%s, memory=%s",
        session_uri, memory_uri,
    )


def _parse_agent_engine_uri(uri: str) -> dict:
    """Parse agentengine://projects/P/locations/L/reasoningEngines/E into kwargs."""
    parsed = urlparse(uri)
    # netloc + path gives: projects/P/locations/L/reasoningEngines/E
    parts = (parsed.netloc + parsed.path).strip("/").split("/")
    result = {}
    if len(parts) >= 2:
        result["project"] = parts[1]
    if len(parts) >= 4:
        result["location"] = parts[3]
    if len(parts) >= 6:
        result["agent_engine_id"] = parts[5]
    return result


def _get_runner() -> Runner:
    """Get or create the ADK Runner for direct agent invocation.

    Uses VertexAiSessionService + VertexAiMemoryBankService when Agent Engine
    URIs are configured (production), or InMemory services for local dev.
    """
    global _runner
    if _runner is not None:
        return _runner

    from dev_signal_agent.agent import root_agent

    print(f"DEBUG _get_runner: _session_service_uri={_session_service_uri}")

    if _session_service_uri and _session_service_uri.startswith("agentengine://"):
        # Production: persistent sessions + memory via Agent Engine
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService
        from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService

        ae_kwargs = _parse_agent_engine_uri(_session_service_uri)
        logger.info("Telegram Runner using Agent Engine: %s", ae_kwargs)

        session_service = VertexAiSessionService(**ae_kwargs)
        memory_service = VertexAiMemoryBankService(**ae_kwargs)
    else:
        # Local dev fallback: in-memory (no persistence)
        from google.adk.sessions import InMemorySessionService
        from google.adk.memory import InMemoryMemoryService

        logger.warning("Telegram Runner using in-memory services (no persistence)")
        session_service = InMemorySessionService()
        memory_service = InMemoryMemoryService()

    _runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
        memory_service=memory_service,
    )
    return _runner


def _get_bot() -> Bot | None:
    """Get the Telegram Bot instance."""
    global _bot
    if _bot is None and TELEGRAM_BOT_TOKEN:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def _get_bot_app():
    """Get or create the bot application (singleton)."""
    global _bot_app
    if _bot_app is None:
        _bot_app = create_bot_application()
        if _bot_app:
            await _bot_app.initialize()
    return _bot_app


# Maps logical session names → Agent Engine numeric session IDs.
# VertexAiSessionService generates IDs automatically and does NOT accept custom IDs.
# We create sessions once per logical name and cache the returned numeric ID.
_session_id_map: dict[str, str] = {}

# Dedup: track recently processed update_ids to prevent double-processing
# when Telegram retries a webhook before we respond.
_processed_updates: set[int] = set()
_MAX_PROCESSED_UPDATES = 200


async def _get_session_id(runner: Runner, logical_name: str) -> str:
    """Get or create an Agent Engine session for the given logical name.

    VertexAiSessionService does NOT support user-provided session IDs.
    We create a session (no ID param) and cache the numeric ID returned.
    For InMemorySessionService (local dev), we use the logical name directly.
    """
    if logical_name in _session_id_map:
        return _session_id_map[logical_name]

    # For InMemorySessionService, we can use any string as session_id
    from google.adk.sessions import InMemorySessionService
    if isinstance(runner.session_service, InMemorySessionService):
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=logical_name,
        )
        _session_id_map[logical_name] = session.id
        return session.id

    # For VertexAiSessionService: always create a fresh session per container
    # lifetime.  Old sessions may have corrupted events.list state (400 errors)
    # from earlier failed attempts.  Memory Bank handles cross-session
    # persistence via load_memory/preload_memory tools, so we don't lose context.
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID,
    )
    _session_id_map[logical_name] = session.id
    logger.info("Created fresh Agent Engine session %s for '%s'", session.id, logical_name)
    return session.id


async def _run_agent_for_telegram(user_message: str, session_id: str = "telegram") -> str:
    """Run the dev-signal agent and return the text response.

    Uses direct ADK Runner invocation (no HTTP self-call).
    Sessions are auto-created in Agent Engine on first use per logical name.
    """
    try:
        runner = _get_runner()

        # Resolve logical name → numeric Agent Engine session ID
        real_session_id = await _get_session_id(runner, session_id)

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_message)],
        )

        response_text = ""
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=real_session_id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text

        return response_text.strip() or "No response from agent."
    except Exception as e:
        logger.error("Agent execution error: %s", e, exc_info=True)
        return f"Agent error: {type(e).__name__}: {str(e)[:200]}"


@router.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram webhook updates."""
    # Verify the secret token from Telegram
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        return Response(status_code=403, content="Forbidden")

    bot_app = await _get_bot_app()
    if not bot_app:
        return Response(status_code=503, content="Bot not configured")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)

    # Dedup: skip if we already processed this update (Telegram retry)
    update_id = data.get("update_id")
    if update_id and update_id in _processed_updates:
        logger.info("Skipping duplicate update_id=%s", update_id)
        return Response(status_code=200)
    if update_id:
        _processed_updates.add(update_id)
        # Keep the set bounded
        if len(_processed_updates) > _MAX_PROCESSED_UPDATES:
            _processed_updates.clear()

    # Process update through handlers (instant — just queues pending_action)
    await bot_app.process_update(update)

    # Check if a handler queued a pending action
    pending = bot_app.bot_data.pop("pending_action", None)
    if pending:
        # Process agent call in background so we return 200 immediately.
        # This prevents Telegram from retrying the webhook (60s timeout)
        # which was causing duplicate messages.
        asyncio.create_task(_process_pending_action(bot_app.bot, pending))

    return Response(status_code=200)


async def _process_pending_action(bot, pending: dict) -> None:
    """Process a pending agent action in background (after webhook returns 200)."""
    try:
        chat_id = pending["chat_id"]
        action = pending["action"]

        if action == "trends":
            query = pending.get("query", "")
            msg = f"what's trending{f' in {query}' if query else ''}?"
            response = await _run_agent_for_telegram(msg, session_id="telegram_trends")
            formatted = format_trends_message(response)
            num_trends = formatted.count("- **")
            keyboard = build_trends_keyboard(num_trends) if num_trends > 0 else None
            await _safe_send(
                bot, chat_id, formatted,
                reply_markup=keyboard, session_id="telegram_trends",
            )

        elif action == "promote":
            url = pending["url"]
            msg = f"create promotion drafts for this post: {url}"
            response = await _run_agent_for_telegram(msg, session_id="telegram_promote")
            await _safe_send(bot, chat_id, response, session_id="telegram_promote")

        elif action == "chat":
            text = pending["text"]
            response = await _run_agent_for_telegram(text, session_id="telegram_chat")
            await _safe_send(bot, chat_id, response, session_id="telegram_chat")

        elif action == "write_trend":
            idx = pending["trend_index"]
            msg = f"write a blog post about trend #{idx} from the latest trend scan"
            response = await _run_agent_for_telegram(msg, session_id="telegram_trends")
            await _safe_send(bot, chat_id, response, session_id="telegram_trends")

        elif action == "mix_trends":
            indices = pending["trend_indices"]
            msg = f"write a blog post mixing trends #{indices} from the latest trend scan"
            response = await _run_agent_for_telegram(msg, session_id="telegram_trends")
            await _safe_send(bot, chat_id, response, session_id="telegram_trends")

    except Exception as e:
        logger.error("Background action error: %s", e, exc_info=True)
        try:
            await bot.send_message(
                chat_id=pending["chat_id"],
                text=f"Error processing your request: {type(e).__name__}: {str(e)[:200]}",
            )
        except Exception:
            pass


@router.post("/cron/trends")
async def cron_daily_trends(request: Request) -> Response:
    """Triggered by Cloud Scheduler every morning.
    Runs trend_scanner and sends results to the owner via Telegram.

    Accepts optional JSON body:
      {"topic": "gcp"}  — filters trends by topic (e.g. gcp, ai, devops)
    """
    bot = _get_bot()
    if not bot or not OWNER_CHAT_ID:
        return Response(status_code=503, content="Bot or owner not configured")

    # Parse optional topic from request body
    topic = ""
    try:
        body = await request.json()
        topic = body.get("topic", "")    except Exception:
        pass  # Empty body or non-JSON is fine

    try:
        topic_clause = f" in {topic}" if topic else ""
        # Use a daily session ID so each day starts fresh (no stale context)
        daily_session = f"telegram_daily_trends_{date.today().isoformat()}"
        response = await _run_agent_for_telegram(
            f"what's trending{topic_clause} in the last 7 days? Show top 5 by engagement.",
            session_id=daily_session,
        )

        formatted = format_trends_message(response)
        num_trends = formatted.count("- **")
        keyboard = build_trends_keyboard(num_trends) if num_trends > 0 else None

        topic_label = f" in **{topic}**" if topic else ""
        header = f"Good morning! Here are today's top trends{topic_label}:\n\n"
        await _safe_send(
            bot, OWNER_CHAT_ID, header + formatted,
            reply_markup=keyboard, session_id=daily_session,
        )
        return Response(status_code=200, content="Trends sent")

    except Exception as e:
        logger.error(f"Cron trends error: {e}")
        return Response(status_code=500, content=str(e))


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into Telegram-safe chunks."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def _safe_send(
    bot, chat_id: int, text: str,
    reply_markup=None, session_id: str = "telegram",
):
    """Send a message with Markdown. If Telegram rejects it, ask the agent to fix.

    Rather than falling back to plain text (which hides formatting issues),
    we send the broken text back to the agent with instructions to fix the
    Markdown so the owner always sees properly formatted content.
    Max 2 retry attempts to avoid infinite loops.
    """
    from telegram.error import BadRequest

    MAX_FIX_ATTEMPTS = 2

    for chunk in _split_message(text):
        current_text = chunk

        for attempt in range(MAX_FIX_ATTEMPTS + 1):
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=current_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
                break  # Success
            except BadRequest as e:
                if attempt >= MAX_FIX_ATTEMPTS:
                    # Last resort: send without parse_mode but warn the owner
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"[Markdown fix failed after {MAX_FIX_ATTEMPTS} attempts]\n\n{current_text}",
                        reply_markup=reply_markup,
                    )
                    break

                # Ask the agent to fix the Markdown
                fix_prompt = (
                    f"The following text failed Telegram Markdown parsing with error: {e}\n\n"
                    f"Fix the Markdown so it's valid for Telegram (escape special chars like "
                    f"*, _, [, ] with backslash, close all bold/italic pairs). "
                    f"Return ONLY the fixed text, nothing else:\n\n{current_text}"
                )
                fixed = await _run_agent_for_telegram(fix_prompt, session_id=session_id)
                if fixed and not fixed.startswith("Agent error:"):
                    current_text = fixed
                else:
                    # Agent couldn't fix — send with warning
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"[Markdown invalid, agent couldn't fix]\n\n{current_text}",
                        reply_markup=reply_markup,
                    )
                    break

        # Only attach keyboard to first chunk
        reply_markup = None
