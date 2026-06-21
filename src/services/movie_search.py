"""Movie discovery — describe a theme / place / scene, get matching movies.

Powered by TMDb (The Movie Database). Two layers:
  1. TMDb text + keyword search  → reliable theme/place/plot matching
       e.g. "Afghanistan" → movies set in / about Afghanistan
  2. Optional AI refinement       → turns a fuzzy free-text scene description
       into a focused query / candidate titles (needs an AI API key)

Standalone: no Library, no Scanner, no local files. Needs a free TMDb API key
stored in settings under "tmdb_api_key" (AI key optional: "ai_api_key").
"""

import requests
from typing import List, Dict, Optional

from src.state import state

_TMDB = "https://api.themoviedb.org/3"
_IMG = "https://image.tmdb.org/t/p/w342"
_BACKDROP = "https://image.tmdb.org/t/p/w780"
_TIMEOUT = 12


def _key() -> str:
    return (state.settings.get("tmdb_api_key") or "").strip()


def has_key() -> bool:
    return bool(_key())


# ───────────────────────────────────────────────────── keyless: Cinemeta (IMDb)
_CINEMETA = "https://v3-cinemeta.strem.io"


def _search_cinemeta(query: str, max_results: int = 30) -> List[dict]:
    """Stremio Cinemeta catalog — keyless, IMDb-backed, includes posters.
    Used when no TMDb key is configured. 'afghanistan' returns themed films."""
    try:
        r = requests.get(f"{_CINEMETA}/catalog/movie/top/search={query}.json",
                         timeout=_TIMEOUT)
        if r.status_code != 200:
            return []
        out = []
        for m in r.json().get("metas", [])[:max_results]:
            imdb = m.get("imdb_id") or m.get("id") or ""
            out.append({
                "id": imdb,
                "title": m.get("name") or "Untitled",
                "year": str(m.get("releaseInfo") or "")[:4],
                "overview": m.get("description") or "",
                "rating": 0,
                "votes": 0,
                "poster": m.get("poster") or "",
                "backdrop": m.get("background") or "",
                "tmdb_url": f"https://www.imdb.com/title/{imdb}/" if imdb else "",
                "imdb_id": imdb,
            })
        return out
    except Exception:
        return []


def get_details(imdb_id: str) -> dict:
    """Fetch full plot + rating + genres for a Cinemeta movie on demand."""
    if not imdb_id:
        return {}
    try:
        r = requests.get(f"{_CINEMETA}/meta/movie/{imdb_id}.json", timeout=_TIMEOUT)
        if r.status_code != 200:
            return {}
        m = r.json().get("meta", {})
        trailers = m.get("trailers") or []
        trailer_id = trailers[0].get("source") if trailers else ""
        return {
            "overview": m.get("description") or "",
            "rating": m.get("imdbRating") or "",
            "genres": ", ".join(m.get("genres", []) or m.get("genre", []) or []),
            "cast": ", ".join((m.get("cast") or [])[:6]),
            "director": ", ".join(m.get("director", []) or []),
            "writer": ", ".join((m.get("writer") or [])[:3]),
            "country": m.get("country") or "",
            "runtime": m.get("runtime") or "",
            "released": (m.get("released") or "")[:10],
            "year": str(m.get("year") or m.get("releaseInfo") or ""),
            "awards": m.get("awards") or "",
            "trailer": (f"https://www.youtube.com/watch?v={trailer_id}" if trailer_id else ""),
        }
    except Exception:
        return {}


# ───────────────────────────────────────────────────── TMDb building blocks
def _to_movie(m: dict) -> Optional[dict]:
    if not m.get("title") and not m.get("name"):
        return None
    date = m.get("release_date") or m.get("first_air_date") or ""
    poster = m.get("poster_path")
    backdrop = m.get("backdrop_path")
    return {
        "id": m.get("id"),
        "title": m.get("title") or m.get("name") or "Untitled",
        "year": (date[:4] if date else ""),
        "overview": m.get("overview") or "",
        "rating": round(float(m.get("vote_average") or 0), 1),
        "votes": int(m.get("vote_count") or 0),
        "poster": (_IMG + poster) if poster else "",
        "backdrop": (_BACKDROP + backdrop) if backdrop else "",
        "tmdb_url": f"https://www.themoviedb.org/movie/{m.get('id')}",
    }


def _search_text(query: str, key: str) -> List[dict]:
    try:
        r = requests.get(f"{_TMDB}/search/movie", params={
            "api_key": key, "query": query, "include_adult": "false",
            "language": "en-US", "page": 1,
        }, timeout=_TIMEOUT)
        return r.json().get("results", []) if r.status_code == 200 else []
    except Exception:
        return []


def _keyword_ids(query: str, key: str) -> List[int]:
    try:
        r = requests.get(f"{_TMDB}/search/keyword", params={
            "api_key": key, "query": query,
        }, timeout=_TIMEOUT)
        items = r.json().get("results", []) if r.status_code == 200 else []
        return [k["id"] for k in items[:3] if k.get("id")]
    except Exception:
        return []


