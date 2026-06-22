import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

from handlers.card import start_handler, help_handler, card_handler
from handlers.search import free_handler, find_handler
from handlers.admin import admin_list_handler

load_dotenv()

def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("card", card_handler))
    app.add_handler(CommandHandler("free", free_handler))
    app.add_handler(CommandHandler("find", find_handler))
    app.add_handler(CommandHandler("admin_list", admin_list_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
