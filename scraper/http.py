import asyncio
import logging
import os
import httpx

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Fetch strategies tried in order. Direct first (free, fast); the proxy is an
# automatic fallback used only when direct fails. Switching happens per request
# with no config changes or restarts: if direct breaks, every request falls to
# the proxy on its own; when direct recovers, requests use it again.
_FETCH_ORDER = ("direct", "proxy")


async def _do_fetch(fetch_url: str, headers: dict, timeout: float, encoding: str | None, proxy: str | None = None) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=proxy) as client:
        response = await client.get(fetch_url, headers=headers)
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text


def _strategies() -> list[tuple[str, str | None]]:
    """(name, proxy) attempts in fallback order; proxy is skipped if PROXY_URL is unset."""
    proxy_url = os.getenv("PROXY_URL", "")
    out: list[tuple[str, str | None]] = []
    for name in _FETCH_ORDER:
        if name == "direct":
            out.append(("direct", None))
        elif name == "proxy" and proxy_url:
            out.append(("proxy", proxy_url))
    return out


async def fetch_html(url: str, timeout: float = 15.0, encoding: str | None = None) -> str:
    last_exc: Exception | None = None
    for name, proxy in _strategies():
        try:
            return await asyncio.wait_for(
                _do_fetch(url, _DEFAULT_HEADERS, timeout, encoding, proxy),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — any failure falls through to the next strategy
            last_exc = exc
            logging.warning(
                "fetch_html: strategy '%s' failed for %s: %s",
                name, url, type(exc).__name__,
            )
            continue
    # Every strategy failed. Preserve the timeout contract so callers (lfl.py)
    # can show "lfl.ru не отвечает" when nothing answered in time.
    if isinstance(last_exc, asyncio.TimeoutError):
        raise httpx.TimeoutException(f"Timeout after {timeout}s") from last_exc
    if last_exc is not None:
        raise last_exc
    raise httpx.HTTPError("No fetch strategy configured")
