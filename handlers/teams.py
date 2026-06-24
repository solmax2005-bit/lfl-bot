import io
import os
import logging
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from database.db import init_db
from database.queries import upsert_team, get_teams, get_team_by_tg_id, deactivate_team
from card_generator.generator import draw_team_card

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

RT_NAME, RT_LEAGUE, RT_DISTRICTS, RT_DIVISION, RT_POSITIONS, RT_CONTACT, RT_COMMENT, RT_CUSTOM_LEAGUE = range(8)

LEAGUES    = ["ЛФЛ", "AFL", "Pari Amateur", "F-лига"]
DISTRICTS  = ["ЮГ", "Юго-восток", "Запад", "Северо-запад", "Север", "Северо-Восток", "Восток"]
DIVISIONS  = ["Высший", "Первый", "Второй", "Третий"]
POSITIONS  = ["Нападающий", "Полузащитник", "Защитник", "Вратарь"]


# ── Keyboard builders ────────────────────────────────────────────────────────

def _leagues_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(l, callback_data=f"rt_league:{l}") for l in LEAGUES[:2]],
        [InlineKeyboardButton(l, callback_data=f"rt_league:{l}") for l in LEAGUES[2:]],
        [InlineKeyboardButton("➕ Другая лига", callback_data="rt_league_custom")],
    ])


def _districts_kb(selected: set) -> InlineKeyboardMarkup:
    rows = []
    for d in DISTRICTS:
        mark = "✅" if d in selected else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {d}", callback_data=f"rt_dist:{d}")])
    rows.append([InlineKeyboardButton("✅ Готово", callback_data="rt_dist_done")])
    return InlineKeyboardMarkup(rows)


def _divisions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(d, callback_data=f"rt_div:{d}") for d in DIVISIONS[:2]],
        [InlineKeyboardButton(d, callback_data=f"rt_div:{d}") for d in DIVISIONS[2:]],
    ])


def _positions_kb(selected: set) -> InlineKeyboardMarkup:
    rows = []
    for p in POSITIONS:
        mark = "✅" if p in selected else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {p}", callback_data=f"rt_pos:{p}")])
    rows.append([InlineKeyboardButton("✅ Готово", callback_data="rt_pos_done")])
    return InlineKeyboardMarkup(rows)


# ── Registration conversation ────────────────────────────────────────────────

async def register_team_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await init_db(DB_PATH)
    context.user_data["rt"] = {}
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("Название команды:")
    else:
        await update.message.reply_text("Название команды:")
    return RT_NAME


async def rt_custom_league_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    league = update.message.text.strip()
    context.user_data["rt"]["league"] = league
    context.user_data["rt"]["sel_districts"] = set()
    context.user_data["rt"]["districts"] = []
    context.user_data["rt"]["division"] = ""
    context.user_data["rt"]["sel_positions"] = set()
    await update.message.reply_text(
        "Выбери позиции, которых ищёте, и нажми «Готово»:",
        reply_markup=_positions_kb(set()),
    )
    return RT_POSITIONS


async def rt_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rt"]["name"] = update.message.text.strip()
    await update.message.reply_text("Лига:", reply_markup=_leagues_kb())
    return RT_LEAGUE


