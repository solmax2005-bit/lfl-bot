from dotenv import load_dotenv
load_dotenv()

import os
import io
import json
import hmac
import base64
import hashlib
import time
import asyncio
from urllib.parse import parse_qsl

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import aiosqlite
import httpx

from scraper.parsers.registry import detect_and_parse
from database.queries import (
    upsert_agent, get_agent_by_tg_id, deactivate_agent, activate_agent,
    update_looking, delete_agent_permanently, save_card_photo,
    upsert_team, get_teams, get_team_by_tg_id, deactivate_team, save_team_photo,
    add_favorite, remove_favorite, is_favorite, get_favorites,
    get_active_teams_for_notification, get_active_agents_for_notification,
    incr_stat,
)

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

POSITIONS = {"Нападающий", "Полузащитник", "Защитник", "Вратарь"}
LEAGUES = {"ЛФЛ", "AFL", "Pari Amateur", "F-лига", ""}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PHOTOS_DIR = "photos"
os.makedirs(PHOTOS_DIR, exist_ok=True)
app.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")


# ── Telegram WebApp initData validation ──────────────────────────────────────

def verify_init_data(raw: str, max_age: int = 86400) -> dict:
    """Validate Telegram WebApp initData (HMAC-SHA256), return verified user.

    Raises HTTPException(403) on any failure. Returns {"tg_id": int, "username": str}.
    Only the signature proves identity — never trust an unsigned tg_id for writes.
    """
    if not raw or not BOT_TOKEN:
        raise HTTPException(status_code=403, detail="no init data")
    try:
        pairs = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    except Exception:
        raise HTTPException(status_code=403, detail="bad init data")
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=403, detail="no hash")
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status_code=403, detail="bad signature")
    auth_date = int(pairs.get("auth_date") or 0)
    if max_age and auth_date and (time.time() - auth_date) > max_age:
        raise HTTPException(status_code=403, detail="expired")
    try:
        user = json.loads(pairs.get("user") or "{}")
    except Exception:
        user = {}
    tg_id = user.get("id")
    if not tg_id:
        raise HTTPException(status_code=403, detail="no user")
    return {
        "tg_id": int(tg_id),
        "username": user.get("username") or "",
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
    }


def _contact_for(user: dict) -> str:
    return f"@{user['username']}" if user.get("username") else str(user["tg_id"])


def _profile_to_json(p) -> str:
    return json.dumps({
        "name": p.name, "position": p.position,
        "birthdate": getattr(p, "birthdate", ""), "age": p.age,
        "current_club": p.current_club, "club_id": getattr(p, "club_id", 0),
        "career_clubs": p.career_clubs, "goals": p.goals, "matches": p.matches,
        "assists": p.assists, "yellow_cards": p.yellow_cards, "red_cards": p.red_cards,
        "debut_year": p.debut_year, "lfl_url": p.lfl_url,
        "is_free_agent": p.is_free_agent, "experience": getattr(p, "experience", ""),
    }, ensure_ascii=False)


def _parse_profile(data: dict) -> dict:
    profile = {}
    if data.get("profile_json"):
        try:
            profile = json.loads(data["profile_json"])
        except Exception:
            pass
    return {
        "found": True,
        "tg_id": data["tg_id"],
        "name": data["name"] or "Неизвестно",
        "position": data["position"] or "—",
        "age": data["age"] or 0,
        "current_club": profile.get("current_club") or data.get("current_team") or "Свободный агент",
        "lfl_url": data.get("lfl_url") or "",
        "active": data.get("active", 0),
        "looking": data.get("looking", 0),
        "photo": data.get("photo") or "",
        "contact": data.get("contact") or "",
        "comment": data.get("comment") or "",
        "division": data.get("division") or "",
        "current_team": data.get("current_team") or "",
        "experience": data.get("experience") or "",
        "goals": profile.get("goals", 0),
        "matches": profile.get("matches", 0),
        "assists": profile.get("assists", 0),
        "yellow_cards": profile.get("yellow_cards", 0),
        "red_cards": profile.get("red_cards", 0),
        "debut_year": profile.get("debut_year") or "",
        "career_clubs": profile.get("career_clubs") or [],
        "birthdate": profile.get("birthdate") or "",
        "is_free_agent": profile.get("is_free_agent", False),
    }


async def _card_response(tg_id: int) -> dict:
    row = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not row:
        return {"ok": True, "profile": {"found": False}}
    return {"ok": True, "profile": _parse_profile(row)}


# ── Read endpoints (unverified tg_id, read-only) ─────────────────────────────

