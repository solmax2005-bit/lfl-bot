import asyncio
import io
import os
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")


async def notify_players_new_team(bot, team_tg_id: int, team_name: str, league: str, positions: list[str]) -> None:
    """After a team registers — notify active players whose league matches."""
    from database.queries import get_active_agents_for_notification
    agents = await get_active_agents_for_notification(DB_PATH, league=league)
    pos_str = ", ".join(positions) if positions else "любая"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👀 Показать карточку", callback_data=f"notif_team:{team_tg_id}")
    ]])
    for agent in agents:
        if agent["tg_id"] == team_tg_id:
            continue
        try:
            await bot.send_message(
                chat_id=agent["tg_id"],
                text=(
                    f"🏟 Появилась новая команда!\n\n"
                    f"*{team_name}* — {league}\n"
                    f"Ищут: {pos_str}"
                ),
                parse_mode="Markdown",
                reply_markup=kb,
            )
            await asyncio.sleep(0.05)
        except Exception:
            pass


async def notify_teams_new_player(bot, agent_tg_id: int, agent_name: str, position: str, league: str) -> None:
    """After a player becomes active — notify teams looking for that position and league."""
    from database.queries import get_active_teams_for_notification
    teams = await get_active_teams_for_notification(DB_PATH, position=position, league=league)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👀 Показать карточку", callback_data=f"notif_agent:{agent_tg_id}")
    ]])
    for team in teams:
        if team["tg_id"] == agent_tg_id:
            continue
        try:
            await bot.send_message(
                chat_id=team["tg_id"],
                text=(
                    f"🔍 Появился новый свободный агент!\n\n"
                    f"*{agent_name}* — {position}"
                ),
                parse_mode="Markdown",
                reply_markup=kb,
            )
            await asyncio.sleep(0.05)
        except Exception:
            pass


async def notif_show_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show player card when user taps 'Показать карточку' from a player notification."""
    query = update.callback_query
    await query.answer()
    agent_tg_id = int(query.data.split(":")[1])

    from database.queries import get_agent_by_tg_id
    from database.db import init_db
    from handlers.search import _send_agent_card
    await init_db(DB_PATH)
    agent = await get_agent_by_tg_id(DB_PATH, agent_tg_id)
    if not agent or not agent.get("active"):
        await query.message.reply_text("Игрок уже не ищет команду.")
        return
    await _send_agent_card(context.bot, query.message.chat_id, [agent], 0, viewer_tg_id=query.from_user.id)


async def notif_show_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show team card when user taps 'Показать карточку' from a team notification."""
    query = update.callback_query
    await query.answer()
    team_tg_id = int(query.data.split(":")[1])

    from database.queries import get_team_by_tg_id
    from database.db import init_db
    from card_generator.generator import draw_team_card
    await init_db(DB_PATH)
    team = await get_team_by_tg_id(DB_PATH, team_tg_id)
    if not team or not team.get("active"):
        await query.message.reply_text("Команда уже не ищет игроков.")
        return

    png = draw_team_card(team)
    contact = team.get("contact", "")
    contact_url = f"https://t.me/{contact.lstrip('@')}" if contact.startswith("@") else ""
    viewer_id = query.from_user.id

    kb_buttons = []
    if contact_url:
        kb_buttons.append(InlineKeyboardButton("💬 Написать", url=contact_url))
    if team_tg_id and viewer_id != team_tg_id:
        kb_buttons.append(InlineKeyboardButton("📩 Подать заявку", callback_data=f"apply_team:{team_tg_id}"))
    kb = InlineKeyboardMarkup([kb_buttons]) if kb_buttons else None

    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=io.BytesIO(png),
        caption=f"*{team['name']}* — {team['league']}",
        parse_mode="Markdown",
        reply_markup=kb,
    )
