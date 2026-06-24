from dotenv import load_dotenv
load_dotenv()

import os
import logging
import httpx

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

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)
from handlers.card import (
    start_handler, help_handler, mycard_handler,
    message_url_handler, delete_card_callback,
    build_multi_card_conversation, multi_done_callback, become_agent_callback,
    skip_exp_callback, skip_comment_callback, looking_callback,
    refresh_card_callback,
)
from handlers.search import (
    build_free_conversation, find_handler,
    find_position_callback, leave_handler,
    edit_card_handler, agent_next_callback, agent_done_callback,
    no_url_entry,
)
from handlers.teams import (
    build_team_conversation, my_team_handler,
    find_teams_handler, find_teams_callback,
    delete_team_callback,
)
from handlers.admin import admin_list_handler, admin_deactivate_handler
from database.db import init_db


async def post_init(app):
    db_path = os.getenv("DB_PATH", "lfl_bot.db")
    await init_db(db_path)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).post_init(post_init).build()

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

    # Admin
    app.add_handler(CommandHandler("admin_list",  admin_list_handler))
    app.add_handler(CommandHandler("admin_clear", admin_deactivate_handler))

    # Text / URL fallback (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_url_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
