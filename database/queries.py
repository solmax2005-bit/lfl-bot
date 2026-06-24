import json
import aiosqlite


async def upsert_agent(
    db_path: str, tg_id: int, name: str, position: str,
    division: str, contact: str, comment: str, lfl_url: str = "",
    experience: str = "", current_team: str = "", age: int = 0,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            INSERT INTO free_agents
                (tg_id, name, position, division, contact, comment, lfl_url,
                 experience, current_team, age, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(tg_id) DO UPDATE SET
                name=excluded.name, position=excluded.position,
                division=excluded.division, contact=excluded.contact,
                comment=excluded.comment, lfl_url=excluded.lfl_url,
                experience=excluded.experience, current_team=excluded.current_team,
                age=excluded.age, active=1, created_at=CURRENT_TIMESTAMP
        """, (tg_id, name, position, division, contact, comment, lfl_url,
              experience, current_team, age))
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


async def deactivate_agent(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("UPDATE free_agents SET active=0 WHERE tg_id=?", (tg_id,))
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
