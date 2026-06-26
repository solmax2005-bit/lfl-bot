import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
from database.db import init_db

TEST_TOKEN = "123456:TEST_TOKEN_ABC"
client = TestClient(api.app)


def make_init_data(user: dict, token: str = TEST_TOKEN, auth_date: int | None = None) -> str:
    """Build a signed Telegram WebApp initData string, exactly как это делает Telegram."""
    if auth_date is None:
        auth_date = int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    asyncio.run(init_db(db))
    phdir = tmp_path / "photos"
    phdir.mkdir()
    monkeypatch.setattr(api, "DB_PATH", db)
    monkeypatch.setattr(api, "BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(api, "PHOTOS_DIR", str(phdir))
    yield


# ── initData validation (security core) ──────────────────────────────────────

def test_verify_valid():
    out = api.verify_init_data(make_init_data({"id": 42, "username": "bob"}))
    assert out["tg_id"] == 42
    assert out["username"] == "bob"


def test_verify_bad_signature():
    raw = make_init_data({"id": 42}, token="wrong:token")
    with pytest.raises(HTTPException) as e:
        api.verify_init_data(raw)
    assert e.value.status_code == 403


def test_verify_expired():
    raw = make_init_data({"id": 42}, auth_date=int(time.time()) - 100_000)
    with pytest.raises(HTTPException) as e:
        api.verify_init_data(raw)
    assert e.value.status_code == 403


def test_verify_empty():
    with pytest.raises(HTTPException):
        api.verify_init_data("")


# ── card/save ─────────────────────────────────────────────────────────────────

def test_save_creates_card():
    raw = make_init_data({"id": 7, "username": "joe"})
    r = client.post("/api/card/save", json={
        "init_data": raw, "name": "Иван", "position": "Нападающий",
        "age": 25, "division": "ЛФЛ", "current_team": "Спартак",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["found"] is True
    assert body["profile"]["name"] == "Иван"
    assert body["profile"]["position"] == "Нападающий"


def test_save_rejects_bad_age():
    raw = make_init_data({"id": 7})
    r = client.post("/api/card/save", json={
        "init_data": raw, "name": "X", "position": "Нападающий", "age": 5,
    })
    assert r.json()["ok"] is False


def test_save_rejects_bad_position():
    raw = make_init_data({"id": 7})
    r = client.post("/api/card/save", json={
        "init_data": raw, "name": "X", "position": "Тренер", "age": 25,
    })
    assert r.json()["ok"] is False


def test_save_rejects_forged_init_data():
    r = client.post("/api/card/save", json={
        "init_data": "user=%7B%22id%22%3A1%7D&hash=deadbeef",
        "name": "X", "position": "Нападающий", "age": 25,
    })
    assert r.status_code == 403


# ── card/status + delete ────────────────────────────────────────────────────

def test_status_toggles_flags():
    raw = make_init_data({"id": 9, "username": "k"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "A", "position": "Вратарь", "age": 30, "division": "ЛФЛ",
    })
    r = client.post("/api/card/status", json={"init_data": raw, "active": 1, "looking": 1})
    prof = r.json()["profile"]
    assert prof["active"] == 1
    assert prof["looking"] == 1


def test_delete_removes_card():
    raw = make_init_data({"id": 10, "username": "d"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "B", "position": "Защитник", "age": 22, "division": "ЛФЛ",
    })
    r = client.post("/api/card/delete", json={"init_data": raw})
    assert r.json()["ok"] is True
    me = client.get("/api/me", params={"tg_id": 10}).json()
    assert me["found"] is False


# ── card/import (parser mocked) ───────────────────────────────────────────────

def test_import_saves_parsed_profile(monkeypatch):
    fake = SimpleNamespace(
        name="Пётр", position="Защитник", lfl_url="https://lfl.ru/person1?player_id=1",
        career_clubs=["Спартак", "Зенит"], is_free_agent=True, current_club="Спартак",
        age=28, goals=3, matches=20, assists=5, yellow_cards=2, red_cards=0,
        debut_year=2019, birthdate="", club_id=0, experience="",
    )

    async def fake_parse(url):
        return fake

    monkeypatch.setattr(api, "detect_and_parse", fake_parse)
    raw = make_init_data({"id": 11, "username": "p"})
    r = client.post("/api/card/import", json={"init_data": raw, "url": "https://lfl.ru/person1?player_id=1"})
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["name"] == "Пётр"
    assert body["profile"]["goals"] == 3
    assert body["profile"]["active"] == 0  # imported cards start hidden


def test_import_unrecognized_url(monkeypatch):
    async def fake_parse(url):
        return None

    monkeypatch.setattr(api, "detect_and_parse", fake_parse)
    raw = make_init_data({"id": 12})
    r = client.post("/api/card/import", json={"init_data": raw, "url": "https://example.com"})
    assert r.json()["ok"] is False


# ── Teams (Phase 2) ───────────────────────────────────────────────────────────

def _save_team(uid, name, positions, league="ЛФЛ", districts=None):
    raw = make_init_data({"id": uid, "username": f"u{uid}"})
    return client.post("/api/team/save", json={
        "init_data": raw, "name": name, "league": league,
        "districts": districts or [], "division": "Первый",
        "positions": positions, "contact": "@cap", "comment": "ищем игроков",
    })


def test_team_save_and_list():
    r = _save_team(100, "Спартак-Юг", ["Нападающий", "Защитник"])
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["team"]["name"] == "Спартак-Юг"
    assert "Нападающий" in body["team"]["positions"]

    teams = client.get("/api/teams").json()
    assert any(t["name"] == "Спартак-Юг" for t in teams)


def test_team_save_requires_position():
    raw = make_init_data({"id": 101})
    r = client.post("/api/team/save", json={
        "init_data": raw, "name": "X", "league": "ЛФЛ", "positions": [],
    })
    assert r.json()["ok"] is False


def test_team_save_rejects_forged():
    r = client.post("/api/team/save", json={
        "init_data": "bad", "name": "X", "league": "ЛФЛ", "positions": ["Вратарь"],
    })
    assert r.status_code == 403


def test_teams_filter_by_position():
    _save_team(102, "Только нападающие", ["Нападающий"])
    _save_team(103, "Только вратари", ["Вратарь"])
    fwd = client.get("/api/teams", params={"position": "Нападающий"}).json()
    names = [t["name"] for t in fwd]
    assert "Только нападающие" in names
    assert "Только вратари" not in names


def test_team_me_and_delete():
    _save_team(104, "Моя Команда", ["Полузащитник"])
    me = client.get("/api/team/me", params={"tg_id": 104}).json()
    assert me["found"] is True
    assert me["name"] == "Моя Команда"
    raw = make_init_data({"id": 104})
    assert client.post("/api/team/delete", json={"init_data": raw}).json()["ok"] is True
    assert client.get("/api/team/me", params={"tg_id": 104}).json()["found"] is False


def test_team_apply_notifies_captain(monkeypatch):
    sent = {}

    async def fake_send(chat_id, text, parse_mode=None, reply_markup=None):
        sent["chat_id"] = chat_id
        sent["text"] = text

    monkeypatch.setattr(api, "_send_telegram", fake_send)
    raw = make_init_data({"id": 200, "username": "applicant", "first_name": "Игорь"})
    r = client.post("/api/team/apply", json={"init_data": raw, "team_tg_id": 999})
    assert r.json()["ok"] is True
    assert sent["chat_id"] == 999
    assert "Игорь" in sent["text"]


# ── Favorites + notifications (Phase 3) ───────────────────────────────────────

def test_fav_toggle_and_list():
    raw_target = make_init_data({"id": 300, "username": "tgt"})
    client.post("/api/card/save", json={
        "init_data": raw_target, "name": "Цель", "position": "Нападающий", "age": 25, "division": "ЛФЛ",
    })
    raw_viewer = make_init_data({"id": 301, "username": "viewer"})
    r = client.post("/api/fav/toggle", json={"init_data": raw_viewer, "target_tg_id": 300})
    assert r.json() == {"ok": True, "fav": True}
    favs = client.get("/api/favorites", params={"tg_id": 301}).json()
    assert any(f["tg_id"] == 300 for f in favs)
    r2 = client.post("/api/fav/toggle", json={"init_data": raw_viewer, "target_tg_id": 300})
    assert r2.json()["fav"] is False
    assert client.get("/api/favorites", params={"tg_id": 301}).json() == []


def test_fav_rejects_forged():
    r = client.post("/api/fav/toggle", json={"init_data": "bad", "target_tg_id": 1})
    assert r.status_code == 403


def test_status_activation_notifies_teams(monkeypatch):
    called = {}

    async def fake_notify(agent_tg_id, name, pos, league):
        called["args"] = (agent_tg_id, name, pos, league)

    monkeypatch.setattr(api, "_notify_teams_new_player", fake_notify)
    raw = make_init_data({"id": 310, "username": "p"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "Игрок", "position": "Защитник", "age": 24, "division": "ЛФЛ",
    })
    client.post("/api/card/status", json={"init_data": raw, "active": 1})
    assert called.get("args") is not None
    assert called["args"][0] == 310


def test_status_no_double_notify(monkeypatch):
    count = {"n": 0}

    async def fake_notify(*a):
        count["n"] += 1

    monkeypatch.setattr(api, "_notify_teams_new_player", fake_notify)
    raw = make_init_data({"id": 311})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "P", "position": "Вратарь", "age": 24, "division": "ЛФЛ",
    })
    client.post("/api/card/status", json={"init_data": raw, "active": 1})
    client.post("/api/card/status", json={"init_data": raw, "active": 1})
    assert count["n"] == 1


def test_team_save_notifies_players_once(monkeypatch):
    count = {"n": 0}

    async def fake_notify(*a):
        count["n"] += 1

    monkeypatch.setattr(api, "_notify_players_new_team", fake_notify)
    raw = make_init_data({"id": 320, "username": "cap"})
    client.post("/api/team/save", json={"init_data": raw, "name": "T", "league": "ЛФЛ", "positions": ["Нападающий"]})
    client.post("/api/team/save", json={"init_data": raw, "name": "T2", "league": "ЛФЛ", "positions": ["Нападающий"]})
    assert count["n"] == 1


# ── Photo + refresh (2026-06-27) ──────────────────────────────────────────────

def _png_b64(w=50, h=80):
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_card_photo_upload():
    raw = make_init_data({"id": 400, "username": "ph"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "Фото", "position": "Вратарь", "age": 25, "division": "ЛФЛ",
    })
    r = client.post("/api/card/photo", json={"init_data": raw, "image": _png_b64()})
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["photo"].startswith("/photos/400.jpg")
    assert os.path.exists(os.path.join(api.PHOTOS_DIR, "400.jpg"))


def test_card_photo_rejects_non_image():
    raw = make_init_data({"id": 403, "username": "x"})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "X", "position": "Вратарь", "age": 25, "division": "ЛФЛ",
    })
    bad = "data:image/png;base64," + base64.b64encode(b"not an image").decode()
    r = client.post("/api/card/photo", json={"init_data": raw, "image": bad})
    assert r.json()["ok"] is False


