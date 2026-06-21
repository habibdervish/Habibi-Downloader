"""Library page — SUNO library only.

All songs displayed here come from the connected SUNO account.
Local files, Scanner, Discovery, and YouTube are not involved.
"""

import hashlib
import os
import threading
import datetime
import flet as ft

from src.theme import AppTheme
from src.state import state
from src.components.song_card import SongCard


# ─────────────────────────────────────── empty-state messages per filter
_FILTER_EMPTY = {
    "all":             (ft.Icons.SYNC_OUTLINED,
                        "No songs found in your SUNO library",
                        "Generate music in SUNO and press Sync"),
    "favorites":       (ft.Icons.FAVORITE_BORDER,
                        "No favorites yet",
                        "Tap ♥ on any song to add it to your favorites"),
    "missing_lyrics":  (ft.Icons.LYRICS_OUTLINED,
                        "All songs have lyrics",
                        "Every song in your SUNO library has lyrics"),
    "missing_artwork": (ft.Icons.IMAGE_OUTLINED,
                        "All songs have artwork",
                        "Every song in your SUNO library has artwork"),
}


class LibraryView(ft.Container):
    def __init__(self):
        super().__init__(expand=True, padding=ft.Padding(30, 24, 30, 0), bgcolor=AppTheme.BG)
        self._filter = "all"
        self._sort = "date"       # newest first by default
        self._sort_asc = False    # date desc → most recent on top
        self._view_mode = state.library_view_mode
        self._last_playing_id = None
        self._sort_col_labels: dict = {}
        self._chip_texts: dict = {}
        self._syncing = False
        # Memoized statistics (single O(n) pass; updated incrementally)
        self._stats: dict = {}
        self._total_storage_bytes = 0
        self._filtered_cache: list = []
        self._rendered_count = 0

        if not state.songs_loaded:
            self.content = self._build_loading()
            return

        self._build()
        self._populate()

    # ─────────────────────────────────── loading screen
    def _build_loading(self):
        return ft.Column(
            [ft.Row([ft.Column(
                [ft.Text("Library", size=28, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                 ft.Text("Connecting to SUNO…", size=13, color=AppTheme.TEXT_SECONDARY)],
                spacing=2)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
             ft.Container(expand=True, alignment=ft.Alignment(0, 0),
                content=ft.Column(
                    [ft.ProgressRing(width=32, height=32, color=AppTheme.ACCENT),
                     ft.Text("Loading your SUNO library…", size=14, color=AppTheme.TEXT_SECONDARY)],
                    spacing=16, horizontal_alignment=ft.CrossAxisAlignment.CENTER))],
            spacing=8, expand=True)

    # ─────────────────────────────────── stats (memoized)
    def _recompute_stats(self) -> dict:
        """Single O(n) pass over the library, cached in self._stats."""
        fav = lrc = art = 0
        dur = 0.0
        for s in state.songs:
            if s.is_favorite:
                fav += 1
            if not s.lyrics_text:
                lrc += 1
            if not s.thumbnail_path:
                art += 1
            dur += s.duration or 0
        self._stats = {
            "total": len(state.songs),
            "favorites": fav,
            "missing_lyrics": lrc,
            "missing_artwork": art,
            "duration": dur,
        }
        return self._stats

    # ─────────────────────────────────── main build
    def _build(self):
        st = self._recompute_stats()
        n = st["total"]
        total_dur = st["duration"]
        lrc_pct = int((n - st["missing_lyrics"]) / n * 100) if n else 0
        art_pct = int((n - st["missing_artwork"]) / n * 100) if n else 0

        # ── stat cards ────────────────────────────────────────────────────
        self._storage_stat_val = ft.Text("–", size=20, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT)
        summary_row = ft.Row([
            self._stat_card("Songs",    str(n),                ft.Icons.LIBRARY_MUSIC_OUTLINED),
            self._stat_card("Duration", _fmt_total(total_dur), ft.Icons.SCHEDULE),
            self._stat_card_widget("Storage", self._storage_stat_val, ft.Icons.STORAGE),
            self._stat_card(f"{lrc_pct}%", "Lyrics",          ft.Icons.LYRICS_OUTLINED),
            self._stat_card(f"{art_pct}%", "Artwork",          ft.Icons.IMAGE_OUTLINED),
        ], spacing=12)

        # ── filter chips ──────────────────────────────────────────────────
        _chip_defs = [
            ("all",             "All"),
            ("recent",          "Recently Added"),
            ("favorites",       "Favorites"),
            ("missing_lyrics",  "Missing Lyrics"),
            ("missing_artwork", "Missing Artwork"),
        ]
        self._filter_ctls: dict = {}
        self._chip_texts: dict = {}
        counts = self._get_chip_counts()
        chip_controls = []
        for key, label in _chip_defs:
            txt = ft.Text(f"{label} ({counts.get(key, 0)})", size=12)
            self._chip_texts[key] = txt
            chip = ft.Container(
                content=txt,
                padding=ft.Padding(14, 6, 14, 6),
                border_radius=20,
                on_click=lambda _, k=key: self._set_filter(k),
                animate=AppTheme.transition,
            )
            self._filter_ctls[key] = chip
            chip_controls.append(chip)
        self._style_filters()
        filter_row = ft.Row(chip_controls, spacing=8, wrap=True)

        # ── summary text ──────────────────────────────────────────────────
        self._summary_text = ft.Text("", size=11, color=AppTheme.TEXT_SECONDARY)

        # ── sync status label ─────────────────────────────────────────────
        self._sync_status = ft.Text(
            _last_sync_label(state.suno_last_sync),
            size=11, color=AppTheme.TEXT_SECONDARY,
        )
        self._sync_spin = ft.ProgressRing(
            width=14, height=14, stroke_width=2,
            color=AppTheme.ACCENT, visible=False,
        )
        self._sync_btn = ft.IconButton(
            ft.Icons.SYNC, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Sync with SUNO",
            on_click=lambda _: self._trigger_sync(),
        )

        # ── header ────────────────────────────────────────────────────────
        self._count_label = ft.Text(f"{n} songs", size=13, color=AppTheme.TEXT_SECONDARY)
        self._sort_labels = {
            "name":     "Title",
            "artist":   "Artist",
            "date":     "Date Added",
            "duration": "Duration",
            "size":     "File Size",
        }
        self._sort_text = ft.Text(f"Sort: {self._sort_labels[self._sort]}", size=12, color=AppTheme.TEXT)
        self._sort_dropdown = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row([self._sort_text,
                                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18,
                                        color=AppTheme.TEXT_SECONDARY)],
                               spacing=4, tight=True),
                bgcolor=AppTheme.CARD, border_radius=AppTheme.button_radius,
                padding=ft.Padding(12, 8, 8, 8),
                border=ft.Border(
                    left=ft.BorderSide(1, AppTheme.BORDER),
                    top=ft.BorderSide(1, AppTheme.BORDER),
                    right=ft.BorderSide(1, AppTheme.BORDER),
                    bottom=ft.BorderSide(1, AppTheme.BORDER)),
            ),
            items=[ft.PopupMenuItem(content=ft.Text(label),
                                    on_click=lambda _, k=key: self._set_sort(k))
                   for key, label in self._sort_labels.items()],
        )
        self._view_toggle = self._build_view_toggle()

        header = ft.Row(
            [
                ft.Column(
                    [ft.Row(
                        [ft.Text("Library", size=28, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                         self._sync_btn, self._sync_spin],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                     ft.Row([self._count_label,
                             ft.Text("·", size=11, color=AppTheme.BORDER),
                             self._sync_status], spacing=8)],
                    spacing=2,
                ),
                ft.Row([self._sort_dropdown, self._view_toggle], spacing=12),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # ── bulk selection bar ────────────────────────────────────────────
        self._sel_label = ft.Text("0 selected", size=13, weight=ft.FontWeight.W_600, color=AppTheme.TEXT)
        self._selection_bar = ft.Container(
            visible=False, bottom=8, left=0, right=0,
            bgcolor=AppTheme.CARD, border_radius=AppTheme.button_radius,
            padding=ft.Padding(14, 8, 14, 8),
            content=ft.Row(
                [self._sel_label,
                 ft.Row([
                     AppTheme.secondary_button("Clear",
                         on_click=lambda _: self._clear_selection()),
                     AppTheme.secondary_button("Play Selected",
                         icon=ft.Icons.PLAY_ARROW,
                         on_click=lambda _: self._play_selected()),
                     AppTheme.secondary_button("Add to Queue",
                         icon=ft.Icons.QUEUE_MUSIC,
                         on_click=lambda _: self._add_to_queue()),
                     AppTheme.secondary_button("Favorite",
                         icon=ft.Icons.FAVORITE_BORDER,
                         on_click=lambda _: self._favorite_selected()),
                     AppTheme.secondary_button("Refresh Metadata",
                         icon=ft.Icons.REFRESH,
                         on_click=lambda _: self._refresh_selected_metadata()),
                     AppTheme.secondary_button("Export",
                         icon=ft.Icons.SAVE_ALT,
                         on_click=lambda _: self._export_selected()),
                     AppTheme.danger_button("Delete",
                         icon=ft.Icons.DELETE_OUTLINE,
                         on_click=lambda _: self._delete_selected()),
                 ], spacing=8)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )

        # ── grid ──────────────────────────────────────────────────────────
        self._grid = ft.GridView(
            runs_count=0, max_extent=200, child_aspect_ratio=0.78,
            spacing=16, run_spacing=16, padding=ft.Padding(top=8), expand=True,
            on_scroll=self._on_scroll_near_bottom,
        )

        # ── table — 9 columns ─────────────────────────────────────────────
        self._sort_col_labels = {}
        self._table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("", size=12)),                          # 0 checkbox
                ft.DataColumn(ft.Text("", size=12)),                          # 1 artwork
                ft.DataColumn(self._sortable_col("Title",      "name")),      # 2
                ft.DataColumn(self._sortable_col("Artist",     "artist")),    # 3
                ft.DataColumn(self._sortable_col("Duration",   "duration")),  # 4
                ft.DataColumn(self._sortable_col("Added",      "date")),      # 5
                ft.DataColumn(ft.Text("Style",  size=12, color=AppTheme.TEXT_SECONDARY)),   # 6
                ft.DataColumn(ft.Text("Model",  size=12, color=AppTheme.TEXT_SECONDARY)),   # 7
                ft.DataColumn(ft.Text("",       size=12)),                    # 8 status
                ft.DataColumn(ft.Text("Actions", size=12, color=AppTheme.TEXT_SECONDARY)),  # 9
            ],
            rows=[], column_spacing=12,
            heading_row_color=AppTheme.PANEL,
            bgcolor=AppTheme.CARD, border_radius=12,
            expand=True, visible=False,
        )
        self._update_sort_indicators()

        self._table_container = ft.Container(
            content=ft.Column([self._table], scroll=ft.ScrollMode.AUTO, expand=True,
                              on_scroll=self._on_scroll_near_bottom),
            expand=True, visible=False,
        )

        # ── empty state overlay ───────────────────────────────────────────
        self._filter_empty = ft.Container(
            visible=False, expand=True, alignment=ft.Alignment(0, 0),
            content=ft.Column([], spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER),
        )

        is_grid = self._view_mode == "grid"
        self._grid.visible = is_grid
        self._table_container.visible = not is_grid
        self._table.visible = not is_grid

        # Playback is shown by the single app-level docked PlayerBar — the
        # Library no longer has its own mini player (that was a duplicate).
        inner = ft.Column(
            [summary_row, filter_row, self._summary_text, header,
             ft.Divider(height=8, color=ft.Colors.TRANSPARENT),
             ft.Stack([self._grid, self._table_container, self._filter_empty,
                       self._selection_bar], expand=True)],
            spacing=12, expand=True,
        )
        self.content = inner

    # ─────────────────────────────────── stat cards
    def _stat_card(self, value, label, icon):
        return ft.Container(
            content=ft.Column(
                [ft.Icon(icon, size=16, color=AppTheme.ACCENT),
                 ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                 ft.Text(label, size=11, color=AppTheme.TEXT_SECONDARY)],
                spacing=3, tight=True),
            expand=True, bgcolor=AppTheme.PANEL, border_radius=AppTheme.panel_radius,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER)),
            padding=ft.Padding(16, 12, 16, 12))

    def _stat_card_widget(self, label, value_widget, icon):
        return ft.Container(
            content=ft.Column(
                [ft.Icon(icon, size=16, color=AppTheme.ACCENT),
                 value_widget,
                 ft.Text(label, size=11, color=AppTheme.TEXT_SECONDARY)],
                spacing=3, tight=True),
            expand=True, bgcolor=AppTheme.PANEL, border_radius=AppTheme.panel_radius,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER)),
            padding=ft.Padding(16, 12, 16, 12))

    # ─────────────────────────────────── sortable column headers
    def _sortable_col(self, text: str, sort_key: str) -> ft.Container:
        lbl = ft.Text(text, size=12, color=AppTheme.TEXT_SECONDARY)
        self._sort_col_labels[sort_key] = (text, lbl)
        return ft.Container(content=lbl, on_click=lambda _, k=sort_key: self._set_sort_col(k),
                            padding=ft.Padding(0, 4, 0, 4))

    def _update_sort_indicators(self):
        for key, (base, lbl) in self._sort_col_labels.items():
            if key == self._sort:
                lbl.value = base + (" ↑" if self._sort_asc else " ↓")
                lbl.color = AppTheme.ACCENT
            else:
                lbl.value = base
                lbl.color = AppTheme.TEXT_SECONDARY
            self._safe(lbl)

    # ─────────────────────────────────── filter chip counts
    def _get_chip_counts(self) -> dict:
        st = self._stats or self._recompute_stats()
        return {
            "all":             st["total"],
            "recent":          min(self._RECENT_LIMIT, st["total"]),
            "favorites":       st["favorites"],
            "missing_lyrics":  st["missing_lyrics"],
            "missing_artwork": st["missing_artwork"],
        }

    def _update_chip_counts(self):
        labels = {"all": "All", "recent": "Recently Added", "favorites": "Favorites",
                  "missing_lyrics": "Missing Lyrics", "missing_artwork": "Missing Artwork"}
        counts = self._get_chip_counts()
        for key, txt in self._chip_texts.items():
            txt.value = f"{labels[key]} ({counts.get(key, 0)})"
            self._safe(txt)

    def _style_filters(self):
        for key, chip in self._filter_ctls.items():
            active = key == self._filter
            chip.bgcolor = AppTheme.ACCENT if active else AppTheme.CARD
            chip.border = None if active else ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER), top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER), bottom=ft.BorderSide(1, AppTheme.BORDER))
            txt = self._chip_texts.get(key)
            if txt:
                txt.color  = AppTheme.BG if active else AppTheme.TEXT_SECONDARY
                txt.weight = ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL

    # ─────────────────────────────────── view toggle
    def _build_view_toggle(self):
        self._grid_btn = ft.Container(
            content=ft.Icon(ft.Icons.GRID_VIEW, size=18),
            padding=ft.Padding(10, 8, 10, 8), border_radius=AppTheme.button_radius,
            on_click=lambda _: self._set_view("grid"), ink=False)
        self._list_btn = ft.Container(
            content=ft.Icon(ft.Icons.TABLE_ROWS, size=18),
            padding=ft.Padding(10, 8, 10, 8), border_radius=AppTheme.button_radius,
            on_click=lambda _: self._set_view("list"), ink=False)
        self._style_view_toggle()
        return ft.Row([self._grid_btn, self._list_btn], spacing=4)

    def _style_view_toggle(self):
        for btn, mode in ((self._grid_btn, "grid"), (self._list_btn, "list")):
            active = self._view_mode == mode
            btn.content.color = AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY
            btn.bgcolor = (AppTheme.ACCENT + "1A") if active else "transparent"

    # ─────────────────────────────────── lifecycle
    def did_mount(self):
        if not state.songs_loaded:
            return
        from src.services.player import player
        from src.services.suno_sync import ensure_local_audio
        # Let the player download tracks on demand for Play / Next / Prev.
        player.set_resolver(ensure_local_audio)
        # Light listener only to refresh the now-playing highlight on track
        # change — it never rebuilds the grid (see _on_player_change).
        player.add_listener(self._on_player_change)
        # background: storage size
        threading.Thread(target=self._load_storage_size, daemon=True).start()
        # sync status label
        self._update_sync_ui(syncing=state.suno_syncing)
        self._update_summary_text(self._get_filtered(), state.songs)
        self._sync_update()
        # If not connected yet, try auto-detect in background without blocking the UI
        from src.services.suno_api import suno_api
        if not suno_api.is_configured and not self._syncing:
            threading.Thread(target=self._silent_detect, daemon=True).start()

    def _silent_detect(self):
        """Try to pick up the browser cookie quietly on mount — no spinners."""
        try:
            from src.services.cookie_extractor import extract_suno_cookie
            from src.services.suno_api import suno_api
            found = extract_suno_cookie()
            if found and not suno_api.is_configured:
                cookie, browser = found
                suno_api.configure(cookie)
                suno_api.start_keepalive()
                try:
                    from src.services.storage import storage
                    storage.set_setting("suno_cookie", cookie)
                except Exception:
                    pass
                state.suno_connected = True
                state.suno_source = browser
                # Refresh the empty state to show "Sync Now" instead of "Detect"
                if self.page:
                    self.page.run_task(self._repopulate_after_detect)
        except Exception:
            pass

    async def _repopulate_after_detect(self):
        self._populate()
        self._sync_update()

    def will_unmount(self):
        try:
            from src.services.player import player
            player.remove_listener(self._on_player_change)
        except Exception:
            pass

    # ─────────────────────────────────── storage size (background)
    def _load_storage_size(self):
        try:
            from src.services.storage import storage
            total = sum(
                os.path.getsize(s.file_path)
                for s in state.songs
                if s.file_path and os.path.exists(s.file_path)
            )
            if self.page:
                self.page.run_task(self._set_storage_label, total)
        except Exception:
            pass

    async def _set_storage_label(self, total: int):
        self._total_storage_bytes = total
        self._storage_stat_val.value = _fmt_size(total)
        self._safe(self._storage_stat_val)
        self._update_summary_text(self._get_filtered())

    # ─────────────────────────────────── player listener (async — required by player._emit)
    async def _on_player_change(self):
        # Only track the playing song id. We intentionally do NOT rebuild the
        # grid/table here — the docked PlayerBar reflects playback, and a full
        # repopulate on every track change would be a costly rerender.
        from src.services.player import player
        new_id = player.current.id if player.current else None
        if new_id != self._last_playing_id:
            self._last_playing_id = new_id

    def _open_settings(self):
        """Open the settings drawer from the library empty state."""
        try:
            # Navigate up to app-level and call toggle on the settings drawer
            if self.page:
                for control in self.page.controls:
                    if hasattr(control, "settings_drawer"):
                        control.settings_drawer.show()
                        return
                # Try page-level overlay/drawer references
                if hasattr(self.page, "_settings_drawer"):
                    self.page._settings_drawer.show()
        except Exception:
            pass

    def refresh_in_place(self):
        """Re-filter and repopulate without rebuilding the whole view.

        Used by the debounced search so typing doesn't trigger a full-page
        rerender. Resets to the first render batch and updates summary counts.
        """
        if not state.songs_loaded:
            return
        self._populate()
        self._sync_update()

    # ─────────────────────────────────── SUNO sync
    def _trigger_sync(self):
        from src.services.suno_api import suno_api
        if not suno_api.is_configured:
            # Not configured — try to extract the cookie from the browser right now
            self._update_sync_ui(syncing=True)
            if hasattr(self, "_sync_status"):
                self._sync_status.value = "Looking for SUNO session in browser…"
                self._safe(self._sync_status)
            threading.Thread(target=self._detect_then_sync, daemon=True).start()
            return
        self._do_sync()

    def _detect_then_sync(self):
        """Background: extract cookie from browser, configure, then start sync."""
        try:
            from src.services.cookie_extractor import extract_suno_cookie
            from src.services.suno_api import suno_api
            found = extract_suno_cookie()
        except Exception as e:
            found = None

        if found:
            cookie, browser = found
            from src.services.suno_api import suno_api
            suno_api.configure(cookie)
            suno_api.start_keepalive()
            try:
                from src.services.storage import storage
                storage.set_setting("suno_cookie", cookie)
            except Exception:
                pass
            state.suno_connected = True
            state.suno_source = browser
            if self.page:
                self.page.run_task(self._after_detect_ok, browser)
        else:
            if self.page:
                self.page.run_task(self._after_detect_fail)

    async def _after_detect_ok(self, browser: str):
        self._toast(f"Connected via {browser} — starting sync…")
        self._do_sync()

    async def _after_detect_fail(self):
        self._syncing = False
        self._update_sync_ui(syncing=False)
        self._populate()  # re-show empty state with instructions
        self._toast("Auto-detect failed. Open Settings → SUNO, click 'How to get the cookie' and paste it manually.")

    def _do_sync(self):
        if self._syncing:
            return
        self._syncing = True
        self._update_sync_ui(syncing=True)
        from src.services.suno_sync import suno_sync
        suno_sync.sync(
            on_progress=self._on_sync_progress,
            on_done=self._on_sync_done,
            on_error=self._on_sync_error,
        )

    def _on_sync_progress(self, msg: str):
        if self.page:
            self.page.run_task(self._async_sync_progress, msg)

    async def _async_sync_progress(self, msg: str):
        self._sync_status.value = msg
        self._safe(self._sync_status)

    def _on_sync_done(self, added: int, updated: int, removed: int):
        if self.page:
            self.page.run_task(self._async_sync_done, added, updated, removed)

    async def _async_sync_done(self, added: int, updated: int, removed: int):
        from src.services.storage import storage
        self._syncing = False
        state.suno_syncing = False
        state.suno_last_sync = storage.get_last_sync_time("suno")
        songs = storage.get_all_songs()
        state.set_songs(songs)
        self._rebuild_after_sync()
        self._update_sync_ui(syncing=False)
        self._toast(f"Sync complete: +{added} new · {updated} updated · {removed} removed")

    def _on_sync_error(self, err: str):
        if self.page:
            self.page.run_task(self._async_sync_error, err)

    async def _async_sync_error(self, err: str):
        self._syncing = False
        self._update_sync_ui(syncing=False)
        self._toast(f"Sync failed: {err}")

    def _update_sync_ui(self, syncing: bool):
        if not hasattr(self, "_sync_btn"):
            return
        self._sync_spin.visible = syncing
        self._sync_btn.icon_color = AppTheme.ACCENT if syncing else AppTheme.TEXT_SECONDARY
        if not syncing:
            self._sync_status.value = _last_sync_label(state.suno_last_sync)
        self._safe(self._sync_status)
        self._safe(self._sync_spin)
        self._safe(self._sync_btn)

    def _rebuild_after_sync(self):
        """Refresh all displayed values after songs reload."""
        if not hasattr(self, "_count_label"):
            return
        songs = state.songs
        n = len(songs)
        self._count_label.value = f"{n} songs"
        self._safe(self._count_label)
        self._update_chip_counts()
        self._populate()
        self._sync_update()
        threading.Thread(target=self._load_storage_size, daemon=True).start()

    # ─────────────────────────────────── filtering / sorting
    _RECENT_LIMIT = 100

    def _get_filtered(self):
        songs = state.filtered_songs or state.songs
        if self._filter == "favorites":
            songs = [s for s in songs if s.is_favorite]
        elif self._filter == "missing_lyrics":
            songs = [s for s in songs if not s.lyrics_text]
        elif self._filter == "missing_artwork":
            songs = [s for s in songs if not s.thumbnail_path]
        elif self._filter == "recent":
            songs = sorted(songs, key=lambda s: getattr(s, "added_at", "") or "",
                           reverse=True)[:self._RECENT_LIMIT]
        return self._apply_sort(songs)

    def _apply_sort(self, songs):
        asc = self._sort_asc
        if self._sort == "name":
            return sorted(songs, key=lambda s: (s.title or "").lower(), reverse=not asc)
        if self._sort == "artist":
            return sorted(songs, key=lambda s: (s.artist or "").lower(), reverse=not asc)
        if self._sort == "duration":
            return sorted(songs, key=lambda s: s.duration or 0, reverse=not asc)
        if self._sort == "date":
            return sorted(songs, key=lambda s: getattr(s, "added_at", "") or "", reverse=not asc)
        if self._sort == "size":
            return sorted(songs, key=self._file_size, reverse=not asc)
        return list(songs)

    @staticmethod
    def _file_size(song) -> int:
        try:
            if song.file_path and os.path.exists(song.file_path):
                return os.path.getsize(song.file_path)
        except Exception:
            pass
        return 0

    # ─────────────────────────────────── summary text
    def _update_summary_text(self, filtered, all_songs=None):
        st = self._stats or self._recompute_stats()
        n_shown = len(filtered)
        parts = [f"Showing {n_shown} of {st['total']}"]
        if st["favorites"]:
            parts.append(f"{st['favorites']} {'favorite' if st['favorites'] == 1 else 'favorites'}")
        if st["missing_lyrics"]:
            parts.append(f"{st['missing_lyrics']} missing lyrics")
        if st["missing_artwork"]:
            parts.append(f"{st['missing_artwork']} missing artwork")
        parts.append(f"{_fmt_total(st['duration'])} total")
        parts.append(f"{_fmt_size(self._total_storage_bytes)} stored")
        self._summary_text.value = "  ·  ".join(parts)
        self._safe(self._summary_text)

    # ─────────────────────────────────── selection
    def _sync_selection_bar(self):
        n = len(state.selected_song_ids)
        self._selection_bar.visible = n > 0
        self._sel_label.value = f"{n} selected"
        self._sync_update()

    def _on_row_check(self, song, checked: bool):
        if checked:
            state.selected_song_ids.add(song.id)
        else:
            state.selected_song_ids.discard(song.id)
        self._sync_selection_bar()

    def _clear_selection(self):
        state.selected_song_ids.clear()
        for ctl in self._grid.controls:
            if isinstance(ctl, SongCard):
                ctl.deselect()
        self._sync_selection_bar()

    # ─────────────────────────────────── bulk actions
    def _delete_selected(self):
        from src.services.storage import storage
        for sid in list(state.selected_song_ids):
            storage.delete_song(sid)
        state.selected_song_ids.clear()
        state.set_songs(storage.get_all_songs())
        self._refresh_after_change()

    def _selected_songs(self):
        """Selected songs in the current display order."""
        ids = state.selected_song_ids
        return [s for s in self._get_filtered() if s.id in ids]

    def _play_selected(self):
        songs = self._selected_songs()
        if not songs:
            self._toast("Nothing selected")
            return
        self._toast(f"Preparing {len(songs)} song{'s' if len(songs) != 1 else ''}…")
        threading.Thread(target=self._prepare_and_play, args=(songs,), daemon=True).start()

    def _prepare_and_play(self, songs):
        """Download selected songs as needed and play them as a queue.

        Playback starts the moment the first track is ready; later tracks become
        playable as their downloads finish (they share the same Song objects in
        the player's queue)."""
        import os
        from src.services.player import player
        started = False
        for song in songs:
            if not self._ensure_local_audio(song):
                continue
            if not started:
                player.play(song, queue=songs)
                started = True
        if not started:
            self._run_ui(self._toast_async, "Couldn't load selected songs")

    def _add_to_queue(self):
        from src.services.player import player
        songs = self._selected_songs()
        if not songs:
            self._toast("Nothing selected")
            return
        player.queue.extend(songs)
        self._toast(f"Added {len(songs)} to queue")
        threading.Thread(target=self._prefetch_queue, args=(songs,), daemon=True).start()

    def _prefetch_queue(self, songs):
        for song in songs:
            self._ensure_local_audio(song)

    def _ensure_local_audio(self, song) -> bool:
        """Download the song's MP3 if not already local. Returns True if playable."""
        from src.services.suno_sync import ensure_local_audio
        return ensure_local_audio(song)

    def _favorite_selected(self):
        from src.services.storage import storage
        for song in state.songs:
            if song.id in state.selected_song_ids:
                storage.toggle_favorite(song.id)
                song.is_favorite = not song.is_favorite
        self._recompute_stats()
        self._update_chip_counts()
        self._update_summary_text(self._get_filtered())
        self._populate()
        self._sync_update()

    def _refresh_selected_metadata(self):
        songs = [s for s in state.songs if s.id in state.selected_song_ids and s.suno_id]
        if not songs:
            self._toast("No SUNO songs selected")
            return
        from src.services.suno_api import suno_api
        if not suno_api.is_configured:
            self._toast("SUNO not connected")
            return
        self._toast(f"Refreshing metadata for {len(songs)} song(s)…")
        from src.services.suno_sync import suno_sync
        suno_sync.refresh_songs(
            [s.suno_id for s in songs],
            on_done=lambda count: (
                self.page.run_task(self._after_refresh, count)
                if self.page else None
            ),
            on_error=lambda err: (
                self.page.run_task(self._async_sync_error, err)
                if self.page else None
            ),
        )

    async def _after_refresh(self, count: int):
        from src.services.storage import storage
        state.set_songs(storage.get_all_songs())
        self._update_chip_counts()
        self._populate()
        self._sync_update()
        self._toast(f"Refreshed {count} song(s)")

    def _export_selected(self):
        songs = self._selected_songs()
        if not songs:
            self._toast("Nothing selected")
            return
        self._toast("Opening folder picker…")
        threading.Thread(target=self._pick_and_export, args=(songs,), daemon=True).start()

    def _pick_and_export(self, songs):
        """Run folder picker off UI thread (tkinter blocks if called on main thread)."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title="Select export folder")
            root.destroy()
        except Exception:
            folder = None
        if not folder:
            return
        n = len(songs)
        self._run_ui(self._toast_async, f"Exporting {n} song{'s' if n != 1 else ''} — audio, cover, lyrics & data…")
        self._export_worker(songs, folder)

    @staticmethod
    def _safe_name(name: str) -> str:
        import re
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "Untitled")).strip()
        return (cleaned or "Untitled")[:80]

    def _export_worker(self, songs, folder):
        """Download/bundle every asset of each selected song into its own folder:
        <Title> [id]/  ->  <Title>.mp3, cover.jpg, lyrics.txt, info.json"""
        import json
        import shutil
        from src.services.suno_sync import _download_file

        total = len(songs)
        count = 0
        for i, song in enumerate(songs, 1):
            self._run_ui(self._export_progress, i, total)
            try:
                safe = self._safe_name(song.title)
                sid = (song.suno_id or song.id or "")[:8]
                sub = os.path.join(folder, f"{safe} [{sid}]" if sid else safe)
                os.makedirs(sub, exist_ok=True)

                # 1) Audio — ensure it's downloaded, then copy into the folder
                if self._ensure_local_audio(song) and song.file_path and os.path.exists(song.file_path):
                    try:
                        shutil.copy2(song.file_path, os.path.join(sub, f"{safe}.mp3"))
                    except Exception:
                        pass

                # 2) Cover art — local thumbnail if present, else download image_url
                cover_dest = os.path.join(sub, "cover.jpg")
                if song.thumbnail_path and os.path.exists(song.thumbnail_path):
                    try:
                        shutil.copy2(song.thumbnail_path, cover_dest)
                    except Exception:
                        pass
                elif getattr(song, "image_url", ""):
                    _download_file(song.image_url, cover_dest, timeout=30)

                # 3) Lyrics — prefer dedicated field; fall back to lyric section in prompt
                from src.services.suno_sync import _extract_lyrics
                lyrics = (getattr(song, "lyrics_text", "") or "").strip()
                if not lyrics:
                    lyrics = _extract_lyrics(getattr(song, "prompt", "") or "")
                if lyrics:
                    with open(os.path.join(sub, "lyrics.txt"), "w", encoding="utf-8") as fh:
                        fh.write(lyrics)

                # 4) Prompt + full metadata
                meta = {
                    "title": song.title,
                    "artist": song.artist,
                    "duration_seconds": song.duration,
                    "prompt": getattr(song, "prompt", ""),
                    "style": getattr(song, "style", ""),
                    "model_version": getattr(song, "model_version", ""),
                    "suno_id": song.suno_id,
                    "source_url": song.source_url,
                    "audio_url": getattr(song, "audio_url", ""),
                    "image_url": getattr(song, "image_url", ""),
                    "created_at": song.added_at,
                    "updated_at": getattr(song, "updated_at", ""),
                    "is_favorite": bool(song.is_favorite),
                }
                with open(os.path.join(sub, "info.json"), "w", encoding="utf-8") as fh:
                    json.dump(meta, fh, indent=2, ensure_ascii=False)
                # human-readable prompt file too
                if meta["prompt"] or meta["style"]:
                    with open(os.path.join(sub, "prompt.txt"), "w", encoding="utf-8") as fh:
                        fh.write(f"Style: {meta['style']}\n\nPrompt:\n{meta['prompt']}\n")

                count += 1
            except Exception:
                pass

        self._run_ui(self._after_export, count, folder)

    async def _export_progress(self, i: int, total: int):
        self._sel_label.value = f"Exporting {i}/{total}…"
        self._safe(self._sel_label)

    async def _after_export(self, count: int, folder: str):
        n = len(state.selected_song_ids)
        self._sel_label.value = f"{n} selected"
        self._safe(self._sel_label)
        self._toast(f"Exported {count} song(s) with all assets to {os.path.basename(folder)}")

    # ─────────────────────────────────── single-song actions
    def _delete_one(self, song):
        from src.services.storage import storage
        storage.delete_song(song.id)
        state.selected_song_ids.discard(song.id)
        state.set_songs(storage.get_all_songs())
        self._refresh_after_change()

    def _play(self, song):
        from src.services.player import player
        playable = (song.file_path and os.path.exists(song.file_path))
        if not playable and not getattr(song, "audio_url", ""):
            self._toast("No audio available for this song")
            return
        # The player downloads on demand (off the UI thread, with a spinner) via
        # the registered resolver, and Next/Prev walk the whole filtered list.
        player.play(song, queue=self._get_filtered())

    async def _toast_async(self, msg: str):
        self._toast(msg)

    def _toggle_favorite(self, song):
        # The SongCard has already flipped song.is_favorite and updated its own
        # heart icon (optimistic UI). Here we only persist + refresh counters —
        # no full grid rebuild (which would re-create all 2484 cards).
        from src.services.storage import storage
        storage.toggle_favorite(song.id)
        if self._stats:
            self._stats["favorites"] += 1 if song.is_favorite else -1
        self._update_chip_counts()
        self._update_summary_text(self._get_filtered())
        # In the Favorites view an un-favorited song no longer belongs here —
        # repopulate so it drops out (cheap: batched render).
        if self._filter == "favorites" and not song.is_favorite:
            self._populate()
            self._sync_update()

    def _open_lyrics(self, song):
        if not song.lyrics_text:
            self._toast("No lyrics available for this song")
            return
        # Format plain-text lyrics from SUNO into a readable view
        lines = song.lyrics_text.splitlines()
        line_controls = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                # Section header e.g. [Verse 1]
                line_controls.append(
                    ft.Text(stripped, size=11, color=AppTheme.ACCENT,
                            weight=ft.FontWeight.W_600)
                )
            elif stripped:
                line_controls.append(
                    ft.Text(stripped, size=14, color=AppTheme.TEXT)
                )
            else:
                line_controls.append(ft.Container(height=6))

        dlg = ft.AlertDialog(
            modal=False,
            bgcolor=AppTheme.PANEL,
            content=ft.Container(
                width=480, height=520,
                content=ft.Column(
                    [ft.Row([
                        ft.Column([
                            ft.Text(song.title, size=15, weight=ft.FontWeight.BOLD,
                                    color=AppTheme.TEXT, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(song.artist, size=12, color=AppTheme.TEXT_SECONDARY),
                        ], expand=True, spacing=2),
                        ft.IconButton(ft.Icons.CLOSE, icon_color=AppTheme.TEXT_SECONDARY,
                                      on_click=lambda _: self.page.close(dlg)),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                     ft.Divider(height=12, color=AppTheme.BORDER),
                     ft.Column(line_controls, spacing=3, scroll=ft.ScrollMode.AUTO, expand=True)],
                    spacing=8, expand=True,
                ),
                padding=ft.Padding(4, 8, 4, 8),
            ),
            actions=[], actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _open_properties(self, song):
        has_lyrics  = bool(song.lyrics_text)
        has_art     = bool(song.thumbnail_path)
        added_str   = (song.added_at or "")[:10] or "–"
        updated_str = (song.updated_at or "")[:10] or "–"

        rows = [
            ("Title",         song.title or "–"),
            ("Artist",        song.artist or "–"),
            ("Duration",      _fmt_dur(song.duration)),
            ("Lyrics",        "Available" if has_lyrics else "Not available"),
            ("Artwork",       "Available" if has_art else "Not available"),
            ("Prompt",        song.prompt or "–"),
            ("Style",         song.style or "–"),
            ("Model Version", song.model_version or "–"),
            ("Created",       added_str),
            ("Updated",       updated_str),
            ("SUNO Song ID",  song.suno_id or "–"),
        ]

        dlg = ft.AlertDialog(
            title=ft.Text("Song Properties", color=AppTheme.TEXT),
            bgcolor=AppTheme.PANEL,
            content=ft.Container(
                width=460, height=400,
                padding=ft.Padding(0, 8, 0, 8),
                content=ft.Column(
                    [ft.Row([
                        ft.Text(k, size=12, color=AppTheme.TEXT_SECONDARY, width=110),
                        ft.Text(v, size=12, color=AppTheme.TEXT, expand=True,
                                selectable=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ]) for k, v in rows],
                    spacing=8, scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: self.page.close(dlg),
                              style=ft.ButtonStyle(color=AppTheme.TEXT_SECONDARY)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    def _reveal(self, song):
        import subprocess
        if not song.file_path or not os.path.exists(song.file_path):
            self._toast("File not found — audio may not be downloaded yet")
            return
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(song.file_path)])
        except Exception:
            pass

    # ─────────────────────────────────── setters
    def _set_filter(self, key: str):
        self._filter = key
        self._style_filters()
        for chip in self._filter_ctls.values():
            self._safe(chip)
        self._populate()
        self._sync_update()

    def _set_sort(self, key: str):
        self._sort = key
        self._sort_asc = True
        self._sort_text.value = f"Sort: {self._sort_labels[key]}"
        self._safe(self._sort_text)
        self._update_sort_indicators()
        self._populate()
        self._sync_update()

    def _set_sort_col(self, key: str):
        self._sort_asc = not self._sort_asc if self._sort == key else True
        self._sort = key
        self._sort_text.value = f"Sort: {self._sort_labels.get(key, key)}"
        self._safe(self._sort_text)
        self._update_sort_indicators()
        self._populate()
        self._sync_update()

    def _set_view(self, mode: str):
        self._view_mode = mode
        state.library_view_mode = mode
        self._style_view_toggle()
        is_grid = mode == "grid"
        self._grid.visible = is_grid and bool(self._grid.controls)
        self._table_container.visible = not is_grid and bool(self._table.rows)
        self._table.visible = self._table_container.visible
        self._filter_empty.visible = not (self._grid.visible or self._table_container.visible)
        self._populate()
        self._safe(self._grid_btn)
        self._safe(self._list_btn)
        self._sync_update()

    # ─────────────────────────────────── populate
    # Render songs in batches so a large library (1000s of songs) appears
    # instantly instead of stalling while the UI builds every card at once.
    # Smaller batches keep filter/sort clicks snappy; scrolling loads more.
    _RENDER_BATCH = 60

    def _populate(self):
        # Sorting/filtering 2000+ songs is sub-millisecond; the real cost (card
        # creation) is already handled by batched rendering below. Keep this
        # synchronous so the grid is populated reliably before/after mount.
        filtered = self._get_filtered()
        self._filtered_cache = filtered
        self._rendered_count = 0
        self._grid.controls.clear()
        self._table.rows.clear()

        if not filtered:
            self._show_empty_state()
            return

        self._filter_empty.visible = False
        is_grid = self._view_mode == "grid"
        self._grid.visible = is_grid
        self._table_container.visible = not is_grid
        self._table.visible = not is_grid

        self._render_next_batch()
        self._update_summary_text(filtered, state.songs)

    def _render_next_batch(self):
        """Append the next slice from the filtered cache to the ACTIVE view only.

        Only the visible view (grid OR table) is built — building the hidden one
        too would double the work and the controls sent to the UI client.
        """
        filtered = getattr(self, "_filtered_cache", None) or []
        start = self._rendered_count
        if start >= len(filtered):
            return
        end = min(start + self._RENDER_BATCH, len(filtered))
        is_grid = self._view_mode == "grid"

        from src.services.player import player
        playing_id = player.current.id if player.current else None

        for song in filtered[start:end]:
            if is_grid:
                self._grid.controls.append(SongCard(
                    song,
                    on_click=lambda _, s=song: self._play(s),
                    on_select=self._sync_selection_bar,
                    on_favorite=lambda s=song: self._toggle_favorite(s),
                ))
            else:
                self._table.rows.append(self._table_row(song, playing_id))

        self._rendered_count = end
        # Push only the active view to the UI (no-op before mount)
        self._safe(self._grid if is_grid else self._table)

    def _on_scroll_near_bottom(self, e):
        """Load the next batch when the user scrolls close to the end."""
        try:
            max_ext = getattr(e, "max_scroll_extent", None)
            pixels = getattr(e, "pixels", None)
            if max_ext is None or pixels is None:
                return
            if pixels >= max_ext - 800:
                if self._rendered_count < len(getattr(self, "_filtered_cache", [])):
                    self._render_next_batch()
        except Exception:
            pass

    def _show_empty_state(self):
        from src.services.suno_api import suno_api

        if self._filter == "all" and not suno_api.is_configured:
            # ── not connected: show auto-detect + settings shortcut ────────
            detect_btn = ft.Container(
                content=ft.Row(
                    [ft.Icon(ft.Icons.MANAGE_SEARCH, size=18, color=AppTheme.BG),
                     ft.Text("Auto-detect Cookie", size=14,
                             weight=ft.FontWeight.BOLD, color=AppTheme.BG)],
                    spacing=8, tight=True,
                ),
                bgcolor=AppTheme.ACCENT,
                border_radius=10,
                padding=ft.Padding(24, 14, 24, 14),
                ink=True,
                on_click=lambda _: self._trigger_sync(),
            )
            settings_btn = ft.Container(
                content=ft.Row(
                    [ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=16, color=AppTheme.TEXT),
                     ft.Text("Open Settings → SUNO", size=13, color=AppTheme.TEXT)],
                    spacing=6, tight=True,
                ),
                border=ft.Border(
                    left=ft.BorderSide(1, AppTheme.BORDER),
                    top=ft.BorderSide(1, AppTheme.BORDER),
                    right=ft.BorderSide(1, AppTheme.BORDER),
                    bottom=ft.BorderSide(1, AppTheme.BORDER),
                ),
                border_radius=10,
                padding=ft.Padding(20, 10, 20, 10),
                ink=True,
                on_click=lambda _: self._open_settings(),
            )
            controls = [
                ft.Icon(ft.Icons.ACCOUNT_CIRCLE_OUTLINED, size=64,
                        color=AppTheme.TEXT_SECONDARY),
                ft.Text("Connect to SUNO", size=18,
                        weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                ft.Text("Auto-detect tries Edge/Brave when those browsers are closed.",
                        size=13, color=AppTheme.TEXT_SECONDARY),
                ft.Text("For Chrome, paste your cookie manually in Settings → SUNO.",
                        size=13, color=AppTheme.TEXT_SECONDARY),
                ft.Container(height=8),
                detect_btn,
                ft.Container(height=4),
                settings_btn,
            ]

        elif self._filter == "all":
            # ── connected but 0 songs ─────────────────────────────────────
            sync_btn = ft.Container(
                content=ft.Row(
                    [ft.Icon(ft.Icons.SYNC, size=16, color=AppTheme.ACCENT),
                     ft.Text("Sync Now", size=13, color=AppTheme.TEXT)],
                    spacing=8, tight=True,
                ),
                border=ft.Border(
                    left=ft.BorderSide(1, AppTheme.BORDER),
                    top=ft.BorderSide(1, AppTheme.BORDER),
                    right=ft.BorderSide(1, AppTheme.BORDER),
                    bottom=ft.BorderSide(1, AppTheme.BORDER),
                ),
                border_radius=10,
                padding=ft.Padding(20, 12, 20, 12),
                ink=True,
                on_click=lambda _: self._trigger_sync(),
            )
            controls = [
                ft.Icon(ft.Icons.SYNC_OUTLINED, size=56, color=AppTheme.TEXT_SECONDARY),
                ft.Text("No songs found in your SUNO library",
                        size=16, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                ft.Text("Generate music in SUNO and press Sync",
                        size=12, color=AppTheme.TEXT_SECONDARY),
                ft.Container(height=12),
                sync_btn,
            ]

        else:
            # ── other filters ─────────────────────────────────────────────
            icon, title, sub = _FILTER_EMPTY.get(
                self._filter,
                (ft.Icons.SEARCH_OFF, "No results", "Try a different filter"))
            controls = [
                ft.Icon(icon, size=56, color=AppTheme.TEXT_SECONDARY),
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                ft.Text(sub,   size=12, color=AppTheme.TEXT_SECONDARY),
            ]

        self._filter_empty.content = ft.Column(
            controls, spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self._filter_empty.visible = True
        self._grid.visible = False
        self._table_container.visible = False
        self._table.visible = False
        self._update_summary_text([], state.songs)
        self._safe(self._filter_empty)

    # ─────────────────────────────────── table row
    def _table_row(self, song, playing_id=None) -> ft.DataRow:
        is_playing  = playing_id == song.id
        is_selected = song.id in state.selected_song_ids

        cb = ft.Checkbox(value=is_selected, active_color=AppTheme.ACCENT,
                         on_change=lambda e, s=song: self._on_row_check(s, e.control.value))

        # artwork col
        if song.thumbnail_path:
            art_base = ft.Container(
                content=ft.Image(src=song.thumbnail_path, width=36, height=36, fit=ft.BoxFit.COVER),
                width=36, height=36, border_radius=6, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
        else:
            art_base = ft.Container(
                width=36, height=36, border_radius=6, bgcolor="#2A2A2A",
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.MUSIC_NOTE, size=18, color=AppTheme.TEXT_SECONDARY))
        if is_playing:
            art_cell = ft.Stack([
                art_base,
                ft.Container(content=ft.Icon(ft.Icons.EQUALIZER, size=16, color=AppTheme.ACCENT),
                             width=36, height=36, alignment=ft.Alignment(0, 0),
                             bgcolor=ft.Colors.BLACK54, border_radius=6),
            ], width=36, height=36)
        else:
            art_cell = art_base

        # title col
        title_parts = []
        if is_playing:
            title_parts.append(ft.Container(width=6, height=6, bgcolor=AppTheme.ACCENT, border_radius=3))
        title_parts.append(
            ft.Text(song.title, size=12, color=AppTheme.ACCENT if is_playing else AppTheme.TEXT,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                    weight=ft.FontWeight.W_600 if is_playing else ft.FontWeight.NORMAL))
        title_cell = ft.Row(title_parts, spacing=6, tight=True)

        date_str = (song.added_at or "")[:10] or "–"

        # status icons (lyrics + artwork)
        has_lrc = bool(song.lyrics_text)
        has_art = bool(song.thumbnail_path)
        status_cell = ft.Row([
            ft.Icon(ft.Icons.LYRICS if has_lrc else ft.Icons.LYRICS_OUTLINED,
                    size=14,
                    color=AppTheme.ACCENT if has_lrc else AppTheme.BORDER,
                    tooltip="Has lyrics" if has_lrc else "Missing lyrics"),
            ft.Icon(ft.Icons.IMAGE if has_art else ft.Icons.IMAGE_OUTLINED,
                    size=14,
                    color=AppTheme.ACCENT if has_art else AppTheme.BORDER,
                    tooltip="Has artwork" if has_art else "Missing artwork"),
        ], spacing=4, tight=True)

        return ft.DataRow(
            cells=[
                ft.DataCell(cb),
                ft.DataCell(art_cell),
                ft.DataCell(title_cell),
                ft.DataCell(ft.Text(song.artist, size=12, color=AppTheme.TEXT_SECONDARY,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                ft.DataCell(ft.Text(_fmt_dur(song.duration), size=12, color=AppTheme.TEXT_SECONDARY)),
                ft.DataCell(ft.Text(date_str, size=12, color=AppTheme.TEXT_SECONDARY)),
                ft.DataCell(ft.Text(song.style or "–", size=11, color=AppTheme.TEXT_SECONDARY,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                ft.DataCell(ft.Text(song.model_version or "–", size=11, color=AppTheme.TEXT_SECONDARY)),
                ft.DataCell(status_cell),
                ft.DataCell(self._row_actions(song)),
            ],
            color=ft.Colors.WHITE10 if is_selected else None,
        )

    def _row_actions(self, song) -> ft.Row:
        fav_btn = ft.IconButton(
            ft.Icons.FAVORITE if song.is_favorite else ft.Icons.FAVORITE_BORDER,
            icon_size=16, tooltip="Favorite",
            icon_color=AppTheme.DANGER if song.is_favorite else AppTheme.TEXT_SECONDARY)
        fav_btn.on_click = lambda _, s=song, b=fav_btn: self._row_toggle_favorite(s, b)
        return ft.Row([
            ft.IconButton(ft.Icons.PLAY_ARROW, icon_size=18, icon_color=AppTheme.ACCENT,
                          tooltip="Play", on_click=lambda _, s=song: self._play(s)),
            fav_btn,
            ft.IconButton(ft.Icons.LYRICS_OUTLINED, icon_size=16, tooltip="Lyrics",
                          icon_color=AppTheme.TEXT_SECONDARY,
                          on_click=lambda _, s=song: self._open_lyrics(s)),
            ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_size=16, tooltip="Edit",
                          icon_color=AppTheme.TEXT_SECONDARY,
                          on_click=lambda _, s=song: self._open_edit(s)),
            ft.IconButton(ft.Icons.INFO_OUTLINE, icon_size=16, tooltip="Properties",
                          icon_color=AppTheme.TEXT_SECONDARY,
                          on_click=lambda _, s=song: self._open_properties(s)),
            ft.IconButton(ft.Icons.FOLDER_OPEN, icon_size=16, tooltip="Open Folder",
                          icon_color=AppTheme.TEXT_SECONDARY,
                          on_click=lambda _, s=song: self._reveal(s)),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, tooltip="Delete",
                          icon_color=AppTheme.TEXT_SECONDARY,
                          on_click=lambda _, s=song: self._delete_one(s)),
        ], spacing=0, tight=True)

    def _row_toggle_favorite(self, song, btn):
        # Optimistic icon flip on the row, then persist (mirrors the card path).
        song.is_favorite = not song.is_favorite
        btn.icon = ft.Icons.FAVORITE if song.is_favorite else ft.Icons.FAVORITE_BORDER
        btn.icon_color = AppTheme.DANGER if song.is_favorite else AppTheme.TEXT_SECONDARY
        self._safe(btn)
        self._toggle_favorite(song)

    def _open_edit(self, song):
        title_field = ft.TextField(
            label="Title", value=song.title or "", color=AppTheme.TEXT,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, text_size=13)
        artist_field = ft.TextField(
            label="Artist", value=song.artist or "", color=AppTheme.TEXT,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, text_size=13)

        def _save(_):
            new_title = (title_field.value or "").strip()
            new_artist = (artist_field.value or "").strip()
            if new_title:
                song.title = new_title
            if new_artist:
                song.artist = new_artist
            from src.services.storage import storage
            try:
                storage.save_song(song)
            except Exception:
                pass
            try:
                self.page.close(dlg)
            except Exception:
                pass
            self._populate()
            self._sync_update()
            self._toast("Saved")

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=AppTheme.PANEL,
            title=ft.Text("Edit Song", color=AppTheme.TEXT),
            content=ft.Container(
                width=420,
                content=ft.Column([title_field, artist_field], spacing=14, tight=True),
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self.page.close(dlg),
                              style=ft.ButtonStyle(color=AppTheme.TEXT_SECONDARY)),
                ft.TextButton("Save", on_click=_save,
                              style=ft.ButtonStyle(color=AppTheme.ACCENT)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)

    # ─────────────────────────────────── refresh helpers
    def _refresh_after_change(self):
        if not hasattr(self, "_count_label"):
            return
        self._count_label.value = f"{len(state.songs)} songs"
        self._update_chip_counts()
        self._populate()
        self._sync_selection_bar()
        self._safe(self._count_label)
        self._sync_update()

    def _sync_update(self):
        for ctl in (self._grid, self._table_container, self._filter_empty, self._selection_bar):
            try:
                ctl.update()
            except (RuntimeError, AssertionError):
                pass

    def _safe(self, control):
        try:
            control.update()
        except (RuntimeError, AssertionError):
            pass

    @property
    def _pg(self):
        """Page if mounted, else None (safe to call from background threads)."""
        try:
            return self.page
        except Exception:
            return None

    def _run_ui(self, fn, *args):
        pg = self._pg
        if pg is None:
            return
        try:
            pg.run_task(fn, *args)
        except Exception:
            pass

    def _toast(self, msg: str):
        try:
            self.page.open(ft.SnackBar(ft.Text(msg), bgcolor=AppTheme.CARD))
        except Exception:
            pass


# ─────────────────────────────────────────────────── module helpers
def _fmt_dur(seconds: float) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "--:--"
    return f"{s // 60}:{s % 60:02d}"


def _fmt_total(seconds: float) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "0m"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m {s % 60}s"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _last_sync_label(iso_ts: str | None) -> str:
    """Return human-readable 'Last Sync: X ago' or 'Last Sync: Never'."""
    if not iso_ts:
        return "Last Sync: Never"
    try:
        dt = datetime.datetime.fromisoformat(iso_ts)
        delta = datetime.datetime.utcnow() - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "Last Sync: just now"
        if secs < 3600:
            m = secs // 60
            return f"Last Sync: {m} minute{'s' if m != 1 else ''} ago"
        if secs < 86400:
            h = secs // 3600
            return f"Last Sync: {h} hour{'s' if h != 1 else ''} ago"
        d = secs // 86400
        return f"Last Sync: {d} day{'s' if d != 1 else ''} ago"
    except Exception:
        return "Last Sync: –"
