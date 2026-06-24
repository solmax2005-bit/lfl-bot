import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from database.db import init_db
from database.queries import upsert_agent, get_agents_by_position, deactivate_agent

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

MC_NAME, MC_POS, MC_AGE, MC_TEAM, MC_LEAGUE, MC_EXP, MC_COMMENT = range(7)

POSITIONS = ["Нападающий", "Полузащитник", "Защитник", "Вратарь"]
LEAGUES = ["ЛФЛ", "AFL", "Pari Amateur", "F-лига"]

_CANCEL_KB = ReplyKeyboardMarkup([[KeyboardButton("/cancel")]], resize_keyboard=True, one_time_keyboard=True)


def _pos_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(p, callback_data=f"mc_pos:{p}") for p in POSITIONS[:2]],
        [InlineKeyboardButton(p, callback_data=f"mc_pos:{p}") for p in POSITIONS[2:]],
    ])


def _league_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"mc_league:{l}") for l in LEAGUES[:2]],
        [InlineKeyboardButton(l, callback_data=f"mc_league:{l}") for l in LEAGUES[2:]],
    ])


async def free_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, edit_mode: bool = False
) -> int:
    await init_db(DB_PATH)
    context.user_data["edit_mode"] = edit_mode
    prompt = "Редактируем карточку. " if edit_mode else ""
    # Called from message button OR callback query (edit_card inline button)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(f"{prompt}Как тебя зовут?")
    else:
        await update.message.reply_text(f"{prompt}Как тебя зовут?")
    return MC_NAME


