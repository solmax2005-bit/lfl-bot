import pytest
import tempfile
import os
import aiosqlite
from database.db import init_db
from database.queries import (
    upsert_agent, get_agents_by_position, deactivate_agent,
    get_agent_by_tg_id, link_profile,
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
