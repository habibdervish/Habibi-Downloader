"""Image search — Bing, Google, Openverse, Wikimedia Commons, Pexels, Pixabay.
Only providers confirmed to work without an API key are active.
"""

import re
import json
import uuid
import requests
from typing import List, Dict, Callable

from src.models.image_asset import ImageAsset

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
_WIKI_HEADERS = {"User-Agent": "HabibiDownloaderX/1.0", "Accept-Language": "en-US,en;q=0.9"}

PROVIDER_LABELS = [
    {"key": "openverse",  "label": "Openverse"},
    {"key": "bing",       "label": "Bing"},
    {"key": "unsplash",   "label": "Unsplash"},
    {"key": "pexels",     "label": "Pexels"},
    {"key": "pixabay",    "label": "Pixabay"},
    {"key": "wikimedia",  "label": "Wikimedia"},
    {"key": "nasa",       "label": "NASA"},
    {"key": "met",        "label": "Met Museum"},
    {"key": "loc",        "label": "Lib. of Congress"},
    {"key": "google",     "label": "Google"},
]


def _uid() -> str:
    return str(uuid.uuid4())


def _setting(key: str) -> str:
    """Read an optional API key from app settings (empty string if unset)."""
    try:
        from src.state import state
        return (state.settings.get(key) or "").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------ Bing
def _search_bing(query: str) -> List[ImageAsset]:
    try:
        from bs4 import BeautifulSoup
        # The /async endpoint now returns only 1 item; the standard search page
        # returns a full grid, so scrape that instead.
        resp = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": 1},
            headers=_HEADERS, timeout=12,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        seen = set()
        for a in soup.select("a.iusc"):
            try:
                m = json.loads(a.get("m", "{}"))
                full = m.get("murl", "")
                if not full or full in seen:
                    continue
                seen.add(full)
                results.append(ImageAsset(
                    id=_uid(), title=m.get("t", ""),
                    source="Bing",
                    # `turl` can be an empty string (not missing) -> use `or`
                    # so we never hand Flet an empty src (the red error boxes)
                    thumbnail_url=(m.get("turl") or full),
                    full_url=full,
                    page_url=m.get("purl", ""),
                    width=0, height=0,
                ))
            except Exception:
                continue
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Openverse
def _search_openverse(query: str) -> List[ImageAsset]:
    """Openverse — keyless API aggregator of openly-licensed HD images
    (Flickr, Wikimedia, museums…). Deterministic: same query -> same results,
    so images are re-findable and downloadable. Fetches several pages."""
    results = []
    seen = set()
    for page in (1, 2, 3):
        try:
            r = requests.get(
                "https://api.openverse.org/v1/images/",
                params={"q": query, "page_size": 20, "page": page,
                        "mature": "false"},
                headers=_HEADERS, timeout=12,
            )
            if r.status_code != 200:
                break
            items = r.json().get("results", [])
            if not items:
                break
            for it in items:
                thumb = it.get("thumbnail") or it.get("url") or ""
                full = it.get("url") or thumb
                if not thumb or full in seen:
                    continue
                seen.add(full)
                results.append(ImageAsset(
                    id=_uid(), title=it.get("title", ""),
                    source="Openverse",
                    thumbnail_url=thumb, full_url=full,
                    page_url=it.get("foreign_landing_url", ""),
                    author=it.get("creator", ""),
                    width=it.get("width", 0) or 0,
                    height=it.get("height", 0) or 0,
                ))
        except Exception:
            break
    return results


