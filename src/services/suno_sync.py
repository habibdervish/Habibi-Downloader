"""SUNO library sync service.

One SunoSync.sync() call:
  1. Fetches all clips from the SUNO feed API.
  2. Downloads artwork (image_url) and audio (audio_url) for new songs.
  3. Updates metadata for songs that already exist.
  4. Removes songs that were deleted from SUNO.
  5. Writes a sync_log record and updates the last_sync setting.
"""

import os
import datetime
import threading
from typing import Callable, List, Optional

import requests

from src.models.song import Song
from src.utils.file_utils import get_thumbnails_dir, get_downloads_dir


def _extract_lyrics(prompt_text: str) -> str:
    """Pull the lyric block from a combined style+lyrics prompt string.

    SUNO's 'lyric' API field is empty when the user embeds lyrics inside the
    prompt box (e.g. '# LYRIC (COPY THIS BOX)' pattern).  This scans for the
    common markers and returns the text that follows.
    """
    if not prompt_text:
        return ""
    upper = prompt_text.upper()
    for marker in (
        "# LYRIC (COPY THIS BOX)",
        "# LYRICS (COPY THIS BOX)",
        "# LYRICS",
        "# LYRIC",
    ):
        idx = upper.find(marker)
        if idx >= 0:
            return prompt_text[idx + len(marker):].strip()
    return ""


def _clip_to_song(clip: dict, existing: Optional[Song] = None) -> Song:
    """Map a SUNO clip dict to a Song, preserving local favorite state."""
    suno_id = clip.get("id", "")
    meta = clip.get("metadata") or {}

    duration = float(
        clip.get("duration")
        or meta.get("duration")
        or 0
    )

    is_fav = bool(existing.is_favorite) if existing else bool(clip.get("is_liked", False))

    return Song(
        id=suno_id,
        suno_id=suno_id,
        title=clip.get("title") or "Untitled",
        artist=clip.get("display_name") or "SUNO",
        album="",
        duration=duration,
        file_path=existing.file_path if existing else None,
        thumbnail_path=existing.thumbnail_path if existing else None,
        source="suno",
        source_url=f"https://suno.com/song/{suno_id}",
        is_favorite=is_fav,
        download_status=existing.download_status if existing else "none",
        added_at=clip.get("created_at", ""),
        prompt=meta.get("prompt") or meta.get("gpt_description_prompt") or "",
        style=meta.get("tags") or "",
        model_version=clip.get("major_model_version") or clip.get("model_name") or "",
        audio_url=clip.get("audio_url") or "",
        image_url=clip.get("image_url") or "",
        lyrics_text=(clip.get("lyric")
                     or _extract_lyrics(meta.get("prompt") or meta.get("gpt_description_prompt") or "")),
        updated_at=clip.get("updated_at") or clip.get("created_at", ""),
    )


def ensure_local_audio(song) -> bool:
    """Ensure the song has a local MP3 (download on demand). Returns True if playable.

    Shared by the Library (Play / Play Selected / Export) and the player's
    Next/Prev resolver so any path can fetch audio that isn't downloaded yet.
    """
    if song.file_path and os.path.exists(song.file_path):
        return True
    audio_url = getattr(song, "audio_url", "")
    if not audio_url:
        return False
    from src.services.storage import storage
    dest = os.path.join(get_downloads_dir(), f"suno_{song.suno_id or song.id}.mp3")
    if not os.path.exists(dest):
        if not _download_file(audio_url, dest, timeout=120):
            return False
    song.file_path = dest
    song.download_status = "complete"
    try:
        storage.save_song(song)
    except Exception:
        pass
    return True


def _download_file(url: str, dest: str, timeout: int = 120) -> bool:
    """Download url → dest. Returns True on success."""
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                fh.write(chunk)
        return True
    except Exception:
        return False


