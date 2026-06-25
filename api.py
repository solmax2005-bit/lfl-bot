from dotenv import load_dotenv
load_dotenv()

import os
import json
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "lfl_bot.db")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
        "contact": data.get("contact") or "",
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


@app.post("/api/agent/toggle-free")
async def toggle_free(tg_id: int = Query(...), active: int = Query(...)):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE free_agents SET active=? WHERE tg_id=?", (active, tg_id))
        await conn.commit()
    return {"ok": True}