# ------------------------------------------------------------------ NASA
def _search_nasa(query: str) -> List[ImageAsset]:
    try:
        resp = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "image", "page_size": 20},
            headers=_HEADERS, timeout=12,
        )
        if resp.status_code != 200:
            return []
        items = resp.json().get("collection", {}).get("items", [])
        results = []
        for item in items[:20]:
            links = item.get("links", [{}])
            thumb = links[0].get("href", "") if links else ""
            if not thumb:
                continue
            data = (item.get("data") or [{}])[0]
            full = thumb.replace("~thumb.", "~orig.")
            results.append(ImageAsset(
                id=_uid(),
                title=data.get("title", ""),
                source="NASA",
                thumbnail_url=thumb,
                full_url=full,
                page_url=item.get("href", ""),
                author="NASA",
                width=0, height=0,
            ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Wikimedia
def _search_wikimedia(query: str) -> List[ImageAsset]:
    try:
        # Step 1: search for file names
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "list": "search",
                "srsearch": query, "srnamespace": "6",
                "srlimit": 30, "format": "json",
            },
            headers=_WIKI_HEADERS, timeout=12,
        )
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return []

        titles = [h["title"] for h in hits[:30]]

        # Step 2: get image URLs in one batch call
        r2 = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 400,
                "format": "json",
            },
            headers=_WIKI_HEADERS, timeout=12,
        )
        pages = r2.json().get("query", {}).get("pages", {})
        results = []
        for page in pages.values():
            ii = (page.get("imageinfo") or [{}])[0]
            url = ii.get("url", "")
            if not url:
                continue
            title = page.get("title", "").replace("File:", "")
            results.append(ImageAsset(
                id=_uid(), title=title,
                source="Wikimedia",
                thumbnail_url=url, full_url=url,
                page_url=f"https://commons.wikimedia.org/wiki/{page.get('title','')}",
                width=0, height=0,
            ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Google
def _search_google(query: str) -> List[ImageAsset]:
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "tbm": "isch", "hl": "en", "num": "30"},
            headers={**_HEADERS, "Accept": "text/html"},
            timeout=12,
        )
        # Extract image JSON blobs from the page
        raw = resp.text
        seen: set = set()
        results = []

        # Pattern: ["https://...",WIDTHInt,HEIGHTInt] inside JS
        for match in re.finditer(
            r'\["(https?://(?!(?:encrypted-tbn|gstatic|google)[./])[^"]{20,}\.(?:jpg|jpeg|png|webp|gif)[^"]*)",(\d+),(\d+)\]',
            raw,
        ):
            url = match.group(1)
            if url in seen:
                continue
            seen.add(url)
            w = int(match.group(2))
            h = int(match.group(3))
            results.append(ImageAsset(
                id=_uid(), title="",
                source="Google",
                thumbnail_url=url, full_url=url,
                page_url="", width=w, height=h,
            ))
            if len(results) >= 30:
                break
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Unsplash
def _search_unsplash(query: str) -> List[ImageAsset]:
    """Unsplash official API (HD). Needs a free Access Key in Settings."""
    key = _setting("unsplash_api_key")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 30, "content_filter": "high"},
            headers={"Authorization": f"Client-ID {key}", **_HEADERS}, timeout=12,
        )
        if r.status_code != 200:
            return []
        results = []
        for p in r.json().get("results", []):
            urls = p.get("urls", {})
            thumb = urls.get("small") or urls.get("thumb") or ""
            full = urls.get("full") or urls.get("regular") or thumb
            if not thumb:
                continue
            results.append(ImageAsset(
                id=str(p.get("id", _uid())), title=p.get("alt_description") or "",
                source="Unsplash", thumbnail_url=thumb, full_url=full,
                page_url=(p.get("links", {}) or {}).get("html", ""),
                author=(p.get("user", {}) or {}).get("name", ""),
                width=p.get("width", 0) or 0, height=p.get("height", 0) or 0,
            ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Pexels
def _search_pexels(query: str) -> List[ImageAsset]:
    # Official API first (HD, reliable) when a free key is configured
    key = _setting("pexels_api_key")
    if key:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 30},
                headers={"Authorization": key, **_HEADERS}, timeout=12,
            )
            if r.status_code == 200:
                out = []
                for photo in r.json().get("photos", []):
                    src = photo.get("src", {})
                    full = src.get("original") or src.get("large2x") or src.get("large") or ""
                    thumb = src.get("medium") or src.get("small") or full
                    if not thumb:
                        continue
                    out.append(ImageAsset(
                        id=str(photo.get("id", _uid())), title=photo.get("alt", ""),
                        source="Pexels", thumbnail_url=thumb, full_url=full,
                        page_url=photo.get("url", ""), author=photo.get("photographer", ""),
                        width=photo.get("width", 0), height=photo.get("height", 0)))
                if out:
                    return out
        except Exception:
            pass
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            f"https://www.pexels.com/search/{requests.utils.quote(query)}/",
            headers={**_HEADERS,
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://www.pexels.com/"},
            timeout=12,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        # Pexels embeds photo data in Next.js __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            try:
                data = json.loads(script.string)
                photos = (data.get("props", {}).get("pageProps", {})
                              .get("photos", []))
                for photo in photos[:30]:
                    src = photo.get("src", {})
                    full = src.get("original") or src.get("large2x") or src.get("large") or ""
                    thumb = src.get("medium") or src.get("small") or full
                    if not full:
                        continue
                    results.append(ImageAsset(
                        id=str(photo.get("id", _uid())),
                        title=photo.get("alt", ""),
                        source="Pexels",
                        thumbnail_url=thumb, full_url=full,
                        page_url=photo.get("url", ""),
                        author=photo.get("photographer", ""),
                        width=photo.get("width", 0),
                        height=photo.get("height", 0),
                    ))
                return results
            except Exception:
                pass

        # Fallback: look for img tags with pexels CDN URLs
        for img in soup.select("img[srcset]")[:30]:
            src = img.get("data-big-src") or img.get("src") or ""
            if "images.pexels.com" in src:
                results.append(ImageAsset(
                    id=_uid(), title=img.get("alt", ""),
                    source="Pexels",
                    thumbnail_url=src, full_url=src,
                    page_url="", width=0, height=0,
                ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Pixabay
def _search_pixabay(query: str) -> List[ImageAsset]:
    # Official API first (HD, reliable) when a free key is configured
    key = _setting("pixabay_api_key")
    if key:
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={"key": key, "q": query, "image_type": "photo",
                        "per_page": 30, "safesearch": "true"},
                headers=_HEADERS, timeout=12,
            )
            if r.status_code == 200:
                out = []
                for hit in r.json().get("hits", []):
                    thumb = hit.get("webformatURL") or hit.get("previewURL") or ""
                    full = hit.get("largeImageURL") or thumb
                    if not thumb:
                        continue
                    out.append(ImageAsset(
                        id=str(hit.get("id", _uid())), title=hit.get("tags", ""),
                        source="Pixabay", thumbnail_url=thumb, full_url=full,
                        page_url=hit.get("pageURL", ""), author=hit.get("user", ""),
                        width=hit.get("imageWidth", 0), height=hit.get("imageHeight", 0)))
                if out:
                    return out
        except Exception:
            pass
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            f"https://pixabay.com/images/search/{requests.utils.quote(query)}/",
            headers={**_HEADERS,
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://pixabay.com/"},
            timeout=12,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # Try Next.js data
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            try:
                data = json.loads(script.string)
                hits = (data.get("props", {}).get("pageProps", {})
                            .get("hits", []))
                for hit in hits[:30]:
                    thumb = hit.get("webformatURL") or hit.get("previewURL") or ""
                    full = hit.get("largeImageURL") or thumb
                    if not thumb:
                        continue
                    results.append(ImageAsset(
                        id=str(hit.get("id", _uid())),
                        title=hit.get("tags", ""),
                        source="Pixabay",
                        thumbnail_url=thumb, full_url=full,
                        page_url=hit.get("pageURL", ""),
                        author=hit.get("user", ""),
                        width=hit.get("imageWidth", 0),
                        height=hit.get("imageHeight", 0),
                    ))
                return results
            except Exception:
                pass

        # Fallback: CDN URL extraction from raw HTML
        raw = resp.text
        urls = re.findall(r'https://cdn\.pixabay\.com/photo/[^\s"\'<>]+\.jpg', raw)
        seen: set = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            results.append(ImageAsset(
                id=_uid(), title="",
                source="Pixabay",
                thumbnail_url=url, full_url=url,
                page_url="", width=0, height=0,
            ))
            if len(results) >= 30:
                break
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Met Museum
def _search_met(query: str) -> List[ImageAsset]:
    try:
        r = requests.get(
            "https://collectionapi.metmuseum.org/public/collection/v1/search",
            params={"q": query, "hasImages": True},
            headers=_WIKI_HEADERS, timeout=12,
        )
        ids = r.json().get("objectIDs") or []
        results = []
        for obj_id in ids[:20]:
            try:
                r2 = requests.get(
                    f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{obj_id}",
                    headers=_WIKI_HEADERS, timeout=8,
                )
                obj = r2.json()
                thumb = obj.get("primaryImageSmall") or obj.get("primaryImage") or ""
                if not thumb:
                    continue
                results.append(ImageAsset(
                    id=str(obj_id),
                    title=obj.get("title", ""),
                    source="Met Museum",
                    thumbnail_url=thumb,
                    full_url=obj.get("primaryImage") or thumb,
                    page_url=obj.get("objectURL", ""),
                    author=obj.get("artistDisplayName", ""),
                    width=0, height=0,
                ))
            except Exception:
                continue
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Art Institute of Chicago
def _search_artic(query: str) -> List[ImageAsset]:
    try:
        r = requests.get(
            "https://api.artic.edu/api/v1/artworks/search",
            params={"q": query, "fields": "id,title,image_id,artist_display", "limit": 20},
            headers=_WIKI_HEADERS, timeout=12,
        )
        iiif_base = r.json().get("config", {}).get("iiif_url", "https://www.artic.edu/iiif/2")
        results = []
        for a in r.json().get("data", []):
            img_id = a.get("image_id") or ""
            if not img_id:
                continue
            thumb = f"{iiif_base}/{img_id}/full/200,/0/default.jpg"
            full = f"{iiif_base}/{img_id}/full/843,/0/default.jpg"
            results.append(ImageAsset(
                id=str(a.get("id", _uid())),
                title=a.get("title", ""),
                source="Art Institute",
                thumbnail_url=thumb,
                full_url=full,
                page_url=f"https://www.artic.edu/artworks/{a.get('id', '')}",
                author=a.get("artist_display", "")[:60],
                width=0, height=0,
            ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------ Library of Congress
def _search_loc(query: str) -> List[ImageAsset]:
    try:
        r = requests.get(
            "https://www.loc.gov/search/",
            params={"q": query, "fo": "json", "fa": "online-format:image", "c": 20},
            headers=_WIKI_HEADERS, timeout=12,
        )
        results = []
        for item in r.json().get("results", []):
            images = item.get("image_url") or []
            thumb = images[0] if images else ""
            if not thumb:
                continue
            full = images[-1] if len(images) > 1 else thumb
            title = item.get("title") or ""
            if isinstance(title, list):
                title = title[0] if title else ""
            results.append(ImageAsset(
                id=_uid(),
                title=str(title),
                source="Lib. of Congress",
                thumbnail_url=thumb,
                full_url=full,
                page_url=item.get("url", ""),
                author="",
                width=0, height=0,
            ))
        return results
    except Exception:
        return []


# ------------------------------------------------------------------
PROVIDERS: Dict[str, Callable] = {
    "bing":      _search_bing,
    "openverse": _search_openverse,
    "unsplash":  _search_unsplash,   # HD — needs free key in Settings
    "pexels":    _search_pexels,     # HD via API key, else best-effort scrape
    "pixabay":   _search_pixabay,    # HD via API key, else best-effort scrape
    "wikimedia": _search_wikimedia,
    "nasa":      _search_nasa,
    "met":       _search_met,
    "loc":       _search_loc,
    "google":    _search_google,
}


def search_images(query: str, max_results: int = 40) -> List[ImageAsset]:
    return _search_bing(query)[:max_results]
