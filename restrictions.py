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
