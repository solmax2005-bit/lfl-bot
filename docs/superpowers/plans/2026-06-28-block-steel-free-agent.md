# Блокировка свободного агентства для игроков СТИЛ — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игроки команды СТИЛ не могут стать свободными агентами — попытка блокируется с ошибкой, администратору приходит уведомление с ФИО.

**Architecture:** Правило «ограниченных команд» выносится в новый изолированный модуль `restrictions.py`. Две точки контроля — основной путь Mini App (`api.py` → `/api/card/status`) и legacy-путь бота (`handlers/card.py` → `become_agent_callback`) — импортируют общий хелпер `is_restricted_team` и общий текст ошибки. При срабатывании активация не выполняется, в фоне шлётся уведомление администратору.

**Tech Stack:** Python (сервер 3.12, локально 3.14), FastAPI + Starlette TestClient, python-telegram-bot 22.8, pytest / pytest-asyncio, aiosqlite/SQLite.

## Global Constraints

- Текст ошибки игроку — дословно: `Невозможно стать свободным агентом, так как вы являетесь игроком команды СТИЛ.`
- Уведомление администратору — **plain-text, без Markdown** (спецсимволы в имени не должны ломать отправку).
- Определение игрока СТИЛ — по полю `current_team` карточки, без учёта регистра, по целому слову `стил`.
- `ADMIN_TG_ID` берётся из env (на сервере `= 1380368896`); если не задан — уведомление просто не шлётся.
- Новых колонок БД нет — миграции не требуются.
- После изменений кода — `git add` + `commit` + `push origin master` (правило проекта).

---

### Task 1: Модуль правил `restrictions.py`

**Files:**
- Create: `restrictions.py`
- Test: `tests/test_restrictions.py`

**Interfaces:**
- Produces:
  - `RESTRICTED_FREE_AGENT_MSG: str` — текст ошибки игроку.
  - `RESTRICTED_TEAMS: set[str]` — нормализованные названия ограниченных команд.
  - `is_restricted_team(name: str | None) -> bool` — True, если игрок с такой текущей командой не может стать агентом.

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_restrictions.py`:

```python
import pytest

from restrictions import is_restricted_team, RESTRICTED_FREE_AGENT_MSG


@pytest.mark.parametrize("name", ["СТИЛ", "стил", "Стил", "ФК Стил", "  стил  ", "стил москва"])
def test_restricted_true(name):
    assert is_restricted_team(name) is True


@pytest.mark.parametrize("name", ["Бастилия", "Стиляги", "Динамо", "", None, "стильный"])
def test_restricted_false(name):
    assert is_restricted_team(name) is False


def test_error_message_text():
    assert RESTRICTED_FREE_AGENT_MSG == (
        "Невозможно стать свободным агентом, так как вы являетесь игроком команды СТИЛ."
    )
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `py -m pytest tests/test_restrictions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'restrictions'`

- [ ] **Step 3: Реализовать модуль**

Create `restrictions.py`:

