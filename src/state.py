from dataclasses import dataclass, field
from typing import List, Optional, Callable


@dataclass
class AppState:
    _listeners: List[Callable] = field(default_factory=list)

    current_view: str = "library"
    search_query: str = ""
    selected_song_ids: set = field(default_factory=set)

    library_view_mode: str = "grid"
    songs: list = field(default_factory=list)
    filtered_songs: list = field(default_factory=list)

    search_results: list = field(default_factory=list)
    search_loading: bool = False

    image_results: list = field(default_factory=list)
    image_loading: bool = False

    download_queue: list = field(default_factory=list)
    active_downloads: int = 0
    download_speed: str = ""
    download_progress: float = 0.0

    scanner_status: str = "idle"
    scanner_progress: float = 0.0
    scanned_files: int = 0

    settings: dict = field(default_factory=lambda: {
        "download_folder": "",
        "theme": "dark",            # dark | light | system
        "accent": "green",          # green | blue | purple | orange
        "concurrent_downloads": 2,  # 1 | 2 | 4 | 8
        "auto_cover": True,
        "generate_lyrics": False,
        "auto_add_library": True,
        "whisper_model": "base",
        # SUNO
        "suno_cookie": "",
        "suno_auto_sync": False,
        "suno_sync_interval": "15m",  # 5m | 15m | 30m | 1h
    })

    def subscribe(self, callback: Callable):
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            cb()

    def set_view_refresher(self, callback: Callable):
        self._view_refresh = callback

    def _notify_view_refresh(self):
        cb = getattr(self, "_view_refresh", None)
        if cb:
            cb()

    def set_view(self, view: str):
        self.current_view = view
        self._notify()

    def set_search(self, query: str):
        self.search_query = query
        self._notify()

    def toggle_song_selection(self, song_id: str):
        if song_id in self.selected_song_ids:
            self.selected_song_ids.remove(song_id)
        else:
            self.selected_song_ids.add(song_id)
        self._notify()

    def clear_selection(self):
        self.selected_song_ids.clear()
        self._notify()

    def set_songs(self, songs: list):
        self.songs = songs
        self.filtered_songs = list(songs)
        self._notify()

    def set_filtered_songs(self, songs: list):
        self.filtered_songs = songs
        self._notify()

    def set_search_results(self, results: list):
        self.search_results = results
        self.search_loading = False
        self._notify()

    def set_search_loading(self, loading: bool):
        self.search_loading = loading
        self._notify()

    def set_image_results(self, results: list):
        self.image_results = results
        self.image_loading = False
        self._notify()

    def set_image_loading(self, loading: bool):
        self.image_loading = loading
        self._notify()

    def add_download(self, download):
        self.download_queue.append(download)
        self.active_downloads = len([d for d in self.download_queue if d.status == "downloading"])
        self._notify()

    def update_download(self, download_id: str, **kwargs):
        for d in self.download_queue:
            if d.id == download_id:
                for k, v in kwargs.items():
                    setattr(d, k, v)
                break
        self.active_downloads = len([d for d in self.download_queue if d.status in ("downloading", "queued")])
        self._notify()

    def remove_download(self, download_id: str):
        self.download_queue = [d for d in self.download_queue if d.id != download_id]
        self.active_downloads = len([d for d in self.download_queue if d.status in ("downloading", "queued")])
        self._notify()

    def set_scanner_status(self, status: str, progress: float = 0.0, files: int = 0):
        self.scanner_status = status
        self.scanner_progress = progress
        self.scanned_files = files
        self._notify()

    songs_loaded: bool = False

    # SUNO connection state
    suno_connected: bool = False
    suno_syncing: bool = False
    suno_sync_progress: str = ""
    suno_last_sync: Optional[str] = None   # ISO timestamp or None
    suno_source: str = ""                  # e.g. "Chrome (Default)"

    settings_drawer_open: bool = False

    lyrics_song_id: Optional[str] = None
    lyrics_data: Optional[object] = None
    lyrics_mode: str = "view"
    lyrics_playing: bool = False
    lyrics_position: float = 0.0

    def set_lyrics_song(self, song_id: Optional[str], lyrics_data=None):
        self.lyrics_song_id = song_id
        self.lyrics_data = lyrics_data
        self._notify()

    def set_lyrics_mode(self, mode: str):
        self.lyrics_mode = mode
        self._notify()

    def set_lyrics_position(self, pos: float):
        self.lyrics_position = pos
        self._notify()

    def update_setting(self, key: str, value):
        self.settings[key] = value
        self._notify()


state = AppState()
