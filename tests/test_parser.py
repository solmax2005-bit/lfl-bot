import pytest
from scraper.parsers.registry import detect_url, detect_and_parse
from scraper.parsers.lfl import _parse_lfl_html
from scraper.models import PlayerProfile

# ── URL detection ─────────────────────────────────────────────────────────────

def test_detect_lfl_url():
    result = detect_url("смотри https://lfl.ru/person122721?player_id=138246 вот")
    assert result is not None
    url, league = result
    assert "lfl.ru" in url
    assert league == "lfl"


def test_detect_afl_url():
    result = detect_url("https://afl.ru/players/stetsko-igor-482748")
    assert result is not None
    _, league = result
    assert league == "afl"


def test_detect_fleague_url():
    result = detect_url("https://f-league.ru/player/4650740")
    assert result is not None
    _, league = result
    assert league == "fleague"


def test_detect_no_url():
    assert detect_url("просто текст без ссылки") is None


def test_detect_ug_lfl_not_matched():
    # ug.lfl.ru больше не поддерживается
    assert detect_url("https://ug.lfl.ru/player12345") is None


# ── LFL HTML parser ───────────────────────────────────────────────────────────

SAMPLE_LFL_HTML = """
<html><body>
<div class="player_title">
  <p class="player_title_name"><a href="/person1">Иванов Иван Иванович</a></p>
  <p><b>Возраст:</b> 35</p>
  <p><b>Дата рождения:</b> 15.03.1990</p>
  <p><b>Игрок клубов:</b> <a href="/club42">ФК Алматы</a> (<a href="javascript://" title="Нападающий">нап.</a>, ЛФЛ, Юг)</p>
</div>
<table class="round_table stats">
  <thead><tr><th>Турнир</th><th>Команда</th><th>Заявлен</th><th>Отзаявлен</th><th>Игры</th><th>Голы</th><th>Пасы</th><th>ЖК</th><th>КК</th></tr></thead>
  <tbody>
    <tr><td>Лига 2023</td><td>ФК Алматы</td><td>01.01.2023</td><td>-</td><td>10</td><td>5</td><td>3</td><td>1</td><td>0</td></tr>
    <tr><td>Лига 2022</td><td>ФК Тараз</td><td>01.01.2022</td><td>01.12.2022</td><td>8</td><td>3</td><td>2</td><td>2</td><td>1</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_parse_lfl_html_name():
    profile = _parse_lfl_html(SAMPLE_LFL_HTML, "https://lfl.ru/person1?player_id=1")
    assert profile.name == "Иванов Иван Иванович"


def test_parse_lfl_html_stats():
    profile = _parse_lfl_html(SAMPLE_LFL_HTML, "https://lfl.ru/person1?player_id=1")
    assert profile.goals == 8
    assert profile.matches == 18
    assert profile.assists == 5
    assert profile.debut_year == 2022


def test_parse_lfl_html_career_clubs():
    profile = _parse_lfl_html(SAMPLE_LFL_HTML, "https://lfl.ru/person1?player_id=1")
    assert "ФК Алматы" in profile.career_clubs
    assert "ФК Тараз" in profile.career_clubs


def test_parse_lfl_html_not_free_agent():
    profile = _parse_lfl_html(SAMPLE_LFL_HTML, "https://lfl.ru/person1?player_id=1")
    assert not profile.is_free_agent
    assert profile.current_club == "ФК Алматы"