def _discover_by_keywords(ids: List[int], key: str) -> List[dict]:
    if not ids:
        return []
    try:
        r = requests.get(f"{_TMDB}/discover/movie", params={
            "api_key": key, "with_keywords": "|".join(str(i) for i in ids),
            "sort_by": "popularity.desc", "include_adult": "false",
            "language": "en-US", "page": 1,
        }, timeout=_TIMEOUT)
        return r.json().get("results", []) if r.status_code == 200 else []
    except Exception:
        return []


def search_movies(query: str, max_results: int = 30) -> List[dict]:
    """Theme/place/plot search. With a TMDb key, merges TMDb text search with
    keyword discovery so 'Afghanistan' returns both titles mentioning it and
    films tagged with it. With no key, falls back to the keyless iTunes API."""
    query = (query or "").strip()
    if not query:
        return []
    key = _key()
    if not key:
        return _search_cinemeta(query, max_results)

    seen = {}
    # text search first (keeps best title/overview matches on top)
    for raw in _search_text(query, key):
        mv = _to_movie(raw)
        if mv and mv["id"] not in seen:
            seen[mv["id"]] = mv
    # keyword discovery adds thematically-tagged films
    ids = _keyword_ids(query, key)
    for raw in _discover_by_keywords(ids, key):
        mv = _to_movie(raw)
        if mv and mv["id"] not in seen:
            seen[mv["id"]] = mv

    movies = list(seen.values())
    # Prefer ones with a poster + some votes for a cleaner grid
    movies.sort(key=lambda m: (m["poster"] != "", m["votes"]), reverse=True)
    return movies[:max_results]


# ───────────────────────────────────────────────────── optional AI layer
def ai_refine(description: str) -> Optional[str]:
    """If an AI key is configured, turn a fuzzy free-text scene description into
    a focused TMDb search query (or likely title). Returns None if no AI key —
    caller then searches with the raw text, which TMDb still matches on overview.
    """
    ai_key = (state.settings.get("ai_api_key") or "").strip()
    if not ai_key or not description.strip():
        return None
    provider = (state.settings.get("ai_provider") or "").strip().lower()
    prompt = (
        "A user is trying to recall a movie from a vague description. "
        "Given their description, reply with ONLY the most likely movie title "
        "(or 2-3 likely titles separated by commas). No explanation.\n\n"
        f"Description: {description.strip()}"
    )
    try:
        if provider == "openai" or ai_key.startswith("sk-"):
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {ai_key}"},
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 60, "temperature": 0.2},
                timeout=20)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        else:  # default to Anthropic
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ai_key,
                         "anthropic-version": "2023-06-01"},
                json={"model": "claude-haiku-4-5-20251001",
                      "max_tokens": 60,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=20)
            if r.status_code == 200:
                return r.json()["content"][0]["text"].strip()
    except Exception:
        return None
    return None


def search_free_movies(query: str, max_results: int = 40) -> List[dict]:
    """Find FULL movies that are legal & playable in-app: Archive.org's free
    library (public-domain/classic films) + YouTube full free movies.
    Returns playable items: {title, year, thumb, url, source, duration}."""
    results = []
    q = (query or "").strip()
    if not q:
        return []

    # 1) Archive.org — thousands of full, legal, free movies
    try:
        r = requests.get("https://archive.org/advancedsearch.php", params={
            "q": f"({q}) AND mediatype:movies",
            "fl[]": ["identifier", "title", "year"],
            "sort[]": "downloads desc",
            "rows": 25, "output": "json", "page": 1,
        }, headers={"User-Agent": "HabibiDownloaderX/1.0"}, timeout=_TIMEOUT)
        for doc in r.json().get("response", {}).get("docs", []):
            ident = doc.get("identifier", "")
            if not ident:
                continue
            title = doc.get("title", ident)
            if isinstance(title, list):
                title = title[0] if title else ident
            results.append({
                "title": str(title), "year": str(doc.get("year", "") or ""),
                "thumb": f"https://archive.org/services/img/{ident}",
                "url": f"https://archive.org/details/{ident}",
                "source": "Archive.org", "duration": 0,
            })
    except Exception:
        pass

    # 2) YouTube — full free movies (filter out short clips)
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch15:{q} full movie", download=False)
        for e in info.get("entries", []) or []:
            if not e:
                continue
            dur = e.get("duration") or 0
            if dur and dur < 2400:    # < 40 min -> probably a clip, not a full film
                continue
            thumbs = e.get("thumbnails") or []
            vid = e.get("id", "")
            results.append({
                "title": e.get("title", "") or vid,
                "year": "",
                "thumb": thumbs[-1].get("url", "") if thumbs else "",
                "url": e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
                "source": "YouTube", "duration": dur,
            })
    except Exception:
        pass

    return results[:max_results]


def smart_search(description: str, max_results: int = 30) -> Dict:
    """Full pipeline: optionally AI-refine the description, then TMDb search.
    Returns {"query_used", "ai_used", "results"}."""
    refined = ai_refine(description)
    ai_used = bool(refined)
    query = refined or description
    results = search_movies(query, max_results=max_results)
    # If AI gave a comma list and the first query was thin, try each candidate
    if ai_used and len(results) < 3 and "," in (refined or ""):
        for cand in [c.strip() for c in refined.split(",")][:3]:
            for mv in search_movies(cand, max_results=10):
                if mv not in results:
                    results.append(mv)
    return {"query_used": query, "ai_used": ai_used, "results": results[:max_results]}
