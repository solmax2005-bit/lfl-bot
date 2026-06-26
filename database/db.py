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
        # Migrations for new columns (SQLite has no IF NOT EXISTS on ALTER)
        for col_sql in [
            "ALTER TABLE free_agents ADD COLUMN experience TEXT DEFAULT ''",
            "ALTER TABLE free_agents ADD COLUMN current_team TEXT DEFAULT ''",
            "ALTER TABLE free_agents ADD COLUMN age INTEGER DEFAULT 0",
            "ALTER TABLE free_agents ADD COLUMN profile_json TEXT DEFAULT ''",
            "ALTER TABLE free_agents ADD COLUMN looking INTEGER DEFAULT 0",
            "ALTER TABLE free_agents ADD COLUMN extra_clubs TEXT DEFAULT ''",
            "ALTER TABLE free_agents ADD COLUMN views INTEGER DEFAULT 0",
            "ALTER TABLE free_agents ADD COLUMN photo_file_id TEXT DEFAULT ''",
            "ALTER TABLE free_agents ADD COLUMN photo TEXT DEFAULT ''",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass  # column already exists

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                name TEXT,
                league TEXT,
                districts TEXT DEFAULT '[]',
                division TEXT DEFAULT '',
                positions TEXT DEFAULT '[]',
                contact TEXT,
                comment TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                target_type TEXT,
                target_tg_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tg_id, target_type, target_tg_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                text TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER,
                chat_id INTEGER,
                message_id INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                text TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()
