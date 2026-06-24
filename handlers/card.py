import io
import json
import os
import re
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from scraper.parsers.registry import detect_url, detect_and_parse
from scraper.models import PlayerProfile
from card_generator.generator import draw_card
from database.db import init_db
from database.queries import get_agent_by_tg_id, upsert_agent, activate_agent, update_looking

AWAITING_EXTRA_URL = 10

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🃏 Создать карточку"),      KeyboardButton("🪪 Моя карточка")],
        [KeyboardButton("🔍 Найти агентов"),          KeyboardButton("⚽ Найти команду")],
        [KeyboardButton("🏟 Зарегистрировать команду"), KeyboardButton("👥 Моя команда")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие...",
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "игрок"
    await update.message.reply_text(
        f"Привет, {name}!\n\nЯ ЛФЛ Агент — твой помощник в лиге.\n\nВыбери действие 👇",
        reply_markup=MAIN_KEYBOARD,
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Команды:*\n"
        "/start — главное меню\n"
        "/mycard — твоя карточка игрока\n"
        "/my_team — твоя команда\n"
        "/leave — убрать анкету агента\n"
        "/admin_list — (admin) список агентов",
        parse_mode="Markdown",
    )


def _merge_profiles(base: PlayerProfile, extra: PlayerProfile) -> PlayerProfile:
    seen = list(base.career_clubs)
    for c in extra.career_clubs:
        if c not in seen:
            seen.append(c)
    return PlayerProfile(
        name=base.name,
        position=base.position if base.position != "—" else extra.position,
        birthdate=base.birthdate,
        age=base.age,
        current_club=base.current_club,
        club_id=base.club_id,
        career_clubs=seen,
        goals=base.goals + extra.goals,
        matches=base.matches + extra.matches,
        assists=base.assists + extra.assists,
        yellow_cards=base.yellow_cards + extra.yellow_cards,
        red_cards=base.red_cards + extra.red_cards,
        debut_year=min(base.debut_year, extra.debut_year) if base.debut_year and extra.debut_year else base.debut_year or extra.debut_year,
        lfl_url=base.lfl_url,
        is_free_agent=base.is_free_agent,
        experience=getattr(base, "experience", ""),
    )


_ADD_LEAGUE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➕ Добавить ссылку из другой лиги", callback_data="add_league")],
    [
        InlineKeyboardButton("🏃 Стать свободным агентом", callback_data="become_agent"),
        InlineKeyboardButton("✅ Готово", callback_data="multi_done"),
    ],
])

_NO_URL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("Нет ссылки — создать вручную", callback_data="no_url"),
]])

_SKIP_EXP_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("Пропустить ➡️", callback_data="skip_exp"),
]])

_SKIP_COMMENT_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("Пропустить ➡️", callback_data="skip_comment"),
]])

_LOOKING_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔍 Ищу команду", callback_data="looking:1"),
    InlineKeyboardButton("✋ Не ищу",       callback_data="looking:0"),
]])

_MAX_TEXT_LEN = 200


async def _summarize_text(text: str, hint: str = "") -> str:
    """Summarize long text via Groq, or truncate as fallback."""
    if len(text) <= _MAX_TEXT_LEN:
        return text
    import httpx as _httpx
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return text[:_MAX_TEXT_LEN]
    sys_msg = (
        "Сократи текст до 1-2 предложений, не более 150 символов. "
        "Сохрани суть. Отвечай только сокращённым текстом."
    )
    if hint:
        sys_msg += f" Контекст: {hint}."
    try:
        async with _httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 80,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return text[:_MAX_TEXT_LEN]


