"""Threaded download manager.

YouTube sources are fetched with yt-dlp + FFmpeg (extracted to mp3 with embedded
cover art). Direct URLs and images are streamed over HTTP. The manager runs
worker threads gated by the user's "concurrent downloads" setting and reports
progress back to the UI through a registered async callback scheduled on the
Flet page event loop.
"""

import os
import time
import queue
import threading

import requests

from src.models.download import DownloadTask
from src.models.song import Song
from src.state import state
from src.utils.file_utils import (
    get_downloads_dir,
    get_thumbnails_dir,
    generate_id,
    is_audio_file,
)


class _Cancelled(Exception):
    pass


class DownloadManager:
    def __init__(self):
        self._queue: "queue.Queue[DownloadTask]" = queue.Queue()
        self._tasks: dict = {}
        self._page = None
        self._on_update = None
        self._dispatcher: threading.Thread = None
        self._started = False
        self._last_emit = 0.0

    # ------------------------------------------------------------------ setup
    def configure(self, page, on_update=None):
        """Bind the Flet page and an async UI refresh callback."""
        self._page = page
        if on_update is not None:
            self._on_update = on_update

    def start(self):
        if self._started:
            return
        self._started = True
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()

    # --------------------------------------------------------------- public API
    def enqueue(self, task: DownloadTask):
        task.status = "queued"
        self._tasks[task.id] = task
        state.add_download(task)
        self._queue.put(task)
        self._emit(force=True)

    def pause(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status in ("downloading", "queued"):
            task.status = "paused"
            state.update_download(task_id, status="paused")
            self._emit(force=True)

    def resume(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status == "paused":
            task.status = "downloading"
            state.update_download(task_id, status="downloading")
            self._emit(force=True)

    def cancel(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status not in ("complete",):
            task.status = "cancelled"
            state.update_download(task_id, status="cancelled")
            self._emit(force=True)

    def retry(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status in ("failed", "cancelled"):
            task.error = ""
            task.progress = 0.0
            task.speed = ""
            task.eta = ""
            task.status = "queued"
            state.update_download(task_id, status="queued", progress=0.0, error="")
            self._queue.put(task)
            self._emit(force=True)

    def clear_completed(self):
        for task in list(self._tasks.values()):
            if task.status in ("complete", "cancelled", "failed"):
                self._tasks.pop(task.id, None)
                state.remove_download(task.id)
        self._emit(force=True)

    # ------------------------------------------------------------- dispatching
    def _concurrency(self) -> int:
        try:
            return max(1, int(state.settings.get("concurrent_downloads", 3)))
        except (TypeError, ValueError):
            return 3

    def _active_count(self) -> int:
        return len([t for t in self._tasks.values() if t.status == "downloading"])

    def _dispatch_loop(self):
        while True:
            task = self._queue.get()
            if task.status in ("cancelled", "complete"):
                continue
            while self._active_count() >= self._concurrency():
                time.sleep(0.2)
            threading.Thread(target=self._run_task, args=(task,), daemon=True).start()

    def _run_task(self, task: DownloadTask):
        if task.status == "cancelled":
            return
        task.status = "downloading"
        state.update_download(task.id, status="downloading")
        self._emit(force=True)
        try:
            if task.kind == "image":
                self._download_http(task, is_image=True)
            elif task.kind == "direct":
                self._download_http(task, is_image=False)
            elif task.kind == "video":
                self._download_youtube(task, video=True)
            else:
                self._download_youtube(task)

            if task.status == "cancelled":
                self._cleanup_partial(task)
                return

            task.status = "complete"
            task.progress = 1.0
            state.update_download(task.id, status="complete", progress=1.0)
            self._on_complete(task)
        except _Cancelled:
            self._cleanup_partial(task)
            task.status = "cancelled"
            state.update_download(task.id, status="cancelled")
        except Exception as ex:  # noqa: BLE001 - surface any failure to the UI
            task.status = "failed"
            task.error = str(ex)
            state.update_download(task.id, status="failed", error=task.error)
        finally:
            self._emit(force=True)

    # ----------------------------------------------------------- youtube/yt-dlp
    def _download_youtube(self, task: DownloadTask, video: bool = False):
        from yt_dlp import YoutubeDL

        out_dir = get_downloads_dir()
        outtmpl = os.path.join(out_dir, f"%(title).80s__{task.id}.%(ext)s")

        def hook(d):
            self._wait_if_paused(task)
            if task.status == "cancelled":
                raise _Cancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                task.file_size = total
                task.progress = (done / total) if total else 0.0
                task.speed = _format_speed(d.get("speed") or 0)
                task.eta = _format_eta(d.get("eta") or 0)
                state.update_download(
                    task.id, progress=task.progress, speed=task.speed, eta=task.eta
                )
                self._emit()
            elif d.get("status") == "finished":
                task.progress = 0.98  # downloaded; FFmpeg post-processing now
                task.speed = ""
                task.eta = ""
                state.update_download(task.id, progress=0.98, speed="", eta="Converting…")
                self._emit(force=True)

        if video:
            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "progress_hooks": [hook],
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }
        else:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "progress_hooks": [hook],
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
                    {"key": "FFmpegMetadata"},
                    {"key": "EmbedThumbnail"},
                ],
                "writethumbnail": True,
                # Use mobile/web clients to dodge the common "confirm you're not
                # a bot" interstitial that blocks the default web client.
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }

        # Optionally authenticate with the user's browser cookies, which fully
        # bypasses the bot wall for age/region/login-gated videos.
        browser = (state.settings.get("cookies_browser") or "").strip().lower()
        if browser:
            ydl_opts["cookiesfrombrowser"] = (browser,)

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(task.url, download=True)

        if not task.artist:
            task.artist = info.get("uploader") or info.get("channel") or ""
        # Resolve the produced file path (mp3 for audio, mp4 for video).
        ext = ".mp4" if video else ".mp3"
        produced = os.path.join(out_dir, f"{_safe_title(info.get('title', ''))}__{task.id}{ext}")
        if not os.path.exists(produced):
            produced = self._find_output(out_dir, task.id, video=video)
        task.file_path = produced

    # ------------------------------------------------------------- http stream
    def _download_http(self, task: DownloadTask, is_image: bool):
        if not task.url:
            raise ValueError("No URL provided")

        # Image downloads go to <DownloadFolder>/Images (was a hidden cache dir).
        if is_image:
            out_dir = os.path.join(get_downloads_dir(), "Images")
        else:
            out_dir = get_downloads_dir()
        os.makedirs(out_dir, exist_ok=True)
        ext = _guess_ext(task.url, default=".jpg" if is_image else ".mp3")
        safe = _safe_title(task.title) or "download"
        # Clean filename; only add a short id suffix if the name already exists.
        filepath = os.path.join(out_dir, f"{safe}{ext}")
        if os.path.exists(filepath):
            filepath = os.path.join(out_dir, f"{safe}__{task.id[:6]}{ext}")
        task.file_path = filepath

        with requests.get(task.url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            task.file_size = total
            done = 0
            start = time.time()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    self._wait_if_paused(task)
                    if task.status == "cancelled":
                        raise _Cancelled()
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        task.progress = done / total
                    elapsed = time.time() - start
                    if elapsed > 0:
                        speed = done / elapsed
                        task.speed = _format_speed(speed)
                        if task.progress > 0:
                            task.eta = _format_eta((1 - task.progress) * elapsed / task.progress)
                    state.update_download(
                        task.id, progress=task.progress, speed=task.speed, eta=task.eta
                    )
                    self._emit()

    # ----------------------------------------------------------------- helpers
    def _wait_if_paused(self, task: DownloadTask):
        while task.status == "paused":
            time.sleep(0.3)

    def _cleanup_partial(self, task: DownloadTask):
        path = task.file_path
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _find_output(self, out_dir: str, task_id: str, video: bool = False):
        for name in os.listdir(out_dir):
            if task_id not in name:
                continue
            if video and name.lower().endswith((".mp4", ".mkv", ".webm")):
                return os.path.join(out_dir, name)
            if not video and is_audio_file(name):
                return os.path.join(out_dir, name)
        return None

    def _on_complete(self, task: DownloadTask):
        from src.services.storage import storage

        auto_add = bool(state.settings.get("auto_add_library", True))

        if task.kind in ("image", "video") or task.skip_library:
            return

        song = None
        if task.song_id:
            storage.update_song_status(task.song_id, "complete")
            song = storage.get_song(task.song_id)
            if song:
                song.file_path = task.file_path
                song.download_status = "complete"
                storage.save_song(song)

        if auto_add and task.file_path and os.path.exists(task.file_path):
            if song is None:
                song = Song(
                    id=task.song_id or generate_id("song"),
                    title=task.title,
                    artist=task.artist or "Unknown Artist",
                    file_path=task.file_path,
                    thumbnail_path=task.thumbnail,
                    source="youtube" if task.kind == "youtube" else "download",
                    source_url=task.url,
                    download_status="complete",
                )
                storage.save_song(song)
            # Refresh the in-memory library so the new track shows up.
            try:
                state.set_songs(storage.get_all_songs())
            except Exception:
                pass

        # Auto-generate lyrics if enabled (runs off the download worker thread).
        if song and song.file_path and bool(state.settings.get("generate_lyrics")):
            self._generate_lyrics_async(song)

    def _generate_lyrics_async(self, song):
        def work():
            try:
                from src.services.lyrics_engine import lyrics_engine
                from src.services.storage import storage
                from src.utils.file_utils import get_lyrics_dir
                data = lyrics_engine.generate_with_whisper(
                    song, state.settings.get("whisper_model", "base")
                )
                lrc_path = os.path.join(get_lyrics_dir(), f"{song.id}.lrc")
                storage.save_lyrics_meta(song.id, lrc_path, "whisper", len(data.lines))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _emit(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_emit) < 0.12:
            return
        self._last_emit = now
        cb, page = self._on_update, self._page
        if cb and page:
            try:
                page.run_task(cb)
            except Exception:
                pass


def _safe_title(title: str) -> str:
    keep = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    cleaned = "".join(c for c in (title or "") if c in keep).strip()
    return cleaned[:80]


def _guess_ext(url: str, default: str) -> str:
    base = os.path.splitext(url.split("?")[0])[1].lower()
    return base if base and len(base) <= 5 else default


def _format_speed(bytes_per_sec: float) -> str:
    if not bytes_per_sec:
        return ""
    if bytes_per_sec >= 1_000_000:
        return f"{bytes_per_sec / 1_000_000:.1f} MB/s"
    if bytes_per_sec >= 1_000:
        return f"{bytes_per_sec / 1_000:.0f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


def _format_eta(seconds: float) -> str:
    if not seconds or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


download_manager = DownloadManager()
