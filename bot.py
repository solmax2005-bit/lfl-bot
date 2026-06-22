import os
from dotenv import load_dotenv
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)
from handlers.card import start_handler, help_handler, card_handler, message_url_handler, mycard_handler
from handlers.search import (
    build_free_conversation, find_handler,
    find_position_callback, leave_handler,
)
from handlers.admin import admin_list_handler
from database.db import init_db

load_dotenv()


async def post_init(app):
    db_path = os.getenv("DB_PATH", "lfl_bot.db")
    await init_db(db_path)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("card", card_handler))
    app.add_handler(CommandHandler("mycard", mycard_handler))
    app.add_handler(CommandHandler("find", find_handler))
    app.add_handler(CommandHandler("leave", leave_handler))
    app.add_handler(CommandHandler("admin_list", admin_list_handler))
    app.add_handler(build_free_conversation())
    app.add_handler(CallbackQueryHandler(find_position_callback, pattern=r"^find:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_url_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