```python
"""Правила ограничения: игроки каких команд не могут стать свободными агентами."""
import re

# Текст ошибки, который видит игрок при попытке стать агентом.
RESTRICTED_FREE_AGENT_MSG = (
    "Невозможно стать свободным агентом, так как вы являетесь игроком команды СТИЛ."
)

# Нормализованные (casefold) названия команд, чьи игроки не могут стать агентами.
# Чтобы добавить команду в будущем — допиши сюда её название в нижнем регистре.
RESTRICTED_TEAMS = {"стил"}


def _normalize(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def is_restricted_team(name: str | None) -> bool:
    """True, если игрок с текущей командой `name` не может стать свободным агентом.

    Совпадение без учёта регистра: вся нормализованная строка в RESTRICTED_TEAMS
    ИЛИ одно из слов (через пробел) в RESTRICTED_TEAMS. Целые слова, поэтому
    'Бастилия'/'Стиляги' не ловятся.
    """
    norm = _normalize(name)
    if not norm:
        return False
    if norm in RESTRICTED_TEAMS:
        return True
    return any(word in RESTRICTED_TEAMS for word in norm.split(" "))
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `py -m pytest tests/test_restrictions.py -v`
Expected: PASS (все параметры)

- [ ] **Step 5: Коммит**

```bash
git add restrictions.py tests/test_restrictions.py
git commit -m "feat: restrictions module — block СТИЛ players from free agency"
```

---

### Task 2: Контроль в Mini App (`api.py` → `/api/card/status`)

**Files:**
- Modify: `api.py` (env `ADMIN_TG_ID`; импорт из `restrictions`; хелпер `_notify_admin_restricted`; гард в `card_status`)
- Test: `tests/test_card_api.py`

**Interfaces:**
- Consumes: `is_restricted_team`, `RESTRICTED_FREE_AGENT_MSG` (Task 1); существующие `_send_telegram`, `get_agent_by_tg_id`, `activate_agent`, `_notify_teams_new_player`.
- Produces: `_notify_admin_restricted(name: str, username: str | None, tg_id: int, lfl_url: str = "") -> None` (awaitable; вызывается как фоновая задача).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_card_api.py`:

```python
def test_status_steel_player_blocked(monkeypatch):
    notified = {}
    teams = {"n": 0}

    async def fake_admin(name, username, tg_id, lfl_url=""):
        notified["args"] = (name, username, tg_id, lfl_url)

    async def fake_teams(*a):
        teams["n"] += 1

    monkeypatch.setattr(api, "_notify_admin_restricted", fake_admin)
    monkeypatch.setattr(api, "_notify_teams_new_player", fake_teams)
    raw = make_init_data({"id": 500, "username": "steelguy"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "Семён Стилов", "position": "Защитник",
        "age": 26, "division": "ЛФЛ", "current_team": "СТИЛ",
    })
    r = client.post("/api/card/status", json={"init_data": raw, "active": 1})
    body = r.json()
    assert body["ok"] is False
    assert "СТИЛ" in body["error"]
    # карточка НЕ активирована
    me = client.post("/api/me", json={"init_data": raw}).json()
    assert me["active"] == 0
    # командам НЕ уведомили, администратору — уведомили
    assert teams["n"] == 0
    assert notified.get("args") is not None
    assert notified["args"][2] == 500


def test_status_non_steel_activates(monkeypatch):
    async def fake_teams(*a):
        pass

    async def fake_admin(*a, **k):
        raise AssertionError("admin must NOT be notified for a normal player")

    monkeypatch.setattr(api, "_notify_teams_new_player", fake_teams)
    monkeypatch.setattr(api, "_notify_admin_restricted", fake_admin)
    raw = make_init_data({"id": 501, "username": "normal"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "Обычный", "position": "Нападающий",
        "age": 24, "division": "ЛФЛ", "current_team": "Динамо",
    })
    r = client.post("/api/card/status", json={"init_data": raw, "active": 1})
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["active"] == 1
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `py -m pytest tests/test_card_api.py::test_status_steel_player_blocked tests/test_card_api.py::test_status_non_steel_activates -v`
Expected: FAIL — `test_status_steel_player_blocked` падает (`AttributeError: ... _notify_admin_restricted` при monkeypatch, либо `ok` is True), `test_status_non_steel_activates` тоже падает на отсутствии `_notify_admin_restricted`.

- [ ] **Step 3: Добавить env `ADMIN_TG_ID` и импорт из restrictions**

В `api.py` после строки `BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")` (≈ строка 38) добавить:

```python
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "0") or 0)
```

В блок импортов `api.py` (рядом с `from database.queries import ...`) добавить:

```python
from restrictions import is_restricted_team, RESTRICTED_FREE_AGENT_MSG
```

- [ ] **Step 4: Добавить хелпер уведомления администратора**

В `api.py` рядом с `_notify_teams_new_player` (≈ строка 483) добавить:

