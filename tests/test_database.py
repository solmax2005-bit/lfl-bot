import pytest
import tempfile
import os
import aiosqlite
from database.db import init_db
from database.queries import (
    upsert_agent, get_agents_by_position, deactivate_agent,
    get_agent_by_tg_id, link_profile,
    upsert_team, get_teams, get_team_by_tg_id, deactivate_team,
    prune_old_messages,
)


def make_db_path():
    """Return a unique temp file path for an in-memory-style isolated test DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.mark.asyncio
async def test_init_db_creates_table():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='free_agents'")
        row = await cur.fetchone()
    os.unlink(DB_PATH)
    assert row is not None


@pytest.mark.asyncio
async def test_upsert_and_get_agent():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_agent(DB_PATH, 1001, "Иванов", "Нападающий", "Премьер", "@ivan", "быстрый", "")
    agents = await get_agents_by_position(DB_PATH, "Нападающий")
    os.unlink(DB_PATH)
    assert len(agents) == 1
    assert agents[0]["name"] == "Иванов"
    assert agents[0]["tg_id"] == 1001


@pytest.mark.asyncio
async def test_upsert_updates_existing():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_agent(DB_PATH, 1002, "Петров", "Вратарь", "Любой", "@petr", "", "")
    await upsert_agent(DB_PATH, 1002, "Петров П.", "Вратарь", "1-я лига", "@petr2", "", "")
    agents = await get_agents_by_position(DB_PATH, "Вратарь")
    os.unlink(DB_PATH)
    matching = [a for a in agents if a["tg_id"] == 1002]
    assert len(matching) == 1
    assert matching[0]["name"] == "Петров П."


@pytest.mark.asyncio
async def test_get_all_agents_when_position_none():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_agent(DB_PATH, 2001, "A", "Нападающий", "Любой", "@a", "", "")
    await upsert_agent(DB_PATH, 2002, "B", "Защитник", "Любой", "@b", "", "")
    all_agents = await get_agents_by_position(DB_PATH, None)
    os.unlink(DB_PATH)
    ids = [a["tg_id"] for a in all_agents]
    assert 2001 in ids and 2002 in ids


@pytest.mark.asyncio
async def test_deactivate_agent():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_agent(DB_PATH, 3001, "X", "Полузащитник", "Любой", "@x", "", "")
    await deactivate_agent(DB_PATH, 3001)
    agents = await get_agents_by_position(DB_PATH, None)
    os.unlink(DB_PATH)
    ids = [a["tg_id"] for a in agents]
    assert 3001 not in ids


@pytest.mark.asyncio
async def test_link_profile():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_agent(DB_PATH, 4001, "Y", "Защитник", "Любой", "@y", "", "")
    await link_profile(DB_PATH, 4001, "https://ug.lfl.ru/player999")
    agent = await get_agent_by_tg_id(DB_PATH, 4001)
    os.unlink(DB_PATH)
    assert agent["lfl_url"] == "https://ug.lfl.ru/player999"


@pytest.mark.asyncio
async def test_free_agents_has_experience_column():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("PRAGMA table_info(free_agents)")
        cols = [row[1] for row in await cur.fetchall()]
    os.unlink(DB_PATH)
    assert "experience" in cols
    assert "current_team" in cols
    assert "age" in cols


@pytest.mark.asyncio
async def test_teams_table_created():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='teams'"
        )
        row = await cur.fetchone()
    os.unlink(DB_PATH)
    assert row is not None


@pytest.mark.asyncio
async def test_upsert_and_get_team():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_team(
        DB_PATH, 5001, "ФК Алматы", "ЛФЛ",
        ["ЮГ", "Юго-восток"], "Первый",
        ["Нападающий", "Полузащитник"], "@coach", "Набор активный",
    )
    teams = await get_teams(DB_PATH, league=None, districts=[], positions=[])
    os.unlink(DB_PATH)
    assert len(teams) == 1
    assert teams[0]["name"] == "ФК Алматы"


@pytest.mark.asyncio
async def test_get_teams_filter_by_league():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_team(DB_PATH, 6001, "ЛФЛ Команда", "ЛФЛ", ["ЮГ"], "Первый", ["Защитник"], "@a", "")
    await upsert_team(DB_PATH, 6002, "AFL Команда", "AFL", [], "", ["Нападающий"], "@b", "")
    lfl_teams = await get_teams(DB_PATH, league="ЛФЛ", districts=[], positions=[])
    os.unlink(DB_PATH)
    assert len(lfl_teams) == 1
    assert lfl_teams[0]["name"] == "ЛФЛ Команда"


@pytest.mark.asyncio
async def test_deactivate_team():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    await upsert_team(DB_PATH, 7001, "Команда X", "AFL", [], "", ["Вратарь"], "@x", "")
    await deactivate_team(DB_PATH, 7001)
    teams = await get_teams(DB_PATH, league=None, districts=[], positions=[])
    os.unlink(DB_PATH)
    assert all(t["tg_id"] != 7001 for t in teams)


@pytest.mark.asyncio
async def test_prune_old_messages():
    DB_PATH = make_db_path()
    await init_db(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO bot_messages (tg_id, text, created_at) VALUES (?, ?, datetime('now', '-40 days'))",
            (1, "old"),
        )
        await conn.execute("INSERT INTO bot_messages (tg_id, text) VALUES (?, ?)", (2, "new"))
        await conn.commit()
    deleted = await prune_old_messages(DB_PATH, 30)
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT text FROM bot_messages")
        rows = [r[0] for r in await cur.fetchall()]
    os.unlink(DB_PATH)
    assert deleted == 1
    assert rows == ["new"]