def test_card_refresh(monkeypatch):
    raw = make_init_data({"id": 401, "username": "rf"})
    old = SimpleNamespace(
        name="Старый", position="Защитник", lfl_url="https://lfl.ru/person1?player_id=1",
        career_clubs=["Клуб"], is_free_agent=True, current_club="Клуб", age=20,
        goals=1, matches=5, assists=0, yellow_cards=0, red_cards=0, debut_year=2020,
        birthdate="", club_id=0, experience="",
    )
    monkeypatch.setattr(api, "detect_and_parse", lambda url: _async_return(old))
    client.post("/api/card/import", json={"init_data": raw, "url": old.lfl_url})

    new = SimpleNamespace(**{**old.__dict__, "name": "Новый", "goals": 9, "matches": 15, "assists": 3})
    monkeypatch.setattr(api, "detect_and_parse", lambda url: _async_return(new))
    r = client.post("/api/card/refresh", json={"init_data": raw})
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["name"] == "Новый"
    assert body["profile"]["goals"] == 9


def test_card_refresh_no_url():
    raw = make_init_data({"id": 402})
    client.post("/api/card/save", json={
        "init_data": raw, "name": "Ручной", "position": "Вратарь", "age": 22, "division": "ЛФЛ",
    })
    assert client.post("/api/card/refresh", json={"init_data": raw}).json()["ok"] is False


async def _async_return(val):
    return val
