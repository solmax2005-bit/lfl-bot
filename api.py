from dotenv import load_dotenv
load_dotenv()

import os
import json
import hmac
import hashlib
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import aiosqlite

from scraper.parsers.registry import detect_and_parse
from database.queries import (
    upsert_agent, get_agent_by_tg_id, deactivate_agent, activate_agent,
    update_looking, delete_agent_permanently,
)

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

POSITIONS = {"Нападающий", "Полузащитник", "Защитник", "Вратарь"}
LEAGUES = {"ЛФЛ", "AFL", "Pari Amateur", "F-лига", ""}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    return {"tg_id": int(tg_id), "username": user.get("username") or ""}


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
    return FileResponse("webapp/index.html")


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
async def card_status(req: StatusReq):
    user = verify_init_data(req.init_data)
    tg_id = user["tg_id"]
    existing = await get_agent_by_tg_id(DB_PATH, tg_id)
    if not existing:
        return {"ok": False, "error": "Сначала создай карточку"}
    if req.active is not None:
        if req.active:
            await activate_agent(DB_PATH, tg_id)
        else:
            await deactivate_agent(DB_PATH, tg_id)
    if req.looking is not None:
        await update_looking(DB_PATH, tg_id, 1 if req.looking else 0)
    return await _card_response(tg_id)


@app.post("/api/card/delete")
async def card_delete(req: InitReq):
    user = verify_init_data(req.init_data)
    await delete_agent_permanently(DB_PATH, user["tg_id"])
    return {"ok": True}


# Backward-compat alias for the old Mini App profile toggle.
@app.post("/api/agent/toggle-free")
async def toggle_free(tg_id: int = Query(...), active: int = Query(...)):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE free_agents SET active=? WHERE tg_id=?", (active, tg_id))
        await conn.commit()
    return {"ok": True}
