import asyncio

from database.db import init_db
from database.queries import upsert_agent, get_agent_by_tg_id
from maintenance import sweep_restricted_agents


def test_sweep_deactivates_only_active_steel(tmp_path):
    db = str(tmp_path / "t.db")

    async def scenario():
        await init_db(db)
        # активный игрок СТИЛ → должен быть снят с доски
        await upsert_agent(db, 1, name="Стилов", position="Защитник", division="ЛФЛ",
                           contact="@a", comment="", current_team="СТИЛ", active=1)
        # активный обычный игрок → остаётся
        await upsert_agent(db, 2, name="Динамов", position="Нападающий", division="ЛФЛ",
                           contact="@b", comment="", current_team="Динамо", active=1)
        # неактивный игрок СТИЛ → не попадает в выборку (уже 0)
        await upsert_agent(db, 3, name="Запасной", position="Вратарь", division="ЛФЛ",
                           contact="@c", comment="", current_team="СТИЛ", active=0)

        swept = await sweep_restricted_agents(db)
        assert {a["tg_id"] for a in swept} == {1}
        assert (await get_agent_by_tg_id(db, 1))["active"] == 0
        assert (await get_agent_by_tg_id(db, 2))["active"] == 1
        assert (await get_agent_by_tg_id(db, 3))["active"] == 0

        # идемпотентность: повторный запуск никого не снимает
        swept_again = await sweep_restricted_agents(db)
        assert swept_again == []

    asyncio.run(scenario())
