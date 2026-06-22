from telegram import Update
from telegram.ext import ContextTypes

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name
    text = (
        f"Привет, {name}! 👋\n\n"
        "Я бот *ЛФЛ Южная*. Вот что я умею:\n\n"
        "📇 /card [ссылка] — карточка игрока по ссылке ug.lfl.ru\n"
        "🔍 /find — найти свободных агентов\n"
        "✋ /free — заявить себя как свободного агента\n"
        "🪪 /mycard — моя карточка\n"
        "❓ /help — справка"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Команды бота:*\n\n"
        "/card https://ug.lfl.ru/player12345 — карточка игрока\n"
        "/free — стать свободным агентом\n"
        "/find — список свободных агентов\n"
        "/mycard — своя карточка (нужно привязать профиль через /card)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def card_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Функция в разработке.")
