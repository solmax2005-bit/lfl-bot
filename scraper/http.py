import os
import httpx

_SCRAPER_KEY = os.getenv("SCRAPERAPI_KEY", "")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def fetch_html(url: str, timeout: float = 20.0, encoding: str | None = None) -> str:
    key = os.getenv("SCRAPERAPI_KEY", "")
    if key:
        fetch_url = f"https://api.scraperapi.com?api_key={key}&url={url}"
        headers = {}
    else:
        fetch_url = url
        headers = _DEFAULT_HEADERS

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(fetch_url, headers=headers)
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text