async def rt_league(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "rt_league_custom":
        await query.edit_message_text("Введи название лиги:")
        return RT_CUSTOM_LEAGUE
    league = query.data.split(":", 1)[1]
    context.user_data["rt"]["league"] = league
    context.user_data["rt"]["sel_districts"] = set()
    if league == "ЛФЛ":
        await query.edit_message_text(
            "Выбери округ(а) и нажми «Готово»:",
            reply_markup=_districts_kb(set()),
        )
        return RT_DISTRICTS
    # Skip districts/division for non-LFL leagues
    context.user_data["rt"]["districts"] = []
    context.user_data["rt"]["division"] = ""
    context.user_data["rt"]["sel_positions"] = set()
    await query.edit_message_text(
        "Выбери позиции, которых ищёте, и нажми «Готово»:",
        reply_markup=_positions_kb(set()),
    )
    return RT_POSITIONS


async def rt_toggle_district(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    district = query.data.split(":", 1)[1]
    sel = context.user_data["rt"]["sel_districts"]
    if district in sel:
        sel.discard(district)
    else:
        sel.add(district)
    await query.edit_message_text(
        "Выбери округ(а) и нажми «Готово»:",
        reply_markup=_districts_kb(sel),
    )
    return RT_DISTRICTS


async def rt_districts_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["rt"]["districts"] = list(context.user_data["rt"]["sel_districts"])
    await query.edit_message_text("Дивизион:", reply_markup=_divisions_kb())
    return RT_DIVISION


async def rt_division(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["rt"]["division"] = query.data.split(":", 1)[1]
    context.user_data["rt"]["sel_positions"] = set()
    await query.edit_message_text(
        "Выбери позиции, которых ищёте, и нажми «Готово»:",
        reply_markup=_positions_kb(set()),
    )
    return RT_POSITIONS


async def rt_toggle_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pos = query.data.split(":", 1)[1]
    sel = context.user_data["rt"]["sel_positions"]
    if pos in sel:
        sel.discard(pos)
    else:
        sel.add(pos)
    await query.edit_message_text(
        "Выбери позиции и нажми «Готово»:",
        reply_markup=_positions_kb(sel),
    )
    return RT_POSITIONS


async def rt_positions_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["rt"]["positions"] = list(context.user_data["rt"]["sel_positions"])
    await query.edit_message_text("Контакт для связи (@username):")
    return RT_CONTACT


async def rt_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rt"]["contact"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить", callback_data="rt_comment_skip")]])
    await update.message.reply_text("Комментарий (или пропустить):", reply_markup=kb)
    return RT_COMMENT


async def rt_comment_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rt"]["comment"] = update.message.text.strip()
    return await _save_team(update, context)


async def rt_comment_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["rt"]["comment"] = ""
    return await _save_team(update, context, via_query=query)


async def _save_team(
    update: Update, context: ContextTypes.DEFAULT_TYPE, via_query=None
) -> int:
    rt = context.user_data["rt"]
    tg_id = update.effective_user.id
    await upsert_team(
        DB_PATH, tg_id,
        name=rt["name"], league=rt["league"],
        districts=rt.get("districts", []),
        division=rt.get("division", ""),
        positions=rt.get("positions", []),
        contact=rt["contact"],
        comment=rt.get("comment", ""),
    )
    text = (
        f"✅ Команда зарегистрирована!\n\n"
        f"🏟 {rt['name']}  |  🏆 {rt['league']}\n"
        f"📍 {', '.join(rt.get('districts', [])) or '—'}\n"
        f"🔢 {rt.get('division', '') or '—'}\n"
        f"⚽ {', '.join(rt.get('positions', []))}\n\n"
        "Увидеть своё объявление: /my_team\nУдалить: /my_team → 🗑"
    )
    if via_query:
        await via_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return ConversationHandler.END


async def rt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


_MENU_TEXTS = [
    "🃏 Создать карточку", "🔍 Найти агентов",
    "🪪 Моя карточка", "⚽ Найти команду", "👥 Моя команда", "⭐ Избранное",
]


