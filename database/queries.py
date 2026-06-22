import aiosqlite


async def upsert_agent(
    db_path: str, tg_id: int, name: str, position: str,
    division: str, contact: str, comment: str, lfl_url: str,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            INSERT INTO free_agents (tg_id, name, position, division, contact, comment, lfl_url, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(tg_id) DO UPDATE SET
                name=excluded.name, position=excluded.position,
                division=excluded.division, contact=excluded.contact,
                comment=excluded.comment, lfl_url=excluded.lfl_url,
                active=1, created_at=CURRENT_TIMESTAMP
        """, (tg_id, name, position, division, contact, comment, lfl_url))
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
