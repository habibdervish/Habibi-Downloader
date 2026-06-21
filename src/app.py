import threading
import flet as ft
from src.theme import AppTheme
from src.state import state
from src.navigation.sidebar import build_sidebar
from src.views.library_view import LibraryView
from src.views.search_view import SearchView
from src.views.scanner_view import ScannerView
from src.components.settings_drawer import SettingsDrawer
from src.components.queue_panel import QueuePanel
from src.components.player_bar import PlayerBar
from src.services.storage import storage
from src.services.download_manager import download_manager


class HabibiDownloaderApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self._active_view = None

        self._setup_page()
        self._build_layout()
        self._bind_state()
        self._init_downloads()
        self._start_background_init()

    # ------------------------------------------------------------------ setup
    def _setup_page(self):
        self.page.title = ""
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = AppTheme.BG
        self.page.padding = 0
        # Native desktop window frame (─ □ ✕), resizable.
        self.page.window.title_bar_hidden = False
        self.page.window.resizable = True
        self.page.window.maximizable = True
        self.page.window.width = 1280
        self.page.window.height = 800
        self.page.window.min_width = 900
        self.page.window.min_height = 600
        self.page.on_keyboard_event = self._on_keyboard
        # Ensure audio stops and the process exits when the window is closed
        # (otherwise miniaudio keeps the stream alive after the window is gone).
        self.page.window.prevent_close = False
        self.page.window.on_event = self._on_window_event
        try:
            # Windows taskbar/title-bar icon — multi-size .ico renders crisp
            self.page.window.icon = "icons/habibi_icon.ico"
        except Exception:
            pass

    def _on_window_event(self, e):
        if getattr(e, "type", None) in (ft.WindowEventType.CLOSE, "close"):
            self._shutdown()

    def _shutdown(self):
        try:
            from src.services.player import player
            player.stop()
        except Exception:
            pass
        import os
        os._exit(0)

    def _on_keyboard(self, e: ft.KeyboardEvent):
        if e.ctrl and (e.key or "").upper() == "K":
            try:
                self._global_search.focus()
            except Exception:
                pass

    def _on_global_search(self, e):
        # Debounce 300ms: only filter after the user pauses typing, and refresh
        # the library in place (no full-page rerender per keystroke).
        self._pending_query = e.control.value or ""
        timer = getattr(self, "_search_timer", None)
        if timer is not None:
            timer.cancel()
        self._search_timer = threading.Timer(0.3, self._apply_search)
        self._search_timer.daemon = True
        self._search_timer.start()

    def _apply_search(self):
        query = (getattr(self, "_pending_query", "") or "").strip().lower()
        if not query:
            state.set_filtered_songs(list(state.songs))
        else:
            state.set_filtered_songs([
                s for s in state.songs
                if query in (s.title or "").lower() or query in (s.artist or "").lower()
            ])
        if self.page:
            self.page.run_task(self._refresh_after_search)

    async def _refresh_after_search(self):
        if self._active_view != "library":
            return  # never pull Discovery/Scanner back to Library
        view = self._switcher.content
        if isinstance(view, LibraryView):
            view.refresh_in_place()
        else:
            self._navigate("library")

    def _build_layout(self):
        sidebar = build_sidebar(self.page, on_settings=self._toggle_settings)
        top_bar = self._build_top_bar()
        self._center = LibraryView()
        self._switcher = ft.AnimatedSwitcher(
            content=self._center,
            transition=ft.AnimatedSwitcherTransition.FADE,
            duration=240,
            reverse_duration=140,
            expand=True,
        )
        self._settings_drawer = SettingsDrawer()
        self._queue_panel = QueuePanel()
        self._player_bar = PlayerBar(self.page)
        content_area = ft.Column([top_bar, self._switcher, self._player_bar], spacing=0, expand=True)
        self._layout = ft.Stack(
            [
                ft.Row([sidebar, content_area], spacing=0, expand=True),
                self._queue_panel,
                self._settings_drawer,
            ],
            expand=True,
        )
        self.page.add(self._layout)
        self.page.update()

    def _bind_state(self):
        state.subscribe(self._on_state_change)
        state.set_view_refresher(self._refresh_current_view)

    def _refresh_current_view(self):
        self._navigate(self._active_view or "library")

    def _init_downloads(self):
        download_manager.configure(self.page, on_update=self._refresh_downloads)
        download_manager.start()

    async def _refresh_downloads(self):
        await self._queue_panel.refresh()

    def _toggle_settings(self):
        self._settings_drawer.toggle()

    # ------------------------------------------------------------- navigation
    def _on_state_change(self):
        view = state.current_view
        if view and view != getattr(self, "_active_view", None):
            self._navigate(view)
        self._active_view = state.current_view

    def _navigate(self, view_name: str):
        view = self._create_view(view_name)
        self._switcher.content = view
        try:
            self._switcher.update()
        except (RuntimeError, AssertionError):
            pass
        self._active_view = view_name

    def _create_view(self, name: str) -> ft.Control:
        views = {
            "library": LibraryView,
            "discovery": SearchView,
            "scanner": ScannerView,
        }
        cls = views.get(name, LibraryView)
        return cls()

    # ----------------------------------------------------------------- top bar
    def _build_top_bar(self):
        self._global_search = None
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=140),
                    ft.Container(expand=True),
                    ft.Container(width=140),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            height=60,
            padding=ft.Padding(20, 0, 20, 0),
            bgcolor=AppTheme.PANEL,
            border=ft.Border(bottom=ft.BorderSide(1, AppTheme.BORDER)),
        )

    # ------------------------------------------------------------ background init
    def _start_background_init(self):
        threading.Thread(target=self._init_thread, daemon=True).start()

    def _init_thread(self):
        try:
            storage.connect()
            self._load_settings()
            self._init_suno()
            songs = storage.get_all_songs()
            self._on_songs_ready(songs)
        except Exception as e:
            print(f"init error: {e}")
            self._on_songs_ready([])

    def _init_suno(self):
        """
        Connect to SUNO automatically:
          1. Try to extract the __client cookie directly from Chrome/Edge.
          2. Fall back to the cookie saved in settings from a previous session.
          3. Start a keep-alive thread so the JWT never expires mid-session.
          4. Trigger a background sync if auto-sync is enabled.
        """
        try:
            from src.services.suno_api import suno_api
            from src.services.cookie_extractor import extract_suno_cookie

            # ── 1. try live browser extraction ────────────────────────────
            found = extract_suno_cookie()
            if found:
                cookie, browser = found
                suno_api.configure(cookie)
                # Persist for offline / browser-not-open situations
                storage.set_setting("suno_cookie", cookie)
                state.update_setting("suno_cookie", cookie)
                state.suno_connected = True
                state.suno_source = browser  # informational
                print(f"[SUNO] auto-connected via {browser}")
            else:
                # ── 2. fall back to stored cookie ─────────────────────────
                cookie = state.settings.get("suno_cookie", "")
                if cookie:
                    suno_api.configure(cookie)
                    state.suno_connected = True
                    print("[SUNO] connected via stored cookie")
                else:
                    print("[SUNO] no cookie found — open suno.com in Chrome/Edge first")
                    return

            # ── 3. start keep-alive (refreshes JWT every 45 s) ───────────
            suno_api.start_keepalive()

            # ── 4. load last sync time ────────────────────────────────────
            state.suno_last_sync = storage.get_last_sync_time("suno")

            # ── 5. auto-sync if enabled ───────────────────────────────────
            auto_sync = state.settings.get("suno_auto_sync", False)
            if auto_sync:
                from src.services.suno_sync import suno_sync
                state.suno_syncing = True
                suno_sync.sync(
                    on_done=self._on_startup_sync_done,
                    on_error=self._on_startup_sync_error,
                )

        except Exception as e:
            print(f"SUNO init error: {e}")

    def _on_startup_sync_done(self, added: int, updated: int, removed: int):
        try:
            state.suno_syncing = False
            state.suno_last_sync = storage.get_last_sync_time("suno")
            songs = storage.get_all_songs()
            if self.page:
                self.page.run_task(self._dispatch_songs_reload, songs)
        except Exception as e:
            print(f"startup sync done error: {e}")

    def _on_startup_sync_error(self, err: str):
        state.suno_syncing = False
        print(f"startup sync error: {err}")

    async def _dispatch_songs_reload(self, songs):
        state.set_songs(songs)
        self._navigate(self._active_view or "library")

    def _load_settings(self):
        """Restore persisted settings from the DB into in-memory state."""
        raw = storage.get_all_settings()
        for key, value in raw.items():
            default = state.settings.get(key)
            if isinstance(default, bool):
                state.settings[key] = str(value).lower() in ("true", "1", "yes")
            elif isinstance(default, int):
                try:
                    state.settings[key] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                state.settings[key] = value

        theme = state.settings.get("theme", "dark")
        self.page.theme_mode = {
            "dark": ft.ThemeMode.DARK,
            "light": ft.ThemeMode.LIGHT,
            "system": ft.ThemeMode.SYSTEM,
        }.get(theme, ft.ThemeMode.DARK)

    def _on_songs_ready(self, songs):
        async def _update():
            if songs:
                state.set_songs(songs)
            state.songs_loaded = True
            self._navigate("library")
        try:
            self.page.run_task(_update)
        except Exception as e:
            print(f"dispatch error: {e}")
