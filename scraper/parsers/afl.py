"""Parser for afl.ru player pages.

afl.ru is a client-only SPA with no server-rendered data, so scraping its HTML
yields nothing. The data comes from the footballista REST API (afl.ru is part of
footballista): GET /api/players/<id> for the profile and /api/players/<id>/stats
for career totals + team history. We read those JSON endpoints directly.
"""
import asyncio
import json
import re
from datetime import date, datetime

import httpx

from scraper.models import PlayerProfile
from scraper.http import fetch_html

_AFL_API = "https://footballista.ru/api/players/{pid}"

# afl.ru position codes → the bot's four categories.
_POSITION_MAP = {
    "GK": "Вратарь",
    "CB": "Защитник", "LB": "Защитник", "RB": "Защитник",
    "LWB": "Защитник", "RWB": "Защитник", "SW": "Защитник", "DF": "Защитник",
    "DM": "Полузащитник", "CM": "Полузащитник", "AM": "Полузащитник",
    "LM": "Полузащитник", "RM": "Полузащитник", "MF": "Полузащитник",
    "LW": "Нападающий", "RW": "Нападающий", "ST": "Нападающий",
    "CF": "Нападающий", "SS": "Нападающий", "FW": "Нападающий",
}


def _afl_id(url: str) -> str | None:
    """Player id = the trailing number of the slug (.../zverev-ivan-711043)."""
    m = re.search(r"-(\d+)(?:[/?#]|$)", url)
    return m.group(1) if m else None


def _map_position(code: str) -> str:
    return _POSITION_MAP.get((code or "").strip().upper(), "—")


def _afl_age(iso: str) -> tuple[str, int]:
    """('25.12.2001', age) from '2001-12-25T...'; ('—', 0) if unparseable."""
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "—", 0
    today = date.today()
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return d.strftime("%d.%m.%Y"), age


def _build_afl_profile(profile: dict, stats: dict, url: str) -> PlayerProfile:
    name = " ".join(
        x.strip() for x in (profile.get("lastName"), profile.get("firstName"), profile.get("middleName"))
        if x and x.strip()
    ) or "Неизвестно"

    birthdate, age = _afl_age(profile.get("birthdayDate"))
    position = _map_position(profile.get("position"))

    teams = (stats or {}).get("teams") or []
    # Current club = an active registration (till is null), the most recently joined.
    active = [t for t in teams if not t.get("till")]
    current = max(active or teams, key=lambda t: t.get("from") or "", default=None)
    current_club = ((current or {}).get("team") or {}).get("name", "").strip() if current else ""
    is_free_agent = not current_club

    # Career clubs: most recent first, current pinned to the front.
    career_clubs: list[str] = []
    for t in sorted(teams, key=lambda t: t.get("from") or "", reverse=True):
        nm = ((t.get("team") or {}).get("name") or "").strip()
        if nm and nm not in career_clubs:
            career_clubs.append(nm)
    if current_club and current_club in career_clubs:
        career_clubs.remove(current_club)
        career_clubs.insert(0, current_club)

    years = [int((t.get("from") or "")[:4]) for t in teams if (t.get("from") or "")[:4].isdigit()]
    debut_year = min(years) if years else date.today().year

    return PlayerProfile(
        name=name, position=position, birthdate=birthdate, age=age,
        current_club=current_club or "Свободный агент", club_id=0,
        career_clubs=career_clubs,
        goals=int((stats or {}).get("goals") or 0),
        matches=int((stats or {}).get("played") or 0),
        assists=int((stats or {}).get("assists") or 0),
        # afl.ru's stats summary has no card totals.
        yellow_cards=0, red_cards=0,
        debut_year=debut_year, lfl_url=url, is_free_agent=is_free_agent,
    )


async def parse_afl_player(url: str) -> PlayerProfile:
    pid = _afl_id(url)
    if not pid:
        raise ValueError("AFL: не удалось определить id игрока в ссылке")
    base = _AFL_API.format(pid=pid)
    try:
        profile_raw, stats_raw = await asyncio.gather(
            fetch_html(base, timeout=20.0),
            fetch_html(base + "/stats", timeout=20.0),
            return_exceptions=True,
        )
        if isinstance(profile_raw, Exception):
            raise profile_raw
        profile = json.loads(profile_raw)
        stats = json.loads(stats_raw) if isinstance(stats_raw, str) else {}
        return _build_afl_profile(profile, stats, url)
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль AFL: {type(exc).__name__}") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Ошибка парсера AFL: {type(exc).__name__}: {exc}") from exc
