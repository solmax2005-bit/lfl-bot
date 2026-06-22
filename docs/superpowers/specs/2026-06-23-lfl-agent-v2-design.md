# ЛФЛ Агент v2 — Design Spec

**Date:** 2026-06-23  
**Status:** Approved

---

## Goal

Расширить бота тремя новыми подсистемами:
1. Гибкое создание карточки игрока (мультилиговый парсинг + ручной ввод)
2. Регистрация команды и поиск игроков командами
3. Поиск команд игроками

---

## Architecture

Подход: расширение существующей структуры + реестр парсеров. Новый код добавляется в новые файлы, существующие хендлеры изменяются минимально.

### Новые / изменённые файлы

```
scraper/
  parsers/
    __init__.py
    registry.py       # detect_parser(url) → callable | None
    lfl.py            # lfl.ru/person{ID}?player_id={ID}
    afl.py            # afl.ru/players/{slug}-{ID}
    fleague.py        # f-league.ru/player/{ID}

handlers/
  card.py             # + manual_card_conv (ConversationHandler ручного создания)
                      # + mycard показывает кнопку редактирования
  teams.py            # NEW: register_team_conv, my_team, find_teams_handler,
                      #      find_teams_callback, delete_team_handler
  search.py           # обновить: карточки игроков с кнопками контакта

card_generator/
  generator.py        # + draw_team_card(team: dict) -> bytes
                      # адаптировать draw_card() для ручных профилей (нет цифр)

database/
  db.py               # + CREATE TABLE teams
  queries.py          # + upsert_team, get_teams, get_team_by_tg_id, deactivate_team

bot.py                # зарегистрировать новые хендлеры
```

---

## Feature 1: Парсеры игроков

### Реестр парсеров (`scraper/parsers/registry.py`)

```python
async def detect_and_parse(url: str) -> PlayerProfile | None:
    """Определяет лигу по URL, вызывает нужный парсер.
    Возвращает None если URL не распознан."""
```

Поддерживаемые форматы:
| Лига | URL-паттерн | Кодировка |
|---|---|---|
| ЛФЛ | `lfl.ru/person{ID}?player_id={ID}` | windows-1251 |
| AFL | `afl.ru/players/{slug}-{ID}` | utf-8 |
| F-лига | `f-league.ru/player/{ID}` | utf-8 |
| Pari Amateur | нет сайта | — ручной ввод |

Все парсеры возвращают `PlayerProfile`. Поля которые не представлены на сайте — `0` для цифр, `[]` для списков.

### Удалить

- Убрать `ug.lfl.ru/playerNNN` из `LFL_URL_RE` в `handlers/card.py`
- Старый `scraper/lfl_parser.py` оставить до прохождения тестов новых парсеров, затем удалить

---

## Feature 2: Карточка игрока (ручной ввод)

### ConversationHandler `manual_card_conv`

Состояния: `MC_NAME=0, MC_POS=1, MC_AGE=2, MC_TEAM=3, MC_LEAGUE=4, MC_EXP=5, MC_COMMENT=6`

| Шаг | Вопрос | Тип ввода |
|---|---|---|
| MC_NAME | Как тебя зовут? | Текст |
| MC_POS | Позиция | Кнопки: Нападающий / Полузащитник / Защитник / Вратарь |
| MC_AGE | Возраст | Число (валидация 10–60) |
| MC_TEAM | Текущая команда | Текст или кнопка "Нет команды" |
| MC_LEAGUE | Лига | Кнопки: ЛФЛ / AFL / Pari Amateur / F-лига |
| MC_EXP | Прошлый опыт | Текст (список команд) или кнопка "Нет опыта" |
| MC_COMMENT | Комментарий | Текст или кнопка "Пропустить" |

Результат: `upsert_agent()` + генерация карточки.

### Адаптация `draw_card()` для ручных профилей

Блок статистики (середина карточки):
- Есть данные с сайта → голы / матчи / передачи / карточки (как сейчас)
- Ручной ввод с опытом → `experience` поле отображается как список прошлых команд (текст)
- Ручной ввод, нет опыта → прочерки во всех 4 блоках

