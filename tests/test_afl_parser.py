import json
from datetime import date
from pathlib import Path

import pytest

import scraper.parsers.afl as afl
from scraper.parsers.afl import _build_afl_profile, _afl_id, _map_position
from scraper.parsers.registry import detect_url

FIX = Path(__file__).parent / "fixtures"
URL = "https://afl.ru/players/zverev-ivan-711043"


def _profile() -> dict:
    return json.loads((FIX / "afl_player_711043.json").read_text(encoding="utf-8"))


def _stats() -> dict:
    return json.loads((FIX / "afl_player_711043_stats.json").read_text(encoding="utf-8"))


def test_afl_id_from_url():
    assert _afl_id(URL) == "711043"
    assert _afl_id("https://afl.ru/players/zverev-ivan-711043?from=x") == "711043"


def test_position_mapping():
    assert _map_position("CM") == "Полузащитник"
    assert _map_position("gk") == "Вратарь"
    assert _map_position("CB") == "Защитник"
    assert _map_position("ST") == "Нападающий"
    assert _map_position("???") == "—"


def test_build_profile_basics():
    p = _build_afl_profile(_profile(), _stats(), URL)
    assert p.name == "Зверев Иван Андреевич"   # Фамилия Имя Отчество
    assert p.position == "Полузащитник"
    assert p.current_club == "Van Ararat Media"  # active team (till=null) joined most recently
    assert p.is_free_agent is False
    today = date.today()
    assert p.age == today.year - 2001 - ((today.month, today.day) < (12, 25))
    assert p.birthdate == "25.12.2001"           # from birthdayDate, not the buggy "birthday"


def test_build_profile_stats():
    p = _build_afl_profile(_profile(), _stats(), URL)
    assert (p.matches, p.goals, p.assists) == (41, 28, 14)


def test_stats_failure_keeps_name():
    # stats endpoint down → still get name/position from profile, zero numbers
    p = _build_afl_profile(_profile(), {}, URL)
    assert p.name == "Зверев Иван Андреевич"
    assert (p.matches, p.goals, p.assists) == (0, 0, 0)


@pytest.mark.asyncio
async def test_parse_afl_player_via_api(monkeypatch):
    async def fake_fetch(url, timeout=15.0, encoding=None):
        if url.endswith("/stats"):
            return (FIX / "afl_player_711043_stats.json").read_text(encoding="utf-8")
        if url.endswith("/711043"):
            return (FIX / "afl_player_711043.json").read_text(encoding="utf-8")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(afl, "fetch_html", fake_fetch)
    p = await afl.parse_afl_player(URL)
    assert p.name == "Зверев Иван Андреевич"
    assert (p.matches, p.goals, p.assists) == (41, 28, 14)
    assert p.current_club == "Van Ararat Media"


def test_detect_url_afl_unchanged():
    assert detect_url(URL) == (URL, "afl")
