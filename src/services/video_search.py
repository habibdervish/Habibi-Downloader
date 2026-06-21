"""Video search — YouTube, Vimeo, Dailymotion. Pure scraping via yt-dlp."""

import uuid
import requests
from typing import List, Dict, Callable

from src.models.video_result import VideoResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

PROVIDER_LABELS = [
    {"key": "youtube",     "label": "YouTube"},
    {"key": "dailymotion", "label": "Dailymotion"},
    {"key": "bilibili",    "label": "Bilibili"},
    {"key": "archive",     "label": "Archive.org"},
    {"key": "peertube",    "label": "PeerTube"},
    {"key": "odysee",      "label": "Odysee"},
    {"key": "vimeo",       "label": "Vimeo"},
]


def _uid(prefix: str, raw: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{raw}"))


def _yt_entry_to_video(entry: dict, source: str) -> VideoResult:
    vid_id = entry.get("id", "")
    thumb = entry.get("thumbnail") or ""
    if not thumb:
        thumbs = entry.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url", "")
    url = entry.get("webpage_url") or entry.get("url") or ""
    if source == "youtube" and vid_id and not url:
        url = f"https://youtube.com/watch?v={vid_id}"
    return VideoResult(
        id=_uid(source, vid_id or url),
        title=entry.get("title") or "Unknown",
        channel=entry.get("uploader") or entry.get("channel") or source.title(),
        duration=float(entry.get("duration") or 0),
        views=int(entry.get("view_count") or 0),
        thumbnail_url=thumb,
        source_url=url,
        source=source,
        description=entry.get("description") or "",
    )


def _search_youtube(query: str) -> List[VideoResult]:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch20:{query}", download=False)
            return [_yt_entry_to_video(e, "youtube") for e in (info.get("entries") or []) if e]
    except Exception:
        return []


def _search_vimeo(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://api.vimeo.com/videos",
            params={"query": query, "per_page": 20, "sort": "relevant"},
            headers={**_HEADERS, "Authorization": "Bearer ..."},
            timeout=10,
        )
        # Vimeo API needs token — fall back to their public search page
        if resp.status_code == 401:
            raise Exception("no token")
        results = []
        for v in resp.json().get("data", []):
            thumb = ""
            pics = v.get("pictures", {}).get("sizes", [])
            if pics:
                thumb = pics[-1].get("link", "")
            results.append(VideoResult(
                id=_uid("vimeo", str(v.get("uri", ""))),
                title=v.get("name", "Unknown"),
                channel=v.get("user", {}).get("name", "Vimeo"),
                duration=float(v.get("duration") or 0),
                views=int(v.get("stats", {}).get("plays") or 0),
                thumbnail_url=thumb,
                source_url=v.get("link", ""),
                source="vimeo",
            ))
        return results
    except Exception:
        pass
    # Fallback: yt-dlp Vimeo search URL
    try:
        from yt_dlp import YoutubeDL
        url = f"https://vimeo.com/search?q={requests.utils.quote(query)}"
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True,
                        "playlistend": 20}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and "entries" in info:
                return [_yt_entry_to_video(e, "vimeo") for e in (info.get("entries") or []) if e]
    except Exception:
        pass
    return []


def _search_dailymotion(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://api.dailymotion.com/videos",
            params={
                "search": query,
                "fields": "id,title,owner.screenname,duration,views_total,thumbnail_large_url,url",
                "limit": 20,
            },
            headers=_HEADERS, timeout=10,
        )
        results = []
        for v in resp.json().get("list", []):
            results.append(VideoResult(
                id=_uid("dailymotion", v.get("id", "")),
                title=v.get("title", "Unknown"),
                channel=v.get("owner.screenname", "Dailymotion"),
                duration=float(v.get("duration") or 0),
                views=int(v.get("views_total") or 0),
                thumbnail_url=v.get("thumbnail_large_url", ""),
                source_url=v.get("url", ""),
                source="dailymotion",
            ))
        return results
    except Exception:
        return []


