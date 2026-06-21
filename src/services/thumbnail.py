import os
import uuid
import requests
from src.utils.file_utils import get_thumbnails_dir


def get_thumbnail(url: str, song_id: str = None) -> str:
    if not url:
        return ""

    local_path = _cached_path(url, song_id)
    if local_path and os.path.exists(local_path):
        return local_path

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            ext = _get_ext(url)
            filename = f"{song_id or uuid.uuid4().hex}{ext}"
            dest = os.path.join(get_thumbnails_dir(), filename)
            with open(dest, "wb") as f:
                f.write(resp.content)
            return dest
    except Exception:
        pass

    return ""


def _cached_path(url: str, song_id: str = None) -> str:
    if not url:
        return ""
    ext = _get_ext(url)
    if song_id:
        candidate = os.path.join(get_thumbnails_dir(), f"{song_id}{ext}")
        if os.path.exists(candidate):
            return candidate
    name = uuid.uuid5(uuid.NAMESPACE_URL, url).hex + ext
    candidate = os.path.join(get_thumbnails_dir(), name)
    if os.path.exists(candidate):
        return candidate
    return ""


def _get_ext(url: str) -> str:
    base = os.path.splitext(url.split("?")[0])[1].lower()
    return base if base in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
