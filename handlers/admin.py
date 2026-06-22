import os
from telegram import Update
from telegram.ext import ContextTypes
from database.db import init_db
from database.queries import get_agents_by_position, deactivate_agent

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "0"))


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_TG_ID


async def admin_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    await init_db(DB_PATH)
    agents = await get_agents_by_position(DB_PATH, None)
    if not agents:
        await update.message.reply_text("Список пуст.")
        return
    lines = [f"{a['name']} | {a['position']} | {a['contact']} | tg_id={a['tg_id']}" for a in agents]
    await update.message.reply_text("Свободные агенты:\n\n" + "\n".join(lines))


async def admin_deactivate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /admin_clear <tg_id>")
        return
    try:
        tg_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("tg_id должен быть числом.")
        return
    await init_db(DB_PATH)
    await deactivate_agent(DB_PATH, tg_id)
    await update.message.reply_text(f"Агент {tg_id} деактивирован.")
