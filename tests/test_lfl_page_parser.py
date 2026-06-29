import json
from datetime import date
from pathlib import Path

import pytest

from scraper.parsers.lfl_page import _parse_lfl_page_html
from scraper.parsers.registry import detect_url, detect_and_parse, LFL_PAGE_RE
import scraper.parsers.lfl_page as lfl_page

FIXTURE = Path(__file__).parent / "fixtures" / "lfl_page_191918_pageprops.json"
URL = "https://page.lfl.ru/persons/191918"


def _fixture_html() -> str:
    pp = json.loads(FIXTURE.read_text(encoding="utf-8"))
    next_data = {"props": {"pageProps": pp}}
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data, ensure_ascii=False)
        + "</script></body></html>"
    )


def test_detects_page_lfl_url():
    assert LFL_PAGE_RE.match(URL)
    assert detect_url(URL) == (URL, "lfl")


def test_does_not_match_old_lfl_or_regional():
    # page parser must not hijack the classic format or regional subdomains
    assert LFL_PAGE_RE.match("https://lfl.ru/person220008?player_id=1") is None
    assert LFL_PAGE_RE.match("https://ug.lfl.ru/player12345") is None


def test_parses_name_position_age():
    p = _parse_lfl_page_html(_fixture_html(), URL)
    assert p.name == "Мустафаев Эмиль Теймурович"
    assert p.position == "Нападающий"
    today = date.today()
    expected_age = today.year - 2001 - ((today.month, today.day) < (9, 1))
    assert p.age == expected_age
    assert p.lfl_url == URL


def test_current_club_is_latest_registration():
    p = _parse_lfl_page_html(_fixture_html(), URL)
    assert p.current_club == "СТИЛ"          # newest `included` registration
    assert p.is_free_agent is False
    assert p.career_clubs[0] == "СТИЛ"        # current club first
    assert "HOOKAH BAR" in p.career_clubs


def test_no_stats_in_page_format():
    p = _parse_lfl_page_html(_fixture_html(), URL)
    assert (p.goals, p.matches, p.assists, p.yellow_cards, p.red_cards) == (0, 0, 0, 0, 0)


@pytest.mark.asyncio
async def test_detect_and_parse_routes_to_page_parser(monkeypatch):
    html = _fixture_html()

    async def fake_fetch(url, timeout=15.0, encoding=None):
        return html

    monkeypatch.setattr(lfl_page, "fetch_html", fake_fetch)
    p = await detect_and_parse(URL)
    assert p is not None
    assert p.name == "Мустафаев Эмиль Теймурович"
    assert p.current_club == "СТИЛ"


# ── stats from api.lfl.ru ─────────────────────────────────────────────────────

TOUR_FIXTURES = {
    231918: Path(__file__).parent / "fixtures" / "lfl_page_tour_231918.json",
    260735: Path(__file__).parent / "fixtures" / "lfl_page_tour_260735.json",
    283623: Path(__file__).parent / "fixtures" / "lfl_page_tour_283623.json",
}


def test_player_ids_from_page_props():
    pp = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert lfl_page._player_ids(pp) == [231918, 260735, 283623]


def test_sum_stats_across_registrations():
    payloads = [json.loads(p.read_text(encoding="utf-8")) for p in TOUR_FIXTURES.values()]
    matches, goals, assists, yc, rc = lfl_page._sum_stats(payloads)
    assert (matches, goals, assists) == (15, 16, 9)   # summed across all registrations
    assert (yc, rc) == (0, 0)


@pytest.mark.asyncio
async def test_parse_player_aggregates_stats(monkeypatch):
    page_html = _fixture_html()

    async def fake_fetch(url, timeout=15.0, encoding=None):
        if url.startswith("https://page.lfl.ru/persons/"):
            return page_html
        for pid, path in TOUR_FIXTURES.items():
            if f"/persons/{pid}/tournaments" in url:
                return path.read_text(encoding="utf-8")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(lfl_page, "fetch_html", fake_fetch)
    p = await lfl_page.parse_lfl_page_player(URL)
    assert p.current_club == "СТИЛ"
    assert (p.matches, p.goals, p.assists) == (15, 16, 9)


@pytest.mark.asyncio
async def test_stats_failure_does_not_break_card(monkeypatch):
    # api.lfl.ru down → card still builds with zero stats (best-effort).
    page_html = _fixture_html()

    async def fake_fetch(url, timeout=15.0, encoding=None):
        if url.startswith("https://page.lfl.ru/persons/"):
            return page_html
        raise RuntimeError("api.lfl.ru unreachable")

    monkeypatch.setattr(lfl_page, "fetch_html", fake_fetch)
    p = await lfl_page.parse_lfl_page_player(URL)
    assert p.name == "Мустафаев Эмиль Теймурович"
    assert (p.matches, p.goals, p.assists) == (0, 0, 0)
