"""Parser for the new Next.js frontend at page.lfl.ru/persons/<id>.

Unlike the classic lfl.ru/person<id> pages (scraped from HTML), page.lfl.ru is a
Next.js app that embeds the full profile — including career stat totals — as JSON
in <script id="__NEXT_DATA__">. We read that JSON; no extra API calls needed.

Career totals live at props.pageProps.person.stats
({matches, goals, assists, fines, ...}); profile basics at person.data (a list of
the player's club/region registrations) and titles (tournament history).
"""
import json
import re
from datetime import date, datetime

import httpx

from scraper.models import PlayerProfile
from scraper.http import fetch_html

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _extract_page_props(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("page.lfl.ru: данных профиля нет на странице")
    return json.loads(m.group(1)).get("props", {}).get("pageProps", {})


def _age_from_birthday(birthday: str) -> tuple[str, int]:
    """('01.09.2001', age) from '2001-09-01'; ('—', 0) if unparseable."""
    try:
        d = datetime.strptime((birthday or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "—", 0
    today = date.today()
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return d.strftime("%d.%m.%Y"), age


def _full_name(rec: dict) -> str:
    parts = [rec.get("family_name"), rec.get("first_name"), rec.get("second_name")]
    name = " ".join(p.strip() for p in parts if p and p.strip())
    return name or "Неизвестно"


def _included_dt(rec: dict) -> datetime:
    try:
        return datetime.strptime((rec.get("included") or "")[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.min


def _build_profile(page_props: dict, url: str) -> PlayerProfile:
    person = page_props.get("person") or {}
    records = [r for r in (person.get("data") or []) if not r.get("archive")]
    if not records:
        raise ValueError("page.lfl.ru: профиль не найден")

    # The player is registered across regions/clubs; treat the most recently
    # joined (`included`) registration as the current one.
    current = max(records, key=_included_dt)
    birthdate, age = _age_from_birthday(current.get("birthday"))
    position = (current.get("amplua_text") or "").strip()
    position = position[:1].upper() + position[1:] if position else "—"
    current_club = (current.get("club_name") or "").strip()

    # Career totals — straight from the page's own stats block.
    stats = person.get("stats") or {}

    # Career clubs: current first, then distinct clubs from tournament history
    # (most recent first) and remaining registrations.
    titles = sorted(
        ((page_props.get("titles") or {}).get("data") or []),
        key=lambda t: (t.get("start_date") or ""), reverse=True,
    )
    career_clubs: list[str] = []
    for club in ([current_club]
                 + [t.get("club_name") or "" for t in titles]
                 + [r.get("club_name") or "" for r in records]):
        club = club.strip()
        if club and club not in career_clubs:
            career_clubs.append(club)

    years = [int((t.get("start_date") or "")[:4]) for t in titles
             if (t.get("start_date") or "")[:4].isdigit()]
    debut_year = min(years) if years else date.today().year

    return PlayerProfile(
        name=_full_name(current), position=position, birthdate=birthdate, age=age,
        current_club=current_club, club_id=int(current.get("club_id_now") or 0),
        career_clubs=career_clubs,
        goals=int(stats.get("goals") or 0),
        matches=int(stats.get("matches") or 0),
        assists=int(stats.get("assists") or 0),
        # page.lfl.ru reports a single "наказания" total, not a yellow/red split.
        yellow_cards=int(stats.get("fines") or 0), red_cards=0,
        debut_year=debut_year, lfl_url=url, is_free_agent=not current_club,
    )


def _parse_lfl_page_html(html: str, url: str) -> PlayerProfile:
    return _build_profile(_extract_page_props(html), url)


async def parse_lfl_page_player(url: str) -> PlayerProfile:
    try:
        html = await fetch_html(url, timeout=45.0)
        return _parse_lfl_page_html(html, url)
    except httpx.TimeoutException as exc:
        raise ValueError("lfl.ru не отвечает — попробуй позже или создай карточку вручную.") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль ЛФЛ: {type(exc).__name__}") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Ошибка парсера ЛФЛ: {type(exc).__name__}: {exc}") from exc