Поле `lfl_url` в `free_agents` = пустая строка для ручных профилей.  
Добавить поле `experience TEXT DEFAULT ''` в таблицу `free_agents`.

### Редактирование `/mycard`

Кнопка "✏️ Редактировать" под своей карточкой:
- Если профиль с URL → предлагает обновить ссылку
- Если ручной → запускает `manual_card_conv` заново (upsert перезапишет)

---

## Feature 3: Команды

### Таблица `teams`

```sql
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    name TEXT,
    league TEXT,
    districts TEXT DEFAULT '[]',  -- JSON list, только ЛФЛ
    division TEXT DEFAULT '',      -- только ЛФЛ
    positions TEXT DEFAULT '[]',   -- JSON list
    contact TEXT,
    comment TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### ConversationHandler `register_team_conv`

Состояния: `RT_NAME=0, RT_LEAGUE=1, RT_DISTRICTS=2, RT_DIVISION=3, RT_POSITIONS=4, RT_CONTACT=5, RT_COMMENT=6`

| Шаг | Вопрос | Тип |
|---|---|---|
| RT_NAME | Название команды | Текст |
| RT_LEAGUE | Лига | Кнопки: ЛФЛ / AFL / Pari Amateur / F-лига |
| RT_DISTRICTS | Округ (только ЛФЛ) | Мультивыбор ✅/☐ + кнопка "Готово" |
| RT_DIVISION | Дивизион (только ЛФЛ) | Кнопки: Высший / Первый / Второй / Третий |
| RT_POSITIONS | Ищем позиции | Мультивыбор ✅/☐ + кнопка "Готово" |
| RT_CONTACT | Контакт | Текст (@username) |
| RT_COMMENT | Комментарий | Текст или "Пропустить" |

Если лига не ЛФЛ — шаги RT_DISTRICTS и RT_DIVISION пропускаются.

### Управление командой `/my_team`

- Показывает PNG карточку команды
- Кнопки под карточкой: "✏️ Редактировать" | "🗑 Удалить объявление"
- Редактирование → `register_team_conv` заново (upsert)
- Удаление → `deactivate_team(db_path, tg_id)` → `active=0`

### Поиск команд (для игроков)

Точка входа: кнопка "⚽ Найти команду" в главном меню.

Фильтры (все опциональны, все мультивыбор):
1. Лига: ЛФЛ / AFL / Pari Amateur / F-лига / кнопка "Все лиги"
2. Если выбрана ЛФЛ → Округ (мультивыбор)
3. Позиция: Нападающий / Полузащитник / Защитник / Вратарь / кнопка "Все позиции"
4. Кнопка "🔍 Показать результаты"

Результат: список команд, каждая — PNG карточка + кнопка "Написать" (t.me/...).

### Карточка команды `draw_team_card(team: dict) -> bytes`

Pillow 600×360, тот же стиль что у игроков:
- **Шапка** (синяя `#1E5C9B`): название команды + лига
- **Середина** (белая): округ + дивизион (если ЛФЛ); список искомых позиций
- **Подвал** (`#F8F9FB`): комментарий + контакт

---

## Обновление главного меню

```python
MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["📇 Карточка игрока",  "🔍 Найти агентов"],
    ["✋ Стать агентом",    "🪪 Моя карточка"],
    ["⚽ Найти команду",    "🏟 Зарегистрировать команду"],
    ["👥 Моя команда"],
], resize_keyboard=True)
```

---

## База данных — изменения

| Таблица | Изменение |
|---|---|
| `free_agents` | Добавить колонку `experience TEXT DEFAULT ''` |
| `teams` | Создать новую таблицу |

Миграция `free_agents` через `ALTER TABLE` при старте (`init_db`).

---

## Команды бота

| Команда | Назначение |
|---|---|
| `/register_team` | Зарегистрировать команду |
| `/my_team` | Моя команда |
| `/find_teams` | Найти команду (для игроков) |
| `/edit_card` | Редактировать свою карточку игрока |

---

## Out of Scope (не делаем сейчас)

- Верификация команд администратором
- Уведомления при совпадении игрок ↔ команда
- История изменений анкет
- Карточки для AFL/F-лиги с реальной статистикой (парсим базовые поля)
