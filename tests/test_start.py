import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_start_handler_sends_welcome():
    from handlers.card import start_handler  # will import after step 8
    update = MagicMock()
    context = MagicMock()
    update.effective_user.first_name = "Иван"
    update.message.reply_text = AsyncMock()
    await start_handler(update, context)
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "ЛФЛ" in call_text
