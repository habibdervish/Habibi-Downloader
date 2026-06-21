"""Scanner — standalone desktop file explorer & media organizer.

Fully independent: no Library, no Discovery, no online services, no storage.
Scans folders / drives / the whole computer and provides professional file
operations (move, copy, rename, delete, bulk-rename, duplicates, …).
"""

import os
import threading

import flet as ft

from src.theme import AppTheme
from src.services import file_scanner as fs
from src.services.file_scanner import (
    FileRecord, ScanOptions, scanner, fmt_size, fmt_date,
)


_PAGE_SIZE = 200  # rows drawn per page (all records kept in memory; paged through)


class ScannerView(ft.Container):
    def __init__(self):
        super().__init__(expand=True, padding=ft.Padding(28, 22, 28, 16), bgcolor=AppTheme.BG)
        self._sources: list = []          # selected folders + drive roots
        self._drive_chips: dict = {}      # root -> chip container
        self._all: list = []              # all FileRecord (unfiltered)
        self._view: list = []             # currently displayed (filtered) records
        self._selected: set = set()       # selected record paths
        self._filter_cat = "all"
        self._search = ""
        self._custom_ext = ""
        self._last_dest = None
        self._row_lookup: dict = {}       # path -> (record, checkbox)
        self._last_live_render = 0.0      # throttle live table refresh during scan
        self._page_idx = 0                # current results page
        self._show_thumbs = True          # load image thumbnails only when not busy scanning
        self.content = self._build()

    # ════════════════════════════════════════════════════════════ build
    def _build(self):
        title = ft.Column([
            ft.Text("Scanner", size=28, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
            ft.Text("Scan drives & folders · organize files like a pro file manager",
                    size=13, color=AppTheme.TEXT_SECONDARY),
        ], spacing=2)

        # ── source selection row
        src_buttons = ft.Row([
            self._btn("Add Folder", ft.Icons.CREATE_NEW_FOLDER_OUTLINED, self._add_folder),
            self._btn("Whole Computer", ft.Icons.COMPUTER, self._select_all_drives),
            self._btn("Refresh Drives", ft.Icons.REFRESH, lambda _: self._load_drives()),
            self._btn("Clear Sources", ft.Icons.CLEAR_ALL, lambda _: self._clear_sources()),
        ], spacing=8, wrap=True)

        self._drives_row = ft.Row([], spacing=8, wrap=True)
        self._sources_label = ft.Text("No sources selected", size=12, color=AppTheme.TEXT_SECONDARY)

        # ── scan options
        self._opt_recursive = self._check("Recursive", True)
        self._opt_hidden = self._check("Hidden", False)
        self._opt_system = self._check("System", False)
        self._opt_symlinks = self._check("Symlinks", False)
        self._opt_dirs = self._check("Include folders", False)
        options_row = ft.Row(
            [self._opt_recursive, self._opt_hidden, self._opt_system,
             self._opt_symlinks, self._opt_dirs],
            spacing=18, wrap=True, run_spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # ── scan control buttons + progress
        self._scan_btn = ft.ElevatedButton(
            "Start Scan", icon=ft.Icons.PLAY_ARROW_ROUNDED,
            bgcolor=AppTheme.ACCENT, color=AppTheme.ON_ACCENT,
            on_click=lambda _: self._start_scan())
        self._pause_btn = ft.ElevatedButton(
            "Pause", icon=ft.Icons.PAUSE, on_click=lambda _: self._pause_scan(),
            bgcolor=AppTheme.CARD, color=AppTheme.TEXT, visible=False)
        self._resume_btn = ft.ElevatedButton(
            "Resume", icon=ft.Icons.PLAY_ARROW, on_click=lambda _: self._resume_scan(),
            bgcolor=AppTheme.CARD, color=AppTheme.TEXT, visible=False)
        self._cancel_btn = ft.ElevatedButton(
            "Cancel", icon=ft.Icons.STOP, on_click=lambda _: self._cancel_scan(),
            bgcolor=AppTheme.DANGER, color=ft.Colors.WHITE, visible=False)
        scan_controls = ft.Row(
            [self._scan_btn, self._pause_btn, self._resume_btn, self._cancel_btn],
            spacing=8)

        self._progress = ft.ProgressBar(value=0, color=AppTheme.ACCENT,
                                        bgcolor=AppTheme.CARD, visible=False)
        self._status = ft.Text("", size=12, color=AppTheme.TEXT_SECONDARY)

        # ── search + filters
        self._search_field = ft.TextField(
            hint_text="Search name, extension or path…",
            prefix_icon=ft.Icons.SEARCH, height=40, expand=True, text_size=13,
            border_radius=8, bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, color=AppTheme.TEXT,
            content_padding=ft.Padding(12, 6, 12, 6),
            on_change=self._on_search)
        self._custom_field = ft.TextField(
            hint_text="e.g. mp4, pdf, psd", width=160, height=40, visible=False,
            text_size=13, border_radius=8,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, color=AppTheme.TEXT,
            content_padding=ft.Padding(12, 6, 12, 6),
            tooltip="Comma-separated extensions to show (only when filter = Custom ext)",
            on_change=self._on_custom_ext)
        self._filter_dd = ft.Dropdown(
            value="all", width=140, height=40, text_size=13, border_radius=8,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            color=AppTheme.TEXT, content_padding=ft.Padding(12, 4, 8, 4),
            options=[
                ft.dropdown.Option("all", "All files"),
                ft.dropdown.Option("images", "Images"),
                ft.dropdown.Option("videos", "Videos"),
                ft.dropdown.Option("audio", "Audio"),
                ft.dropdown.Option("documents", "Documents"),
                ft.dropdown.Option("archives", "Archives"),
                ft.dropdown.Option("custom", "Custom ext"),
            ],
            on_select=self._on_filter)
        search_row = ft.Row(
            [self._search_field, self._filter_dd, self._custom_field],
            spacing=8)

        # ── operations toolbar — primary actions visible, rest in a "More" menu
        def menu_item(text, icon, handler, danger=False):
            return ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(icon, size=17,
                            color=AppTheme.DANGER if danger else AppTheme.TEXT_SECONDARY),
                    ft.Text(text, size=13,
                            color=AppTheme.DANGER if danger else AppTheme.TEXT),
                ], spacing=10),
                on_click=lambda _: handler())

        more_menu = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.MORE_HORIZ, size=15, color=AppTheme.TEXT),
                    ft.Text("More", size=11, color=AppTheme.TEXT),
                ], spacing=4, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                width=84, height=30, bgcolor=AppTheme.CARD, border_radius=7,
                padding=ft.Padding(10, 0, 10, 0),
                alignment=ft.Alignment(0, 0)),
            menu_position=ft.PopupMenuPosition.UNDER,
            items=[
                menu_item("Rename", ft.Icons.DRIVE_FILE_RENAME_OUTLINE, self._rename_selected),
                menu_item("Bulk Rename", ft.Icons.EDIT_NOTE, self._bulk_rename),
                menu_item("New Folder", ft.Icons.CREATE_NEW_FOLDER, self._new_folder),
                menu_item("Duplicate", ft.Icons.CONTENT_COPY, self._duplicate_selected),
                ft.PopupMenuItem(),  # divider
                menu_item("Open Folder", ft.Icons.FOLDER_OPEN, self._open_folder),
                menu_item("Open", ft.Icons.LAUNCH, self._open_default),
                menu_item("Open With…", ft.Icons.APPS, self._open_with),
            ])

        self._ops_bar = ft.Row([
            self._op("Select All", ft.Icons.SELECT_ALL, self._select_all_rows),
            self._op("Clear", ft.Icons.DESELECT, self._clear_selection),
            ft.Container(width=1, height=20, bgcolor=AppTheme.BORDER),
            self._op("Move", ft.Icons.DRIVE_FILE_MOVE_OUTLINE, self._move_selected),
            self._op("Copy", ft.Icons.COPY_ALL_OUTLINED, self._copy_selected),
            self._op("Delete", ft.Icons.DELETE_OUTLINE, self._delete_selected, danger=True),
            self._op("Find Dupes", ft.Icons.FIND_REPLACE, self._find_duplicates),
            more_menu,
        ], spacing=6, wrap=True, run_spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # ── results table
        def col(label, w=None):
            return ft.DataColumn(ft.Text(label, size=12, weight=ft.FontWeight.W_500,
                                         color=AppTheme.TEXT_SECONDARY))
        self._table = ft.DataTable(
            columns=[
                col(""), col("Name"), col("Ext"), col("Path"),
                col("Size"), col("Created"), col("Modified"), col("Drive"), col("Status"),
            ],
            rows=[], column_spacing=22, heading_row_color=AppTheme.PANEL,
            bgcolor=AppTheme.CARD, border_radius=10, divider_thickness=0.5,
            horizontal_lines=ft.BorderSide(0.5, AppTheme.BORDER),
        )
        self._table_wrap = ft.Column([ft.Row([self._table], scroll=ft.ScrollMode.AUTO)],
                                     scroll=ft.ScrollMode.AUTO, expand=True, visible=False)
        self._result_summary = ft.Text("", size=12, color=AppTheme.TEXT_SECONDARY)

        # ── pagination controls
        self._prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT, icon_color=AppTheme.TEXT,
                                       icon_size=22, tooltip="Previous page",
                                       on_click=lambda _: self._change_page(-1))
        self._next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT, icon_color=AppTheme.TEXT,
                                       icon_size=22, tooltip="Next page",
                                       on_click=lambda _: self._change_page(1))
        self._page_label = ft.Text("", size=12, color=AppTheme.TEXT_SECONDARY)
        self._page_field = ft.TextField(
            width=64, height=36, text_align=ft.TextAlign.CENTER,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, color=AppTheme.TEXT,
            content_padding=ft.Padding(4, 4, 4, 4),
            on_submit=self._goto_page, tooltip="Type a page number and press Enter")
        self._pager = ft.Row(
            [self._result_summary, ft.Container(expand=True),
             self._prev_btn, self._page_label,
             ft.Text("Go to", size=11, color=AppTheme.TEXT_SECONDARY),
             self._page_field, self._next_btn],
            vertical_alignment=ft.CrossAxisAlignment.CENTER, visible=False)

        self._empty = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.TRAVEL_EXPLORE, size=56, color=AppTheme.TEXT_SECONDARY),
                ft.Text("Pick folders or drives above, then Start Scan",
                        size=14, color=AppTheme.TEXT_SECONDARY),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER),
            alignment=ft.Alignment(0, 0), expand=True)

        def panel(child):
            return ft.Container(content=child, padding=14, border_radius=12,
                                bgcolor=AppTheme.PANEL,
                                border=ft.Border(
                                    left=ft.BorderSide(1, AppTheme.BORDER),
                                    top=ft.BorderSide(1, AppTheme.BORDER),
                                    right=ft.BorderSide(1, AppTheme.BORDER),
                                    bottom=ft.BorderSide(1, AppTheme.BORDER)))

        self._load_drives()

        return ft.Column([
            title,
            panel(ft.Column([
                src_buttons,
                self._drives_row,
                self._sources_label,
                ft.Divider(height=8, color=AppTheme.BORDER),
                options_row,
                scan_controls,
                self._progress,
                self._status,
            ], spacing=10)),
            search_row,
            ft.Container(content=self._ops_bar, padding=ft.Padding(0, 2, 0, 2)),
            self._pager,
            ft.Container(content=ft.Stack([self._empty, self._table_wrap]),
                         expand=True),
        ], spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)

    # ── small widget factories ──────────────────────────────────────
    def _btn(self, text, icon, on_click):
        return ft.ElevatedButton(text, icon=icon, on_click=on_click,
                                 bgcolor=AppTheme.CARD, color=AppTheme.TEXT, height=38)

    def _op(self, text, icon, handler, danger=False):
        return ft.ElevatedButton(
            text, icon=icon, on_click=lambda _: handler(), height=30,
            bgcolor=AppTheme.DANGER if danger else AppTheme.CARD,
            color=ft.Colors.WHITE if danger else AppTheme.TEXT,
            style=ft.ButtonStyle(
                text_style=ft.TextStyle(size=11),
                padding=ft.Padding(10, 0, 10, 0),
                shape=ft.RoundedRectangleBorder(radius=7),
                icon_size=15))

    def _check(self, label, value):
        return ft.Checkbox(label=label, value=value, active_color=AppTheme.ACCENT,
                           label_style=ft.TextStyle(color=AppTheme.TEXT, size=12),
                           fill_color=AppTheme.CARD)

    # ════════════════════════════════════════════════════════════ drives
    def _load_drives(self):
        self._drives_row.controls.clear()
        for d in fs.list_drives():
            self._drives_row.controls.append(self._drive_chip(d))
        self._safe(self._drives_row)

    def _drive_chip(self, d):
        icon = {
            "removable": ft.Icons.USB, "network": ft.Icons.LAN,
            "cdrom": ft.Icons.ALBUM, "fixed": ft.Icons.STORAGE,
        }.get(d["type"], ft.Icons.STORAGE)
        free = fmt_size(d["free"]) if d["free"] else ""
        label = f"{d['letter']}:  {d['label'] or d['type']}"
        sub = f"{free} free" if free else d["type"]
        chip = ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=18, color=AppTheme.TEXT_SECONDARY),
                ft.Column([
                    ft.Text(label, size=12, weight=ft.FontWeight.W_500, color=AppTheme.TEXT),
                    ft.Text(sub, size=10, color=AppTheme.TEXT_SECONDARY),
                ], spacing=0),
            ], spacing=8, tight=True),
            padding=ft.Padding(10, 6, 12, 6), border_radius=8, bgcolor=AppTheme.CARD,
            border=ft.Border(left=ft.BorderSide(1, AppTheme.BORDER),
                             top=ft.BorderSide(1, AppTheme.BORDER),
                             right=ft.BorderSide(1, AppTheme.BORDER),
                             bottom=ft.BorderSide(1, AppTheme.BORDER)),
            on_click=lambda _, root=d["root"]: self._toggle_drive(root),
            data=d["root"],
        )
        self._drive_chips[d["root"]] = chip
        return chip

    def _toggle_drive(self, root):
        if root in self._sources:
            self._sources.remove(root)
        else:
            self._sources.append(root)
        self._restyle_chips()
        self._update_sources_label()

    def _restyle_chips(self):
        for root, chip in self._drive_chips.items():
            on = root in self._sources
            chip.bgcolor = AppTheme.ACCENT if on else AppTheme.CARD
            for c in chip.content.controls:
                if isinstance(c, ft.Icon):
                    c.color = AppTheme.ON_ACCENT if on else AppTheme.TEXT_SECONDARY
                if isinstance(c, ft.Column):
                    for t in c.controls:
                        t.color = AppTheme.ON_ACCENT if on else (
                            AppTheme.TEXT if t.size == 12 else AppTheme.TEXT_SECONDARY)
            self._safe(chip)

    def _select_all_drives(self, _=None):
        for d in fs.list_drives():
            if d["root"] not in self._sources:
                self._sources.append(d["root"])
        self._restyle_chips()
        self._update_sources_label()

    def _clear_sources(self):
        self._sources.clear()
        self._restyle_chips()
        self._update_sources_label()

    def _add_folder(self, _=None):
        threading.Thread(target=self._pick_folder_bg, daemon=True).start()

    def _pick_folder_bg(self):
        folder = _ask_directory("Add a folder to scan")
        if folder and folder not in self._sources:
            self._sources.append(folder)
            self._run_ui(self._update_sources_label)

    def _update_sources_label(self):
        if not self._sources:
            self._sources_label.value = "No sources selected"
        else:
            self._sources_label.value = f"{len(self._sources)} source(s): " + "   ".join(self._sources)
        self._safe(self._sources_label)

    async def _update_sources_label_async(self):
        self._update_sources_label()

    # ════════════════════════════════════════════════════════════ scan
    def _start_scan(self):
        if scanner.is_running():
            self._toast("A scan is already running")
            return
        if not self._sources:
            self._toast("Select at least one folder or drive first")
            return
        self._all = []
        self._selected.clear()
        self._table.rows.clear()
        self._row_lookup.clear()
        self._empty.visible = False
        self._table_wrap.visible = True
        self._progress.value = None
        self._progress.visible = True
        self._status.value = "Starting…"
        self._scan_btn.visible = False
        self._pause_btn.visible = True
        self._cancel_btn.visible = True
        self._resume_btn.visible = False
        self._show_thumbs = False  # icons-only while scanning keeps the UI snappy
        self._safe(self)

        opts = ScanOptions(
            recursive=self._opt_recursive.value,
            include_hidden=self._opt_hidden.value,
            include_system=self._opt_system.value,
            follow_symlinks=self._opt_symlinks.value,
            include_dirs=self._opt_dirs.value,
        )
        scanner.scan(
            list(self._sources), opts,
            on_batch=self._on_batch,
            on_progress=self._on_progress,
            on_done=self._on_done,
        )

    def _on_batch(self, records):
        # worker thread → extend store, schedule a throttled refresh so a
        # million-file scan doesn't rebuild the table hundreds of times/sec
        self._all.extend(records)
        import time as _t
        now = _t.time()
        if now - self._last_live_render > 1.2:
            self._last_live_render = now
            self._run_ui(self._refresh_results_async)

    def _on_progress(self, scanned, matched, current):
        self._run_ui(self._progress_async, scanned, matched, current)

    def _on_done(self, scanned, matched, cancelled):
        self._run_ui(self._done_async, scanned, matched, cancelled)

    async def _progress_async(self, scanned, matched, current):
        self._status.value = f"Scanning… {scanned:,} seen · {matched:,} matched · {current[:70]}"
        self._safe(self._status)

    async def _done_async(self, scanned, matched, cancelled):
        self._progress.visible = False
        self._scan_btn.visible = True
        self._pause_btn.visible = False
        self._resume_btn.visible = False
        self._cancel_btn.visible = False
        verb = "Cancelled" if cancelled else "Done"
        self._status.value = f"{verb} — {matched:,} files from {scanned:,} scanned"
        self._show_thumbs = True  # render with image previews now that we're idle
        self._safe(self)
        self._apply_filter(reset_page=False)

    def _pause_scan(self):
        scanner.pause()
        self._pause_btn.visible = False
        self._resume_btn.visible = True
        self._status.value = "Paused — showing results so far"
        self._show_thumbs = True
        self._safe(self)
        self._apply_filter(reset_page=False)

    def _resume_scan(self):
        scanner.resume()
        self._pause_btn.visible = True
        self._resume_btn.visible = False
        self._show_thumbs = False
        self._safe(self)

    def _cancel_scan(self):
        scanner.cancel()
        self._status.value = "Cancelling…"
        self._safe(self._status)

    # ════════════════════════════════════════════════════════════ filter / search
    def _on_search(self, e):
        self._search = (e.control.value or "").lower().strip()
        self._apply_filter()

    def _on_custom_ext(self, e):
        self._custom_ext = (e.control.value or "").lower().strip()
        if self._filter_cat == "custom":
            self._apply_filter()

    def _on_filter(self, e):
        self._filter_cat = e.control.value
        self._custom_field.visible = self._filter_cat == "custom"
        self._safe(self._custom_field)
        self._apply_filter()

    def _filtered_view(self):
        """Apply current category + search filters to all scanned records."""
        recs = self._all
        cat = self._filter_cat
        if cat == "custom":
            exts = {("." + x.strip().lstrip(".")) for x in self._custom_ext.split(",") if x.strip()}
            if exts:
                recs = [r for r in recs if r.ext.lower() in exts]
        elif cat != "all":
            recs = [r for r in recs if r.category == cat]

        if self._search:
            q = self._search
            recs = [r for r in recs
                    if q in r.name.lower() or q in r.ext.lower() or q in r.path.lower()]
        return recs

    def _apply_filter(self, reset_page=True):
        self._view = self._filtered_view()
        if reset_page:
            self._page_idx = 0
        self._render_table()

    def _page_count(self) -> int:
        return max(1, (len(self._view) + _PAGE_SIZE - 1) // _PAGE_SIZE)

    def _change_page(self, delta):
        self._page_idx = max(0, min(self._page_count() - 1, self._page_idx + delta))
        self._render_table()

    def _goto_page(self, e):
        try:
            n = int((e.control.value or "1").strip()) - 1
        except ValueError:
            return
        self._page_idx = max(0, min(self._page_count() - 1, n))
        self._render_table()

    def _render_table(self):
        self._table.rows.clear()
        self._row_lookup.clear()
        total = len(self._view)
        pages = self._page_count()
        self._page_idx = max(0, min(self._page_idx, pages - 1))
        start = self._page_idx * _PAGE_SIZE
        end = min(start + _PAGE_SIZE, total)
        for r in self._view[start:end]:
            self._table.rows.append(self._row(r))

        sel = f"  ·  {len(self._selected):,} selected" if self._selected else ""
        if total:
            self._result_summary.value = f"Showing {start + 1:,}–{end:,} of {total:,} files{sel}"
        else:
            self._result_summary.value = "0 files"
        self._page_label.value = f"Page {self._page_idx + 1} / {pages:,}"
        self._page_field.value = str(self._page_idx + 1)
        self._prev_btn.disabled = self._page_idx <= 0
        self._next_btn.disabled = self._page_idx >= pages - 1
        self._pager.visible = total > 0
        self._empty.visible = total == 0
        self._table_wrap.visible = total > 0
        self._safe(self)

    def _row(self, r: FileRecord):
        cb = ft.Checkbox(value=r.path in self._selected, active_color=AppTheme.ACCENT,
                         on_change=lambda e, p=r.path: self._toggle_row(p, e.control.value))
        self._row_lookup[r.path] = (r, cb)

        def t(val, w=None, color=AppTheme.TEXT, size=12):
            return ft.Container(width=w, content=ft.Text(
                val, size=size, color=color, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))

        # Real thumbnail for image files; otherwise a clean type icon.
        # Thumbnails are skipped during active scanning (loading 200 images from
        # disk every refresh would freeze the UI); they appear once scan pauses/ends.
        if self._show_thumbs and (not r.is_dir) and r.ext.lower() in fs.IMAGE_EXTS:
            lead = ft.Container(
                width=30, height=30, border_radius=5, bgcolor=AppTheme.PANEL,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=r.path, width=30, height=30, fit=ft.BoxFit.COVER,
                                 error_content=ft.Icon(ft.Icons.IMAGE_OUTLINED, size=15,
                                                       color=AppTheme.TEXT_SECONDARY)))
        else:
            lead = ft.Container(
                width=30, height=30, alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.FOLDER if r.is_dir else _file_icon(r.ext),
                                size=17,
                                color=AppTheme.ACCENT if r.is_dir else AppTheme.TEXT_SECONDARY))
        name_cell = ft.Row([lead, ft.Text(r.name, size=12, color=AppTheme.TEXT,
                                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                           spacing=8, tight=True, width=280)
        return ft.DataRow(cells=[
            ft.DataCell(cb),
            ft.DataCell(name_cell),
            ft.DataCell(t(r.ext.lstrip(".").upper() or "—", 60, AppTheme.TEXT_SECONDARY)),
            ft.DataCell(t(os.path.dirname(r.path), 300, AppTheme.TEXT_SECONDARY, 11)),
            ft.DataCell(t("—" if r.is_dir else fmt_size(r.size), 80, AppTheme.TEXT_SECONDARY)),
            ft.DataCell(t(fmt_date(r.created), 130, AppTheme.TEXT_SECONDARY, 11)),
            ft.DataCell(t(fmt_date(r.modified), 130, AppTheme.TEXT_SECONDARY, 11)),
            ft.DataCell(t(r.drive, 50, AppTheme.TEXT_SECONDARY)),
            ft.DataCell(t(r.status, 90, AppTheme.ACCENT if r.status != "Found" else AppTheme.TEXT_SECONDARY)),
        ])

    def _toggle_row(self, path, checked):
        if checked:
            self._selected.add(path)
        else:
            self._selected.discard(path)
        self._update_summary_only()

    def _update_summary_only(self):
        total = len(self._view)
        pages = self._page_count()
        start = self._page_idx * _PAGE_SIZE
        end = min(start + _PAGE_SIZE, total)
        sel = f"  ·  {len(self._selected):,} selected" if self._selected else ""
        if total:
            self._result_summary.value = f"Showing {start + 1:,}–{end:,} of {total:,} files{sel}"
        else:
            self._result_summary.value = "0 files"
        self._safe(self._result_summary)

    def _select_all_rows(self):
        for r in self._view:
            self._selected.add(r.path)
        self._render_table()

    def _clear_selection(self):
        self._selected.clear()
        self._render_table()

    def _selected_records(self):
        sel = self._selected
        return [r for r in self._all if r.path in sel]

    # ════════════════════════════════════════════════════════════ operations
    def _need_selection(self):
        if not self._selected:
            self._toast("Select files first")
            return False
        return True

    def _move_selected(self):
        if not self._need_selection():
            return
        threading.Thread(target=self._move_worker, daemon=True).start()

    def _move_worker(self):
        dest = _ask_directory("Move selected to…", self._last_dest)
        if not dest:
            return
        self._last_dest = dest
        recs = self._selected_records()
        for r in recs:
            try:
                new = fs.move_file(r.path, dest)
                r.path, r.status, r.drive = new, "Moved", os.path.splitdrive(new)[0]
            except Exception:
                r.status = "Error"
        self._selected.clear()
        self._run_ui(self._after_op_async, f"Moved {len(recs)} item(s)")

    def _copy_selected(self):
        if not self._need_selection():
            return
        threading.Thread(target=self._copy_worker, daemon=True).start()

    def _copy_worker(self):
        dest = _ask_directory("Copy selected to…", self._last_dest)
        if not dest:
            return
        self._last_dest = dest
        recs = self._selected_records()
        ok = 0
        for r in recs:
            try:
                fs.copy_file(r.path, dest)
                r.status = "Copied"
                ok += 1
            except Exception:
                r.status = "Error"
        self._run_ui(self._after_op_async, f"Copied {ok} item(s)")

    def _delete_selected(self):
        if not self._need_selection():
            return
        recs = self._selected_records()
        self._confirm(f"Delete {len(recs)} item(s)? (sent to Recycle Bin)",
                      lambda: threading.Thread(target=self._delete_worker, args=(recs,),
                                               daemon=True).start())

    def _delete_worker(self, recs):
        ok = 0
        for r in recs:
            if fs.delete_path(r.path, to_trash=True):
                r.status = "Deleted"
                ok += 1
            else:
                r.status = "Error"
        # drop deleted from store
        deleted = {r.path for r in recs if r.status == "Deleted"}
        self._all = [r for r in self._all if r.path not in deleted]
        self._selected.clear()
        self._run_ui(self._after_op_async, f"Deleted {ok} item(s)")

    def _rename_selected(self):
        recs = self._selected_records()
        if len(recs) != 1:
            self._toast("Select exactly one file to rename")
            return
        r = recs[0]
        self._prompt("Rename", r.name, lambda v: self._do_rename(r, v))

    def _do_rename(self, r, new_name):
        if not new_name or new_name == r.name:
            return
        try:
            new = fs.rename_path(r.path, new_name)
            r.path, r.name, r.status = new, os.path.basename(new), "Renamed"
            self._toast("Renamed")
        except Exception as ex:
            self._toast(f"Rename failed: {ex}")
        self._selected.clear()
        self._apply_filter()

    def _bulk_rename(self):
        if not self._need_selection():
            return
        self._prompt("Bulk rename pattern  (tokens: {n} {name} {ext})",
                     "{name}_{n}.{ext}", self._do_bulk_rename)

    def _do_bulk_rename(self, pattern):
        if not pattern:
            return
        recs = self._selected_records()
        paths = [r.path for r in recs]
        new_paths = fs.bulk_rename(paths, pattern)
        for r, np in zip(recs, new_paths):
            r.path, r.name, r.status = np, os.path.basename(np), "Renamed"
        self._selected.clear()
        self._toast(f"Renamed {len(recs)} item(s)")
        self._apply_filter()

    def _new_folder(self):
        threading.Thread(target=self._new_folder_bg, daemon=True).start()

    def _new_folder_bg(self):
        parent = _ask_directory("Create new folder inside…", self._last_dest)
        if not parent:
            return
        self._run_ui(self._prompt_async, "New folder name", "New Folder",
                     lambda v: self._do_new_folder(parent, v))

    def _do_new_folder(self, parent, name):
        if not name:
            return
        try:
            path = fs.create_folder(parent, name)
            self._toast(f"Created {os.path.basename(path)}")
        except Exception as ex:
            self._toast(f"Failed: {ex}")

    def _duplicate_selected(self):
        if not self._need_selection():
            return
        threading.Thread(target=self._duplicate_worker, daemon=True).start()

    def _duplicate_worker(self):
        recs = self._selected_records()
        ok = 0
        for r in recs:
            try:
                fs.duplicate_path(r.path)
                ok += 1
                r.status = "Duplicated"
            except Exception:
                r.status = "Error"
        self._run_ui(self._after_op_async, f"Duplicated {ok} item(s)")

    def _find_duplicates(self):
        if not self._all:
            self._toast("Scan some files first")
            return
        self._choose_dupe_method()

    def _run_dupes(self, method):
        self._status.value = f"Finding duplicates by {method}…"
        self._progress.visible = True
        self._progress.value = None
        self._safe(self)
        threading.Thread(target=self._dupes_worker, args=(method,), daemon=True).start()

    def _dupes_worker(self, method):
        groups = fs.find_duplicates(self._view or self._all, method=method)
        dup_paths = {r.path for g in groups for r in g}
        for r in self._all:
            if r.path in dup_paths:
                r.status = "Duplicate"
        # show only duplicates
        self._view = [r for g in groups for r in g]
        self._run_ui(self._after_dupes_async, len(groups), len(dup_paths))

    async def _after_dupes_async(self, n_groups, n_files):
        self._progress.visible = False
        self._status.value = f"{n_files} duplicate files in {n_groups} groups"
        self._render_table()

    def _open_folder(self):
        recs = self._selected_records()
        if not recs:
            self._toast("Select a file")
            return
        fs.open_in_explorer(recs[0].path)

    def _open_default(self):
        recs = self._selected_records()
        if not recs:
            self._toast("Select a file")
            return
        for r in recs[:8]:
            fs.open_default(r.path)

    def _open_with(self):
        recs = self._selected_records()
        if not recs:
            self._toast("Select a file")
            return
        threading.Thread(target=self._open_with_bg, args=(recs[0],), daemon=True).start()

    def _open_with_bg(self, r):
        app = _ask_open_file("Choose application")
        if app:
            fs.open_with(r.path, app)

    async def _after_op_async(self, msg):
        self._toast(msg)
        self._apply_filter()

    async def _refresh_results_async(self):
        # While results stream in, only auto-refresh the table when the user is
        # on the first page. If they've paged deeper (to inspect/select), leave
        # their view stable so the scan doesn't fight their interaction.
        if self._page_idx == 0:
            self._apply_filter(reset_page=False)
        else:
            # still update the live count without rebuilding rows
            self._view = self._filtered_view()
            self._update_summary_only()
            self._safe(self._result_summary)

    # ════════════════════════════════════════════════════════════ dialogs
    def _choose_dupe_method(self):
        def pick(m):
            self.page.close(dlg)
            self._run_dupes(m)
        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Text("Find duplicates by", color=AppTheme.TEXT),
            content=ft.Column([
                ft.Text("Choose how to compare files:", size=12, color=AppTheme.TEXT_SECONDARY),
                ft.Row([
                    self._btn("Hash (content)", ft.Icons.TAG, lambda _: pick("hash")),
                    self._btn("Filename", ft.Icons.ABC, lambda _: pick("filename")),
                ], spacing=8),
                ft.Row([
                    self._btn("Size", ft.Icons.STRAIGHTEN, lambda _: pick("size")),
                    self._btn("Date", ft.Icons.CALENDAR_MONTH, lambda _: pick("date")),
                ], spacing=8),
            ], tight=True, spacing=12, width=360),
            actions=[ft.TextButton("Cancel", on_click=lambda _: self.page.close(dlg))],
        )
        self.page.open(dlg)

    def _confirm(self, msg, on_yes):
        def yes(_):
            self.page.close(dlg)
            on_yes()
        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Text("Confirm", color=AppTheme.TEXT),
            content=ft.Text(msg, size=13, color=AppTheme.TEXT_SECONDARY),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self.page.close(dlg)),
                ft.ElevatedButton("Yes", bgcolor=AppTheme.DANGER, color=ft.Colors.WHITE, on_click=yes),
            ],
        )
        self.page.open(dlg)

    def _prompt(self, title, default, on_submit):
        field = ft.TextField(value=default, autofocus=True, bgcolor=AppTheme.CARD,
                             border_color=AppTheme.BORDER, focused_border_color=AppTheme.ACCENT,
                             color=AppTheme.TEXT)

        def submit(_):
            self.page.close(dlg)
            on_submit(field.value)
        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Text(title, color=AppTheme.TEXT, size=15),
            content=ft.Container(content=field, width=420),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self.page.close(dlg)),
                ft.ElevatedButton("OK", bgcolor=AppTheme.ACCENT, color=AppTheme.ON_ACCENT, on_click=submit),
            ],
        )
        self.page.open(dlg)

    async def _prompt_async(self, title, default, on_submit):
        self._prompt(title, default, on_submit)

    # ════════════════════════════════════════════════════════════ ui helpers
    def _toast(self, msg):
        try:
            self.page.open(ft.SnackBar(ft.Text(msg, color=ft.Colors.WHITE),
                                       bgcolor=AppTheme.ACCENT, duration=2500))
        except Exception:
            pass

    def _safe(self, control):
        try:
            control.update()
        except (RuntimeError, AssertionError):
            pass

    def _run_ui(self, fn, *args):
        try:
            if self.page:
                self.page.run_task(fn, *args)
        except Exception:
            pass


# ───────────────────────────────────────────────────── module helpers
def _file_icon(ext: str):
    e = ext.lower()
    if e in fs.IMAGE_EXTS:
        return ft.Icons.IMAGE_OUTLINED
    if e in fs.VIDEO_EXTS:
        return ft.Icons.MOVIE_OUTLINED
    if e in fs.AUDIO_EXTS:
        return ft.Icons.AUDIOTRACK
    if e in fs.DOC_EXTS:
        return ft.Icons.DESCRIPTION_OUTLINED
    if e in fs.ARCHIVE_EXTS:
        return ft.Icons.FOLDER_ZIP_OUTLINED
    return ft.Icons.INSERT_DRIVE_FILE_OUTLINED


def _ask_directory(title, initial=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title=title, initialdir=initial or os.path.expanduser("~"))
        root.destroy()
        return folder or None
    except Exception:
        return None


def _ask_open_file(title):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title=title,
                                          filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        root.destroy()
        return path or None
    except Exception:
        return None
