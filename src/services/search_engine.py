"""Music search — YouTube, SoundCloud, Bandcamp, Archive.org, Jamendo, FMA, Audiomack, Podcasts."""

import uuid
import requests
from typing import List, Dict, Callable

from src.models.song import Song

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PROVIDER_LABELS = [
    {"key": "youtube",    "label": "YouTube"},
    {"key": "soundcloud", "label": "SoundCloud"},
    {"key": "bandcamp",   "label": "Bandcamp"},
    {"key": "archive",    "label": "Archive.org"},
    {"key": "jamendo",    "label": "Jamendo"},
    {"key": "fma",        "label": "Free Music Archive"},
    {"key": "audiomack",  "label": "Audiomack"},
    {"key": "podcasts",   "label": "Podcasts"},
    {"key": "mixcloud",   "label": "Mixcloud"},
]


def _uid(prefix: str, raw: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{raw}"))


def _yt_to_song(entry: dict, source: str) -> Song:
    vid_id = entry.get("id", "")
    thumb = entry.get("thumbnail") or ""
    if not thumb:
        thumbs = entry.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url", "")
    url = entry.get("webpage_url") or entry.get("url") or ""
    if source == "youtube" and vid_id and not url:
        url = f"https://youtube.com/watch?v={vid_id}"
    return Song(
        id=_uid(source, vid_id or url),
        title=entry.get("title") or "Unknown",
        artist=entry.get("uploader") or entry.get("channel") or source.title(),
        duration=float(entry.get("duration") or 0),
        source=source,
        source_url=url,
        thumbnail_path=thumb,
        download_status="none",
    )


def _search_youtube(query: str) -> List[Song]:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch20:{query}", download=False)
            return [_yt_to_song(e, "youtube") for e in (info.get("entries") or []) if e]
    except Exception:
        return []


def _search_soundcloud(query: str) -> List[Song]:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"scsearch20:{query}", download=False)
            return [_yt_to_song(e, "soundcloud") for e in (info.get("entries") or []) if e]
    except Exception:
        return []


