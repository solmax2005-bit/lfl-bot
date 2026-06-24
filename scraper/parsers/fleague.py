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


def _parse_fleague_html(html: str, url: str) -> PlayerProfile:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1") or soup.find(class_=re.compile(r"player.?name|title", re.I))
    name = h1.text.strip() if h1 else "Неизвестно"

    POSITIONS_RE = re.compile(r"Нападающий|Полузащитник|Защитник|Вратарь", re.I)
    pos_tag = soup.find(string=POSITIONS_RE)
    if pos_tag:
        position = str(pos_tag).strip()
    else:
        pos_block = soup.find(class_=re.compile(r"pos|role", re.I))
        position = pos_block.text.strip() if pos_block else "—"

    DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
    birthdate = "—"
    bd = soup.find(string=DATE_RE)
    if bd:
        m = DATE_RE.search(str(bd))
        if m:
            birthdate = m.group(0)
    age = _extract_age(birthdate)

    club_tag = (
        soup.find(class_=re.compile(r"club|team", re.I))
        or soup.find("a", href=re.compile(r"/club|/team", re.I))
    )
    current_club = club_tag.text.strip() if club_tag else "Свободный агент"
    is_free_agent = current_club in ("", "Свободный агент", "—")

    goals = matches = assists = yellow_cards = red_cards = 0
    debut_year = date.today().year
    career_clubs: list[str] = []

    table = soup.find("table")
    if table:
        rows = table.find_all("tr")[1:]
        years = []
        for row in rows:
            cols = [td.text.strip() for td in row.find_all("td")]
            if len(cols) < 3:
                continue
            try:
                year = int(cols[0]) if cols[0].isdigit() else 0
                club = cols[1] if len(cols) > 1 else ""
                m_val = int(cols[2]) if len(cols) > 2 and cols[2].isdigit() else 0
                g_val = int(cols[3]) if len(cols) > 3 and cols[3].isdigit() else 0
                a_val = int(cols[4]) if len(cols) > 4 and cols[4].isdigit() else 0
            except (ValueError, IndexError):
                continue
            matches += m_val
            goals += g_val
            assists += a_val
            if club and club not in career_clubs:
                career_clubs.append(club)
            if year:
                years.append(year)
        if years:
            debut_year = min(years)

    return PlayerProfile(
        name=name, position=position, birthdate=birthdate, age=age,
        current_club=current_club, club_id=0, career_clubs=career_clubs,
        goals=goals, matches=matches, assists=assists,
        yellow_cards=0, red_cards=0,
        debut_year=debut_year, lfl_url=url, is_free_agent=is_free_agent,
    )


async def parse_fleague_player(url: str) -> PlayerProfile:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LFLBot/1.0)"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_fleague_html(response.text, url)
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось загрузить профиль F-лиги: {exc}") from exc