@app.get("/")
async def root():
    # no-store so Telegram clients always fetch the latest Mini App (avoid stale cache)
    return FileResponse("webapp/index.html", headers={"Cache-Control": "no-store, must-revalidate"})


@app.post("/api/visit")
async def visit():
    # Called once when the Mini App loads — counts opens for admin stats.
    await incr_stat(DB_PATH, "miniapp_opens")
    return {"ok": True}


@app.get("/api/me")
async def get_me(tg_id: int = Query(...)):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM free_agents WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
    if not row:
        return {"found": False}
    return _parse_profile(dict(row))


@app.get("/api/agents")
async def get_agents(position: str = Query(default="")):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        if position and position not in ("", "Все"):
            cur = await conn.execute(
                "SELECT * FROM free_agents WHERE active=1 AND position=? ORDER BY created_at DESC LIMIT 60",
                (position,),
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM free_agents WHERE active=1 ORDER BY created_at DESC LIMIT 60"
            )
        rows = await cur.fetchall()
    return [_parse_profile(dict(r)) for r in rows]


# ── Write endpoints (require verified Telegram initData) ─────────────────────

class ImportReq(BaseModel):
    init_data: str
    url: str


class SaveReq(BaseModel):
    init_data: str
    name: str
    position: str
    age: int = 0
    current_team: str = ""
    division: str = ""
    experience: str = ""
    comment: str = ""


class InitReq(BaseModel):
    init_data: str


class StatusReq(BaseModel):
    init_data: str
    active: int | None = None
    looking: int | None = None


