import asyncio
import os
import httpx

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def _do_fetch(fetch_url: str, headers: dict, timeout: float, encoding: str | None, proxy: str | None = None) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=proxy) as client:
        response = await client.get(fetch_url, headers=headers)
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text


async def fetch_html(url: str, timeout: float = 15.0, encoding: str | None = None) -> str:
    proxy_url = os.getenv("PROXY_URL", "")
    scraperapi_key = os.getenv("SCRAPERAPI_KEY", "")
    cf_worker = os.getenv("CF_WORKER_URL", "")

    cf_secret = os.getenv("CF_WORKER_SECRET", "")
    if cf_worker and cf_secret and "lfl.ru" in url:
        from urllib.parse import quote
        fetch_url = f"{cf_worker}?secret={cf_secret}&url={quote(url, safe='')}"
        headers = {}
        proxy = None
    elif proxy_url:
        fetch_url = url
        headers = _DEFAULT_HEADERS
        proxy = proxy_url
    elif scraperapi_key:
        fetch_url = (
            f"https://api.scraperapi.com"
            f"?api_key={scraperapi_key}&url={url}&country_code=ru&timeout=12000"
        )
        headers = {}
        proxy = None
    else:
        fetch_url = url
        headers = _DEFAULT_HEADERS
        proxy = None

    try:
        return await asyncio.wait_for(
            _do_fetch(fetch_url, headers, timeout, encoding, proxy),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise httpx.TimeoutException(f"Timeout after {timeout}s") from exc
