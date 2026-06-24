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


def _keep_btn(field: str, value) -> list | None:
    """Return a [keep button] row if value is non-empty, else None."""
    if not value and value != 0:
        return None
    display = str(value)
    if len(display) > 28:
        display = display[:28] + "…"
    return [InlineKeyboardButton(f"⬅️ Оставить: {display}", callback_data=f"mc_keep:{field}")]


def _pos_kb(keep_pos: str = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(p, callback_data=f"mc_pos:{p}") for p in POSITIONS[:2]],
        [InlineKeyboardButton(p, callback_data=f"mc_pos:{p}") for p in POSITIONS[2:]],
    ]
    if keep_pos:
        rows.append([InlineKeyboardButton(f"⬅️ Оставить: {keep_pos}", callback_data="mc_keep:pos")])
    return InlineKeyboardMarkup(rows)


def _league_kb(keep_league: str = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(l, callback_data=f"mc_league:{l}") for l in LEAGUES[:2]],
        [InlineKeyboardButton(l, callback_data=f"mc_league:{l}") for l in LEAGUES[2:]],
    ]
    if keep_league:
        rows.append([InlineKeyboardButton(f"⬅️ Оставить: {keep_league}", callback_data="mc_keep:league")])
    return InlineKeyboardMarkup(rows)


def _old(context) -> dict:
    return context.user_data.get("old_mc", {})


def _edit(context) -> bool:
    return context.user_data.get("edit_mode", False)


# ── prompt helpers ──────────────────────────────────────────────────────────

async def _prompt_name(msg, context):
    old = _old(context)
    rows = []
    kb_row = _keep_btn("name", old.get("name", "")) if _edit(context) else None
    kb = InlineKeyboardMarkup([kb_row]) if kb_row else None
    await msg.reply_text("Как тебя зовут?", reply_markup=kb)
    return MC_NAME


async def _prompt_pos(msg, context):
    old = _old(context)
    keep = old.get("position", "") if _edit(context) else None
    await msg.reply_text("Позиция:", reply_markup=_pos_kb(keep))
    return MC_POS


async def _prompt_age(msg, context):
    old = _old(context)
    rows = [[InlineKeyboardButton("Нет команды", callback_data="mc_team:none")]]
    kb_row = _keep_btn("age", old.get("age", 0)) if _edit(context) else None
    kb = InlineKeyboardMarkup([kb_row]) if kb_row else None
    await msg.reply_text("Возраст (полных лет):", reply_markup=kb)
    return MC_AGE


async def _prompt_team(msg, context):
    old = _old(context)
    rows = [[InlineKeyboardButton("Нет команды", callback_data="mc_team:none")]]
    kb_row = _keep_btn("team", old.get("current_team", "")) if _edit(context) else None
    if kb_row:
        rows.append(kb_row)
    kb = InlineKeyboardMarkup(rows)
    await msg.reply_text("Текущая команда (или нажми кнопку):", reply_markup=kb)
    return MC_TEAM


async def _prompt_league(msg, context):
    old = _old(context)
    keep = old.get("division", "") if _edit(context) else None
    await msg.reply_text("Лига:", reply_markup=_league_kb(keep))
    return MC_LEAGUE


async def _prompt_exp(msg, context):
    old = _old(context)
    rows = [[InlineKeyboardButton("Нет опыта", callback_data="mc_exp:none")]]
    kb_row = _keep_btn("exp", old.get("experience", "")) if _edit(context) else None
    if kb_row:
        rows.append(kb_row)
    await msg.reply_text(
        "Прошлый опыт — перечисли команды через запятую\n(или нажми «Нет опыта»):",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return MC_EXP


async def _prompt_comment(msg, context):
    old = _old(context)
    rows = [[InlineKeyboardButton("Пропустить", callback_data="mc_comment:skip")]]
    kb_row = _keep_btn("comment", old.get("comment", "")) if _edit(context) else None
    if kb_row:
        rows.append(kb_row)
    await msg.reply_text("Комментарий (о себе, пожеланиях и т.д.):", reply_markup=InlineKeyboardMarkup(rows))
    return MC_COMMENT


# ── entry points ────────────────────────────────────────────────────────────

async def free_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, edit_mode: bool = False
) -> int:
    await init_db(DB_PATH)
    context.user_data["edit_mode"] = edit_mode
    if edit_mode:
        tg_id = update.effective_user.id
        agent = await get_agent_by_tg_id(DB_PATH, tg_id)
        context.user_data["old_mc"] = agent or {}
    else:
        context.user_data["old_mc"] = {}

    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    prefix = "Редактируем карточку. " if edit_mode else ""
    await msg.reply_text(f"{prefix}Шаг 1/7")
    return await _prompt_name(msg, context)


async def edit_card_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await free_handler(update, context, edit_mode=True)


async def no_url_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["edit_mode"] = False
    context.user_data["old_mc"] = {}
    return await _prompt_name(query.message, context)


# ── step handlers ───────────────────────────────────────────────────────────

async def mc_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_name"] = update.message.text.strip()
    return await _prompt_pos(update.message, context)


