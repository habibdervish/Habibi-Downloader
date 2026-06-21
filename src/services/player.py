"""Unified media player — one engine for Library songs AND Discovery streams.

Primary backend: libmpv via flet-video (plays local files, streamed audio, and
video from a URL). A `just_playback` fallback keeps local audio working if the
video control isn't mounted yet or fails — so the Library never fully breaks.

The UI mounts a single `flet_video.Video` control and registers it with
`set_video()`. Position/duration/auto-next come from the control's events.
"""

import os
import threading
from typing import Callable, List, Optional

from src.models.song import Song

try:
    import flet_video as fv
except Exception:  # pragma: no cover
    fv = None

try:
    from just_playback import Playback
except Exception:  # pragma: no cover
    Playback = None


class Player:
    def __init__(self):
        self.page = None
        self.video = None                 # flet_video.Video, set by the UI
        self._pb = Playback() if Playback else None   # local-audio fallback
        self._using_fallback = False
        self._listeners = []
        self._poll_thread = None
        self._poll_running = False

        self.queue: List[Song] = []
        self.index: int = -1
        self.is_playing: bool = False
        self.position: float = 0.0
        self.duration: float = 0.0
        self.volume: float = 1.0
        self.repeat: bool = False
        self.shuffle: bool = False
        self.is_loading: bool = False
        self.has_video: bool = False      # True when current media shows a picture
        self.resolve_fn: Optional[Callable[[Song], bool]] = None
        self._load_token = 0

    # ------------------------------------------------------------------ attach
    def attach(self, page, on_change=None):
        self.page = page
        if on_change is not None:
            self.add_listener(on_change)

    def set_video(self, video):
        """Register the mounted flet_video.Video control as the primary engine."""
        self.video = video
        try:
            video.on_position_change = self._on_position
            video.on_duration_change = self._on_duration
            video.on_complete = self._on_complete
        except Exception:
            pass

    def add_listener(self, cb):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb):
        if cb in self._listeners:
            self._listeners.remove(cb)

    @property
    def current(self) -> Optional[Song]:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def set_resolver(self, fn: Callable[[Song], bool]):
        self.resolve_fn = fn

    # ----------------------------------------------------------------- play API
    def play(self, song: Song, queue: Optional[List[Song]] = None):
        if not song:
            return
        self.queue = queue or [song]
        try:
            self.index = next(i for i, s in enumerate(self.queue) if s.id == song.id)
        except StopIteration:
            self.queue = [song]
            self.index = 0
        self._load_and_play()

    def play_url(self, url: str, title: str, audio_only: bool = False, thumb: str = ""):
        """Discovery entry point — stream a URL through the same player/UI."""
        if not url:
            return
        s = Song(id="url:" + url, title=title or url, artist="",
                 source_url=url, thumbnail_path=thumb or "")
        s._needs_stream = True       # type: ignore[attr-defined]
        s._audio_only = audio_only   # type: ignore[attr-defined]
        self.play(s, queue=[s])

    def _load_and_play(self):
        song = self.current
        if not song:
            return
        self._load_token += 1
        token = self._load_token
        self.is_loading = True
        self.has_video = False
        self._emit()

        def _bg():
            media = None
            is_stream = bool(getattr(song, "_needs_stream", False))
            audio_only = bool(getattr(song, "_audio_only", False))
            try:
                if is_stream:
                    media = self._resolve_stream(song.source_url, audio_only)
                elif song.file_path and os.path.exists(song.file_path):
                    media = song.file_path
                elif self.resolve_fn:
                    if self.resolve_fn(song) and song.file_path and os.path.exists(song.file_path):
                        media = song.file_path
            except Exception:
                media = None
            if token != self._load_token:
                return
            self.is_loading = False
            if media:
                self.has_video = is_stream and not audio_only
                self._start_media(media, song)
            else:
                self._emit()

        threading.Thread(target=_bg, daemon=True).start()

    def _resolve_stream(self, url: str, audio_only: bool) -> Optional[str]:
        from yt_dlp import YoutubeDL
        fmt = ("bestaudio/best" if audio_only
               else "best[ext=mp4][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/best")
        with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                        "format": fmt}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("url") or (info.get("requested_formats") or [{}])[0].get("url")

    def _start_media(self, media: str, song: Song):
        is_local = os.path.exists(media)
        # Local AUDIO files keep using the proven just_playback engine (zero
        # regression risk for the Library). Streams + video use libmpv.
        if is_local and not self.has_video and self._pb is not None:
            try:
                self._using_fallback = True
                self._pb.load_file(media)
                self._pb.set_volume(self.volume)
                self._pb.play()
                self.is_playing = True
                self.position = 0.0
                self.duration = song.duration or 0.0
                self._start_poll()
                self._emit()
                return
            except Exception:
                pass

        # Streams / video via libmpv (shown in the same Now Playing surface)
        if self.video is not None and fv is not None:
            self._using_fallback = False
            self.is_playing = True
            self.position = 0.0
            self.duration = song.duration or 0.0

            def _apply():
                try:
                    self.video.playlist = [fv.VideoMedia(resource=media)]
                    self.video.volume = int(self.volume * 100)
                    self.video.update()
                    if self.page:
                        self.page.run_task(self.video.play)
                except Exception:
                    pass
            self._run_ui(_apply)
            self._emit()
            return

        # Last-resort local fallback
        if is_local and self._pb is not None:
            try:
                self._using_fallback = True
                self._pb.load_file(media)
                self._pb.set_volume(self.volume)
                self._pb.play()
                self.is_playing = True
                self._start_poll()
                self._emit()
                return
            except Exception:
                pass
        self.is_playing = False
        self._emit()

    # ----------------------------------------------------------------- controls
    def toggle_play(self):
        if self.current is None:
            return
        self.is_playing = not self.is_playing
        if self._using_fallback and self._pb is not None:
            try:
                (self._pb.resume if self.is_playing else self._pb.pause)()
            except Exception:
                pass
        elif self.video is not None and self.page is not None:
            try:
                self.page.run_task(self.video.play if self.is_playing else self.video.pause)
            except Exception:
                pass
        self._emit()

    def next(self):
        if not self.queue:
            return
        import random
        if self.shuffle and len(self.queue) > 1:
            self.index = random.randrange(len(self.queue))
        else:
            self.index = (self.index + 1) % len(self.queue)
        self._load_and_play()

    def prev(self):
        if not self.queue:
            return
        if self.position > 3:
            self.seek(0)
            return
        self.index = (self.index - 1) % len(self.queue)
        self._load_and_play()

    def seek(self, seconds: float):
        seconds = max(0, seconds)
        self.position = seconds
        if self._using_fallback and self._pb is not None:
            try:
                self._pb.seek(seconds)
            except Exception:
                pass
        elif self.video is not None and self.page is not None:
            try:
                self.page.run_task(self.video.seek, seconds)
            except Exception:
                pass
        self._emit()

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, vol))
        if self._using_fallback and self._pb is not None:
            try:
                self._pb.set_volume(self.volume)
            except Exception:
                pass
        elif self.video is not None:
            try:
                self.video.volume = int(self.volume * 100)
                self.video.update()
            except Exception:
                pass
        self._emit()

    def stop(self):
        self._poll_running = False
        self.is_playing = False
        try:
            if self._using_fallback and self._pb is not None:
                self._pb.stop()
            elif self.video is not None and self.page is not None:
                self.page.run_task(self.video.stop)
        except Exception:
            pass

    def toggle_repeat(self):
        self.repeat = not self.repeat
        self._emit()

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self._emit()

    # ------------------------------------------------------- video-control events
    async def _on_position(self, e):
        try:
            v = float(getattr(e, "data", 0) or 0)
            # flet-video reports milliseconds
            self.position = v / 1000.0 if v > 10000 else v
        except Exception:
            return
        self._emit()

    async def _on_duration(self, e):
        try:
            v = float(getattr(e, "data", 0) or 0)
            self.duration = v / 1000.0 if v > 10000 else v
        except Exception:
            return
        self._emit()

    async def _on_complete(self, e):
        if self.repeat:
            self._load_and_play()
        elif len(self.queue) > 1:
            self.next()
        else:
            self.is_playing = False
            self.position = 0.0
            self._emit()

    # ------------------------------------------------------- fallback poll thread
    def _start_poll(self):
        if self._poll_running:
            return
        self._poll_running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        import time
        while self._poll_running and self._pb is not None:
            time.sleep(1.0)
            if not (self._using_fallback and self.is_playing):
                continue
            try:
                self.position = self._pb.curr_pos
                if self._pb.duration:
                    self.duration = self._pb.duration
                finished = not self._pb.playing and not self._pb.paused
            except Exception:
                finished = False
            if finished:
                if self.page:
                    self.page.run_task(self._on_complete, None)
            else:
                self._emit()

    # ------------------------------------------------------------------- helpers
    def _run_ui(self, fn):
        try:
            fn()
        except Exception:
            pass

    def _emit(self):
        page = self.page
        if not page:
            return
        for cb in list(self._listeners):
            try:
                page.run_task(cb)
            except Exception:
                pass


player = Player()