async def _menu_escape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit conversation and execute the keyboard button the user actually pressed."""
    context.user_data.pop("rt", None)
    text = update.message.text
    if text == "⚽ Найти команду":
        await find_teams_handler(update, context)
    elif text == "👥 Моя команда":
        await my_team_handler(update, context)
    elif text == "🪪 Моя карточка":
        from handlers.card import mycard_handler
        await mycard_handler(update, context)
    elif text == "🔍 Найти агентов":
        from handlers.search import find_handler
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
        from handlers.search import favorites_handler
        await favorites_handler(update, context)
    else:
        from handlers.card import MAIN_KEYBOARD
        await update.message.reply_text("Нажми ещё раз.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


def build_team_conversation() -> ConversationHandler:
    # IMPORTANT: button text must be an entry_point for PTB to track conversation state.
    return ConversationHandler(
        entry_points=[
            CommandHandler("register_team", register_team_start),
            MessageHandler(filters.Text(["🏟 Зарегистрировать команду"]), register_team_start),
            CallbackQueryHandler(edit_team_callback, pattern=r"^edit_team$"),
        ],
        states={
            RT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rt_name)],
            RT_LEAGUE: [
                CallbackQueryHandler(rt_league, pattern=r"^rt_league:"),
                CallbackQueryHandler(rt_league, pattern=r"^rt_league_custom$"),
            ],
            RT_CUSTOM_LEAGUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rt_custom_league_text)],
            RT_DISTRICTS: [
                CallbackQueryHandler(rt_toggle_district, pattern=r"^rt_dist:[^_]"),
                CallbackQueryHandler(rt_districts_done, pattern=r"^rt_dist_done$"),
            ],
            RT_DIVISION: [CallbackQueryHandler(rt_division, pattern=r"^rt_div:")],
            RT_POSITIONS: [
                CallbackQueryHandler(rt_toggle_position, pattern=r"^rt_pos:[^_]"),
                CallbackQueryHandler(rt_positions_done, pattern=r"^rt_pos_done$"),
            ],
            RT_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rt_contact)],
            RT_COMMENT: [
                CallbackQueryHandler(rt_comment_skip, pattern=r"^rt_comment_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rt_comment_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", rt_cancel),
            MessageHandler(filters.Text(_MENU_TEXTS), _menu_escape),
        ],
        allow_reentry=True,
    )


# ── My Team ──────────────────────────────────────────────────────────────────

async def my_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    team = await get_team_by_tg_id(DB_PATH, tg_id)
    if not team or not team.get("active"):
        await update.message.reply_text(
            "Команда не зарегистрирована. Нажми *🏟 Зарегистрировать команду*.",
            parse_mode="Markdown",
        )
        return
    png = draw_team_card(team)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_team"),
        InlineKeyboardButton("🗑 Удалить", callback_data="delete_team"),
    ]])
    await update.message.reply_photo(
        photo=io.BytesIO(png),
        caption=f"*{team['name']}* — {team['league']}",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def edit_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await register_team_start(update, context)


async def delete_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await deactivate_team(DB_PATH, query.from_user.id)
    await query.edit_message_caption("🗑 Объявление удалено.")


async def apply_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Заявка отправлена!")
    team_tg_id = int(query.data.split(":", 1)[1])
    applicant = query.from_user
    name = f"{applicant.first_name or ''} {applicant.last_name or ''}".strip()
    username = f"@{applicant.username}" if applicant.username else f"tg_id: {applicant.id}"
    try:
        await context.bot.send_message(
            chat_id=team_tg_id,
            text=(
                f"⚽ Новая заявка на вступление!\n\n"
                f"👤 {name}\n"
                f"📱 {username}\n\n"
                f"Напиши игроку напрямую чтобы договориться."
            ),
        )
    except Exception:
        pass
    await query.message.reply_text("✅ Заявка отправлена капитану команды!")


# ── Find Teams ───────────────────────────────────────────────────────────────

def _ft_filter_kb(context) -> InlineKeyboardMarkup:
    ud = context.user_data.get("ft", {})
    sel_leagues  = ud.get("leagues", set())
    sel_dist     = ud.get("districts", set())
    sel_pos      = ud.get("positions", set())
    custom_leagues = ud.get("custom_leagues", [])

    rows = []

    # Known leagues
    league_btns = []
    for l in LEAGUES:
        mark = "✅" if l in sel_leagues else "☐"
        league_btns.append(InlineKeyboardButton(f"{mark} {l}", callback_data=f"ft_l:{l}"))
    rows.append(league_btns[:2])
    rows.append(league_btns[2:])
    # Custom leagues (user-entered)
    for cl in custom_leagues:
        mark = "✅" if cl in sel_leagues else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {cl}", callback_data=f"ft_l:{cl}")])
    rows.append([
        InlineKeyboardButton("☑ Все лиги",       callback_data="ft_l:all"),
        InlineKeyboardButton("✏️ Другая лига", callback_data="ft_l_custom"),
    ])

    # District row (only if ЛФЛ selected)
    if "ЛФЛ" in sel_leagues:
        for d in DISTRICTS:
            mark = "✅" if d in sel_dist else "☐"
            rows.append([InlineKeyboardButton(f"{mark} {d}", callback_data=f"ft_d:{d}")])

    rows.append([InlineKeyboardButton("─── Позиция ───", callback_data="ft_noop")])
    for p in POSITIONS:
        mark = "✅" if p in sel_pos else "☐"
        rows.append([InlineKeyboardButton(f"{mark} {p}", callback_data=f"ft_p:{p}")])
    rows.append([InlineKeyboardButton("☑ Все позиции", callback_data="ft_p:all")])

    rows.append([InlineKeyboardButton("🔍 Показать результаты", callback_data="ft_search")])
    return InlineKeyboardMarkup(rows)


async def find_teams_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    context.user_data["ft"] = {"leagues": set(), "districts": set(), "positions": set()}
    await update.message.reply_text(
        "Настрой фильтры и нажми «Показать результаты».\n"
        "Без фильтров — покажет все команды.",
        reply_markup=_ft_filter_kb(context),
    )


async def find_teams_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ft_noop":
        return

    ft = context.user_data.setdefault("ft", {"leagues": set(), "districts": set(), "positions": set()})

    if data == "ft_l_custom":
        context.user_data["awaiting_ft_league"] = True
        await query.message.reply_text("Введи название лиги для поиска:")
        return

    if data.startswith("ft_l:"):
        val = data.split(":", 1)[1]
        if val == "all":
            ft["leagues"] = set()
            ft["districts"] = set()
        else:
            if val in ft["leagues"]:
                ft["leagues"].discard(val)
                if val == "ЛФЛ":
                    ft["districts"] = set()
            else:
                ft["leagues"].add(val)
        await query.edit_message_reply_markup(_ft_filter_kb(context))
        return

    if data.startswith("ft_d:"):
        district = data.split(":", 1)[1]
        if district in ft["districts"]:
            ft["districts"].discard(district)
        else:
            ft["districts"].add(district)
        await query.edit_message_reply_markup(_ft_filter_kb(context))
        return

    if data.startswith("ft_p:"):
        val = data.split(":", 1)[1]
        if val == "all":
            ft["positions"] = set()
        else:
            if val in ft["positions"]:
                ft["positions"].discard(val)
            else:
                ft["positions"].add(val)
        await query.edit_message_reply_markup(_ft_filter_kb(context))
        return

    if data == "ft_search":
        league_filter = list(ft["leagues"]) or None
        dist_filter   = list(ft["districts"])
        pos_filter    = list(ft["positions"])
        # For single-league filter pass as string, None means all
        league_str = league_filter[0] if league_filter and len(league_filter) == 1 else None
        teams = await get_teams(DB_PATH, league=league_str, districts=dist_filter, positions=pos_filter)

        # Multi-league filter when >1 selected
        if league_filter and len(league_filter) > 1:
            teams = [t for t in teams if t["league"] in league_filter]

        if not teams:
            await query.edit_message_text("Команды не найдены. Попробуй убрать фильтры.")
            return

        await query.edit_message_text(f"Найдено команд: {len(teams)}")
        for team in teams:
            png = draw_team_card(team)
            contact = team.get("contact", "")
            contact_url = (
                f"https://t.me/{contact.lstrip('@')}" if contact.startswith("@")
                else f"tel:{contact}" if contact else ""
            )
            viewer_id = query.from_user.id
            team_owner = team.get("tg_id", 0)
            kb_buttons = []
            if contact_url:
                kb_buttons.append(InlineKeyboardButton("💬 Написать", url=contact_url))
            if team_owner and viewer_id != team_owner:
                kb_buttons.append(InlineKeyboardButton("📩 Подать заявку", callback_data=f"apply_team:{team_owner}"))
            kb = InlineKeyboardMarkup([kb_buttons]) if kb_buttons else None
            caption = f"*{team['name']}* — {team['league']}"
            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=io.BytesIO(png),
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            except Exception as exc:
                logger.warning("Failed to send team card: %s", exc)
