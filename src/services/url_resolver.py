"""Direct URL resolver — auto-detects content type and extracts metadata."""

import re
import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

_AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".opus", ".wma"}
_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4v"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif"}
_DOC_EXTS   = {".pdf", ".doc", ".docx", ".epub", ".zip", ".rar", ".7z"}


def resolve(url: str) -> dict:
    """Return dict: {type, title, thumbnail, duration, author, direct_url, error}."""
    if not url.startswith("http"):
        return {"type": "unknown", "error": "Not a valid URL"}

    # Detect playlists/channels first so the user gets every item, not just one
    playlist = _try_playlist(url)
    if playlist:
        return playlist

    # Try yt-dlp first (handles YouTube, SoundCloud, Vimeo, Bandcamp, etc.)
    result = _try_ytdlp(url)
    if result:
        return result

    # Fall back to HEAD request content-type detection
    return _try_head(url)


def _try_playlist(url: str) -> dict:
    """If the URL is a real playlist, return all its items as a flat list.
    Watch-URLs with a ?list= param are resolved to the full playlist so the
    user can grab every song, not just the one video."""
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url)
    is_playlist_path = "/playlist" in url or "/sets/" in url
    list_id = m.group(1) if m else None
    # Skip YouTube auto-mixes/radios (RD*, UL*) — they're endless, not real lists
    if list_id and list_id[:2] in ("RD", "UL"):
        list_id = None
    if not list_id and not is_playlist_path:
        return {}

    target = (f"https://www.youtube.com/playlist?list={list_id}"
              if list_id else url)
    try:
        from yt_dlp import YoutubeDL
        opts = {"quiet": True, "no_warnings": True,
                "extract_flat": True, "skip_download": True}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info or info.get("_type") != "playlist":
            return {}
        entries = []
        for e in info.get("entries") or []:
            if not e:
                continue
            vid = e.get("id") or ""
            ent_url = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
            if not ent_url:
                continue
            thumbs = e.get("thumbnails") or []
            entries.append({
                "title": e.get("title") or vid or "Untitled",
                "url": ent_url,
                "thumbnail": thumbs[-1].get("url", "") if thumbs else "",
                "duration": float(e.get("duration") or 0),
                "author": e.get("uploader") or e.get("channel") or "",
            })
        if not entries:
            return {}
        return {
            "type": "playlist",
            "title": info.get("title") or "Playlist",
            "author": info.get("uploader") or info.get("channel") or "",
            "count": len(entries),
            "entries": entries,
            "direct_url": target,
            "error": None,
        }
    except Exception:
        return {}


def _try_ytdlp(url: str) -> dict:
    try:
        from yt_dlp import YoutubeDL
        opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": False, "skip_download": True,
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return {}
            kind = "video"
            if info.get("vcodec") == "none" or not info.get("vcodec"):
                kind = "audio"
            thumb = info.get("thumbnail") or ""
            thumbs = info.get("thumbnails") or []
            if not thumb and thumbs:
                thumb = thumbs[-1].get("url", "")
            return {
                "type": kind,
                "title": info.get("title") or url,
                "thumbnail": thumb,
                "duration": float(info.get("duration") or 0),
                "author": info.get("uploader") or info.get("channel") or "",
                "direct_url": url,
                "error": None,
            }
    except Exception:
        return {}


def _try_head(url: str) -> dict:
    try:
        path = url.split("?")[0].lower()
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""

        kind = "unknown"
        if ext in _AUDIO_EXTS:
            kind = "audio"
        elif ext in _VIDEO_EXTS:
            kind = "video"
        elif ext in _IMAGE_EXTS:
            kind = "image"
        elif ext in _DOC_EXTS:
            kind = "document"

        if kind == "unknown":
            resp = requests.head(url, headers=_HEADERS, timeout=8, allow_redirects=True)
            ct = resp.headers.get("Content-Type", "").lower()
            if "audio" in ct:
                kind = "audio"
            elif "video" in ct:
                kind = "video"
            elif "image" in ct:
                kind = "image"
            elif "pdf" in ct or "document" in ct:
                kind = "document"

        title = url.split("/")[-1].split("?")[0] or url
        return {
            "type": kind,
            "title": title,
            "thumbnail": "",
            "duration": 0,
            "author": "",
            "direct_url": url,
            "error": None,
        }
    except Exception as e:
        return {"type": "unknown", "error": str(e), "title": url,
                "thumbnail": "", "duration": 0, "author": "", "direct_url": url}
