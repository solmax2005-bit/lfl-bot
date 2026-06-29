import re
from datetime import date
import httpx
from bs4 import BeautifulSoup
from scraper.models import PlayerProfile
from scraper.http import fetch_html

_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# Maps f-league summary labels (div.stats-info__text) to PlayerProfile fields.
_STAT_LABELS = {
    "Игры": "matches", "Голы": "goals", "Передачи": "assists",
    "ЖК": "yellow_cards", "КК": "red_cards",
}


def _parse_ru_date(raw: str) -> tuple[str, int]:
    """('02.02.1991', age) from '02 февраля 1991'; ('—', 0) if unparseable."""
    m = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", (raw or "").lower())
    if not m:
        return "—", 0
    month = _RU_MONTHS.get(m.group(2))
    if not month:
        return "—", 0
    try:
        born = date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return "—", 0
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return born.strftime("%d.%m.%Y"), age


def _promo_value(soup: BeautifulSoup, modifier: str) -> str:
    """Text of .player-promo__value inside the li with the given --modifier."""
    li = soup.find("li", class_=re.compile(rf"player-promo__item--{modifier}\b"))
    if li:
        value = li.find(class_="player-promo__value")
        if value:
            return value.get_text(" ", strip=True)
    return ""


def _parse_fleague_html(html: str, url: str) -> PlayerProfile:
    soup = BeautifulSoup(html, "html.parser")

    name_el = soup.find(class_="player-promo__name-main") or soup.find(class_="player-promo__name")
    name = name_el.get_text(" ", strip=True) if name_el else "Неизвестно"

    current_club = _promo_value(soup, "club") or "Свободный агент"
    is_free_agent = current_club in ("", "Свободный агент", "—")

    birthdate, age = _parse_ru_date(_promo_value(soup, "birth"))

    # Summary stats block (div.stats-info__text label + div.stats-info__number value).
    stats = {"matches": 0, "goals": 0, "assists": 0, "yellow_cards": 0, "red_cards": 0}
    container = soup.find(class_=re.compile(r"stats-info--player\b"))
    if container:
        for item in container.find_all(class_="stats-info__item"):
            label = item.find(class_="stats-info__text")
            number = item.find(class_="stats-info__number")
            field = _STAT_LABELS.get(label.get_text(strip=True)) if label else None
            if field and number:
                value = number.get_text(strip=True)
                stats[field] = int(value) if value.lstrip("-").isdigit() else 0

    career_clubs = [current_club] if not is_free_agent else []

    return PlayerProfile(
        name=name, position="—", birthdate=birthdate, age=age,
        current_club=current_club, club_id=0, career_clubs=career_clubs,
        goals=stats["goals"], matches=stats["matches"], assists=stats["assists"],
        yellow_cards=stats["yellow_cards"], red_cards=stats["red_cards"],
        debut_year=date.today().year, lfl_url=url, is_free_agent=is_free_agent,
    )


async def parse_fleague_player(url: str) -> PlayerProfile:
    try:
        html = await fetch_html(url, timeout=20.0)
        return _parse_fleague_html(html, url)
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль F-лиги: {type(exc).__name__}") from exc
