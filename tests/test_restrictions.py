import pytest

from restrictions import is_restricted_team, RESTRICTED_FREE_AGENT_MSG


@pytest.mark.parametrize("name", ["СТИЛ", "стил", "Стил", "ФК Стил", "  стил  ", "стил москва"])
def test_restricted_true(name):
    assert is_restricted_team(name) is True


@pytest.mark.parametrize("name", ["Бастилия", "Стиляги", "Динамо", "", None, "стильный"])
def test_restricted_false(name):
    assert is_restricted_team(name) is False


def test_error_message_text():
    assert RESTRICTED_FREE_AGENT_MSG == (
        "Невозможно стать свободным агентом, так как вы являетесь игроком команды СТИЛ."
    )
