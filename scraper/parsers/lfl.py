import re
from datetime import date
import httpx
from bs4 import BeautifulSoup
from scraper.models import PlayerProfile


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

    h1 = soup.find("h1")
    name = h1.text.strip() if h1 else "Неизвестно"

    pos_tag = soup.find(class_="position") or soup.find(
        "span", string=re.compile(r"Нападающий|Полузащитник|Защитник|Вратарь")
    )
    position = pos_tag.text.strip() if pos_tag else "—"

    bd_tag = soup.find(class_="birthdate")
    birthdate = bd_tag.text.strip() if bd_tag else "—"
    age = _extract_age(birthdate)

    club_link = soup.find("a", class_="club-link") or soup.find(
        "a", href=re.compile(r"/club/\d+")
    )
    current_club = "Свободный агент"
    club_id = 0
    if club_link:
        current_club = club_link.text.strip()
        m = re.search(r"/club/(\d+)", club_link.get("href", ""))
        if m:
            club_id = int(m.group(1))
    is_free_agent = club_id == 0

    goals = matches = assists = yellow_cards = red_cards = 0
    debut_year = date.today().year
    career_clubs: list[str] = []

    stat_table = soup.find("table", class_="stat-table") or soup.find("table")
    if stat_table:
        rows = stat_table.find_all("tr")[1:]
        years = []
        for row in rows:
            cols = [td.text.strip() for td in row.find_all("td")]
            if len(cols) < 7:
                continue
            try:
                year = int(cols[0]) if cols[0].isdigit() else 0
                club = cols[1]
                m_val = int(cols[2]) if cols[2].isdigit() else 0
                g_val = int(cols[3]) if cols[3].isdigit() else 0
                a_val = int(cols[4]) if cols[4].isdigit() else 0
                yk_val = int(cols[5]) if cols[5].isdigit() else 0
                rk_val = int(cols[6]) if cols[6].isdigit() else 0
            except (ValueError, IndexError):
                continue
            matches += m_val
            goals += g_val
            assists += a_val
            yellow_cards += yk_val
            red_cards += rk_val
            if club and club not in career_clubs:
                career_clubs.append(club)
            if year:
                years.append(year)
        if years:
            debut_year = min(years)

    return PlayerProfile(
        name=name, position=position, birthdate=birthdate, age=age,
        current_club=current_club, club_id=club_id, career_clubs=career_clubs,
        goals=goals, matches=matches, assists=assists,
        yellow_cards=yellow_cards, red_cards=red_cards,
        debut_year=debut_year, lfl_url=url, is_free_agent=is_free_agent,
    )


async def parse_lfl_player(url: str) -> PlayerProfile:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LFLBot/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            response.encoding = "windows-1251"
            return _parse_lfl_html(response.text, url)
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль ЛФЛ: {exc}") from exc
