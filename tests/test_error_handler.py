import logging
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, TimedOut

import bot


def test_message_not_modified_is_ignorable():
    err = BadRequest(
        "Message is not modified: specified new message content and reply markup "
        "are exactly the same as a current content and reply markup of the message"
    )
    assert bot._is_ignorable_telegram_error(err) is True


def test_message_not_modified_case_insensitive():
    assert bot._is_ignorable_telegram_error(BadRequest("message is not modified")) is True


def test_other_badrequest_not_ignorable():
    assert bot._is_ignorable_telegram_error(BadRequest("Chat not found")) is False


def test_non_badrequest_not_ignorable():
    assert bot._is_ignorable_telegram_error(TimedOut("timed out")) is False
    assert bot._is_ignorable_telegram_error(ValueError("boom")) is False


@pytest.mark.asyncio
async def test_error_handler_ignores_message_not_modified(caplog):
    ctx = SimpleNamespace(error=BadRequest("Message is not modified: exactly the same"))
    caplog.set_level(logging.ERROR)
    await bot.error_handler(None, ctx)
    assert all(r.levelno < logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_error_handler_logs_real_errors(caplog):
    ctx = SimpleNamespace(error=BadRequest("Chat not found"))
    caplog.set_level(logging.ERROR)
    await bot.error_handler(None, ctx)
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
