import io
import os
import re
from telegram import Update
from telegram.ext import ContextTypes
from scraper.lfl_parser import parse_player
from card_generator.generator import draw_card
from database.db import init_db
from database.queries import get_agent_by_tg_id, link_profile

LFL_URL_RE = re.compile(r"https?://(?:ug\.)?lfl\.ru/player\d+", re.IGNORECASE)

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name
    text = (
        f"Привет, {name}!\n\n"
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
        "/mycard — своя карточка"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def _process_lfl_url(update: Update, url: str) -> None:
    await update.message.reply_text("Загружаю профиль...")
    try:
        profile = await parse_player(url)
    except ValueError as e:
        await update.message.reply_text(f"Не удалось загрузить профиль: {e}")
        return
    # Auto-link profile to the user's Telegram account
    tg_id = update.effective_user.id
    try:
        existing = await get_agent_by_tg_id(DB_PATH, tg_id)
        if existing:
            await link_profile(DB_PATH, tg_id, url)
    except Exception:
        pass  # non-critical
    png = draw_card(profile)
    caption = f"*{profile.name}* — {profile.position}\n{profile.current_club}"
    await update.message.reply_photo(photo=io.BytesIO(png), caption=caption, parse_mode="Markdown")


async def card_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Пришли ссылку на профиль: /card https://ug.lfl.ru/player12345"
        )
        return
    url = context.args[0]
    if not LFL_URL_RE.match(url):
        await update.message.reply_text(
            "Ссылка должна быть вида https://ug.lfl.ru/player12345"
        )
        return
    await _process_lfl_url(update, url)


async def message_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    m = LFL_URL_RE.search(text)
    if m:
        await _process_lfl_url(update, m.group(0))


async def mycard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    agent = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not agent or not agent.get("lfl_url"):
        await update.message.reply_text(
            "Профиль не привязан. Используй /card [ссылка] чтобы создать карточку — "
            "после этого она сохранится как твоя."
        )
        return
    await _process_lfl_url(update, agent["lfl_url"])
