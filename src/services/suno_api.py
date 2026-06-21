"""SUNO API client.

Authentication flow:
  1. User pastes their browser __client cookie from suno.com into Settings.
  2. We call Clerk to resolve the session ID and obtain a short-lived JWT.
  3. JWT is used in Authorization: Bearer headers for all studio-api calls.
  4. Token is refreshed automatically before expiry (Clerk tokens last ~60 s).
"""

import time
import threading
from typing import List, Optional

import requests


_CLERK_BASE = "https://clerk.suno.com/v1/client"
_STUDIO_URL = "https://studio-api-prod.suno.com"
_CLERK_VER  = "5.35.0"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)


class SunoApi:
    def __init__(self):
        self._cookie: str = ""
        self._jwt: Optional[str] = None
        self._jwt_exp: float = 0.0
        self._session_id: Optional[str] = None
        self._lock = threading.Lock()
        self._keepalive_running = False

    # ---------------------------------------------------------------- config
    @property
    def is_configured(self) -> bool:
        return bool(self._cookie)

    def configure(self, cookie: str):
        with self._lock:
            self._cookie = cookie.strip()
            self._jwt = None
            self._jwt_exp = 0.0
            self._session_id = None

    # --------------------------------------------------------- keep-alive
    def start_keepalive(self):
        """Background thread: refresh JWT every 45 s so the session never expires."""
        if self._keepalive_running:
            return
        self._keepalive_running = True
        threading.Thread(target=self._keepalive_loop, daemon=True).start()

    def stop_keepalive(self):
        self._keepalive_running = False

    def _keepalive_loop(self):
        import time
        while self._keepalive_running:
            time.sleep(45)
            if not self._cookie:
                continue
            try:
                self._get_jwt()
            except Exception:
                pass  # will retry on next tick

    # ---------------------------------------------------------------- auth
    def _clerk_headers(self) -> dict:
        return {"Cookie": f"__client={self._cookie}", "User-Agent": _UA}

    def _api_headers(self, jwt: str) -> dict:
        return {
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
            "User-Agent": _UA,
        }

    def _resolve_session_id(self) -> str:
        resp = requests.get(
            _CLERK_BASE,
            headers=self._clerk_headers(),
            params={"_clerk_js_version": _CLERK_VER},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        # Clerk wraps the payload in a "response" key
        payload = body.get("response", body)
        # Try last_active_session first, then scan sessions list
        session = payload.get("last_active_session")
        if not session:
            for s in payload.get("sessions", []):
                if s.get("status") == "active":
                    session = s
                    break
        if not session:
            raise ValueError(
                "No active SUNO session found. "
                "Check your cookie or log in to suno.com again."
            )
        return session["id"]

    def _refresh_jwt(self) -> str:
        if not self._session_id:
            self._session_id = self._resolve_session_id()
        resp = requests.post(
            f"{_CLERK_BASE}/sessions/{self._session_id}/tokens",
            headers=self._clerk_headers(),
            params={"_clerk_js_version": _CLERK_VER},
            timeout=15,
        )
        if resp.status_code == 404:
            # Session expired — re-resolve
            self._session_id = self._resolve_session_id()
            resp = requests.post(
                f"{_CLERK_BASE}/sessions/{self._session_id}/tokens",
                headers=self._clerk_headers(),
                params={"_clerk_js_version": _CLERK_VER},
                timeout=15,
            )
        resp.raise_for_status()
        data = resp.json()
        jwt = data.get("jwt") or data.get("token") or ""
        if not jwt:
            raise ValueError("Clerk returned empty JWT. Cookie may be expired.")
        self._jwt = jwt
        self._jwt_exp = time.time() + 50  # refresh 10 s before the 60-s expiry
        return jwt

    def _get_jwt(self) -> str:
        with self._lock:
            if not self._cookie:
                raise ValueError("SUNO cookie not set. Configure in Settings → SUNO.")
            if not self._jwt or time.time() >= self._jwt_exp:
                self._refresh_jwt()
            return self._jwt  # type: ignore[return-value]

    # ------------------------------------------------------------ API calls
    def fetch_page(self, page: int = 0, page_size: int = 20) -> tuple:
        """
        Fetch one page from the v2 feed.

        Returns (clips: list[dict], has_more: bool).
        The v2 endpoint paginates correctly and reports `has_more`, unlike the
        legacy /api/feed/ which returned a full page for every index (causing
        runaway pagination and 429 rate-limit errors).
        """
        jwt = self._get_jwt()
        resp = requests.get(
            f"{_STUDIO_URL}/api/feed/v2/",
            headers=self._api_headers(jwt),
            params={"page": page, "page_size": page_size},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data, len(data) >= page_size
        clips = data.get("clips") or data.get("data", {}).get("clips") or []
        has_more = bool(data.get("has_more"))
        return clips, has_more

    def fetch_all(self, on_progress=None) -> List[dict]:
        """
        Paginate through the entire SUNO library, excluding trashed clips.

        Resilient to SUNO's rate limiter: on HTTP 429 it backs off (honouring
        Retry-After) and retries; if the limit is persistent it returns whatever
        was fetched so far instead of raising, so the sync still saves songs.
        Clips are de-duplicated by id.
        """
        import time as _time
        all_clips: List[dict] = []
        seen = set()
        page = 0
        page_size = 20
        max_pages = 150          # hard safety cap (~3000 songs)
        consecutive_429 = 0
        while page < max_pages:
            try:
                batch, has_more = self.fetch_page(page=page, page_size=page_size)
                consecutive_429 = 0
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code == 429:
                    consecutive_429 += 1
                    if consecutive_429 > 5:
                        break  # give up paging — return what we have
                    wait = 6.0
                    try:
                        ra = e.response.headers.get("Retry-After")
                        if ra:
                            wait = min(float(ra), 30.0)
                    except Exception:
                        pass
                    _time.sleep(wait)
                    continue  # retry the same page
                # Any other HTTP error: stop with partial results
                break

            if not batch:
                break
            new = [c for c in batch if c.get("id") and c.get("id") not in seen]
            for c in new:
                seen.add(c["id"])
            all_clips.extend(new)
            if on_progress:
                try:
                    on_progress(len(all_clips))
                except Exception:
                    pass
            if not has_more or not new:
                break
            page += 1
            _time.sleep(1.0)  # gentle pacing to avoid the rate limiter
        return [c for c in all_clips if not c.get("is_trashed", False)]

    def fetch_by_ids(self, suno_ids: List[str]) -> List[dict]:
        """Fetch specific clips by their SUNO IDs (for metadata refresh)."""
        jwt = self._get_jwt()
        id_str = ",".join(suno_ids)
        resp = requests.get(
            f"{_STUDIO_URL}/api/feed/",
            headers=self._api_headers(jwt),
            params={"ids": id_str},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("clips") or data.get("data", {}).get("clips") or []

    def validate_cookie(self) -> bool:
        """Return True if the stored cookie can produce an active session."""
        try:
            with self._lock:
                self._session_id = None
            self._resolve_session_id()
            return True
        except Exception:
            return False


suno_api = SunoApi()
