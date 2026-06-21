import os
import hashlib
import time
from typing import Optional


def get_app_data_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), ".habibi")
    os.makedirs(base, exist_ok=True)
    return base


def get_db_path() -> str:
    return os.path.join(get_app_data_dir(), "library.db")


def get_downloads_dir() -> str:
    path = os.path.join(get_app_data_dir(), "downloads")
    os.makedirs(path, exist_ok=True)
    return path


def get_thumbnails_dir() -> str:
    path = os.path.join(get_app_data_dir(), "thumbnails")
    os.makedirs(path, exist_ok=True)
    return path


def get_lyrics_dir() -> str:
    path = os.path.join(get_app_data_dir(), "lyrics")
    os.makedirs(path, exist_ok=True)
    return path


def generate_id(source: str = "") -> str:
    raw = f"{source}_{time.time_ns()}_{os.urandom(8).hex()}"
    return hashlib.md5(raw.encode()).hexdigest()


def hash_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read(65536)).hexdigest()
    except Exception:
        return None


AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
LYRICS_EXTENSIONS = {".lrc", ".txt"}


def is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def is_lyrics_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in LYRICS_EXTENSIONS
