from telegram import Update
from telegram.ext import ContextTypes

async def admin_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Функция в разработке.")
