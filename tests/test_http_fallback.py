import asyncio

import httpx
import pytest

import scraper.http as http


@pytest.mark.asyncio
async def test_uses_direct_first_and_skips_proxy_on_success(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://user:pass@1.2.3.4:1111")
    calls = []

    async def fake_do_fetch(fetch_url, headers, timeout, encoding, proxy=None):
        calls.append("direct" if proxy is None else "proxy")
        return "<html>OK</html>"

    monkeypatch.setattr(http, "_do_fetch", fake_do_fetch)
    result = await http.fetch_html("https://lfl.ru/person1", timeout=5.0)
    assert calls == ["direct"]            # proxy never tried when direct works
    assert result == "<html>OK</html>"


@pytest.mark.asyncio
async def test_falls_back_to_proxy_when_direct_fails(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://user:pass@1.2.3.4:1111")
    calls = []

    async def fake_do_fetch(fetch_url, headers, timeout, encoding, proxy=None):
        calls.append("direct" if proxy is None else "proxy")
        if proxy is None:
            raise httpx.ConnectError("direct down")
        return "<html>player_title_name</html>"

    monkeypatch.setattr(http, "_do_fetch", fake_do_fetch)
    result = await http.fetch_html("https://lfl.ru/person1", timeout=5.0)
    assert calls == ["direct", "proxy"]   # direct first, then automatic fallback to proxy
    assert "player_title_name" in result


@pytest.mark.asyncio
async def test_only_direct_when_no_proxy_configured(monkeypatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    calls = []

    async def fake_do_fetch(fetch_url, headers, timeout, encoding, proxy=None):
        calls.append("direct" if proxy is None else "proxy")
        return "<html>OK</html>"

    monkeypatch.setattr(http, "_do_fetch", fake_do_fetch)
    await http.fetch_html("https://lfl.ru/person1", timeout=5.0)
    assert calls == ["direct"]            # no proxy strategy when PROXY_URL unset


@pytest.mark.asyncio
async def test_raises_http_error_when_all_strategies_fail(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://user:pass@1.2.3.4:1111")

    async def fake_do_fetch(fetch_url, headers, timeout, encoding, proxy=None):
        raise httpx.ConnectError("everything down")

    monkeypatch.setattr(http, "_do_fetch", fake_do_fetch)
    with pytest.raises(httpx.HTTPError):
        await http.fetch_html("https://lfl.ru/person1", timeout=5.0)


@pytest.mark.asyncio
async def test_all_timeouts_raise_httpx_timeout(monkeypatch):
    # Preserves the existing contract: lfl.py catches httpx.TimeoutException
    # and shows "lfl.ru не отвечает". A timeout on every strategy must surface as one.
    monkeypatch.setenv("PROXY_URL", "http://user:pass@1.2.3.4:1111")

    async def fake_do_fetch(fetch_url, headers, timeout, encoding, proxy=None):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(http, "_do_fetch", fake_do_fetch)
    with pytest.raises(httpx.TimeoutException):
        await http.fetch_html("https://lfl.ru/person1", timeout=5.0)
