import re
from scraper.models import PlayerProfile

LFL_PAGE_RE = re.compile(r"https?://page\.lfl\.ru/persons/\d+[^\s]*", re.I)
LFL_RE = re.compile(r"https?://lfl\.ru/person\d+[^\s]*", re.I)
AFL_RE = re.compile(r"https?://afl\.ru/players/[\w-]+-\d+[^\s]*", re.I)
FLEAGUE_RE = re.compile(r"https?://f-league\.ru/player/\d+[^\s]*", re.I)


def detect_url(text: str) -> tuple[str, str] | None:
    """Return (url, league_key) or None. League keys: 'lfl', 'afl', 'fleague'."""
    m = LFL_PAGE_RE.search(text)
    if m:
        return m.group(0), "lfl"
    m = LFL_RE.search(text)
    if m:
        return m.group(0), "lfl"
    m = AFL_RE.search(text)
    if m:
        return m.group(0), "afl"
    m = FLEAGUE_RE.search(text)
    if m:
        return m.group(0), "fleague"
    return None


async def detect_and_parse(url: str) -> PlayerProfile | None:
    """Determine league from URL and call the right parser."""
    if LFL_PAGE_RE.match(url):
        from scraper.parsers.lfl_page import parse_lfl_page_player
        return await parse_lfl_page_player(url)
    if LFL_RE.match(url):
        from scraper.parsers.lfl import parse_lfl_player
        return await parse_lfl_player(url)
    if AFL_RE.match(url):
        from scraper.parsers.afl import parse_afl_player
        return await parse_afl_player(url)
    if FLEAGUE_RE.match(url):
        from scraper.parsers.fleague import parse_fleague_player
        return await parse_fleague_player(url)
    return None