async def _process_url(update: Update, url: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Загружаю профиль...")
    try:
        profile = await detect_and_parse(url)
    except ValueError as e:
        await update.message.reply_text(f"Не удалось загрузить профиль: {e}")
        return
    if profile is None:
        await update.message.reply_text("Ссылка не распознана. Поддерживаются: lfl.ru, afl.ru, f-league.ru")
        return
    context.user_data["multi_profile"] = profile
    context.user_data["multi_sources"] = [url]

    # Auto-save profile to DB (inactive — not in search yet)
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    contact = (
        f"@{update.effective_user.username}"
        if update.effective_user.username else str(tg_id)
    )
    await upsert_agent(
        DB_PATH, tg_id,
        name=profile.name,
        position=profile.position,
        division="",
        contact=contact,
        comment="",
        lfl_url=profile.lfl_url,
        experience=" · ".join(profile.career_clubs),
        current_team="" if profile.is_free_agent else profile.current_club,
        age=profile.age,
        profile_json=_profile_to_json(profile),
        active=0,
    )

    png = draw_card(profile)
    caption = f"*{profile.name}* — {profile.position}\n{profile.current_club}"
    await update.message.reply_photo(
        photo=io.BytesIO(png), caption=caption, parse_mode="Markdown",
    )
    context.user_data["_contact"] = contact
    context.user_data["awaiting_exp"] = True
    await update.message.reply_text(
        "Добавь дополнительный опыт — клубы из других лиг, не указанные на lfl.ru "
        "(через запятую, например: *Аль-Кашаф, ФК Олимп*).\n"
        "Или напиши в свободной форме — бот сам сократит.",
        parse_mode="Markdown",
        reply_markup=_SKIP_EXP_KB,
    )


_SKIP_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("Пропустить ➡️", callback_data="add_league_skip"),
]])