async def mc_pos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_pos"] = query.data.split(":", 1)[1]
    return await _prompt_age(query.message, context)


async def mc_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (10 <= int(text) <= 60):
        await update.message.reply_text("Введи число от 10 до 60:")
        return MC_AGE
    context.user_data["mc_age"] = int(text)
    return await _prompt_team(update.message, context)


async def mc_team_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_team"] = update.message.text.strip()
    return await _prompt_league(update.message, context)


async def mc_team_none(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_team"] = ""
    return await _prompt_league(query.message, context)


async def mc_league(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_league"] = query.data.split(":", 1)[1]
    return await _prompt_exp(query.message, context)


async def mc_exp_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_exp"] = update.message.text.strip()
    return await _prompt_comment(update.message, context)


async def mc_exp_none(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_exp"] = ""
    return await _prompt_comment(query.message, context)


async def mc_comment_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["mc_comment"] = update.message.text.strip()
    return await _save_manual(update, context)


async def mc_comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["mc_comment"] = ""
    return await _save_manual(update, context, via_query=query)


# ── keep handler (single handler for all fields) ────────────────────────────

async def mc_keep_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User pressed 'Оставить' — keep old value and move to next step."""
    query = update.callback_query
    await query.answer("Оставлено без изменений")
    field = query.data.split(":", 1)[1]
    old = _old(context)

    if field == "name":
        context.user_data["mc_name"] = old.get("name", "")
        return await _prompt_pos(query.message, context)
    elif field == "pos":
        context.user_data["mc_pos"] = old.get("position", "")
        return await _prompt_age(query.message, context)
    elif field == "age":
        context.user_data["mc_age"] = old.get("age", 0)
        return await _prompt_team(query.message, context)
    elif field == "team":
        context.user_data["mc_team"] = old.get("current_team", "")
        return await _prompt_league(query.message, context)
    elif field == "league":
        context.user_data["mc_league"] = old.get("division", "")
        return await _prompt_exp(query.message, context)
    elif field == "exp":
        context.user_data["mc_exp"] = old.get("experience", "")
        return await _prompt_comment(query.message, context)
    elif field == "comment":
        context.user_data["mc_comment"] = old.get("comment", "")
        return await _save_manual(update, context, via_query=query)
    return MC_COMMENT


# ── save ─────────────────────────────────────────────────────────────────────

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

    # Notify matching teams in background
    from handlers.notifications import notify_teams_new_player
    import asyncio
    asyncio.ensure_future(notify_teams_new_player(
        context.bot, tg_id,
        agent_name=d["mc_name"],
        position=d["mc_pos"],
        league=d["mc_league"],
    ))

    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


_MENU_TEXTS = [
    "🃏 Создать карточку", "🔍 Найти агентов",
    "🪪 Моя карточка", "⚽ Найти команду", "👥 Моя команда",
    "🏟 Зарегистрировать команду", "⭐ Избранное", "🆘 Помощь",
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
    elif text == "🆘 Помощь":
        from handlers.card import help_button_handler
        await help_button_handler(update, context)
    else:
        from handlers.card import MAIN_KEYBOARD
        await update.message.reply_text(
            "Что-то пошло не так. Нажми /start чтобы вернуться в главное меню.",
            reply_markup=MAIN_KEYBOARD,
        )
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

    if viewer_tg_id and viewer_tg_id != agent_tg_id:
        await increment_views(DB_PATH, agent_tg_id)

    from handlers.card import _download_avatar
    avatar = await _download_avatar(bot, agent["photo_file_id"]) if agent.get("photo_file_id") else None
    png = draw_card(_agent_to_profile(agent), avatar_bytes=avatar)

    contact = agent.get("contact", "")
    contact_url = None
    if contact.startswith("@"):
        contact_url = f"https://t.me/{contact.lstrip('@')}"
    elif contact.startswith("http"):
        contact_url = contact

    comment = agent.get("comment", "")
    caption = f"*{agent['name']}* ({idx + 1}/{total})"
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
    _keep = CallbackQueryHandler(mc_keep_cb, pattern=r"^mc_keep:")
    return ConversationHandler(
        entry_points=[
            CommandHandler("free", free_handler),
            CallbackQueryHandler(edit_card_handler, pattern=r"^edit_card$"),
            CallbackQueryHandler(no_url_entry,       pattern=r"^no_url$"),
        ],
        states={
            MC_NAME: [_keep, MessageHandler(filters.TEXT & ~filters.COMMAND, mc_name)],
            MC_POS:  [_keep, CallbackQueryHandler(mc_pos, pattern=r"^mc_pos:")],
            MC_AGE:  [_keep, MessageHandler(filters.TEXT & ~filters.COMMAND, mc_age)],
            MC_TEAM: [
                _keep,
                CallbackQueryHandler(mc_team_none, pattern=r"^mc_team:none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mc_team_text),
            ],
            MC_LEAGUE: [_keep, CallbackQueryHandler(mc_league, pattern=r"^mc_league:")],
            MC_EXP: [
                _keep,
                CallbackQueryHandler(mc_exp_none, pattern=r"^mc_exp:none$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mc_exp_text),
            ],
            MC_COMMENT: [
                _keep,
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
