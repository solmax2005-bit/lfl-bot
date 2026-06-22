import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from database.db import init_db
from database.queries import upsert_agent, get_agents_by_position, deactivate_agent

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

ASK_NAME, ASK_POSITION, ASK_DIVISION, ASK_CONTACT, ASK_COMMENT = range(5)

POSITIONS = ["Нападающий", "Полузащитник", "Защитник", "Вратарь"]
DIVISIONS = ["Премьер", "1-я лига", "2-я лига", "Любой"]


async def free_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await init_db(DB_PATH)
    await update.message.reply_text(
        "Заполним анкету. Как тебя зовут? (или пришли ссылку на профиль ug.lfl.ru)"
    )
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.startswith("http"):
        context.user_data["lfl_url"] = text
        context.user_data["name"] = text  # will overwrite from profile if needed
    else:
        context.user_data["name"] = text
        context.user_data["lfl_url"] = ""
    keyboard = [[InlineKeyboardButton(p, callback_data=p)] for p in POSITIONS]
    await update.message.reply_text("Выбери позицию:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_POSITION


async def ask_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["position"] = query.data
    keyboard = [[InlineKeyboardButton(d, callback_data=d)] for d in DIVISIONS]
    await query.edit_message_text("Предпочтительный дивизион:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_DIVISION


async def ask_division(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["division"] = query.data
    await query.edit_message_text("Контакт для связи (@username или телефон):")
    return ASK_CONTACT


async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["contact"] = update.message.text.strip()
    await update.message.reply_text("Комментарий (или /skip чтобы пропустить):")
    return ASK_COMMENT


async def ask_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["comment"] = update.message.text.strip()
    return await _save_agent(update, context)


async def skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["comment"] = ""
    return await _save_agent(update, context)


async def _save_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    tg_id = update.effective_user.id
    await upsert_agent(
        DB_PATH, tg_id, d["name"], d["position"],
        d["division"], d["contact"], d.get("comment", ""), d.get("lfl_url", ""),
    )
    await update.message.reply_text(
        f"✅ Анкета сохранена!\n\n"
        f"👤 {d['name']}\n"
        f"⚽ {d['position']} | 🏆 {d['division']}\n"
        f"📞 {d['contact']}\n\n"
        "Тебя увидят при поиске /find. Чтобы убрать анкету — /leave"
    )
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def leave_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    await deactivate_agent(DB_PATH, update.effective_user.id)
    await update.message.reply_text("Анкета удалена. Ты больше не в списке свободных агентов.")


async def find_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    keyboard = [
        [InlineKeyboardButton(p, callback_data=f"find:{p}") for p in POSITIONS[:2]],
        [InlineKeyboardButton(p, callback_data=f"find:{p}") for p in POSITIONS[2:]],
        [InlineKeyboardButton("Все позиции", callback_data="find:all")],
    ]
    await update.message.reply_text("Выбери позицию для поиска:", reply_markup=InlineKeyboardMarkup(keyboard))


async def find_position_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, pos = query.data.split(":", 1)
    position = None if pos == "all" else pos
    agents = await get_agents_by_position(DB_PATH, position)
    if not agents:
        await query.edit_message_text("Свободных агентов не найдено.")
        return
    await query.edit_message_text(f"Найдено: {len(agents)}")
    for agent in agents:
        contact = agent["contact"]
        text = (
            f"👤 *{agent['name']}*\n"
            f"⚽ {agent['position']} | 🏆 {agent['division']}\n"
            f"💬 {agent.get('comment') or '—'}"
        )
        if contact.startswith("@"):
            contact_url = f"https://t.me/{contact.lstrip('@')}"
        else:
            contact_url = f"tel:{contact}"
        keyboard = [[InlineKeyboardButton("Написать", url=contact_url)]]
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            pass


def build_free_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("free", free_handler)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_POSITION: [CallbackQueryHandler(ask_position, pattern="^(Нападающий|Полузащитник|Защитник|Вратарь)$")],
            ASK_DIVISION: [CallbackQueryHandler(ask_division, pattern="^(Премьер|1-я лига|2-я лига|Любой)$")],
            ASK_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_contact)],
            ASK_COMMENT: [
                CommandHandler("skip", skip_comment),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_comment),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
    )
