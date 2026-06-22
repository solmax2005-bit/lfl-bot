import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tests.conftest import SAMPLE_HTML, SAMPLE_HTML_FREE_AGENT
from scraper.models import PlayerProfile
from scraper.lfl_parser import parse_player, _parse_html


def test_parse_html_in_club():
    profile = _parse_html(SAMPLE_HTML, "https://ug.lfl.ru/player1")
    assert isinstance(profile, PlayerProfile)
    assert profile.name == "Иванов Иван Иванович"
    assert profile.position == "Нападающий"
    assert profile.birthdate == "15.03.1990"
    assert profile.current_club == "ФК Алматы"
    assert profile.club_id == 42
    assert profile.is_free_agent is False
    assert profile.goals == 8
    assert profile.matches == 18
    assert profile.assists == 5
    assert profile.yellow_cards == 3
    assert profile.red_cards == 1
    assert "ФК Алматы" in profile.career_clubs
    assert "ФК Тараз" in profile.career_clubs
    assert profile.debut_year == 2022


def test_parse_html_free_agent():
    profile = _parse_html(SAMPLE_HTML_FREE_AGENT, "https://ug.lfl.ru/player2")
    assert profile.is_free_agent is True
    assert profile.club_id == 0
    assert profile.current_club == "Свободный агент"
    assert profile.matches == 12
    assert profile.goals == 0


@pytest.mark.asyncio
async def test_parse_player_calls_httpx():
    mock_response = MagicMock()
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = MagicMock()

    with patch("scraper.lfl_parser.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        profile = await parse_player("https://ug.lfl.ru/player1")
        assert profile.name == "Иванов Иван Иванович"
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1].get("headers") or call_kwargs[0]


@pytest.mark.asyncio
async def test_parse_player_raises_on_http_error():
    import httpx
    with patch("scraper.lfl_parser.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("404"))
        with pytest.raises(ValueError):
            await parse_player("https://ug.lfl.ru/player99999")
