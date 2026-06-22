import aiosqlite


async def init_db(db_path: str = "lfl_bot.db") -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS free_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                name TEXT,
                position TEXT,
                division TEXT,
                contact TEXT,
                comment TEXT,
                lfl_url TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()
