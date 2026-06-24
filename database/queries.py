import json
import aiosqlite


async def save_help_request(db_path: str, tg_id: int, username: str, full_name: str, text: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO help_requests (tg_id, username, full_name, text) VALUES (?, ?, ?, ?)",
            (tg_id, username or "", full_name or "", text or ""),
        )
        await conn.commit()


async def get_help_requests(db_path: str, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM help_requests ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def log_message(db_path: str, tg_id: int, username: str, full_name: str, text: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO bot_messages (tg_id, username, full_name, text) VALUES (?, ?, ?, ?)",
            (tg_id, username or "", full_name or "", text or ""),
        )
        await conn.commit()


async def get_messages(db_path: str, limit: int = 100) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM bot_messages ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def upsert_agent(
    db_path: str, tg_id: int, name: str, position: str,
    division: str, contact: str, comment: str, lfl_url: str = "",
    experience: str = "", current_team: str = "", age: int = 0,
    profile_json: str = "", active: int = 1,
    looking: int = 0, extra_clubs: str = "",
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            INSERT INTO free_agents
                (tg_id, name, position, division, contact, comment, lfl_url,
                 experience, current_team, age, profile_json, active, looking, extra_clubs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                name=excluded.name, position=excluded.position,
                division=excluded.division, contact=excluded.contact,
                comment=excluded.comment, lfl_url=excluded.lfl_url,
                experience=excluded.experience, current_team=excluded.current_team,
                age=excluded.age, profile_json=excluded.profile_json,
                active=excluded.active, looking=excluded.looking,
                extra_clubs=excluded.extra_clubs, created_at=CURRENT_TIMESTAMP
        """, (tg_id, name, position, division, contact, comment, lfl_url,
              experience, current_team, age, profile_json, active, looking, extra_clubs))
        await conn.commit()


async def get_agents_by_position(db_path: str, position: str | None) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        if position:
            cur = await conn.execute(
                "SELECT * FROM free_agents WHERE active=1 AND position=? ORDER BY created_at DESC",
                (position,),
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM free_agents WHERE active=1 ORDER BY created_at DESC"
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_agents_admin(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT tg_id, name, position, active FROM free_agents ORDER BY active DESC, name ASC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_all_teams_admin(db_path: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT tg_id, name, league, active FROM teams ORDER BY active DESC, name ASC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_agent_permanently(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DELETE FROM free_agents WHERE tg_id=?", (tg_id,))
        await conn.commit()


async def delete_team_permanently(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DELETE FROM teams WHERE tg_id=?", (tg_id,))
        await conn.commit()


async def deactivate_agent(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE free_agents SET active=0 WHERE tg_id=?", (tg_id,))
        await conn.commit()


async def activate_agent(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE free_agents SET active=1 WHERE tg_id=?", (tg_id,))
        await conn.commit()


async def update_looking(db_path: str, tg_id: int, looking: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE free_agents SET looking=? WHERE tg_id=?", (looking, tg_id))
        await conn.commit()


async def get_agent_by_tg_id(db_path: str, tg_id: int) -> dict | None:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM free_agents WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
    return dict(row) if row else None


async def link_profile(db_path: str, tg_id: int, lfl_url: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE free_agents SET lfl_url=? WHERE tg_id=?", (lfl_url, tg_id)
        )
        await conn.commit()


# ── Teams ────────────────────────────────────────────────────────────────────

async def upsert_team(
    db_path: str, tg_id: int, name: str, league: str,
    districts: list[str], division: str,
    positions: list[str], contact: str, comment: str,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            INSERT INTO teams
                (tg_id, name, league, districts, division, positions, contact, comment, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(tg_id) DO UPDATE SET
                name=excluded.name, league=excluded.league,
                districts=excluded.districts, division=excluded.division,
                positions=excluded.positions, contact=excluded.contact,
                comment=excluded.comment, active=1,
                created_at=CURRENT_TIMESTAMP
        """, (tg_id, name, league, json.dumps(districts, ensure_ascii=False),
              division, json.dumps(positions, ensure_ascii=False), contact, comment))
        await conn.commit()


async def get_teams(
    db_path: str,
    league: str | None,
    districts: list[str],
    positions: list[str],
) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM teams WHERE active=1 ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
    results = []
    for row in rows:
        t = dict(row)
        t["districts"] = json.loads(t["districts"])
        t["positions"] = json.loads(t["positions"])
        if league and t["league"] != league:
            continue
        if districts and not any(d in t["districts"] for d in districts):
            continue
        if positions and not any(p in t["positions"] for p in positions):
            continue
        results.append(t)
    return results


async def get_team_by_tg_id(db_path: str, tg_id: int) -> dict | None:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM teams WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
    if not row:
        return None
    t = dict(row)
    t["districts"] = json.loads(t["districts"])
    t["positions"] = json.loads(t["positions"])
    return t


async def deactivate_team(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE teams SET active=0 WHERE tg_id=?", (tg_id,))
        await conn.commit()


# ── Views ─────────────────────────────────────────────────────────────────────

async def increment_views(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE free_agents SET views = views + 1 WHERE tg_id=?", (tg_id,)
        )
        await conn.commit()


# ── Photo ─────────────────────────────────────────────────────────────────────

async def save_photo(db_path: str, tg_id: int, file_id: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE free_agents SET photo_file_id=? WHERE tg_id=?", (file_id, tg_id)
        )
        await conn.commit()


# ── Favorites ─────────────────────────────────────────────────────────────────

async def add_favorite(db_path: str, tg_id: int, target_type: str, target_tg_id: int) -> bool:
    """Returns True if added, False if already exists."""
    async with aiosqlite.connect(db_path) as conn:
        try:
            await conn.execute(
                "INSERT INTO favorites (tg_id, target_type, target_tg_id) VALUES (?,?,?)",
                (tg_id, target_type, target_tg_id),
            )
            await conn.commit()
            return True
        except Exception:
            return False


async def remove_favorite(db_path: str, tg_id: int, target_type: str, target_tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "DELETE FROM favorites WHERE tg_id=? AND target_type=? AND target_tg_id=?",
            (tg_id, target_type, target_tg_id),
        )
        await conn.commit()


async def get_favorites(db_path: str, tg_id: int, target_type: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT target_tg_id FROM favorites WHERE tg_id=? AND target_type=? ORDER BY created_at DESC",
            (tg_id, target_type),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def is_favorite(db_path: str, tg_id: int, target_type: str, target_tg_id: int) -> bool:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM favorites WHERE tg_id=? AND target_type=? AND target_tg_id=?",
            (tg_id, target_type, target_tg_id),
        )
        return await cur.fetchone() is not None


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def get_active_agents_for_notification(db_path: str, league: str) -> list[dict]:
    """Active players whose division matches the league, or lfl.ru players if league is ЛФЛ."""
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT tg_id, name, position, division, lfl_url
            FROM free_agents
            WHERE active=1 AND (
                division = ?
                OR (lfl_url != '' AND ? IN ('ЛФЛ', 'lfl', 'лфл', 'ЛФЛ Москва'))
            )
        """, (league, league))
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_active_teams_for_notification(db_path: str, position: str, league: str) -> list[dict]:
    """Active teams whose positions list includes the player's position and league matches."""
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM teams WHERE active=1")
        rows = await cur.fetchall()
    results = []
    for row in rows:
        t = dict(row)
        t["positions"] = json.loads(t["positions"])
        t["districts"] = json.loads(t["districts"])
        if position and position not in t["positions"]:
            continue
        if league and t["league"] != league:
            continue
        results.append(t)
    return results


async def create_broadcast(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("INSERT INTO broadcasts DEFAULT VALUES")
        broadcast_id = cur.lastrowid
        await conn.commit()
    return broadcast_id


async def save_broadcast_message(db_path: str, broadcast_id: int, chat_id: int, message_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO broadcast_messages (broadcast_id, chat_id, message_id) VALUES (?,?,?)",
            (broadcast_id, chat_id, message_id),
        )
        await conn.commit()


async def get_broadcast_messages(db_path: str, broadcast_id: int) -> list[dict]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT chat_id, message_id FROM broadcast_messages WHERE broadcast_id=?",
            (broadcast_id,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def upsert_user(db_path: str, tg_id: int, username: str, full_name: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            INSERT INTO users (tg_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                last_seen=CURRENT_TIMESTAMP
        """, (tg_id, username or "", full_name or ""))
        await conn.commit()


async def get_all_tg_ids(db_path: str) -> list[int]:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("""
            SELECT tg_id FROM users
            UNION
            SELECT DISTINCT tg_id FROM free_agents
            UNION
            SELECT DISTINCT tg_id FROM bot_messages
        """)
        rows = await cur.fetchall()
    return [r[0] for r in rows]
