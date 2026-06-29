from datetime import date
from pathlib import Path

from scraper.parsers.fleague import _parse_fleague_html
from scraper.parsers.registry import detect_url

FIXTURE = Path(__file__).parent / "fixtures" / "fleague_player_6691548.html"
URL = "https://f-league.ru/player/6691548"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_name_is_clean():
    p = _parse_fleague_html(_html(), URL)
    assert p.name == "Власенков Александр"   # no "ЛИГА F. Официальный сайт" junk


def test_current_club_only():
    p = _parse_fleague_html(_html(), URL)
    assert p.current_club == "Комтех"        # not the "Клуб:" label or a wall of nav text
    assert p.is_free_agent is False
    assert p.career_clubs == ["Комтех"]


def test_stats_from_summary_block():
    p = _parse_fleague_html(_html(), URL)
    assert p.matches == 28
    assert p.goals == 17
    assert p.assists == 7
    assert p.yellow_cards == 1
    assert p.red_cards == 0


def test_birthdate_russian_format():
    p = _parse_fleague_html(_html(), URL)
    assert p.birthdate == "02.02.1991"
    today = date.today()
    expected_age = today.year - 1991 - ((today.month, today.day) < (2, 2))
    assert p.age == expected_age


def test_detect_url_fleague_unchanged():
    assert detect_url(URL) == (URL, "fleague")
