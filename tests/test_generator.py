import io
import pytest
from PIL import Image
from scraper.models import PlayerProfile
from card_generator.generator import draw_card


def make_profile(is_free_agent: bool = False) -> PlayerProfile:
    return PlayerProfile(
        name="Иванов Иван Иванович",
        position="Нападающий",
        birthdate="15.03.1990",
        age=34,
        current_club="Свободный агент" if is_free_agent else "ФК Алматы",
        club_id=0 if is_free_agent else 42,
        career_clubs=["ФК Алматы", "ФК Тараз"],
        goals=8,
        matches=18,
        assists=5,
        yellow_cards=3,
        red_cards=1,
        debut_year=2022,
        lfl_url="https://ug.lfl.ru/player1",
        is_free_agent=is_free_agent,
    )


W, H = 600, 390


def test_draw_card_returns_valid_png():
    profile = make_profile()
    result = draw_card(profile)
    assert isinstance(result, bytes)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"
    assert img.size == (W, H)


def test_draw_card_blue_header_when_in_club():
    # Dark theme: header top is C_HEADER_TOP = (0x1A, 0x32, 0x52)
    profile = make_profile(is_free_agent=False)
    result = draw_card(profile)
    img = Image.open(io.BytesIO(result)).convert("RGB")
    r, g, b = img.getpixel((10, 10))
    # Top-left is gradient starting from C_HEADER_TOP — r channel dominant
    assert r > 0 and b > g  # dark blue hue


def test_draw_card_gold_accent_when_free_agent():
    # Free agent uses gold accent (avatar ring, position badge)
    profile = make_profile(is_free_agent=True)
    result = draw_card(profile)
    img = Image.open(io.BytesIO(result)).convert("RGB")
    # Avatar ring pixel should have gold accent (R>>G>>B)
    r, g, b = img.getpixel((22, 77))  # left edge of avatar ring
    assert r > 200 and r > b + 50  # gold: high R, low B


def make_manual_profile(experience: str = "") -> PlayerProfile:
    return PlayerProfile(
        name="Новиков Алексей",
        position="Полузащитник",
        birthdate="—",
        age=25,
        current_club="—",
        club_id=0,
        career_clubs=[],
        goals=0, matches=0, assists=0,
        yellow_cards=0, red_cards=0,
        debut_year=0,
        lfl_url="",
        is_free_agent=True,
        experience=experience,
    )


def test_draw_card_manual_no_experience_returns_png():
    profile = make_manual_profile(experience="")
    result = draw_card(profile)
    img = Image.open(io.BytesIO(result))
    assert img.size == (W, H)


def test_draw_card_manual_with_experience_returns_png():
    profile = make_manual_profile(experience="ФК Звезда, ФК Луч")
    result = draw_card(profile)
    img = Image.open(io.BytesIO(result))
    assert img.size == (W, H)


def test_draw_team_card_returns_valid_png():
    from card_generator.generator import draw_team_card
    team = {
        "name": "ФК Алматы",
        "league": "ЛФЛ",
        "districts": ["ЮГ", "Юго-восток"],
        "division": "Первый",
        "positions": ["Нападающий", "Защитник"],
        "contact": "@coach_almaty",
        "comment": "Набор открыт",
    }
    result = draw_team_card(team)
    assert isinstance(result, bytes)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"
    assert img.size == (W, H)