```python
async def _notify_admin_restricted(name: str, username: str | None, tg_id: int, lfl_url: str = "") -> None:
    """Сообщить администратору, что игрок СТИЛ пытался стать свободным агентом."""
    if not ADMIN_TG_ID:
        return
    contact = f"@{username}" if username else f"tg_id: {tg_id}"
    lines = [
        "🚫 Игрок СТИЛ пытался стать свободным агентом",
        "",
        f"👤 {name or '—'}",
        f"📱 {contact}",
    ]
    if lfl_url:
        lines.append(f"🔗 {lfl_url}")
    await _send_telegram(ADMIN_TG_ID, "\n".join(lines))
```

- [ ] **Step 5: Добавить гард в `card_status`**

В `api.py`, в обработчике `card_status`, сразу после строки `was_active = existing.get("active", 0)` вставить:

```python
    # Игроки ограниченных команд (СТИЛ) не могут попасть на доску свободных агентов.
    if req.active == 1 and not was_active and is_restricted_team(existing.get("current_team")):
        background.add_task(
            _notify_admin_restricted,
            existing.get("name", ""), user.get("username"), tg_id,
            existing.get("lfl_url", ""),
        )
        return {"ok": False, "error": RESTRICTED_FREE_AGENT_MSG}
```

(Гард стоит ДО блоков `if req.active is not None:` и уведомления команд — при срабатывании активация и уведомление командам не выполняются.)

- [ ] **Step 6: Запустить новые тесты — убедиться, что проходят**

Run: `py -m pytest tests/test_card_api.py::test_status_steel_player_blocked tests/test_card_api.py::test_status_non_steel_activates -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Прогнать весь api-сьют — нет регрессов**

Run: `py -m pytest tests/test_card_api.py -v`
Expected: все ранее зелёные тесты по-прежнему PASS, +2 новых PASS.

- [ ] **Step 8: Коммит**

```bash
git add api.py tests/test_card_api.py
git commit -m "feat: block СТИЛ players from free agency in Mini App API + notify admin"
```

---

### Task 3: Контроль в боте (legacy `handlers/card.py` → `become_agent_callback`)

**Files:**
- Modify: `handlers/card.py` (импорт из `restrictions`; хелпер `_notify_admin_steel_attempt`; гарды в обеих ветках `become_agent_callback`)

**Interfaces:**
- Consumes: `is_restricted_team`, `RESTRICTED_FREE_AGENT_MSG` (Task 1); существующий `ADMIN_TG_ID` из `handlers.admin`; `get_agent_by_tg_id`, `activate_agent`.

> Примечание: клавиатура бота урезана до `[🆘 Помощь]`, поэтому этот путь — защитный (legacy). Отдельный handler-тест не пишем: набор `tests/test_card_handler.py` уже имеет предсуществующие падения на Python 3.14, а ядро логики (`is_restricted_team`) покрыто юнит-тестами в Task 1 и переиспользуется здесь. Проверка — прогон существующего сьюта (нет регресса импорта) + ручной смоук в Task 4.

- [ ] **Step 1: Добавить импорт из restrictions**

В начало `handlers/card.py` (рядом с прочими импортами проекта) добавить:

```python
from restrictions import is_restricted_team, RESTRICTED_FREE_AGENT_MSG
```

- [ ] **Step 2: Добавить хелпер уведомления администратора**

В `handlers/card.py` (на уровне модуля, рядом с `become_agent_callback`) добавить:

```python
async def _notify_admin_steel_attempt(context, name, user, lfl_url=""):
    """Сообщить администратору, что игрок СТИЛ пытался стать свободным агентом."""
    from handlers.admin import ADMIN_TG_ID
    if not ADMIN_TG_ID:
        return
    contact = f"@{user.username}" if user.username else f"tg_id: {user.id}"
    lines = [
        "🚫 Игрок СТИЛ пытался стать свободным агентом",
        "",
        f"👤 {name or '—'}",
        f"📱 {contact}",
    ]
    if lfl_url:
        lines.append(f"🔗 {lfl_url}")
    try:
        await context.bot.send_message(ADMIN_TG_ID, "\n".join(lines))
    except Exception:
        pass