def _search_archive(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"subject:movie mediatype:movies {query}",
                "fl[]": "identifier,title,description,creator,year,downloads",
                "output": "json", "rows": 15,
            },
            headers=_HEADERS, timeout=12,
        )
        results = []
        for d in resp.json().get("response", {}).get("docs", []):
            ident = d.get("identifier", "")
            if not ident:
                continue
            results.append(VideoResult(
                id=_uid("archive", ident),
                title=d.get("title", ident),
                channel=d.get("creator", "Archive.org"),
                duration=0,
                views=int(d.get("downloads") or 0),
                thumbnail_url=f"https://archive.org/services/img/{ident}",
                source_url=f"https://archive.org/details/{ident}",
                source="archive",
                description=d.get("description", ""),
            ))
        return results
    except Exception:
        return []


def _search_bilibili(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/search/all/v2",
            params={"keyword": query},
            headers={**_HEADERS, "Referer": "https://www.bilibili.com"},
            timeout=12,
        )
        result_groups = resp.json().get("data", {}).get("result", [])
        vid_group = next((g for g in result_groups if g.get("result_type") == "video"), {})
        results = []
        for v in vid_group.get("data", [])[:20]:
            bvid = v.get("bvid", "")
            pic = v.get("pic", "")
            if pic.startswith("//"):
                pic = "https:" + pic
            results.append(VideoResult(
                id=_uid("bilibili", bvid or v.get("arcurl", "")),
                title=v.get("title", "Unknown").replace("<em class=\"keyword\">", "").replace("</em>", ""),
                channel=v.get("author", "Bilibili"),
                duration=0,
                views=int(v.get("play") or 0),
                thumbnail_url=pic,
                source_url=f"https://www.bilibili.com/video/{bvid}" if bvid else v.get("arcurl", ""),
                source="bilibili",
            ))
        return results
    except Exception:
        return []


def _search_peertube(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://sepiasearch.org/api/v1/search/videos",
            params={"search": query, "count": 20},
            headers=_HEADERS, timeout=12,
        )
        results = []
        for v in resp.json().get("data", []):
            host = v.get("channel", {}).get("host", "")
            uuid = v.get("uuid", "")
            url = f"https://{host}/videos/watch/{uuid}" if host else ""
            thumb = v.get("thumbnailPath", "")
            if thumb and not thumb.startswith("http"):
                thumb = f"https://{host}{thumb}"
            results.append(VideoResult(
                id=_uid("peertube", uuid or url),
                title=v.get("name", "Unknown"),
                channel=v.get("channel", {}).get("displayName", host),
                duration=float(v.get("duration") or 0),
                views=int(v.get("views") or 0),
                thumbnail_url=thumb,
                source_url=url,
                source="peertube",
            ))
        return results
    except Exception:
        return []


def _search_odysee(query: str) -> List[VideoResult]:
    try:
        resp = requests.get(
            "https://lighthouse.lbry.com/search",
            params={"s": query, "mediaType": "video", "size": 20, "nsfw": "false"},
            headers=_HEADERS, timeout=12,
        )
        results = []
        for d in resp.json():
            name = d.get("name", "")
            cid = d.get("claimId", "")
            if not (name and cid):
                continue
            results.append(VideoResult(
                id=_uid("odysee", cid),
                title=name.replace("-", " ").title(),
                channel=d.get("channel_claim_id", "Odysee")[:30],
                duration=0,
                views=0,
                thumbnail_url="",
                source_url=f"https://odysee.com/{name}:{cid}",
                source="odysee",
            ))
        return results
    except Exception:
        return []


PROVIDERS: Dict[str, Callable] = {
    "youtube":     _search_youtube,
    "dailymotion": _search_dailymotion,
    "bilibili":    _search_bilibili,
    "archive":     _search_archive,
    "peertube":    _search_peertube,
    "odysee":      _search_odysee,
    "vimeo":       _search_vimeo,
}
