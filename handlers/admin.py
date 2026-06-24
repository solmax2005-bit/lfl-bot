import asyncio
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from database.db import init_db
from database.queries import (
    get_agents_by_position, deactivate_agent, activate_agent, get_all_tg_ids,
    create_broadcast, save_broadcast_message, get_broadcast_messages,
    get_all_agents_admin, get_all_teams_admin,
    delete_agent_permanently, delete_team_permanently,
    deactivate_team,
)

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


_PAGE_SIZE = 6


def _agents_kb(agents: list, page: int) -> InlineKeyboardMarkup:
    total = len(agents)
    start = page * _PAGE_SIZE
    chunk = agents[start:start + _PAGE_SIZE]
    rows = []
    for a in chunk:
        status = "✅" if a["active"] else "🔴"
        toggle_label = "🙈 Скрыть" if a["active"] else "👁 Показать"
        short = a["name"][:14]
        rows.append([
            InlineKeyboardButton(f"{status} {short} ({a['position'] or '—'})", callback_data="noop"),
        ])
        rows.append([
            InlineKeyboardButton(toggle_label, callback_data=f"admin_toggle_agent:{a['tg_id']}:{page}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_del_agent:{a['tg_id']}:{page}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_agents:{page - 1}"))
    pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
    nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if start + _PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_agents:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")])
    return InlineKeyboardMarkup(rows)


def _teams_kb(teams: list, page: int) -> InlineKeyboardMarkup:
    total = len(teams)
    start = page * _PAGE_SIZE
    chunk = teams[start:start + _PAGE_SIZE]
    rows = []
    for t in chunk:
        status = "✅" if t["active"] else "🔴"
        toggle_label = "🙈 Скрыть" if t["active"] else "👁 Показать"
        short = t["name"][:14]
        rows.append([
            InlineKeyboardButton(f"{status} {short} ({t['league'] or '—'})", callback_data="noop"),
        ])
        rows.append([
            InlineKeyboardButton(toggle_label, callback_data=f"admin_toggle_team:{t['tg_id']}:{page}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_del_team:{t['tg_id']}:{page}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"admin_teams:{page - 1}"))
    pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
    nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if start + _PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"admin_teams:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")])
    return InlineKeyboardMarkup(rows)


async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Сделать рассылку",    callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("📋 Последние рассылки",  callback_data="admin_broadcasts")],
        [InlineKeyboardButton("👤 Карточки игроков",    callback_data="admin_agents:0")],
        [InlineKeyboardButton("🏟 Карточки команд",     callback_data="admin_teams:0")],
    ])
    await update.message.reply_text("Панель администратора:", reply_markup=kb)


async def admin_panel_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer()
        return
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Сделать рассылку",    callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("📋 Последние рассылки",  callback_data="admin_broadcasts")],
        [InlineKeyboardButton("👤 Карточки игроков",    callback_data="admin_agents:0")],
        [InlineKeyboardButton("🏟 Карточки команд",     callback_data="admin_teams:0")],
    ])
    await query.edit_message_text("Панель администратора:", reply_markup=kb)


async def admin_agents_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    page = int(query.data.split(":")[1])
    await init_db(DB_PATH)
    agents = await get_all_agents_admin(DB_PATH)
    if not agents:
        await query.edit_message_text("Карточек игроков нет.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")]
        ]))
        return
    active = sum(1 for a in agents if a["active"])
    text = f"👤 Карточки игроков: {active} активных, {len(agents) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_agents_kb(agents, page))


async def admin_toggle_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    _, tg_id_str, page_str = query.data.split(":")
    tg_id, page = int(tg_id_str), int(page_str)
    await init_db(DB_PATH)
    agents = await get_all_agents_admin(DB_PATH)
    agent = next((a for a in agents if a["tg_id"] == tg_id), None)
    if agent:
        if agent["active"]:
            await deactivate_agent(DB_PATH, tg_id)
            await query.answer("🙈 Скрыто")
        else:
            await activate_agent(DB_PATH, tg_id)
            await query.answer("👁 Показано")
    agents = await get_all_agents_admin(DB_PATH)
    active = sum(1 for a in agents if a["active"])
    text = f"👤 Карточки игроков: {active} активных, {len(agents) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_agents_kb(agents, page))


async def admin_del_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    _, tg_id_str, page_str = query.data.split(":")
    tg_id, page = int(tg_id_str), int(page_str)
    await init_db(DB_PATH)
    await delete_agent_permanently(DB_PATH, tg_id)
    await query.answer("🗑 Удалено")
    agents = await get_all_agents_admin(DB_PATH)
    if not agents:
        await query.edit_message_text("Карточек игроков нет.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")]
        ]))
        return
    page = min(page, max(0, (len(agents) - 1) // _PAGE_SIZE))
    active = sum(1 for a in agents if a["active"])
    text = f"👤 Карточки игроков: {active} активных, {len(agents) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_agents_kb(agents, page))


async def admin_teams_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    page = int(query.data.split(":")[1])
    await init_db(DB_PATH)
    teams = await get_all_teams_admin(DB_PATH)
    if not teams:
        await query.edit_message_text("Карточек команд нет.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")]
        ]))
        return
    active = sum(1 for t in teams if t["active"])
    text = f"🏟 Карточки команд: {active} активных, {len(teams) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_teams_kb(teams, page))