```

- [ ] **Step 3: Гард в ветке свежего импорта**

В `become_agent_callback`, внутри `if profile:`, ПЕРВОЙ строкой блока (до `contact = ...` / `upsert_agent`) вставить:

```python
        if not profile.is_free_agent and is_restricted_team(profile.current_club):
            await query.answer(RESTRICTED_FREE_AGENT_MSG, show_alert=True)
            await _notify_admin_steel_attempt(
                context, profile.name, update.effective_user, profile.lfl_url,
            )
            return
```

- [ ] **Step 4: Гард в ветке активации существующей карточки**

В ветке `else:`, сразу после блока `if not agent: ... return` (до `await activate_agent(...)`) вставить:

```python
        if is_restricted_team(agent.get("current_team")):
            await query.answer(RESTRICTED_FREE_AGENT_MSG, show_alert=True)
            await _notify_admin_steel_attempt(
                context, agent.get("name", ""), update.effective_user, agent.get("lfl_url", ""),
            )
            return
```

(`query.answer(..., show_alert=True)` повторяет существующий паттерн ветки «Профиль не найден» строкой выше — стиль кодовой базы сохранён.)

- [ ] **Step 5: Проверить, что модуль импортируется и сьют не сломан**

Run: `py -c "import handlers.card"`
Expected: без ошибок (импорт `restrictions` валиден).

Run: `py -m pytest tests/test_card_api.py tests/test_restrictions.py -v`
Expected: всё PASS (регресса нет).

- [ ] **Step 6: Коммит**

```bash
git add handlers/card.py
git commit -m "feat: block СТИЛ players from free agency in bot become_agent flow + notify admin"
```

---

### Task 4: Пуш и деплой на сервер

**Files:** —

> Деплой выполняется на сервере в Амстердаме через **веб-консоль Timeweb** (root). SSH из этой сессии нет — серверные команды выполняет пользователь. Пуш в GitHub делаю я.

- [ ] **Step 1: Финальный прогон затронутых тестов локально**

Run: `py -m pytest tests/test_restrictions.py tests/test_card_api.py -v`
Expected: всё PASS (включая 2 новых из Task 2 и юнит-тесты из Task 1).

- [ ] **Step 2: Запушить в origin/master**

```bash
git push origin master
```

- [ ] **Step 3: Деплой на сервере (команды для пользователя в веб-консоли Timeweb)**

```bash
cd /opt/lfl-bot && git pull
systemctl restart lfl-api lfl-bot
systemctl is-active lfl-api lfl-bot      # ожидается: active / active
```

(Перезапускаем оба сервиса: правится и `api.py`, и `handlers/card.py`. Новых колонок БД нет — миграции не нужны.)

- [ ] **Step 4: Смоук-тест в Telegram**

1. Открыть Mini App у тестовой карточки, где `current_team = СТИЛ` (импорт профиля игрока СТИЛ с lfl.ru).
2. Нажать «Заявить себя свободным агентом» / «Добавить в поиск агентов».
3. Ожидается: всплывает ошибка «Невозможно стать свободным агентом, так как вы являетесь игроком команды СТИЛ.»; карточка НЕ появляется на доске агентов.
4. Администратору (1380368896) приходит уведомление «🚫 Игрок СТИЛ пытался стать свободным агентом» с ФИО игрока.
5. Контроль: обычный игрок (не СТИЛ) активируется как раньше.

---

## Зависимости задач

- Task 1 → Task 2 (api.py импортирует `is_restricted_team`, `RESTRICTED_FREE_AGENT_MSG`)
- Task 1 → Task 3 (handlers/card.py импортирует те же)
- Task 2, Task 3 → Task 4 (деплой)