def _search_bandcamp(query: str) -> List[Song]:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            "https://bandcamp.com/search",
            params={"q": query, "item_type": "t"},
            headers=_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".searchresult.track")[:20]:
            heading = item.select_one(".heading a")
            sub = item.select_one(".subhead")
            img = item.select_one(".art img")
            if not heading:
                continue
            url = heading.get("href", "").split("?")[0]
            results.append(Song(
                id=_uid("bandcamp", url),
                title=heading.get_text(strip=True),
                artist=sub.get_text(strip=True) if sub else "Bandcamp",
                duration=0, source="bandcamp", source_url=url,
                thumbnail_path=img.get("src", "") if img else "",
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_archive(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"({query}) AND mediatype:audio",
                "fl[]": ["identifier", "title", "creator"],
                "rows": 20, "output": "json", "page": 1,
            },
            timeout=10,
        )
        results = []
        for doc in resp.json().get("response", {}).get("docs", []):
            ident = doc.get("identifier", "")
            artist = doc.get("creator", "Archive.org")
            if isinstance(artist, list):
                artist = artist[0] if artist else "Archive.org"
            results.append(Song(
                id=_uid("archive", ident),
                title=doc.get("title", ident),
                artist=artist, duration=0,
                source="archive.org",
                source_url=f"https://archive.org/details/{ident}",
                thumbnail_path=f"https://archive.org/services/img/{ident}",
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_jamendo(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://api.jamendo.com/v3.0/tracks/",
            params={
                "client_id": "b6747d04",
                "format": "json", "limit": 20,
                "namesearch": query,
                "audioformat": "mp32", "imagesize": "200",
            },
            timeout=10,
        )
        results = []
        for t in resp.json().get("results", []):
            results.append(Song(
                id=_uid("jamendo", str(t.get("id", ""))),
                title=t.get("name", "Unknown"),
                artist=t.get("artist_name", "Jamendo"),
                duration=float(t.get("duration") or 0),
                source="jamendo",
                source_url=t.get("shareurl", ""),
                thumbnail_path=t.get("image", ""),
                audio_url=t.get("audio", ""),
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_fma(query: str) -> List[Song]:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(
            "https://freemusicarchive.org/search/",
            params={"quicksearch": query},
            headers=_HEADERS, timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for el in soup.select("a[href*='/track/']")[:20]:
            href = el.get("href", "")
            if not href.startswith("http"):
                href = "https://freemusicarchive.org" + href
            title = el.get_text(strip=True)
            if not title:
                continue
            results.append(Song(
                id=_uid("fma", href),
                title=title, artist="FMA",
                duration=0, source="fma",
                source_url=href, thumbnail_path="",
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_audiomack(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://audiomack.com/api/music/search",
            params={"q": query, "type": "song", "limit": 20},
            headers=_HEADERS, timeout=10,
        )
        data = resp.json()
        raw = data.get("results", {})
        items = raw.get("results", []) if isinstance(raw, dict) else raw
        results = []
        for item in items[:20]:
            slug = item.get("url_slug") or item.get("slug") or ""
            a_slug = item.get("artist") or item.get("artist_slug") or ""
            url = f"https://audiomack.com/song/{a_slug}/{slug}" if slug else ""
            results.append(Song(
                id=_uid("audiomack", str(item.get("id", slug))),
                title=item.get("title", "Unknown"),
                artist=item.get("artist_name") or item.get("artist") or "Audiomack",
                duration=0, source="audiomack", source_url=url,
                thumbnail_path=item.get("image_base") or item.get("image") or "",
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_podcasts(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "podcast", "limit": 20},
            timeout=10,
        )
        results = []
        for item in resp.json().get("results", []):
            results.append(Song(
                id=_uid("podcast", str(item.get("trackId", ""))),
                title=item.get("trackName", "Unknown"),
                artist=item.get("artistName", "Podcast"),
                duration=0, source="podcast",
                source_url=item.get("trackViewUrl", ""),
                thumbnail_path=item.get("artworkUrl100", ""),
                audio_url=item.get("feedUrl", ""),
                download_status="none",
            ))
        return results
    except Exception:
        return []


def _search_ccmixter(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://ccmixter.org/api/query",
            params={"f": "json", "search": query, "datasource": "uploads",
                    "sort": "date", "limit": 20},
            headers=_HEADERS, timeout=12,
        )
        results = []
        for item in resp.json():
            audio_url = ""
            for f in item.get("files", []):
                mime = f.get("file_format_info", {}).get("mime_type", "")
                if "mp3" in mime or "mpeg" in mime:
                    audio_url = f.get("download_url", "")
                    break
            page = item.get("file_page_url", "")
            results.append(Song(
                id=_uid("ccmixter", str(item.get("upload_id", _uid("cc", query)))),
                title=item.get("upload_name", "Unknown"),
                artist=item.get("user_real_name") or item.get("user_name", ""),
                source="ccmixter",
                source_url=audio_url or page,
                audio_url=audio_url,
            ))
        return results
    except Exception:
        return []


def _search_mixcloud(query: str) -> List[Song]:
    try:
        resp = requests.get(
            "https://api.mixcloud.com/search/",
            params={"q": query, "type": "cloudcast", "limit": 20},
            headers=_HEADERS, timeout=12,
        )
        results = []
        for item in resp.json().get("data", []):
            results.append(Song(
                id=_uid("mixcloud", item.get("key", _uid("mc", query))),
                title=item.get("name", "Unknown"),
                artist=item.get("user", {}).get("name", ""),
                thumbnail_path=item.get("pictures", {}).get("medium", ""),
                source="mixcloud",
                source_url=f"https://www.mixcloud.com{item.get('key', '')}",
                audio_url="",
            ))
        return results
    except Exception:
        return []


PROVIDERS: Dict[str, Callable] = {
    "youtube":    _search_youtube,
    "soundcloud": _search_soundcloud,
    "bandcamp":   _search_bandcamp,
    "archive":    _search_archive,
    "jamendo":    _search_jamendo,
    "fma":        _search_fma,
    "audiomack":  _search_audiomack,
    "podcasts":   _search_podcasts,
    "mixcloud":   _search_mixcloud,
}


def search_all(query: str, max_results: int = 50) -> List[Song]:
    return _search_youtube(query)[:max_results]
