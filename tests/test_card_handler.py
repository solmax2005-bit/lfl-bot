import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scraper.models import PlayerProfile


def _make_profile():
    return PlayerProfile(
        name="Иванов Иван", position="Нападающий", birthdate="01.01.1990", age=34,
        current_club="ФК Алматы", club_id=42, career_clubs=["ФК Алматы"],
        goals=5, matches=10, assists=2, yellow_cards=1, red_cards=0,
        debut_year=2022, lfl_url="https://ug.lfl.ru/player1", is_free_agent=False,
    )


@pytest.mark.asyncio
async def test_card_handler_with_url_in_args():
    from handlers.card import card_handler
    update = MagicMock()
    context = MagicMock()
    context.args = ["https://ug.lfl.ru/player1"]
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.effective_user.id = 123

    with patch("handlers.card.parse_player", AsyncMock(return_value=_make_profile())), \
         patch("handlers.card.draw_card", return_value=b"PNGBYTES"):
        await card_handler(update, context)

    update.message.reply_photo.assert_called_once()


@pytest.mark.asyncio
async def test_card_handler_no_args_shows_usage():
    from handlers.card import card_handler
    update = MagicMock()
    context = MagicMock()
    context.args = []
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 123

    await card_handler(update, context)
    update.message.reply_text.assert_called_once()
    assert "ug.lfl.ru" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_card_handler_invalid_url_shows_error():
    from handlers.card import card_handler
    update = MagicMock()
    context = MagicMock()
    context.args = ["https://ug.lfl.ru/player1"]
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.effective_user.id = 123

    with patch("handlers.card.parse_player", AsyncMock(side_effect=ValueError("not found"))):
        await card_handler(update, context)

    assert update.message.reply_text.call_count >= 1
    # Last reply_text call should contain the error message
    last_call_text = update.message.reply_text.call_args[0][0]
    assert "не удалось" in last_call_text.lower()