async def _finalize_card(bot, chat_id: int, tg_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redraw card with extra exp/comment, save to DB, ask looking status."""
    profile = context.user_data.get("multi_profile")
    if not profile:
        return
    extra_comment = context.user_data.get("extra_comment", "")
    extra_clubs_added = context.user_data.get("extra_clubs_added", [])
    contact = context.user_data.get("_contact", str(tg_id))

    png = draw_card(profile)
    caption = f"*{profile.name}* — {profile.position}\n{profile.current_club}"
    if extra_comment:
        caption += f"\n_{extra_comment}_"

    await upsert_agent(
        DB_PATH, tg_id,
        name=profile.name,
        position=profile.position,
        division="",
        contact=contact,
        comment=extra_comment,
        lfl_url=profile.lfl_url,
        experience=" · ".join(profile.career_clubs),
        current_team="" if profile.is_free_agent else profile.current_club,
        age=profile.age,
        profile_json=_profile_to_json(profile),
        active=0,
        extra_clubs=", ".join(extra_clubs_added),
    )

    await bot.send_photo(
        chat_id=chat_id,
        photo=io.BytesIO(png),
        caption=caption,
        parse_mode="Markdown",
        reply_markup=_ADD_LEAGUE_KB,
    )
    await bot.send_message(
        chat_id=chat_id,
        text="Укажи статус поиска команды:",
        reply_markup=_LOOKING_KB,
    )


async def looking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    val = int(query.data.split(":")[1])
    tg_id = update.effective_user.id
    await init_db(DB_PATH)
    await update_looking(DB_PATH, tg_id, val)
    status_text = "🔍 Ищу команду" if val else "✋ Не ищу команду"
    await query.edit_message_text(f"Статус сохранён: *{status_text}*", parse_mode="Markdown")


async def _handle_extra_exp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_exp", None)
    text = update.message.text.strip()

    raw_clubs = [c.strip() for c in re.split(r"[,;\n]+", text) if c.strip()]
    added = []

    if raw_clubs:
        profile = context.user_data.get("multi_profile")
        if profile:
            existing = set(profile.career_clubs)
            for club in raw_clubs:
                if club not in existing:
                    profile.career_clubs.append(club)
                    existing.add(club)
                    added.append(club)
    context.user_data["extra_clubs_added"] = added

    context.user_data["awaiting_comment"] = True
    await update.message.reply_text(
        "Добавь комментарий о себе — пожелания к команде, особые условия, что-то важное.\n"
        "Если текст длинный — бот сократит сам.",
        reply_markup=_SKIP_COMMENT_KB,
    )


async def _handle_extra_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("awaiting_comment", None)
    text = update.message.text.strip()
    if len(text) > _MAX_TEXT_LEN:
        await update.message.reply_text("Сокращаю текст...")
        text = await _summarize_text(text, hint="комментарий игрока для карточки в футбольной лиге")
    context.user_data["extra_comment"] = text
    await _finalize_card(
        context.bot, update.message.chat_id,
        update.effective_user.id, context,
    )


async def skip_exp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_exp", None)
    context.user_data["awaiting_comment"] = True
    await query.message.reply_text(
        "Добавь комментарий о себе — пожелания к команде, особые условия.\n"
        "Если текст длинный — бот сократит сам.",
        reply_markup=_SKIP_COMMENT_KB,
    )


async def skip_comment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_comment", None)
    context.user_data["extra_comment"] = ""
    await _finalize_card(
        context.bot, query.message.chat_id,
        update.effective_user.id, context,
    )


async def add_league_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Пришли ссылку из другой лиги (lfl.ru, afl.ru, f-league.ru).",
        reply_markup=_SKIP_KB,
    )
    return AWAITING_EXTRA_URL


async def add_league_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    context.user_data.pop("multi_profile", None)
    context.user_data.pop("multi_sources", None)
    return ConversationHandler.END


async def add_league_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    detected = detect_url(text)
    if not detected:
        await update.message.reply_text("Ссылка не распознана. Попробуй ещё раз или /skip")
        return AWAITING_EXTRA_URL

    url, _ = detected
    sources = context.user_data.get("multi_sources", [])
    if url in sources:
        await update.message.reply_text("Эта ссылка уже добавлена. Пришли другую или /skip")
        return AWAITING_EXTRA_URL

    await update.message.reply_text("Загружаю...")
    try:
        extra = await detect_and_parse(url)
    except ValueError as e:
        await update.message.reply_text(f"Не удалось загрузить: {e}")
        return AWAITING_EXTRA_URL

    if extra is None:
        await update.message.reply_text("Ссылка не распознана. Попробуй ещё раз или /skip")
        return AWAITING_EXTRA_URL

    base = context.user_data.get("multi_profile")
    if base is None:
        await update.message.reply_text("Сессия устарела. Начни заново — пришли первую ссылку.")
        return ConversationHandler.END

    merged = _merge_profiles(base, extra)
    context.user_data["multi_profile"] = merged
    sources.append(url)
    context.user_data["multi_sources"] = sources

    png = draw_card(merged)
    caption = (
        f"*{merged.name}* — {merged.position}\n"
        f"{merged.current_club}\n"
        f"📊 Объединено лиг: {len(sources)}"
    )
    await update.message.reply_photo(
        photo=io.BytesIO(png), caption=caption,
        parse_mode="Markdown", reply_markup=_ADD_LEAGUE_KB,
    )
    return AWAITING_EXTRA_URL


async def add_league_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("multi_profile", None)
    context.user_data.pop("multi_sources", None)
    await update.message.reply_text("Готово!", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


async def multi_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("Готово!")
    await query.edit_message_reply_markup(reply_markup=None)
    context.user_data.pop("multi_profile", None)
    context.user_data.pop("multi_sources", None)
    return ConversationHandler.END


def _profile_to_json(profile: PlayerProfile) -> str:
    return json.dumps({
        "name": profile.name,
        "position": profile.position,
        "birthdate": profile.birthdate,
        "age": profile.age,
        "current_club": profile.current_club,
        "club_id": profile.club_id,
        "career_clubs": profile.career_clubs,
        "goals": profile.goals,
        "matches": profile.matches,
        "assists": profile.assists,
        "yellow_cards": profile.yellow_cards,
        "red_cards": profile.red_cards,
        "debut_year": profile.debut_year,
        "lfl_url": profile.lfl_url,
        "is_free_agent": profile.is_free_agent,
        "experience": profile.experience,
    }, ensure_ascii=False)


async def become_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    profile = context.user_data.get("multi_profile")

    if profile:
        # Called from card view — save/update full profile with active=1
        contact = (
            f"@{update.effective_user.username}"
            if update.effective_user.username else str(tg_id)
        )
        await upsert_agent(
            DB_PATH, tg_id,
            name=profile.name,
            position=profile.position,
            division="",
            contact=contact,
            comment="",
            lfl_url=profile.lfl_url,
            experience=" · ".join(profile.career_clubs),
            current_team="" if profile.is_free_agent else profile.current_club,
            age=profile.age,
            profile_json=_profile_to_json(profile),
            active=1,
        )
        context.user_data.pop("multi_profile", None)
        context.user_data.pop("multi_sources", None)
        name = profile.name
    else:
        # Called from "Моя карточка" — just activate existing record
        agent = await get_agent_by_tg_id(DB_PATH, tg_id)
        if not agent:
            await query.answer("Профиль не найден.", show_alert=True)
            return
        await activate_agent(DB_PATH, tg_id)
        name = agent.get("name", "")

    try:
        await query.edit_message_caption(
            f"✅ *{name}* добавлен в поиск агентов!\n"
            "Тебя найдут при поиске по позиции.",
            parse_mode="Markdown",
        )
    except Exception:
        await query.edit_message_reply_markup(reply_markup=None)


_MULTI_MENU_TEXTS = [
    "🃏 Создать карточку", "🔍 Найти агентов",
    "🪪 Моя карточка", "⚽ Найти команду", "🏟 Зарегистрировать команду", "👥 Моя команда",
]


async def _multi_menu_escape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("multi_profile", None)
    context.user_data.pop("multi_sources", None)
    text = update.message.text
    if text == "🔍 Найти агентов":
        from handlers.search import find_handler
        await find_handler(update, context)
    elif text == "🪪 Моя карточка":
        await mycard_handler(update, context)
    elif text == "🃏 Создать карточку":
        await update.message.reply_text(
            "Пришли ссылку на свой профиль из поддерживаемых лиг:\n\n"
            "• *lfl.ru* — `https://lfl.ru/personNNNNN?player_id=NNNNN`\n"
            "• *afl.ru* — `https://afl.ru/players/имя-NNNNN`\n"
            "• *f-league.ru* — `https://f-league.ru/player/NNNNN`\n\n"
            "Или создай карточку вручную:",
            parse_mode="Markdown",
            reply_markup=_NO_URL_KB,
        )
    elif text == "⚽ Найти команду":
        from handlers.teams import find_teams_handler
        await find_teams_handler(update, context)
    elif text == "👥 Моя команда":
        from handlers.teams import my_team_handler
        await my_team_handler(update, context)
    else:
        await update.message.reply_text("Нажми ещё раз.", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


def build_multi_card_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_league_start, pattern="^add_league$")],
        states={
            AWAITING_EXTRA_URL: [
                CallbackQueryHandler(add_league_start,         pattern="^add_league$"),
                CallbackQueryHandler(add_league_skip_callback, pattern="^add_league_skip$"),
                CallbackQueryHandler(multi_done_callback,      pattern="^multi_done$"),
                MessageHandler(filters.Text(_MULTI_MENU_TEXTS), _multi_menu_escape),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_league_url),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(add_league_skip_callback, pattern="^add_league_skip$"),
            CallbackQueryHandler(multi_done_callback,       pattern="^multi_done$"),
            MessageHandler(filters.Text(_MULTI_MENU_TEXTS), _multi_menu_escape),
        ],
        per_message=False,
        allow_reentry=True,
    )


_MENU_BUTTON_TEXTS = {
    "🃏 Создать карточку", "🔍 Найти агентов", "🪪 Моя карточка",
    "⚽ Найти команду", "👥 Моя команда",
}


async def message_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""

    # Menu buttons cancel any pending input collection
    if text in _MENU_BUTTON_TEXTS:
        context.user_data.pop("awaiting_exp", None)
        context.user_data.pop("awaiting_comment", None)
        context.user_data.pop("awaiting_ft_league", None)
    elif context.user_data.get("awaiting_ft_league"):
        league = text.strip()
        ft = context.user_data.setdefault("ft", {"leagues": set(), "districts": set(), "positions": set()})
        ft.setdefault("custom_leagues", [])
        if league not in ft["custom_leagues"]:
            ft["custom_leagues"].append(league)
        ft["leagues"].add(league)
        context.user_data.pop("awaiting_ft_league", None)
        from handlers.teams import _ft_filter_kb
        await update.message.reply_text(
            f"✅ Лига «{league}» добавлена. Настрой остальные фильтры и нажми «Показать результаты».",
            reply_markup=_ft_filter_kb(context),
        )
        return
    elif context.user_data.get("awaiting_exp"):
        await _handle_extra_exp(update, context)
        return
    elif context.user_data.get("awaiting_comment"):
        await _handle_extra_comment(update, context)
        return

    if text == "🃏 Создать карточку":
        await update.message.reply_text(
            "Пришли ссылку на свой профиль из поддерживаемых лиг:\n\n"
            "• *lfl.ru* — `https://lfl.ru/personNNNNN?player_id=NNNNN`\n"
            "• *afl.ru* — `https://afl.ru/players/имя-NNNNN`\n"
            "• *f-league.ru* — `https://f-league.ru/player/NNNNN`\n\n"
            "Или создай карточку вручную:",
            parse_mode="Markdown",
            reply_markup=_NO_URL_KB,
        )
        return

    if text == "🔍 Найти агентов":
        from handlers.search import find_handler
        await find_handler(update, context)
        return

    # NOTE: "✋ Стать агентом" and "🏟 Зарегистрировать команду" are NOT handled here.
    # They are ConversationHandler entry_points in search.py and teams.py respectively.
    # PTB intercepts them before this handler when ConversationHandlers are registered first.

    if text == "🪪 Моя карточка":
        await mycard_handler(update, context)
        return

    if text == "⚽ Найти команду":
        from handlers.teams import find_teams_handler
        await find_teams_handler(update, context)
        return

    if text == "👥 Моя команда":
        from handlers.teams import my_team_handler
        await my_team_handler(update, context)
        return

    # URL in free text
    detected = detect_url(text)
    if detected:
        url, _ = detected
        await _process_url(update, url, context)


async def mycard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await init_db(DB_PATH)
    tg_id = update.effective_user.id
    agent = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not agent:
        await update.message.reply_text(
            "Профиль не найден. Нажми *🃏 Создать карточку* чтобы создать свою карточку.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    profile = _profile_from_agent(agent)
    png = draw_card(profile)
    is_active = bool(agent.get("active"))
    looking = bool(agent.get("looking", 0))
    status = "" if is_active else "\n_Не отображаешься в поиске агентов_"
    caption = f"*{agent['name']}* — {agent.get('position', '—')}{status}"

    btn_rows = [
        [
            InlineKeyboardButton("🔍 Ищу команду ✓" if looking else "🔍 Ищу команду", callback_data="looking:1"),
            InlineKeyboardButton("✋ Не ищу ✓" if not looking else "✋ Не ищу",        callback_data="looking:0"),
        ],
    ]
    if agent.get("lfl_url"):
        btn_rows.append([InlineKeyboardButton("🔄 Обновить с сайта", callback_data="refresh_card")])
    if not is_active:
        btn_rows.append([InlineKeyboardButton("🏃 Добавить в поиск агентов", callback_data="become_agent")])
    btn_rows.append([
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_card"),
        InlineKeyboardButton("🗑 Удалить",        callback_data="delete_card"),
    ])
    await update.message.reply_photo(
        photo=io.BytesIO(png), caption=caption,
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btn_rows),
    )


def _profile_from_agent(agent: dict) -> PlayerProfile:
    """Build PlayerProfile from DB agent dict (cached, no network)."""
    pj = agent.get("profile_json") or ""
    if pj:
        try:
            d = json.loads(pj)
            return PlayerProfile(
                name=d.get("name", "—"), position=d.get("position", "—"),
                birthdate=d.get("birthdate", "—"), age=d.get("age", 0),
                current_club=d.get("current_club", "Свободный агент"),
                club_id=d.get("club_id", 0), career_clubs=d.get("career_clubs", []),
                goals=d.get("goals", 0), matches=d.get("matches", 0),
                assists=d.get("assists", 0), yellow_cards=d.get("yellow_cards", 0),
                red_cards=d.get("red_cards", 0), debut_year=d.get("debut_year", 0),
                lfl_url=d.get("lfl_url", ""), is_free_agent=d.get("is_free_agent", True),
                experience=d.get("experience", ""),
                looking=bool(agent.get("looking", 0)),
            )
        except Exception:
            pass
    return PlayerProfile(
        name=agent.get("name", "—"), position=agent.get("position", "—"),
        birthdate="—", age=agent.get("age", 0),
        current_club=agent.get("current_team") or "—",
        club_id=0, career_clubs=[],
        goals=0, matches=0, assists=0, yellow_cards=0, red_cards=0,
        debut_year=0, lfl_url="", is_free_agent=True,
        experience=agent.get("experience", ""),
        looking=bool(agent.get("looking", 0)),
    )


async def refresh_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Загружаю актуальные данные...")
    tg_id = update.effective_user.id
    await init_db(DB_PATH)
    agent = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not agent or not agent.get("lfl_url"):
        return

    loading = await query.message.reply_text("🔄 Загружаю данные с сайта...")
    try:
        fresh = await detect_and_parse(agent["lfl_url"])
    except Exception:
        fresh = None
    await loading.delete()

    if not fresh:
        await query.message.reply_text("Не удалось загрузить данные. Показываю кешированную версию.")
        return

    # Merge extra clubs from DB
    extra_clubs = [c.strip() for c in (agent.get("extra_clubs") or "").split(",") if c.strip()]
    seen = set(fresh.career_clubs)
    for c in extra_clubs:
        if c not in seen:
            fresh.career_clubs.append(c)
            seen.add(c)
    fresh.looking = bool(agent.get("looking", 0))

    await upsert_agent(
        DB_PATH, tg_id,
        name=fresh.name, position=fresh.position, division="",
        contact=agent.get("contact", str(tg_id)),
        comment=agent.get("comment", ""),
        lfl_url=agent["lfl_url"],
        experience=" · ".join(fresh.career_clubs),
        current_team="" if fresh.is_free_agent else fresh.current_club,
        age=fresh.age,
        profile_json=_profile_to_json(fresh),
        active=agent.get("active", 0),
        looking=agent.get("looking", 0),
        extra_clubs=agent.get("extra_clubs", ""),
    )

    png = draw_card(fresh)
    is_active = bool(agent.get("active"))
    looking = fresh.looking
    status = "" if is_active else "\n_Не отображаешься в поиске агентов_"
    caption = f"*{fresh.name}* — {fresh.position}{status}"
    btn_rows = [
        [
            InlineKeyboardButton("🔍 Ищу команду ✓" if looking else "🔍 Ищу команду", callback_data="looking:1"),
            InlineKeyboardButton("✋ Не ищу ✓" if not looking else "✋ Не ищу",        callback_data="looking:0"),
        ],
        [InlineKeyboardButton("🔄 Обновить с сайта", callback_data="refresh_card")],
    ]
    if not is_active:
        btn_rows.append([InlineKeyboardButton("🏃 Добавить в поиск агентов", callback_data="become_agent")])
    btn_rows.append([
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_card"),
        InlineKeyboardButton("🗑 Удалить",        callback_data="delete_card"),
    ])
    await query.message.reply_photo(
        photo=io.BytesIO(png), caption=caption,
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btn_rows),
    )


async def delete_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from database.queries import deactivate_agent
    await deactivate_agent(DB_PATH, query.from_user.id)
    await query.edit_message_caption("🗑 Анкета удалена.")
