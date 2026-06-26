from dotenv import load_dotenv
load_dotenv()

import os
import time
import logging
import httpx
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Bypass SOCKS4 system proxy (Windows VPN software sets ALL_PROXY)
_orig_httpx_init = httpx.AsyncClient.__init__
def _httpx_no_proxy_init(self, *args, **kwargs):
    kwargs["trust_env"] = False
    _orig_httpx_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _httpx_no_proxy_init

import asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ApplicationHandlerStop,
)
from telegram.request import HTTPXRequest

# Outbound calls to api.telegram.org from the RU server intermittently fail to
# establish a connection (DPI throttling of new TLS handshakes). getUpdates
# survives because the Updater retries it; send_message/answer_callback_query
# have no retry, so a single ConnectTimeout makes buttons look "dead".
# Retry ONLY connection-establishment errors (request never reached Telegram),
# so we never risk sending a message twice.
_RETRYABLE_CAUSES = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.WriteTimeout,
    httpx.WriteError,
)


class RetryRequest(HTTPXRequest):
    async def do_request(self, *args, **kwargs):
        last_exc = None
        for attempt in range(5):
            try:
                return await super().do_request(*args, **kwargs)
            except Exception as exc:
                if not isinstance(exc.__cause__, _RETRYABLE_CAUSES):
                    raise
                last_exc = exc
                logging.warning(
                    "Telegram connect failed (attempt %d/5): %s — retrying",
                    attempt + 1, exc.__cause__.__class__.__name__,
                )
                await asyncio.sleep(min(0.5 * 2 ** attempt, 4.0))
        raise last_exc
from handlers.card import (
    start_handler, help_handler, help_button_handler, help_contact_callback,
    mycard_handler,
    message_url_handler, delete_card_callback,
    build_multi_card_conversation, multi_done_callback, become_agent_callback,
    skip_exp_callback, skip_comment_callback, looking_callback,
    refresh_card_callback, upload_photo_callback, photo_message_handler,
)
from handlers.search import (
    build_free_conversation, find_handler,
    find_position_callback, leave_handler,
    edit_card_handler, agent_next_callback, agent_done_callback,
    no_url_entry, fav_agent_callback, favorites_handler,
)
from handlers.teams import (
    build_team_conversation, my_team_handler,
    find_teams_handler, find_teams_callback,
    delete_team_callback, apply_team_callback,
)
from handlers.notifications import notif_show_agent_callback, notif_show_team_callback
from handlers.admin import (
    admin_list_handler, admin_deactivate_handler,
    broadcast_handler, broadcast_delete_handler,
    admin_panel_handler, admin_broadcasts_callback, admin_del_broadcast_callback,
    admin_broadcast_start_callback, handle_broadcast_input,
    admin_panel_back_callback, admin_stats_callback,
    admin_agents_callback, admin_toggle_agent_callback, admin_del_agent_callback,
    admin_teams_callback, admin_toggle_team_callback, admin_del_team_callback,
)
from database.db import init_db
from database.queries import log_message

_spam: dict[int, list[float]] = defaultdict(list)
_RATE_LIMIT = 10   # max messages per window
_RATE_WINDOW = 10  # seconds


async def _rate_limit(update, context):
    if not update.message or not update.effective_user:
        return
    admin_id = os.getenv("ADMIN_TG_ID", "")
    uid = update.effective_user.id
    if admin_id and str(uid) == admin_id:
        return  # never rate-limit admin
    now = time.time()
    _spam[uid] = [t for t in _spam[uid] if now - t < _RATE_WINDOW]
    if len(_spam[uid]) >= _RATE_LIMIT:
        try:
            await update.message.reply_text("⏳ Слишком много сообщений. Подожди немного.")
        except Exception:
            pass
        raise ApplicationHandlerStop()
    _spam[uid].append(now)


async def _log_all_messages(update, context):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    if not user:
        return
    db_path = os.getenv("DB_PATH", "lfl_bot.db")
    try:
        await log_message(
            db_path,
            tg_id=user.id,
            username=user.username or "",
            full_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
            text=update.message.text,
        )
    except Exception:
        pass


