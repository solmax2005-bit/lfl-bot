import httpx
import pytest
from unittest.mock import AsyncMock, patch

import bot
from telegram.error import TimedOut


def _timed_out(cause):
    """Build a TimedOut like PTB does: raised `from` an httpx error."""
    exc = TimedOut("Timed out")
    exc.__cause__ = cause
    return exc


@pytest.mark.asyncio
async def test_retries_connect_timeout_then_succeeds():
    req = bot.RetryRequest()
    side = [
        _timed_out(httpx.ConnectTimeout("connect timed out")),
        _timed_out(httpx.ConnectTimeout("connect timed out")),
        (200, b"ok"),
    ]
    with patch.object(bot.HTTPXRequest, "do_request", new=AsyncMock(side_effect=side)), \
         patch.object(bot.asyncio, "sleep", new=AsyncMock()):
        result = await req.do_request("https://api.telegram.org", "POST")
    assert result == (200, b"ok")


@pytest.mark.asyncio
async def test_gives_up_after_five_attempts():
    req = bot.RetryRequest()
    parent = AsyncMock(side_effect=_timed_out(httpx.ConnectTimeout("nope")))
    with patch.object(bot.HTTPXRequest, "do_request", new=parent), \
         patch.object(bot.asyncio, "sleep", new=AsyncMock()):
        with pytest.raises(TimedOut):
            await req.do_request("https://api.telegram.org", "POST")
    assert parent.await_count == 5


@pytest.mark.asyncio
async def test_does_not_retry_read_timeout():
    # ReadTimeout = request may already have been processed by Telegram.
    # Retrying would risk sending a duplicate message, so it must re-raise at once.
    req = bot.RetryRequest()
    parent = AsyncMock(side_effect=_timed_out(httpx.ReadTimeout("read timed out")))
    with patch.object(bot.HTTPXRequest, "do_request", new=parent), \
         patch.object(bot.asyncio, "sleep", new=AsyncMock()):
        with pytest.raises(TimedOut):
            await req.do_request("https://api.telegram.org", "POST")
    assert parent.await_count == 1