class SunoSync:
    def __init__(self):
        self._running = False
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    def sync(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[int, int, int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """Start a background sync. No-op if a sync is already running."""
        with self._lock:
            if self._running:
                return
            self._running = True

        def _work():
            try:
                self._do_sync(on_progress, on_done)
            except Exception as exc:
                if on_error:
                    on_error(str(exc))
            finally:
                with self._lock:
                    self._running = False

        threading.Thread(target=_work, daemon=True).start()

    # ---------------------------------------------------------------- core
    def _do_sync(
        self,
        on_progress: Optional[Callable[[str], None]],
        on_done: Optional[Callable[[int, int, int], None]],
    ):
        from src.services.suno_api import suno_api
        from src.services.storage import storage

        _prog = on_progress or (lambda _: None)

        _prog("Connecting to SUNO…")
        clips: List[dict] = suno_api.fetch_all()
        total = len(clips)
        _prog(f"Found {total} songs in SUNO library")

        existing_songs = {s.suno_id: s for s in storage.get_all_songs() if s.suno_id}
        suno_ids_fetched = {c["id"] for c in clips if c.get("id")}

        thumbs_dir = get_thumbnails_dir()
        audio_dir  = get_downloads_dir()
        added = updated = removed = 0

        for i, clip in enumerate(clips):
            suno_id = clip.get("id", "")
            if not suno_id:
                continue

            title = clip.get("title") or "…"
            _prog(f"Syncing {i + 1}/{total}: {title}")

            existing = existing_songs.get(suno_id)
            song = _clip_to_song(clip, existing)

            # Artwork — download once; re-download if image_url changed
            img_url = clip.get("image_url") or ""
            if img_url:
                local_img = os.path.join(thumbs_dir, f"suno_{suno_id}.jpg")
                needs_dl = not os.path.exists(local_img) or (
                    existing and existing.image_url != img_url
                )
                if needs_dl:
                    _download_file(img_url, local_img, timeout=30)
                if os.path.exists(local_img):
                    song.thumbnail_path = local_img

            # Audio — do NOT bulk-download during sync (would fetch every MP3,
            # which is slow and rate-limit-prone). Just record the streamable
            # audio_url; the file is downloaded on demand when the user plays
            # or downloads the song. Re-use an already-downloaded local file.
            audio_url = clip.get("audio_url") or ""
            if audio_url:
                local_audio = os.path.join(audio_dir, f"suno_{suno_id}.mp3")
                if existing and existing.file_path and os.path.exists(existing.file_path):
                    song.file_path = existing.file_path
                    song.download_status = "complete"
                elif os.path.exists(local_audio):
                    song.file_path = local_audio
                    song.download_status = "complete"
                else:
                    song.file_path = None
                    song.download_status = "none"

            storage.save_song(song)
            if existing:
                updated += 1
            else:
                added += 1

        # Remove songs deleted from SUNO
        for sid, song in existing_songs.items():
            if sid not in suno_ids_fetched:
                storage.delete_song(song.id)
                removed += 1

        # Persist sync timestamp and log entry
        now_iso = datetime.datetime.utcnow().isoformat()
        storage.set_setting("suno_last_sync", now_iso)
        storage.log_sync("suno", added, updated, removed, "success", "")

        _prog(f"Sync complete: +{added} new, {updated} updated, {removed} removed")
        if on_done:
            on_done(added, updated, removed)

    # -------------------------------------- targeted per-song metadata refresh
    def refresh_songs(
        self,
        suno_ids: List[str],
        on_done: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """Re-fetch metadata for specific songs (used by bulk Refresh action)."""
        def _work():
            try:
                from src.services.suno_api import suno_api
                from src.services.storage import storage
                clips = suno_api.fetch_by_ids(suno_ids)
                existing = {s.suno_id: s for s in storage.get_all_songs() if s.suno_id}
                count = 0
                thumbs_dir = get_thumbnails_dir()
                for clip in clips:
                    sid = clip.get("id", "")
                    if not sid:
                        continue
                    song = _clip_to_song(clip, existing.get(sid))
                    # Keep local paths
                    ex = existing.get(sid)
                    if ex:
                        if ex.file_path and os.path.exists(ex.file_path):
                            song.file_path = ex.file_path
                            song.download_status = "complete"
                        song.thumbnail_path = ex.thumbnail_path
                    # Re-download artwork if URL changed
                    img_url = clip.get("image_url") or ""
                    if img_url:
                        local_img = os.path.join(thumbs_dir, f"suno_{sid}.jpg")
                        if ex and ex.image_url != img_url:
                            _download_file(img_url, local_img, timeout=30)
                        if os.path.exists(local_img):
                            song.thumbnail_path = local_img
                    storage.save_song(song)
                    count += 1
                if on_done:
                    on_done(count)
            except Exception as exc:
                if on_error:
                    on_error(str(exc))

        threading.Thread(target=_work, daemon=True).start()


suno_sync = SunoSync()