async def admin_toggle_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    _, tg_id_str, page_str = query.data.split(":")
    tg_id, page = int(tg_id_str), int(page_str)
    await init_db(DB_PATH)
    teams = await get_all_teams_admin(DB_PATH)
    team = next((t for t in teams if t["tg_id"] == tg_id), None)
    if team:
        if team["active"]:
            await deactivate_team(DB_PATH, tg_id)
            await query.answer("🙈 Скрыто")
        else:
            async with __import__("aiosqlite").connect(DB_PATH) as conn:
                await conn.execute("UPDATE teams SET active=1 WHERE tg_id=?", (tg_id,))
                await conn.commit()
            await query.answer("👁 Показано")
    teams = await get_all_teams_admin(DB_PATH)
    active = sum(1 for t in teams if t["active"])
    text = f"🏟 Карточки команд: {active} активных, {len(teams) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_teams_kb(teams, page))


async def admin_del_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    _, tg_id_str, page_str = query.data.split(":")
    tg_id, page = int(tg_id_str), int(page_str)
    await init_db(DB_PATH)
    await delete_team_permanently(DB_PATH, tg_id)
    await query.answer("🗑 Удалено")
    teams = await get_all_teams_admin(DB_PATH)
    if not teams:
        await query.edit_message_text("Карточек команд нет.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ В меню", callback_data="admin_panel_back")]
        ]))
        return
    page = min(page, max(0, (len(teams) - 1) // _PAGE_SIZE))
    active = sum(1 for t in teams if t["active"])
    text = f"🏟 Карточки команд: {active} активных, {len(teams) - active} скрытых"
    await query.edit_message_text(text, reply_markup=_teams_kb(teams, page))


async def admin_broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    context.user_data["awaiting_broadcast"] = True
    await query.edit_message_text("📢 Отправь текст или фото для рассылки:\n\n(или /cancel чтобы отменить)")


async def admin_broadcasts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer()
    await init_db(DB_PATH)
    async with __import__("aiosqlite").connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT id, created_at FROM broadcasts ORDER BY id DESC LIMIT 10"
        )
        rows = await cur.fetchall()
    if not rows:
        await query.edit_message_text("Рассылок ещё не было.")
        return
    btn_rows = []
    for bid, created_at in rows:
        btn_rows.append([InlineKeyboardButton(
            f"🗑 Удалить рассылку #{bid} ({created_at[:16]})",
            callback_data=f"admin_del_broadcast:{bid}",
        )])
    btn_rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel_back")])
    await query.edit_message_text("Выбери рассылку для удаления:", reply_markup=InlineKeyboardMarkup(btn_rows))


async def admin_del_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_TG_ID:
        await query.answer("Нет доступа.", show_alert=True)
        return
    await query.answer("Удаляю...")
    broadcast_id = int(query.data.split(":")[1])
    await init_db(DB_PATH)
    messages = await get_broadcast_messages(DB_PATH, broadcast_id)
    if not messages:
        await query.edit_message_text("Рассылка не найдена.")
        return
    await query.edit_message_text(f"🗑 Удаляю {len(messages)} сообщений...")
    ok, fail = 0, 0
    for m in messages:
        try:
            await context.bot.delete_message(chat_id=m["chat_id"], message_id=m["message_id"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await query.edit_message_text(f"✅ Удалено: {ok}\nНе удалось: {fail}")


async def _do_broadcast(bot, reply_msg, text: str, photo: str | None) -> None:
    """Core broadcast logic: send to all users, show delete button on completion."""
    await init_db(DB_PATH)
    ids = await get_all_tg_ids(DB_PATH)
    if not ids:
        await reply_msg.reply_text("Нет пользователей для рассылки.")
        return

    broadcast_id = await create_broadcast(DB_PATH)
    status = await reply_msg.reply_text(f"📨 Отправляю {len(ids)} пользователям...")
    ok, fail = 0, 0
    for tg_id in ids:
        try:
            if photo:
                msg = await bot.send_photo(chat_id=tg_id, photo=photo, caption=text or "")
            else:
                msg = await bot.send_message(chat_id=tg_id, text=text)
            await save_broadcast_message(DB_PATH, broadcast_id, tg_id, msg.message_id)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Удалить у всех", callback_data=f"admin_del_broadcast:{broadcast_id}")
    ]])
    await status.edit_text(
        f"✅ Рассылка #{broadcast_id} завершена\nОтправлено: {ok}\nНе доставлено: {fail}",
        reply_markup=kb,
    )


async def handle_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Called from message_url_handler / photo_message_handler when awaiting_broadcast is set.
    Returns True if handled, False otherwise."""
    if not context.user_data.get("awaiting_broadcast"):
        return False
    if update.effective_user.id != ADMIN_TG_ID:
        return False
    context.user_data.pop("awaiting_broadcast", None)

    text = ""
    photo = None
    if update.message.photo:
        photo = update.message.photo[-1].file_id
        text = update.message.caption or ""
    elif update.message.text:
        text = update.message.text.strip()

    await _do_broadcast(context.bot, update.message, text, photo)
    return True


async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return

    text = " ".join(context.args) if context.args else ""
    photo = None
    if update.message.photo:
        photo = update.message.photo[-1].file_id
    elif update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1].file_id

    if not text and not photo:
        await update.message.reply_text(
            "Использование:\n"
            "• /broadcast текст — текстовая рассылка\n"
            "• Или нажми /admin → 📢 Сделать рассылку"
        )
        return

    await _do_broadcast(context.bot, update.message, text, photo)


async def broadcast_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /broadcast_delete <id>")
        return
    broadcast_id = int(context.args[0])
    await init_db(DB_PATH)
    messages = await get_broadcast_messages(DB_PATH, broadcast_id)
    if not messages:
        await update.message.reply_text(f"Рассылка #{broadcast_id} не найдена.")
        return
    status = await update.message.reply_text(f"🗑 Удаляю {len(messages)} сообщений...")
    ok, fail = 0, 0
    for m in messages:
        try:
            await context.bot.delete_message(chat_id=m["chat_id"], message_id=m["message_id"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Удалено: {ok}\nНе удалось: {fail}")
