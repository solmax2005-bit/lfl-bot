import asyncio
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from database.db import init_db
from database.queries import (
    get_agents_by_position, deactivate_agent, get_all_tg_ids,
    create_broadcast, save_broadcast_message, get_broadcast_messages,
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


async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Сделать рассылку", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("📋 Последние рассылки", callback_data="admin_broadcasts")],
    ])
    await update.message.reply_text("Панель администратора:", reply_markup=kb)


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
