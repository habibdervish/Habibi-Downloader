"""Audio playback singleton backed by just_playback (miniaudio).

This avoids Flet's flet_audio control, which the prebuilt desktop client does not
recognise ("Unknown control: Audio"). Position is polled on a daemon thread and
pushed to UI listeners through the Flet page event loop.
"""

import os
import time
import random
import threading
from typing import Callable, List, Optional

from src.models.song import Song

try:
    from just_playback import Playback
except Exception:  # pragma: no cover - dependency missing
    Playback = None


class Player:
    def __init__(self):
        self.page = None
        self._pb = Playback() if Playback else None
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
        # Optional callback(song) -> bool that ensures the song has a local
        # audio file (downloads on demand). Set by the Library.
        self.resolve_fn: Optional[Callable[[Song], bool]] = None
        self._load_token = 0

    # ------------------------------------------------------------------ attach
    def attach(self, page, on_change=None):
        self.page = page
        if on_change is not None:
            self.add_listener(on_change)

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

    # ----------------------------------------------------------------- control
    def set_resolver(self, fn: Callable[[Song], bool]):
        """Register a callback that downloads a song's audio on demand."""
        self.resolve_fn = fn

    def play(self, song: Song, queue: Optional[List[Song]] = None):
        if not song or self._pb is None:
            return
        self.queue = queue or [song]
        try:
            self.index = next(i for i, s in enumerate(self.queue) if s.id == song.id)
        except StopIteration:
            self.queue = [song]
            self.index = 0
        self._load_and_play()

    def _load_and_play(self):
        song = self.current
        if not song or self._pb is None:
            return
        # Invalidate any in-flight load (rapid next/prev clicks)
        self._load_token += 1
        token = self._load_token

        if song.file_path and os.path.exists(song.file_path):
            self._do_load_play(song, token)
            return

        # Needs downloading — do it OFF the UI thread so clicks never freeze
        if not self.resolve_fn:
            return
        self.is_loading = True
        self._emit()

        def _bg():
            ok = False
            try:
                ok = bool(self.resolve_fn(song))
            except Exception:
                ok = False
            # Ignore if a newer load was requested meanwhile
            if token != self._load_token:
                return
            self.is_loading = False
            if ok and song.file_path and os.path.exists(song.file_path):
                self._do_load_play(song, token)
            else:
                self._emit()

        threading.Thread(target=_bg, daemon=True).start()

    def _do_load_play(self, song: Song, token: int):
        if token != self._load_token:
            return
        try:
            self._pb.load_file(song.file_path)
            self._pb.set_volume(self.volume)
            self._pb.play()
        except Exception:
            self.is_loading = False
            self._emit()
            return
        self.is_loading = False
        self.is_playing = True
        self.position = 0.0
        self.duration = song.duration or 0.0
        self._start_poll()
        self._emit()

    def toggle_play(self):
        if self._pb is None or self.current is None:
            return
        try:
            if self.is_playing:
                self._pb.pause()
                self.is_playing = False
            else:
                self._pb.resume()
                self.is_playing = True
        except Exception:
            # Force stop as fallback so audio never gets stuck
            try:
                self._pb.stop()
            except Exception:
                pass
            self.is_playing = False
        self._emit()

    def next(self):
        if not self.queue:
            return
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
        if self._pb is None:
            return
        try:
            self._pb.seek(max(0, seconds))
        except Exception:
            pass
        self.position = seconds
        self._emit()

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.0, vol))
        if self._pb is not None:
            try:
                self._pb.set_volume(self.volume)
            except Exception:
                pass
        self._emit()

    def stop(self):
        """Stop playback and the poll thread (used on app shutdown)."""
        self._poll_running = False
        self.is_playing = False
        try:
            if self._pb is not None:
                self._pb.stop()
        except Exception:
            pass

    def toggle_repeat(self):
        self.repeat = not self.repeat
        self._emit()

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self._emit()

    # ------------------------------------------------------------- poll thread
    def _start_poll(self):
        if self._poll_running:
            return
        self._poll_running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        while self._poll_running and self._pb is not None:
            time.sleep(1.0)
            if not self.is_playing:
                # If underlying audio is still running despite is_playing=False, force stop
                try:
                    if self._pb.playing and not self._pb.paused:
                        self._pb.pause()
                except Exception:
                    pass
                continue
            try:
                self.position = self._pb.curr_pos
                if self._pb.duration:
                    self.duration = self._pb.duration
                finished = not self._pb.playing and not self._pb.paused
            except Exception:
                finished = False
            if finished:
                self._on_finished()
            else:
                self._emit()

    def _on_finished(self):
        if self.repeat:
            self._load_and_play()
        elif len(self.queue) > 1:
            self.next()
        else:
            # Single track finished — stop cleanly instead of replaying
            self.is_playing = False
            self.position = 0.0
            self._emit()

    # ------------------------------------------------------------------- emit
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
