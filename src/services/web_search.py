"""Web search — DuckDuckGo, Bing, Google. Pure HTML scraping, no API keys."""

import requests
from typing import List, Dict, Callable

from src.models.web_result import WebResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PROVIDER_LABELS = [
    {"key": "duckduckgo", "label": "DuckDuckGo"},
    {"key": "bing",       "label": "Bing"},
    {"key": "google",     "label": "Google"},
]


def _favicon(url: str) -> str:
    try:
        domain = url.split("/")[2]
        return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
    except Exception:
        return ""


def _search_duckduckgo(query: str) -> List[WebResult]:
    try:
        from bs4 import BeautifulSoup
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": ""},
            headers=_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for div in soup.select(".result__body")[:20]:
            title_el = div.select_one(".result__title a")
            url_el = div.select_one(".result__url")
            snip_el = div.select_one(".result__snippet")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            raw_url = (url_el.get_text(strip=True) if url_el else "")
            url = raw_url if raw_url.startswith("http") else "https://" + raw_url
            snippet = snip_el.get_text(strip=True) if snip_el else ""
            results.append(WebResult(
                title=title, url=url,
                description=snippet,
                source="DuckDuckGo",
                favicon_url=_favicon(url),
            ))
        return results
    except Exception:
        return []


def _search_bing(query: str) -> List[WebResult]:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query, "count": 20},
            headers=_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for li in soup.select("li.b_algo")[:20]:
            h2 = li.select_one("h2 a")
            snip = li.select_one(".b_caption p")
            if not h2:
                continue
            title = h2.get_text(strip=True)
            url = h2.get("href", "")
            snippet = snip.get_text(strip=True) if snip else ""
            results.append(WebResult(
                title=title, url=url,
                description=snippet,
                source="Bing",
                favicon_url=_favicon(url),
            ))
        return results
    except Exception:
        return []


def _search_google(query: str) -> List[WebResult]:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "hl": "en", "num": "20"},
            headers=_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for div in soup.select("div.g")[:20]:
            h3 = div.select_one("h3")
            a = div.select_one("a[href^='http']")
            snip = div.select_one(".VwiC3b, .lEBKkf, span.st")
            if not h3 or not a:
                continue
            title = h3.get_text(strip=True)
            url = a.get("href", "")
            snippet = snip.get_text(strip=True) if snip else ""
            results.append(WebResult(
                title=title, url=url,
                description=snippet,
                source="Google",
                favicon_url=_favicon(url),
            ))
        return results
    except Exception:
        return []


PROVIDERS: Dict[str, Callable] = {
    "duckduckgo": _search_duckduckgo,
    "bing":       _search_bing,
    "google":     _search_google,
}
