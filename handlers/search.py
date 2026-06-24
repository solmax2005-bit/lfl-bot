import io
import json
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from database.db import init_db
from database.queries import (
    upsert_agent, get_agents_by_position, deactivate_agent,
    increment_views, add_favorite, remove_favorite, get_favorites,
    is_favorite, get_agent_by_tg_id,
)
from scraper.models import PlayerProfile
from card_generator.generator import draw_card

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
    return await free_handler(update, context, edit_mode=True)


async def no_url_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """'Нет ссылки' button — enter manual card creation."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Как тебя зовут?")
    return MC_NAME


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
    "🃏 Создать карточку", "🔍 Найти агентов",
    "🪪 Моя карточка", "⚽ Найти команду", "👥 Моя команда",
    "🏟 Зарегистрировать команду", "⭐ Избранное",
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
    elif text == "🃏 Создать карточку":
        from handlers.card import _NO_URL_KB
        await update.message.reply_text(
            "Пришли ссылку на свой профиль из поддерживаемых лиг:\n\n"
            "• *lfl.ru* — `https://lfl.ru/personNNNNN?player_id=NNNNN`\n"
            "• *afl.ru* — `https://afl.ru/players/имя-NNNNN`\n"
            "• *f-league.ru* — `https://f-league.ru/player/NNNNN`\n\n"
            "Или создай карточку вручную:",
            parse_mode="Markdown",
            reply_markup=_NO_URL_KB,
        )
    elif text == "⭐ Избранное":
        await favorites_handler(update, context)
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


def _agent_to_profile(agent: dict) -> PlayerProfile:
    pj = agent.get("profile_json") or ""
    if pj:
        try:
            d = json.loads(pj)
            return PlayerProfile(
                name=d.get("name", "—"),
                position=d.get("position", "—"),
                birthdate=d.get("birthdate", "—"),
                age=d.get("age", 0),
                current_club=d.get("current_club", "Свободный агент"),
                club_id=d.get("club_id", 0),
                career_clubs=d.get("career_clubs", []),
                goals=d.get("goals", 0),
                matches=d.get("matches", 0),
                assists=d.get("assists", 0),
                yellow_cards=d.get("yellow_cards", 0),
                red_cards=d.get("red_cards", 0),
                debut_year=d.get("debut_year", 0),
                lfl_url=d.get("lfl_url", ""),
                is_free_agent=d.get("is_free_agent", True),
                experience=d.get("experience", ""),
            )
        except Exception:
            pass
    exp = agent.get("experience") or ""
    career = [s.strip() for s in exp.split(",") if s.strip()]
    return PlayerProfile(
        name=agent.get("name", "—"),
        position=agent.get("position", "—"),
        birthdate="—",
        age=agent.get("age", 0),
        current_club=agent.get("current_team") or "Свободный агент",
        club_id=0,
        career_clubs=career,
        goals=0, matches=0, assists=0,
        yellow_cards=0, red_cards=0,
        debut_year=0,
        lfl_url="",
        is_free_agent=True,
        experience=exp,
    )


async def _send_agent_card(bot, chat_id: int, agents: list, idx: int, viewer_tg_id: int = 0) -> None:
    agent = agents[idx]
    total = len(agents)
    agent_tg_id = agent.get("tg_id", 0)

    # Increment view counter (don't count own card)
    if viewer_tg_id and viewer_tg_id != agent_tg_id:
        await increment_views(DB_PATH, agent_tg_id)

    png = draw_card(_agent_to_profile(agent))

    contact = agent.get("contact", "")
    contact_url = None
    if contact.startswith("@"):
        contact_url = f"https://t.me/{contact.lstrip('@')}"
    elif contact.startswith("http"):
        contact_url = contact

    comment = agent.get("comment", "")
    views = agent.get("views", 0) + (1 if viewer_tg_id and viewer_tg_id != agent_tg_id else 0)
    caption = f"*{agent['name']}* ({idx + 1}/{total})  👁 {views}"
    if comment:
        caption += f"\n_{comment}_"

    fav = await is_favorite(DB_PATH, viewer_tg_id, "agent", agent_tg_id) if viewer_tg_id else False

    btn_rows = []
    if contact_url:
        btn_rows.append([InlineKeyboardButton("💬 Написать", url=contact_url)])
    btn_rows.append([
        InlineKeyboardButton(
            "❤️ В избранном" if fav else "🤍 В избранное",
            callback_data=f"fav_agent:{'del' if fav else 'add'}:{agent_tg_id}:{idx}",
        )
    ])
    if idx < total - 1:
        btn_rows.append([InlineKeyboardButton(
            f"Следующий ➡️ ({idx + 2}/{total})", callback_data=f"fa_next:{idx + 1}"
        )])
    else:
        btn_rows.append([InlineKeyboardButton("✅ Завершить", callback_data="fa_done")])

    await bot.send_photo(
        chat_id=chat_id,
        photo=io.BytesIO(png),
        caption=caption,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(btn_rows),
    )


async def find_position_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, pos = query.data.split(":", 1)
    position = None if pos == "all" else pos
    agents = await get_agents_by_position(DB_PATH, position)
    if not agents:
        await query.edit_message_text("Свободных агентов не найдено.")
        return
    context.user_data["fa_agents"] = agents
    await query.edit_message_text(f"Найдено агентов: {len(agents)}")
    await _send_agent_card(context.bot, query.message.chat_id, agents, 0, viewer_tg_id=query.from_user.id)


async def agent_next_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":", 1)[1])
    agents = context.user_data.get("fa_agents", [])
    if not agents or idx >= len(agents):
        await query.edit_message_reply_markup(reply_markup=None)
        return
    await _send_agent_card(context.bot, query.message.chat_id, agents, idx, viewer_tg_id=query.from_user.id)


async def fav_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, agent_tg_id_str, idx_str = query.data.split(":")
    agent_tg_id = int(agent_tg_id_str)
    idx = int(idx_str)
    viewer = query.from_user.id

    if action == "add":
        await add_favorite(DB_PATH, viewer, "agent", agent_tg_id)
        await query.answer("❤️ Добавлено в избранное")
        new_action = "del"
        new_label = "❤️ В избранном"
    else:
        await remove_favorite(DB_PATH, viewer, "agent", agent_tg_id)
        await query.answer("Убрано из избранного")
        new_action = "add"
        new_label = "🤍 В избранное"

    # Update just the favorite button
    kb = query.message.reply_markup
    new_rows = []
    for row in kb.inline_keyboard:
        new_row = []
        for btn in row:
            if btn.callback_data and btn.callback_data.startswith("fav_agent:"):
                new_row.append(InlineKeyboardButton(
                    new_label,
                    callback_data=f"fav_agent:{new_action}:{agent_tg_id}:{idx}",
                ))
            else:
                new_row.append(btn)
        new_rows.append(new_row)
    await query.edit_message_reply_markup(InlineKeyboardMarkup(new_rows))


async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    favs = await get_favorites(DB_PATH, tg_id, "agent")
    if not favs:
        await update.message.reply_text("У тебя нет сохранённых агентов.\n\nНайди агентов через 🔍 Найти агентов и нажми 🤍 В избранное.")
        return
    agents = []
    for f in favs:
        agent = await get_agent_by_tg_id(DB_PATH, f["target_tg_id"])
        if agent:
            agents.append(agent)
    if not agents:
        await update.message.reply_text("Избранные агенты не найдены.")
        return
    context.user_data["fa_agents"] = agents
    await update.message.reply_text(f"⭐ Избранные агенты: {len(agents)}")
    await _send_agent_card(context.bot, update.effective_chat.id, agents, 0, viewer_tg_id=tg_id)


async def agent_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Поиск завершён")
    context.user_data.pop("fa_agents", None)
    await query.edit_message_reply_markup(reply_markup=None)


def build_free_conversation() -> ConversationHandler:
    # IMPORTANT: button text "✋ Стать агентом" must be an entry_point so PTB tracks
    # conversation state correctly. Calling free_handler from message_url_handler directly
    # does NOT register state in the ConversationHandler.
    return ConversationHandler(
        entry_points=[
            CommandHandler("free", free_handler),
            CallbackQueryHandler(edit_card_handler, pattern=r"^edit_card$"),
            CallbackQueryHandler(no_url_entry,       pattern=r"^no_url$"),
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
