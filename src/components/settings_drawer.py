import platform
import subprocess
import threading

import flet as ft
from src.theme import AppTheme
from src.state import state


DEFAULTS = {
    "download_folder": "",
    "concurrent_downloads": 2,
    "generate_lyrics": False,
    "auto_cover": True,
    "theme": "dark",
}


class SettingsDrawer(ft.Container):
    """Left slide-in settings drawer (320px)."""

    def __init__(self):
        self._visible = False
        super().__init__(
            width=320,
            top=0, left=0,
            height=800,  # synced to window height in show()
            bgcolor=AppTheme.PANEL,
            border=ft.Border(right=ft.BorderSide(1, AppTheme.BORDER)),
            padding=ft.Padding(20, 20, 20, 20),
            animate_offset=AppTheme.transition,
            offset=ft.Offset(-1.5, 0),
            shadow=ft.BoxShadow(blur_radius=24, color=ft.Colors.BLACK54),
        )
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        from src.utils.file_utils import get_downloads_dir
        custom = (state.settings.get("download_folder") or "").strip()
        self._folder_display = ft.Text(
            custom or get_downloads_dir(),  # show the real effective folder
            size=12, color=AppTheme.TEXT_SECONDARY, max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS, expand=True,
        )

        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Settings", size=18, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                        ft.IconButton(ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
                                      on_click=lambda _: self.hide()),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Column(
                    [
                        self._label("Download folder"),
                        ft.Row(
                            [self._folder_display,
                             AppTheme.secondary_button("Browse", on_click=self._browse_folder)],
                            spacing=8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self._divider(),

                        self._label("Concurrent downloads"),
                        self._concurrency_selector(),
                        self._divider(),

                        self._toggle("Generate Lyrics", "generate_lyrics", False),
                        ft.Container(height=6),
                        self._toggle("Download Artwork", "auto_cover", True),
                        self._divider(),

                        self._label("Theme"),
                        self._theme_selector(),
                        self._divider(),

                        self._label("About"),
                        self._about_block(),
                        self._divider(),

                        self._label("Cache"),
                        self._cache_block(),
                        self._divider(),

                        self._label("Movies (Discovery)"),
                        self._movies_block(),
                        self._divider(),

                        self._label("SUNO"),
                        self._suno_block(),
                        ft.Container(height=18),

                        AppTheme.secondary_button("Reset Settings", icon=ft.Icons.RESTART_ALT,
                                                  on_click=self._reset),
                    ],
                    spacing=8, scroll=ft.ScrollMode.AUTO, expand=True,
                ),
                ft.Text("Habibi Downloader X  ·  v1.0", size=11, color=AppTheme.TEXT_SECONDARY,
                        text_align=ft.TextAlign.CENTER),
            ],
            spacing=14, expand=True,
        )

    # --------------------------------------------------------------- builders
    def _label(self, text):
        return ft.Text(text.upper(), size=11, weight=ft.FontWeight.W_700, color=AppTheme.TEXT_SECONDARY)

    def _divider(self):
        return ft.Divider(height=18, color=AppTheme.BORDER)

    def _toggle(self, label, key, default):
        sw = ft.Switch(
            value=bool(state.settings.get(key, default)),
            active_color=AppTheme.ACCENT,
            on_change=lambda e, k=key: self._save(k, e.control.value),
        )
        setattr(self, f"_sw_{key}", sw)
        return ft.Row(
            [ft.Text(label, size=13, color=AppTheme.TEXT, expand=True), sw],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _concurrency_selector(self):
        current = int(state.settings.get("concurrent_downloads", 2))
        self._conc_row = ft.Row(spacing=8)
        for n in (1, 2, 4, 8):
            active = n == current
            self._conc_row.controls.append(
                ft.Container(
                    content=ft.Text(str(n), size=13,
                                    color=AppTheme.ON_ACCENT if active else AppTheme.TEXT,
                                    weight=ft.FontWeight.BOLD),
                    width=44, height=36, alignment=ft.Alignment(0, 0), border_radius=8,
                    bgcolor=AppTheme.ACCENT if active else AppTheme.CARD,
                    border=ft.Border(
                        left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                        right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER),
                    ),
                    on_click=lambda _, v=n: self._set_concurrency(v),
                )
            )
        return self._conc_row

    def _set_concurrency(self, n):
        self._save("concurrent_downloads", n)
        for c in self._conc_row.controls:
            active = c.content.value == str(n)
            c.bgcolor = AppTheme.ACCENT if active else AppTheme.CARD
            c.content.color = AppTheme.ON_ACCENT if active else AppTheme.TEXT
        self._safe(self._conc_row)

    def _theme_selector(self):
        current = state.settings.get("theme", "dark")
        self._theme_row = ft.Row(spacing=8)
        for mode in ("dark", "light", "system"):
            active = mode == current
            self._theme_row.controls.append(
                ft.Container(
                    content=ft.Text(mode.capitalize(), size=12,
                                    color=AppTheme.ON_ACCENT if active else AppTheme.TEXT,
                                    weight=ft.FontWeight.W_600),
                    height=34, expand=True, alignment=ft.Alignment(0, 0), border_radius=8,
                    bgcolor=AppTheme.ACCENT if active else AppTheme.CARD,
                    border=ft.Border(
                        left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                        right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER),
                    ),
                    on_click=lambda _, m=mode: self._set_theme(m),
                )
            )
        return self._theme_row

    def _set_theme(self, mode):
        self._save("theme", mode)
        for c in self._theme_row.controls:
            active = c.content.value.lower() == mode
            c.bgcolor = AppTheme.ACCENT if active else AppTheme.CARD
            c.content.color = AppTheme.ON_ACCENT if active else AppTheme.TEXT
        self._safe(self._theme_row)
        if self.page:
            self.page.theme_mode = {
                "dark": ft.ThemeMode.DARK, "light": ft.ThemeMode.LIGHT, "system": ft.ThemeMode.SYSTEM,
            }.get(mode, ft.ThemeMode.DARK)
            try:
                self.page.update()
            except Exception:
                pass

    def _about_block(self):
        rows = [
            ("Version", "1.0.0"),
            ("Python", platform.python_version()),
            ("yt-dlp", _ytdlp_version()),
            ("FFmpeg", _ffmpeg_version()),
        ]
        return ft.Column(
            [
                ft.Row([ft.Text(k, size=12, color=AppTheme.TEXT_SECONDARY, expand=True),
                        ft.Text(v, size=12, color=AppTheme.TEXT)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                for k, v in rows
            ],
            spacing=6,
        )

    def _cache_block(self):
        self._cache_size_text = ft.Text("Computing…", size=12, color=AppTheme.TEXT_SECONDARY)
        return ft.Row(
            [
                ft.Column(
                    [
                        self._cache_size_text,
                        ft.Text("Thumbnail cache", size=11, color=AppTheme.TEXT_SECONDARY),
                    ],
                    spacing=2, expand=True,
                ),
                AppTheme.secondary_button("Clear", icon=ft.Icons.DELETE_SWEEP,
                                          on_click=self._clear_cache),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _movies_block(self):
        self._tmdb_field = ft.TextField(
            value=state.settings.get("tmdb_api_key", ""),
            hint_text="Paste your free TMDb API key…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=11),
            password=True, can_reveal_password=True,
            color=AppTheme.TEXT, bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, text_size=11, expand=True,
            on_change=lambda e: self._save("tmdb_api_key", (e.control.value or "").strip()))
        self._ai_field = ft.TextField(
            value=state.settings.get("ai_api_key", ""),
            hint_text="Optional: AI key for fuzzy scene search (Anthropic/OpenAI)…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=11),
            password=True, can_reveal_password=True,
            color=AppTheme.TEXT, bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, text_size=11, expand=True,
            on_change=lambda e: self._save("ai_api_key", (e.control.value or "").strip()))
        get_key = ft.Container(
            content=ft.Text("Get a free TMDb key ▸", size=12, color=AppTheme.ACCENT),
            on_click=lambda _: self._open_url("https://www.themoviedb.org/settings/api"),
            padding=ft.Padding(0, 2, 0, 2))
        return ft.Column([
            ft.Text("Powers the Movies tab in Discovery — describe a scene, theme or "
                    "place to find films.", size=11, color=AppTheme.TEXT_SECONDARY),
            get_key,
            self._tmdb_field,
            ft.Container(height=4),
            self._ai_field,
        ], spacing=6)

    def _open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    # ----------------------------------------------------------------- actions
    def _save(self, key, value):
        state.update_setting(key, value)
        try:
            from src.services.storage import storage
            storage.set_setting(key, str(value))
        except Exception:
            pass

    def _browse_folder(self, e):
        # Run the OS folder picker off the UI thread (tkinter blocks otherwise)
        import threading
        threading.Thread(target=self._pick_folder_bg, daemon=True).start()

    def _pick_folder_bg(self):
        from src.services.scanner import pick_folder
        folder = pick_folder()
        if not folder:
            return
        self._save("download_folder", folder)

        def _apply():
            self._folder_display.value = folder
            self._safe(self._folder_display)
        try:
            if self.page:
                self.page.run_task(self._async_apply, _apply)
        except Exception:
            pass

    async def _async_apply(self, fn):
        fn()

    def _reset(self, e):
        for key, value in DEFAULTS.items():
            self._save(key, value)
        self._build()
        self._safe(self)

    def _clear_cache(self, e):
        from src.services.storage import storage
        storage.clear_cache()
        self._refresh_cache_size()
        try:
            self.page.show_dialog(ft.SnackBar(ft.Text("Cache cleared"), bgcolor=AppTheme.CARD))
        except Exception:
            pass

    def _refresh_cache_size(self):
        def _compute():
            try:
                from src.services.storage import storage
                sz = storage.get_cache_size()
                if self.page:
                    self.page.run_task(self._set_cache_label, sz)
            except Exception:
                pass
        threading.Thread(target=_compute, daemon=True).start()

    async def _set_cache_label(self, sz: int):
        self._cache_size_text.value = _fmt_size(sz)
        self._safe(self._cache_size_text)

    # -------------------------------------------------------------- SUNO block
    def _suno_block(self):
        connected = state.suno_connected
        source = getattr(state, "suno_source", "")

        self._suno_status_dot = ft.Container(
            width=8, height=8, border_radius=4,
            bgcolor=AppTheme.ACCENT if connected else "#555555",
        )
        status_text = "Connected"
        if connected and source:
            status_text = f"Connected via {source}"
        elif not connected:
            status_text = "Not connected"
        self._suno_status_label = ft.Text(
            status_text, size=12,
            color=AppTheme.ACCENT if connected else AppTheme.TEXT_SECONDARY,
        )

        self._suno_detect_btn = AppTheme.secondary_button(
            "Auto-detect cookie", icon=ft.Icons.MANAGE_SEARCH,
            on_click=self._suno_redetect,
        )

        # Instructions (collapsible)
        self._suno_instructions_visible = False
        self._suno_instructions = ft.Column([
            ft.Text(
                "1.  Open suno.com in Chrome or Edge\n"
                "2.  Press F12  →  Application tab\n"
                "3.  Expand Cookies  →  click auth.suno.com\n"
                "4.  Find __client row, click the Value cell\n"
                "5.  Select all (Ctrl+A) and copy\n"
                "6.  Paste below and tap Connect",
                size=11, color=AppTheme.TEXT_SECONDARY,
            ),
        ], visible=False, spacing=4)

        self._suno_help_toggle_text = ft.Text(
            "How to get the cookie ▾",
            size=12, color=AppTheme.ACCENT,
        )
        self._suno_help_toggle = ft.Container(
            content=self._suno_help_toggle_text,
            on_click=self._toggle_suno_help,
            padding=ft.Padding(0, 2, 0, 2),
        )

        # Cookie field
        self._suno_cookie_field = ft.TextField(
            value=state.settings.get("suno_cookie", ""),
            hint_text="Paste __client cookie from auth.suno.com…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=11),
            password=True, can_reveal_password=True,
            color=AppTheme.TEXT, bgcolor=AppTheme.CARD,
            border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT,
            text_size=11, expand=True,
        )
        self._suno_connect_btn = AppTheme.secondary_button(
            "Connect", icon=ft.Icons.LINK,
            on_click=self._suno_connect,
        )
        self._suno_disconnect_btn = AppTheme.secondary_button(
            "Disconnect", icon=ft.Icons.LINK_OFF,
            on_click=self._suno_disconnect,
            visible=connected,
        )

        self._suno_auto_sw = ft.Switch(
            value=bool(state.settings.get("suno_auto_sync", False)),
            active_color=AppTheme.ACCENT,
            on_change=lambda e: self._save("suno_auto_sync", e.control.value),
        )

        current_interval = state.settings.get("suno_sync_interval", "15m")
        self._suno_interval_row = ft.Row(spacing=6)
        for val, label in (("5m", "5 min"), ("15m", "15 min"), ("30m", "30 min"), ("1h", "1 hr")):
            active = val == current_interval
            self._suno_interval_row.controls.append(
                ft.Container(
                    content=ft.Text(label, size=11,
                                    color=AppTheme.ON_ACCENT if active else AppTheme.TEXT,
                                    weight=ft.FontWeight.BOLD),
                    height=30, expand=True, alignment=ft.Alignment(0, 0), border_radius=6,
                    bgcolor=AppTheme.ACCENT if active else AppTheme.CARD,
                    border=ft.Border(
                        left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                        right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER),
                    ),
                    on_click=lambda _, v=val: self._set_suno_interval(v),
                )
            )

        return ft.Column([
            ft.Row([self._suno_status_dot, self._suno_status_label,
                    ft.Container(expand=True),
                    self._suno_disconnect_btn], spacing=6,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self._suno_detect_btn,
            ft.Container(height=6),
            self._suno_help_toggle,
            self._suno_instructions,
            ft.Container(height=2),
            ft.Row([self._suno_cookie_field, self._suno_connect_btn], spacing=8),
            ft.Container(height=6),
            ft.Row([ft.Text("Auto-sync on startup", size=13, color=AppTheme.TEXT, expand=True),
                    self._suno_auto_sw],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=2),
            ft.Text("Sync interval", size=11, color=AppTheme.TEXT_SECONDARY),
            self._suno_interval_row,
        ], spacing=4)

    def _toggle_suno_help(self, e=None):
        self._suno_instructions_visible = not self._suno_instructions_visible
        self._suno_instructions.visible = self._suno_instructions_visible
        self._suno_help_toggle_text.value = (
            "How to get the cookie ▴" if self._suno_instructions_visible
            else "How to get the cookie ▾"
        )
        self._safe(self._suno_instructions)
        self._safe(self._suno_help_toggle_text)

    def _suno_redetect(self, e=None):
        self._suno_status_label.value = "Scanning browsers…"
        self._suno_status_label.color = AppTheme.TEXT_SECONDARY
        self._suno_status_dot.bgcolor = "#555555"
        self._safe(self._suno_status_label)
        self._safe(self._suno_status_dot)

        def _work():
            try:
                from src.services.cookie_extractor import extract_suno_cookie
                found = extract_suno_cookie()
                if self.page:
                    self.page.run_task(self._on_redetect_done, found)
            except Exception as exc:
                if self.page:
                    self.page.run_task(self._on_redetect_done, None, str(exc))

        threading.Thread(target=_work, daemon=True).start()

    async def _on_redetect_done(self, found, error: str = ""):
        if found:
            cookie, browser = found
            from src.services.suno_api import suno_api
            suno_api.configure(cookie)
            suno_api.start_keepalive()
            self._save("suno_cookie", cookie)
            state.suno_connected = True
            state.suno_source = browser
            self._suno_status_label.value = f"Connected via {browser} — syncing…"
            self._suno_status_label.color = AppTheme.ACCENT
            self._suno_status_dot.bgcolor = AppTheme.ACCENT
            self._suno_disconnect_btn.visible = True
            self._suno_cookie_field.value = cookie
            # Auto-sync immediately
            from src.services.suno_sync import suno_sync
            from src.services.storage import storage
            def _sync_done(added, updated, removed):
                songs = storage.get_all_songs()
                state.set_songs(songs)
                if self.page:
                    self.page.run_task(self._after_auto_sync, added)
            suno_sync.sync(on_done=_sync_done)
        else:
            msg = f"Not found: {error}" if error else "No SUNO cookie found — open suno.com in Chrome/Edge first"
            self._suno_status_label.value = msg
            self._suno_status_label.color = AppTheme.DANGER
        self._safe(self._suno_status_label)
        self._safe(self._suno_status_dot)
        self._safe(self._suno_disconnect_btn)
        self._safe(self._suno_cookie_field)

    def _suno_connect(self, e=None):
        cookie = (self._suno_cookie_field.value or "").strip()
        if not cookie:
            self._suno_status_label.value = "Enter a cookie first"
            self._suno_status_label.color = AppTheme.DANGER
            self._safe(self._suno_status_label)
            return

        self._suno_status_label.value = "Validating…"
        self._suno_status_label.color = AppTheme.TEXT_SECONDARY
        self._suno_status_dot.bgcolor = "#555555"
        self._safe(self._suno_status_label)
        self._safe(self._suno_status_dot)

        def _work():
            try:
                from src.services.suno_api import suno_api
                suno_api.configure(cookie)
                ok = suno_api.validate_cookie()
                if self.page:
                    self.page.run_task(self._on_suno_validated, cookie, ok)
            except Exception as exc:
                if self.page:
                    self.page.run_task(self._on_suno_validated, cookie, False, str(exc))

        threading.Thread(target=_work, daemon=True).start()

    async def _on_suno_validated(self, cookie: str, ok: bool, error: str = ""):
        if ok:
            self._save("suno_cookie", cookie)
            state.suno_connected = True
            self._suno_status_label.value = "Connected — syncing library…"
            self._suno_status_label.color = AppTheme.ACCENT
            self._suno_status_dot.bgcolor = AppTheme.ACCENT
            self._suno_disconnect_btn.visible = True
            # Immediately sync so songs appear without extra user action
            from src.services.suno_sync import suno_sync
            from src.services.storage import storage
            def _sync_done(added, updated, removed):
                songs = storage.get_all_songs()
                state.set_songs(songs)
                if self.page:
                    self.page.run_task(self._after_auto_sync, added)
            suno_sync.sync(on_done=_sync_done)
        else:
            state.suno_connected = False
            self._suno_status_label.value = f"Failed: {error}" if error else "Invalid cookie"
            self._suno_status_label.color = AppTheme.DANGER
            self._suno_status_dot.bgcolor = "#555555"
            self._suno_disconnect_btn.visible = False
        self._safe(self._suno_status_label)
        self._safe(self._suno_status_dot)
        self._safe(self._suno_disconnect_btn)

    async def _after_auto_sync(self, added: int):
        self._suno_status_label.value = f"Connected · {added} songs synced"
        self._safe(self._suno_status_label)

    def _suno_disconnect(self, e=None):
        self._save("suno_cookie", "")
        try:
            from src.services.suno_api import suno_api
            suno_api.configure("")
        except Exception:
            pass
        state.suno_connected = False
        self._suno_status_label.value = "Not connected"
        self._suno_status_label.color = AppTheme.TEXT_SECONDARY
        self._suno_status_dot.bgcolor = "#555555"
        self._suno_disconnect_btn.visible = False
        self._suno_cookie_field.value = ""
        self._safe(self._suno_status_label)
        self._safe(self._suno_status_dot)
        self._safe(self._suno_disconnect_btn)
        self._safe(self._suno_cookie_field)

    def _set_suno_interval(self, val: str):
        self._save("suno_sync_interval", val)
        for c in self._suno_interval_row.controls:
            active = c.content.value == {"5m": "5 min", "15m": "15 min",
                                         "30m": "30 min", "1h": "1 hr"}[val]
            c.bgcolor = AppTheme.ACCENT if active else AppTheme.CARD
            c.content.color = AppTheme.ON_ACCENT if active else AppTheme.TEXT
        self._safe(self._suno_interval_row)

    # -------------------------------------------------------------- show/hide
    def show(self):
        self._visible = True
        # Sync drawer height to the live window so the scroll column gets a
        # bounded height (otherwise the body renders blank/gray in Flet 0.85.3).
        try:
            h = self.page.height or self.page.window.height or 800
            self.height = h
        except Exception:
            self.height = 800
        self.offset = ft.Offset(0, 0)
        self.update()
        self._refresh_cache_size()

    def hide(self):
        self._visible = False
        self.offset = ft.Offset(-1.5, 0)
        self.update()

    def toggle(self):
        self.hide() if self._visible else self.show()

    def _safe(self, control):
        try:
            control.update()
        except (RuntimeError, AssertionError):
            pass


def _ytdlp_version():
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return "n/a"


def _ffmpeg_version():
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        first = out.stdout.splitlines()[0]
        return first.split("version")[1].strip().split("-")[0].split()[0]
    except Exception:
        return "not found"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"
