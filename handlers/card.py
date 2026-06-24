import io
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
from database.queries import get_agent_by_tg_id

AWAITING_EXTRA_URL = 10

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📇 Карточка игрока"), KeyboardButton("🔍 Найти агентов")],
        [KeyboardButton("✋ Стать агентом"),   KeyboardButton("🪪 Моя карточка")],
        [KeyboardButton("⚽ Найти команду"),   KeyboardButton("🏟 Зарегистрировать команду")],
        [KeyboardButton("👥 Моя команда")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие...",
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Привет, {name}!\n\nЯ *ЛФЛ Агент* — твой помощник в лиге.\n\nВыбери действие 👇",
        parse_mode="Markdown",
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


_ADD_LEAGUE_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("➕ Добавить ссылку из другой лиги", callback_data="add_league"),
    InlineKeyboardButton("✅ Готово", callback_data="multi_done"),
]])


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
    png = draw_card(profile)
    caption = f"*{profile.name}* — {profile.position}\n{profile.current_club}"
    await update.message.reply_photo(
        photo=io.BytesIO(png), caption=caption,
        parse_mode="Markdown", reply_markup=_ADD_LEAGUE_KB,
    )


async def add_league_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Пришли ссылку из другой лиги (lfl.ru, afl.ru, f-league.ru).\n"
        "Или /skip чтобы пропустить."
    )
    return AWAITING_EXTRA_URL


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


def build_multi_card_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_league_start, pattern="^add_league$")],
        states={
            AWAITING_EXTRA_URL: [
                CallbackQueryHandler(add_league_start, pattern="^add_league$"),
                CallbackQueryHandler(multi_done_callback, pattern="^multi_done$"),
                CommandHandler("skip", add_league_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_league_url),
            ],
        },
        fallbacks=[
            CommandHandler("skip", add_league_skip),
            CallbackQueryHandler(multi_done_callback, pattern="^multi_done$"),
        ],
        per_message=False,
    )


async def message_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""

    if text == "📇 Карточка игрока":
        await update.message.reply_text(
            "Пришли ссылку на профиль игрока:\n"
            "`https://lfl.ru/person122721?player_id=138246`\n"
            "`https://afl.ru/players/ivanov-ivan-482748`\n"
            "`https://f-league.ru/player/4650740`",
            parse_mode="Markdown",
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
    if not agent or not agent.get("active"):
        await update.message.reply_text(
            "Профиль не найден. Нажми *✋ Стать агентом* чтобы создать карточку.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    lfl_url = agent.get("lfl_url", "")
    if lfl_url:
        try:
            profile = await detect_and_parse(lfl_url)
        except ValueError:
            profile = None
    else:
        profile = None

    if profile:
        png = draw_card(profile)
    else:
        # Build manual profile from DB data
        profile = PlayerProfile(
            name=agent["name"],
            position=agent.get("position", "—"),
            birthdate="—",
            age=agent.get("age", 0),
            current_club=agent.get("current_team") or agent.get("division", "—"),
            club_id=0,
            career_clubs=[],
            goals=0, matches=0, assists=0,
            yellow_cards=0, red_cards=0,
            debut_year=0,
            lfl_url="",
            is_free_agent=True,
            experience=agent.get("experience", ""),
        )
        png = draw_card(profile)

    caption = f"*{agent['name']}* — {agent.get('position', '—')}"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_card"),
        InlineKeyboardButton("🗑 Удалить", callback_data="delete_card"),
    ]])
    await update.message.reply_photo(
        photo=io.BytesIO(png), caption=caption,
        parse_mode="Markdown", reply_markup=keyboard,
    )
    # NOTE: "edit_card" callback is handled by build_free_conversation() entry_point in search.py


async def delete_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from database.queries import deactivate_agent
    await deactivate_agent(DB_PATH, query.from_user.id)
    await query.edit_message_caption("🗑 Анкета удалена.")
