import os
from typing import Callable, Optional
from src.utils.file_utils import is_audio_file, is_image_file, is_lyrics_file, generate_id
from src.models.song import Song
from src.models.image_asset import ImageAsset
from src.services.storage import storage


def pick_folder() -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select folder to scan")
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def scan_folder(
    path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict:
    audio_files = []
    image_files = []
    lyrics_files = []

    all_files = []
    for root, dirs, files in os.walk(path):
        for f in files:
            all_files.append(os.path.join(root, f))

    total = len(all_files)

    for idx, filepath in enumerate(all_files):
        if progress_callback:
            progress_callback(idx + 1, total)

        if is_audio_file(filepath):
            song = _process_audio(filepath)
            if song:
                audio_files.append(song)
                storage.save_song(song)

        elif is_image_file(filepath):
            img = _process_image(filepath)
            if img:
                image_files.append(img)
                storage.save_image(img)

        elif is_lyrics_file(filepath):
            lyrics_files.append(filepath)

    return {
        "audio": audio_files,
        "images": image_files,
        "lyrics": lyrics_files,
    }


def _process_audio(filepath: str) -> Optional[Song]:
    try:
        import tinytag

        tag = tinytag.TinyTag.get(filepath)
        song_id = generate_id(filepath)

        return Song(
            id=song_id,
            title=tag.title or os.path.splitext(os.path.basename(filepath))[0],
            artist=tag.artist or "Unknown Artist",
            album=tag.album or "",
            duration=tag.duration or 0,
            file_path=filepath,
            source="local",
            download_status="complete",
        )
    except ImportError:
        song_id = generate_id(filepath)
        return Song(
            id=song_id,
            title=os.path.splitext(os.path.basename(filepath))[0],
            file_path=filepath,
            source="local",
            download_status="complete",
        )
    except Exception:
        return None


def _process_image(filepath: str) -> Optional[ImageAsset]:
    try:
        from PIL import Image

        img = Image.open(filepath)
        w, h = img.size

        return ImageAsset(
            id=generate_id(filepath),
            title=os.path.splitext(os.path.basename(filepath))[0],
            source="local",
            thumbnail_url=filepath,
            full_url=filepath,
            width=w,
            height=h,
            local_path=filepath,
            download_status="complete",
        )
    except Exception:
        return None