async def post_init(app):
    db_path = os.getenv("DB_PATH", "lfl_bot.db")
    await init_db(db_path)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    # Lower connect_timeout so a stalled handshake fails fast and RetryRequest
    # can retry, instead of blocking the whole 30s on one dead connection.
    request = RetryRequest(connect_timeout=15.0, read_timeout=35.0, write_timeout=20.0, pool_timeout=5.0)
    # concurrent_updates: process different users' updates in parallel (so a long
    # broadcast doesn't block replies to everyone else).
    app = (
        Application.builder()
        .token(token)
        .request(request)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # Rate limit (group=-2 stops all further processing if triggered)
    app.add_handler(MessageHandler(filters.ALL, _rate_limit), group=-2)

    # Log all messages (runs silently before all other handlers)
    app.add_handler(MessageHandler(filters.TEXT, _log_all_messages), group=-1)

    # Core
    app.add_handler(CommandHandler("start",  start_handler))
    app.add_handler(CommandHandler("help",   help_handler))
    app.add_handler(CommandHandler("mycard", mycard_handler))
    app.add_handler(CommandHandler("find",   find_handler))
    app.add_handler(CommandHandler("leave",  leave_handler))
    app.add_handler(CommandHandler("my_team", my_team_handler))
    app.add_handler(CommandHandler("find_teams", find_teams_handler))

    # Conversations
    app.add_handler(build_free_conversation())
    app.add_handler(build_team_conversation())
    app.add_handler(build_multi_card_conversation())

    # Callback queries
    app.add_handler(CallbackQueryHandler(find_position_callback, pattern=r"^find:"))
    app.add_handler(CallbackQueryHandler(agent_next_callback,    pattern=r"^fa_next:"))
    app.add_handler(CallbackQueryHandler(agent_done_callback,    pattern=r"^fa_done$"))
    app.add_handler(CallbackQueryHandler(find_teams_callback,    pattern=r"^ft_"))
    # edit_card is handled inside build_free_conversation() entry_points (see search.py)
    app.add_handler(CallbackQueryHandler(delete_card_callback,   pattern=r"^delete_card$"))
    # edit_team is handled inside build_team_conversation() entry_points (see teams.py)
    app.add_handler(CallbackQueryHandler(delete_team_callback,   pattern=r"^delete_team$"))
    app.add_handler(CallbackQueryHandler(multi_done_callback,    pattern=r"^multi_done$"))
    app.add_handler(CallbackQueryHandler(become_agent_callback,  pattern=r"^become_agent$"))
    app.add_handler(CallbackQueryHandler(skip_exp_callback,      pattern=r"^skip_exp$"))
    app.add_handler(CallbackQueryHandler(skip_comment_callback,  pattern=r"^skip_comment$"))
    app.add_handler(CallbackQueryHandler(looking_callback,       pattern=r"^looking:"))
    app.add_handler(CallbackQueryHandler(refresh_card_callback,  pattern=r"^refresh_card$"))
    app.add_handler(CallbackQueryHandler(upload_photo_callback,       pattern=r"^upload_photo$"))
    app.add_handler(CallbackQueryHandler(help_contact_callback,        pattern=r"^help_contact$"))
    app.add_handler(CallbackQueryHandler(notif_show_agent_callback,   pattern=r"^notif_agent:"))
    app.add_handler(CallbackQueryHandler(notif_show_team_callback,    pattern=r"^notif_team:"))
    app.add_handler(CallbackQueryHandler(fav_agent_callback,     pattern=r"^fav_agent:"))
    app.add_handler(CallbackQueryHandler(apply_team_callback,    pattern=r"^apply_team:"))

    # Admin
    app.add_handler(CommandHandler("admin_list",       admin_list_handler))
    app.add_handler(CommandHandler("admin_clear",      admin_deactivate_handler))
    app.add_handler(CommandHandler("admin",            admin_panel_handler))
    app.add_handler(CommandHandler("broadcast",        broadcast_handler))
    app.add_handler(CommandHandler("broadcast_delete", broadcast_delete_handler))
    app.add_handler(CallbackQueryHandler(admin_broadcast_start_callback, pattern=r"^admin_broadcast_start$"))
    app.add_handler(CallbackQueryHandler(admin_broadcasts_callback,     pattern=r"^admin_broadcasts$"))
    app.add_handler(CallbackQueryHandler(admin_del_broadcast_callback,  pattern=r"^admin_del_broadcast:"))
    app.add_handler(CallbackQueryHandler(admin_panel_back_callback,     pattern=r"^admin_panel_back$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback,          pattern=r"^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_agents_callback,         pattern=r"^admin_agents:"))
    app.add_handler(CallbackQueryHandler(admin_toggle_agent_callback,   pattern=r"^admin_toggle_agent:"))
    app.add_handler(CallbackQueryHandler(admin_del_agent_callback,      pattern=r"^admin_del_agent:"))
    app.add_handler(CallbackQueryHandler(admin_teams_callback,          pattern=r"^admin_teams:"))
    app.add_handler(CallbackQueryHandler(admin_toggle_team_callback,    pattern=r"^admin_toggle_team:"))
    app.add_handler(CallbackQueryHandler(admin_del_team_callback,       pattern=r"^admin_del_team:"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern=r"^noop$"))

    # Photo upload
    app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))

    # Favorites command
    app.add_handler(CommandHandler("favorites", favorites_handler))

    # Text / URL fallback (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_url_handler))

    app.run_polling(timeout=20, bootstrap_retries=5, drop_pending_updates=False)


if __name__ == "__main__":
    main()
