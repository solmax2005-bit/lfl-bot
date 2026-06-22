from telegram import Update
from telegram.ext import ContextTypes

async def free_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Функция в разработке.")

async def find_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Функция в разработке.")