@app.post("/api/card/import")
async def card_import(req: ImportReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    try:
        profile = await detect_and_parse(req.url)
    except Exception as e:
        return {"ok": False, "error": str(e) or "Не удалось загрузить профиль"}
    if profile is None:
        return {"ok": False, "error": "Ссылка не распознана. Поддерживаются lfl.ru, afl.ru, f-league.ru"}
    await upsert_agent(
        DB_PATH, tg_id,
        name=profile.name, position=profile.position, division="",
        contact=_contact_for(user), comment="",
        lfl_url=profile.lfl_url,
        experience=" · ".join(profile.career_clubs),
        current_team="" if profile.is_free_agent else profile.current_club,
        age=profile.age, profile_json=_profile_to_json(profile), active=0,
    )
    return await _card_response(tg_id)


@app.post("/api/card/save")
async def card_save(req: SaveReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    if not req.name.strip():
        return {"ok": False, "error": "Укажи имя"}
    if req.position not in POSITIONS:
        return {"ok": False, "error": "Выбери позицию"}
    if not (10 <= req.age <= 60):
        return {"ok": False, "error": "Возраст должен быть от 10 до 60"}
    if req.division not in LEAGUES:
        return {"ok": False, "error": "Неизвестная лига"}

    existing = await get_agent_by_tg_id(DB_PATH, tg_id)
    await upsert_agent(
        DB_PATH, tg_id,
        name=req.name.strip(), position=req.position, division=req.division,
        contact=_contact_for(user), comment=req.comment.strip(),
        lfl_url=(existing.get("lfl_url", "") if existing else ""),
        experience=req.experience.strip(), current_team=req.current_team.strip(),
        age=req.age,
        profile_json=(existing.get("profile_json", "") if existing else ""),
        active=(existing.get("active", 0) if existing else 0),
        looking=(existing.get("looking", 0) if existing else 0),
        extra_clubs=(existing.get("extra_clubs", "") if existing else ""),
    )
    return await _card_response(tg_id)


@app.post("/api/card/status")
async def card_status(req: StatusReq, background: BackgroundTasks):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    existing = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not existing:
        return {"ok": False, "error": "Сначала создай карточку"}
    was_active = existing.get("active", 0)
    if req.active is not None:
        if req.active:
            await activate_agent(DB_PATH, tg_id)
        else:
            await deactivate_agent(DB_PATH, tg_id)
    if req.looking is not None:
        await update_looking(DB_PATH, tg_id, 1 if req.looking else 0)
    # Notify matching teams when the player just became searchable.
    if req.active == 1 and not was_active:
        background.add_task(
            _notify_teams_new_player, tg_id,
            existing.get("name", ""), existing.get("position", ""),
            existing.get("division") or "ЛФЛ",
        )
    return await _card_response(tg_id)


@app.post("/api/card/delete")
async def card_delete(req: InitReq):
    user = verify_init_data(req.init_data)
    await delete_agent_permanently(DB_PATH, user["tg_id"])
    return {"ok": True}


class PhotoReq(BaseModel):
    init_data: str
    image: str  # base64 (optionally a data: URL)


def _save_square_image(image_b64: str, dest_path: str, size: int = 400) -> str | None:
    """Decode base64, center-crop to square, resize, save JPEG. Returns error or None."""
    data = (image_b64 or "").strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
    except Exception:
        return "Не удалось прочитать изображение"
    if len(raw) > 8 * 1024 * 1024:
        return "Фото слишком большое (макс 8 МБ)"
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return "Это не изображение"
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    img.save(dest_path, "JPEG", quality=85)
    return None


@app.post("/api/card/photo")
async def card_photo(req: PhotoReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    if not await get_agent_by_tg_id(DB_PATH, tg_id):
        return {"ok": False, "error": "Сначала создай карточку"}
    err = _save_square_image(req.image, os.path.join(PHOTOS_DIR, f"{tg_id}.jpg"))
    if err:
        return {"ok": False, "error": err}
    await save_card_photo(DB_PATH, tg_id, f"/photos/{tg_id}.jpg?t={int(time.time())}")
    return await _card_response(tg_id)


@app.post("/api/card/refresh")
async def card_refresh(req: InitReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    existing = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not existing or not existing.get("lfl_url"):
        return {"ok": False, "error": "У карточки нет ссылки для обновления"}
    try:
        fresh = await detect_and_parse(existing["lfl_url"])
    except Exception as e:
        return {"ok": False, "error": str(e) or "Не удалось обновить"}
    if not fresh:
        return {"ok": False, "error": "Не удалось загрузить данные с сайта"}
    # keep extra clubs the user added manually
    extra = [c.strip() for c in (existing.get("extra_clubs") or "").split(",") if c.strip()]
    seen = set(fresh.career_clubs)
    for c in extra:
        if c not in seen:
            fresh.career_clubs.append(c)
            seen.add(c)
    await upsert_agent(
        DB_PATH, tg_id,
        name=fresh.name, position=fresh.position, division=existing.get("division", ""),
        contact=existing.get("contact", str(tg_id)), comment=existing.get("comment", ""),
        lfl_url=existing["lfl_url"],
        experience=" · ".join(fresh.career_clubs),
        current_team="" if fresh.is_free_agent else fresh.current_club,
        age=fresh.age, profile_json=_profile_to_json(fresh),
        active=existing.get("active", 0), looking=existing.get("looking", 0),
        extra_clubs=existing.get("extra_clubs", ""),
    )
    return await _card_response(tg_id)


# ── Teams (Phase 2) ──────────────────────────────────────────────────────────

def _team_public(t: dict) -> dict:
    return {
        "tg_id": t.get("tg_id"),
        "name": t.get("name", ""),
        "league": t.get("league", ""),
        "districts": t.get("districts", []),
        "division": t.get("division", ""),
        "positions": t.get("positions", []),
        "contact": t.get("contact", ""),
        "comment": t.get("comment", ""),
        "active": t.get("active", 0),
        "photo": t.get("photo") or "",
    }


async def _send_telegram(chat_id: int, text: str, parse_mode: str | None = None, reply_markup: dict | None = None) -> None:
    if not BOT_TOKEN:
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
    except Exception:
        pass


# Background auto-notifications (mirror handlers/notifications.py; buttons handled by the bot).
async def _notify_teams_new_player(agent_tg_id: int, agent_name: str, position: str, league: str) -> None:
    teams = await get_active_teams_for_notification(DB_PATH, position=position, league=league)
    kb = {"inline_keyboard": [[{"text": "👀 Показать карточку", "callback_data": f"notif_agent:{agent_tg_id}"}]]}
    for team in teams:
        if team["tg_id"] == agent_tg_id:
            continue
        await _send_telegram(
            team["tg_id"], f"🔍 Появился новый свободный агент!\n\n*{agent_name}* — {position}",
            parse_mode="Markdown", reply_markup=kb,
        )
        await asyncio.sleep(0.05)


async def _notify_players_new_team(team_tg_id: int, team_name: str, league: str, positions: list) -> None:
    agents = await get_active_agents_for_notification(DB_PATH, league=league)
    pos_str = ", ".join(positions) if positions else "любая"
    kb = {"inline_keyboard": [[{"text": "👀 Показать карточку", "callback_data": f"notif_team:{team_tg_id}"}]]}
    for agent in agents:
        if agent["tg_id"] == team_tg_id:
            continue
        await _send_telegram(
            agent["tg_id"], f"🏟 Появилась новая команда!\n\n*{team_name}* — {league}\nИщут: {pos_str}",
            parse_mode="Markdown", reply_markup=kb,
        )
        await asyncio.sleep(0.05)


class TeamSaveReq(BaseModel):
    init_data: str
    name: str
    league: str
    districts: list[str] = []
    division: str = ""
    positions: list[str] = []
    contact: str = ""
    comment: str = ""


class ApplyReq(BaseModel):
    init_data: str
    team_tg_id: int


@app.get("/api/teams")
async def api_teams(
    league: str = Query(default=""),
    district: str = Query(default=""),
    position: str = Query(default=""),
):
    districts = [district] if district else []
    positions = [position] if position else []
    teams = await get_teams(DB_PATH, league=league or None, districts=districts, positions=positions)
    return [_team_public(t) for t in teams]


@app.get("/api/team/me")
async def api_team_me(tg_id: int = Query(...)):
    t = await get_team_by_tg_id(DB_PATH, tg_id)
    if not t or not t.get("active"):
        return {"found": False}
    return {"found": True, **_team_public(t)}


@app.post("/api/team/save")
async def team_save(req: TeamSaveReq, background: BackgroundTasks):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    if not req.name.strip():
        return {"ok": False, "error": "Укажи название команды"}
    if not req.league.strip():
        return {"ok": False, "error": "Укажи лигу"}
    positions = [p for p in req.positions if p in POSITIONS]
    if not positions:
        return {"ok": False, "error": "Выбери хотя бы одну нужную позицию"}
    existing = await get_team_by_tg_id(DB_PATH, tg_id)
    was_active = bool(existing and existing.get("active"))
    contact = req.contact.strip() or (f"@{user['username']}" if user.get("username") else str(tg_id))
    await upsert_team(
        DB_PATH, tg_id,
        name=req.name.strip(), league=req.league.strip(),
        districts=req.districts, division=req.division,
        positions=positions, contact=contact, comment=req.comment.strip(),
    )
    t = await get_team_by_tg_id(DB_PATH, tg_id)
    # Notify matching players only on first registration (not on every edit).
    if not was_active:
        background.add_task(
            _notify_players_new_team, tg_id, t["name"], t["league"], t.get("positions", []),
        )
    return {"ok": True, "team": _team_public(t)}


@app.post("/api/team/delete")
async def team_delete(req: InitReq):
    user = verify_init_data(req.init_data)
    await deactivate_team(DB_PATH, user["tg_id"])
    return {"ok": True}


@app.post("/api/team/photo")
async def team_photo(req: PhotoReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    if not await get_team_by_tg_id(DB_PATH, tg_id):
        return {"ok": False, "error": "Сначала зарегистрируй команду"}
    err = _save_square_image(req.image, os.path.join(PHOTOS_DIR, f"team_{tg_id}.jpg"))
    if err:
        return {"ok": False, "error": err}
    await save_team_photo(DB_PATH, tg_id, f"/photos/team_{tg_id}.jpg?t={int(time.time())}")
    t = await get_team_by_tg_id(DB_PATH, tg_id)
    return {"ok": True, "team": _team_public(t)}


@app.post("/api/team/apply")
async def team_apply(req: ApplyReq):
    user = verify_init_data(req.init_data)
    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Игрок"
    uname = f"@{user['username']}" if user.get("username") else f"tg_id: {user['tg_id']}"
    await _send_telegram(
        req.team_tg_id,
        f"⚽ Новая заявка на вступление!\n\n👤 {name}\n📱 {uname}\n\n"
        f"Напиши игроку напрямую чтобы договориться.",
    )
    return {"ok": True}


# ── Favorites (Phase 3) ───────────────────────────────────────────────────────

class FavReq(BaseModel):
    init_data: str
    target_tg_id: int


@app.post("/api/fav/toggle")
async def fav_toggle(req: FavReq):
    user = verify_init_data(req.init_data)
    viewer = user["tg_id"]
    if await is_favorite(DB_PATH, viewer, "agent", req.target_tg_id):
        await remove_favorite(DB_PATH, viewer, "agent", req.target_tg_id)
        return {"ok": True, "fav": False}
    await add_favorite(DB_PATH, viewer, "agent", req.target_tg_id)
    return {"ok": True, "fav": True}


@app.get("/api/favorites")
async def api_favorites(tg_id: int = Query(...)):
    favs = await get_favorites(DB_PATH, tg_id, "agent")
    out = []
    for f in favs:
        a = await get_agent_by_tg_id(DB_PATH, f["target_tg_id"])
        if a:
            out.append(_parse_profile(a))
    return out


# Backward-compat alias for the old Mini App profile toggle.
@app.post("/api/agent/toggle-free")
async def toggle_free(tg_id: int = Query(...), active: int = Query(...)):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE free_agents SET active=? WHERE tg_id=?", (active, tg_id))
        await conn.commit()
    return {"ok": True}