async def edit_card_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for edit_card callback — starts the manual card ConversationHandler in edit mode."""
    return await free_handler(update, context, edit_mode=True)


async def mc_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_name"] = update.message.text.strip()
    await update.message.reply_text("Позиция:", reply_markup=_pos_kb())
    return MC_POS


async def mc_pos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_pos"] = query.data.split(":", 1)[1]
    await query.edit_message_text("Возраст (полных лет):")
    return MC_AGE


async def mc_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (10 <= int(text) <= 60):
        await update.message.reply_text("Введи число от 10 до 60:")
        return MC_AGE
    context.user_data["mc_age"] = int(text)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Нет команды", callback_data="mc_team:none")]])
    await update.message.reply_text("Текущая команда (или нажми кнопку):", reply_markup=kb)
    return MC_TEAM


async def mc_team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_team"] = update.message.text.strip()
    await update.message.reply_text("Лига:", reply_markup=_league_kb())
    return MC_LEAGUE


async def mc_team_none(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_team"] = ""
    await query.edit_message_text("Лига:")
    await query.message.reply_text("Выбери лигу:", reply_markup=_league_kb())
    return MC_LEAGUE


async def mc_league(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_league"] = query.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Нет опыта", callback_data="mc_exp:none")]])
    await query.edit_message_text(
        "Прошлый опыт — перечисли команды через запятую\n(или нажми «Нет опыта»):",
        reply_markup=kb,
    )
    return MC_EXP


async def mc_exp_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_exp"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить", callback_data="mc_comment:skip")]])
    await update.message.reply_text("Комментарий (о себе, пожеланиях и т.д.):", reply_markup=kb)
    return MC_COMMENT


async def mc_exp_none(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_exp"] = ""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить", callback_data="mc_comment:skip")]])
    await query.edit_message_text("Комментарий:", reply_markup=kb)
    return MC_COMMENT


async def mc_comment_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_comment"] = update.message.text.strip()
    return await _save_manual(update, context)


async def mc_comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_comment"] = ""
    return await _save_manual(update, context, via_query=query)


async def _save_manual(
    update: Update, context: ContextTypes.DEFAULT_TYPE, via_query=None
) -> int:
    d = context.user_data
    tg_id = update.effective_user.id
    contact_str = f"@{update.effective_user.username}" if update.effective_user.username else str(tg_id)
    await upsert_agent(
        DB_PATH, tg_id,
        name=d["mc_name"],
        position=d["mc_pos"],
        division=d["mc_league"],
        contact=contact_str,
        comment=d.get("mc_comment", ""),
        lfl_url="",
        experience=d.get("mc_exp", ""),
        current_team=d.get("mc_team", ""),
        age=d.get("mc_age", 0),
    )
    text = (
        f"✅ Карточка сохранена!\n\n"
        f"👤 {d['mc_name']}  |  ⚽ {d['mc_pos']}\n"
        f"🏆 {d['mc_league']}  |  🎂 {d['mc_age']} лет\n"
        f"🏟 {d['mc_team'] or '—'}\n"
        f"📋 {d.get('mc_exp') or 'Без опыта'}\n\n"
        "Тебя увидят при поиске /find. Убрать — /leave"
    )
    if via_query:
        await via_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


_MENU_TEXTS = [
    "📇 Карточка игрока", "🔍 Найти агентов",
    "🪪 Моя карточка", "⚽ Найти команду", "👥 Моя команда",
    "🏟 Зарегистрировать команду",
]


async def _menu_escape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("mc", None)
    text = update.message.text
    if text == "⚽ Найти команду":
        from handlers.teams import find_teams_handler
        await find_teams_handler(update, context)
    elif text == "👥 Моя команда":
        from handlers.teams import my_team_handler
        await my_team_handler(update, context)
    elif text == "🪪 Моя карточка":
        from handlers.card import mycard_handler
        await mycard_handler(update, context)
    elif text == "🔍 Найти агентов":
        await find_handler(update, context)
    elif text == "🏟 Зарегистрировать команду":
        from handlers.card import MAIN_KEYBOARD
        await update.message.reply_text("Нажми ещё раз.", reply_markup=MAIN_KEYBOARD)
    else:
        from handlers.card import MAIN_KEYBOARD
        await update.message.reply_text("Нажми ещё раз.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def leave_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    await deactivate_agent(DB_PATH, update.effective_user.id)
    await update.message.reply_text("Анкета удалена.")


async def find_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(p, callback_data=f"find:{p}") for p in POSITIONS[:2]],
        [InlineKeyboardButton(p, callback_data=f"find:{p}") for p in POSITIONS[2:]],
        [InlineKeyboardButton("Все позиции", callback_data="find:all")],
    ])
    await update.message.reply_text("Выбери позицию для поиска:", reply_markup=keyboard)


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
        exp = agent.get("experience", "")
        exp_line = f"📋 {exp}" if exp else ""
        team_line = f"🏟 {agent['current_team']}" if agent.get("current_team") else ""
        text = (
            f"👤 *{agent['name']}*\n"
            f"⚽ {agent['position']}  |  🏆 {agent.get('division', '—')}\n"
            + (f"🎂 {agent['age']} лет\n" if agent.get("age") else "")
            + (f"{team_line}\n" if team_line else "")
            + (f"{exp_line}\n" if exp_line else "")
            + f"💬 {agent.get('comment') or '—'}"
        )
        contact_url = (
            f"https://t.me/{contact.lstrip('@')}" if contact.startswith("@")
            else f"tel:{contact}"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Написать", url=contact_url)]])
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text, parse_mode="Markdown", reply_markup=kb,
            )
        except Exception as exc:
            logger.warning("Failed to send agent card: %s", exc)


def build_free_conversation() -> ConversationHandler:
    # IMPORTANT: button text "✋ Стать агентом" must be an entry_point so PTB tracks
    # conversation state correctly. Calling free_handler from message_url_handler directly
    # does NOT register state in the ConversationHandler.
    return ConversationHandler(
        entry_points=[
            CommandHandler("free", free_handler),
            MessageHandler(filters.Text(["✋ Стать агентом"]), free_handler),
            CallbackQueryHandler(edit_card_handler, pattern=r"^edit_card$"),
        ],
        states={
            MC_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_name)],
            MC_POS:  [CallbackQueryHandler(mc_pos, pattern=r"^mc_pos:")],
            MC_AGE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_age)],
            MC_TEAM: [
                CallbackQueryHandler(mc_team_none, pattern=r"^mc_team:none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mc_team_text),
            ],
            MC_LEAGUE: [CallbackQueryHandler(mc_league, pattern=r"^mc_league:")],
            MC_EXP: [
                CallbackQueryHandler(mc_exp_none, pattern=r"^mc_exp:none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mc_exp_text),
            ],
            MC_COMMENT: [
                CallbackQueryHandler(mc_comment_skip, pattern=r"^mc_comment:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mc_comment_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler),
            MessageHandler(filters.Text(_MENU_TEXTS), _menu_escape),
        ],
        allow_reentry=True,
    )
