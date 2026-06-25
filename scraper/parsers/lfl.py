import re
from datetime import date
import httpx
from bs4 import BeautifulSoup
from scraper.models import PlayerProfile
from scraper.http import fetch_html


def _extract_age(birthdate_str: str) -> int:
    try:
        day, month, year = birthdate_str.split(".")
        born = date(int(year), int(month), int(day))
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return 0


def _parse_lfl_html(html: str, url: str) -> PlayerProfile:
    soup = BeautifulSoup(html, "html.parser")

    # Name: <p class="player_title_name"><a href="...">Фамилия Имя</a></p>
    name_tag = soup.find("p", class_="player_title_name")
    name = name_tag.get_text(strip=True) if name_tag else "Неизвестно"
    name = re.sub(r"[-/\\|]+$", "", name).strip()  # strip trailing junk like "-///"

    # Age and birthdate: inside <div class="player_title">
    player_title = soup.find("div", class_="player_title")
    pt_text = player_title.get_text(" ", strip=True) if player_title else ""

    age_m = re.search(r"Возраст:\s*(\d+)", pt_text)
    age = int(age_m.group(1)) if age_m else 0

    bd_m = re.search(r"Дата рождения:\s*([\d.]+)", pt_text)
    birthdate = bd_m.group(1) if bd_m else "—"
    if age == 0 and birthdate != "—":
        age = _extract_age(birthdate)

    # Current club and position: <p><b>Игрок клубов:</b> <a href="/clubNNN">Клуб</a> (<a title="Позиция">...)</p>
    current_club = "Свободный агент"
    club_id = 0
    position = "—"
    if player_title:
        club_link = player_title.find("a", href=re.compile(r"^/club\d+"))
        if club_link:
            current_club = club_link.get_text(strip=True)
            m = re.search(r"/club(\d+)", club_link.get("href", ""))
            if m:
                club_id = int(m.group(1))
        pos_link = player_title.find("a", href="javascript://")
        if pos_link and pos_link.get("title"):
            position = pos_link["title"]

    # Stats table: <table class="round_table stats">
    # Columns: Турнир(0), Команда(1), Заявлен(2), Отзаявлен(3), Игры(4), Голы(5), Пасы(6), ЖК(7), КК(8)
    goals = matches = assists = yellow_cards = red_cards = 0
    debut_year = date.today().year
    career_clubs: list[str] = []
    is_free_agent = club_id == 0

    stat_table = soup.find("table", class_=re.compile(r"\bstats\b"))
    if stat_table:
        rows = stat_table.find_all("tr")[1:]  # skip header
        debut_dates = []
        for row in rows:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 7:
                continue
            club = cols[1]
            active = cols[3] == "-"
            try:
                m_val = int(cols[4]) if cols[4].isdigit() else 0
                g_val = int(cols[5]) if cols[5].isdigit() else 0
                a_val = int(cols[6]) if cols[6].isdigit() else 0
                yk_val = int(cols[7]) if len(cols) > 7 and cols[7].isdigit() else 0
                rk_val = int(cols[8]) if len(cols) > 8 and cols[8].isdigit() else 0
            except (ValueError, IndexError):
                continue
            matches += m_val
            goals += g_val
            assists += a_val
            yellow_cards += yk_val
            red_cards += rk_val
            if club and club not in career_clubs:
                career_clubs.append(club)
            if active and club_id == 0 and club:
                is_free_agent = False
            d_m = re.search(r"(\d{4})", cols[2])
            if d_m:
                debut_dates.append(int(d_m.group(1)))
        if debut_dates:
            debut_year = min(debut_dates)

    return PlayerProfile(
        name=name, position=position, birthdate=birthdate, age=age,
        current_club=current_club, club_id=club_id, career_clubs=career_clubs,
        goals=goals, matches=matches, assists=assists,
        yellow_cards=yellow_cards, red_cards=red_cards,
        debut_year=debut_year, lfl_url=url, is_free_agent=is_free_agent,
    )


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def parse_lfl_player(url: str) -> PlayerProfile:
    try:
        html = await fetch_html(url, timeout=45.0, encoding="windows-1251")
        return _parse_lfl_html(html, url)
    except httpx.TimeoutException as exc:
        raise ValueError(
            "lfl.ru не отвечает — попробуй позже или создай карточку вручную."
        ) from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль ЛФЛ: {type(exc).__name__}") from exc
    except Exception as exc:
        raise ValueError(f"Ошибка парсера ЛФЛ: {type(exc).__name__}: {exc}") from exc
