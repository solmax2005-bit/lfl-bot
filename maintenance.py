"""Одноразовое обслуживание: убрать игроков ограниченных команд с доски агентов.

Запуск на сервере:  DB_PATH=/opt/lfl-bot/lfl_bot.db py maintenance.py
(или просто `py maintenance.py`, если DB_PATH в .env/окружении.)
"""
import asyncio
import os

from database.queries import get_agents_by_position, deactivate_agent
from restrictions import is_restricted_team


async def sweep_restricted_agents(db_path: str) -> list[dict]:
    """Снять с доски всех активных агентов из ограниченных команд (active→0).

    Возвращает список снятых карточек. Карточки не удаляются. Идемпотентно:
    выбираются только активные (active=1), поэтому повторный запуск вернёт [].
    """
    active_agents = await get_agents_by_position(db_path, None)
    swept = []
    for agent in active_agents:
        if is_restricted_team(agent.get("current_team")):
            await deactivate_agent(db_path, agent["tg_id"])
            swept.append(agent)
    return swept


async def _main() -> None:
    db_path = os.getenv("DB_PATH", "lfl_bot.db")
    swept = await sweep_restricted_agents(db_path)
    print(f"Снято с доски агентов: {len(swept)}")
    for a in swept:
        print(f"  - {a.get('name', '?')} (tg_id={a.get('tg_id')}, команда={a.get('current_team')})")


if __name__ == "__main__":
    asyncio.run(_main())
