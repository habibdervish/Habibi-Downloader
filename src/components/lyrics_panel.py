"""Lyrics dialog: synced LRC view, Whisper generation, edit, import/export."""

import os
import threading

import flet as ft

from src.theme import AppTheme
from src.state import state
from src.services.player import player
from src.services.lyrics_engine import lyrics_engine


class LyricsPanel:
    def __init__(self, page: ft.Page):
        self.page = page
        self.song = None
        self.data = None
        self._edit = False
        self._line_controls = []
        self._dialog = ft.AlertDialog(
            modal=False,
            bgcolor=AppTheme.PANEL,
            content=ft.Container(width=520, height=560, content=ft.Column([])),
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    # -------------------------------------------------------------------- open
    def open_for_current(self):
        song = player.current
        if song is None:
            self._toast("Play a song first to view its lyrics")
            return
        self.open_for(song)

    def open_for(self, song):
        self.song = song
        self.data = lyrics_engine.get_lyrics(song)
        self._edit = False
        player.add_listener(self._on_tick)
        self._render()
        self.page.open(self._dialog)

    def close(self):
        player.remove_listener(self._on_tick)
        self.page.close(self._dialog)

    # ------------------------------------------------------------------ render
    def _render(self):
        self._body = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self._fill_body()

        header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(self.song.title, size=16, weight=ft.FontWeight.BOLD,
                                color=AppTheme.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(self.song.artist, size=12, color=AppTheme.TEXT_SECONDARY),
                    ],
                    spacing=2, expand=True,
                ),
                ft.IconButton(ft.Icons.CLOSE, icon_color=AppTheme.TEXT_SECONDARY, on_click=lambda _: self.close()),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        toolbar = ft.Row(
            [
                ft.TextButton("Generate (Whisper)", icon=ft.Icons.AUTO_AWESOME,
                              on_click=lambda _: self._generate(),
                              style=ft.ButtonStyle(color=AppTheme.ACCENT)),
                ft.TextButton("Import .lrc", icon=ft.Icons.UPLOAD_FILE, on_click=lambda _: self._import()),
                ft.TextButton("Export .lrc", icon=ft.Icons.DOWNLOAD, on_click=lambda _: self._export()),
                ft.TextButton("Edit" if not self._edit else "Done", icon=ft.Icons.EDIT,
                              on_click=lambda _: self._toggle_edit()),
            ],
            spacing=2, wrap=True,
        )

        self._dialog.content = ft.Container(
            width=520, height=560,
            content=ft.Column([header, ft.Divider(height=8, color=AppTheme.BORDER), toolbar,
                               ft.Divider(height=8, color=AppTheme.BORDER), self._body],
                              spacing=8, expand=True),
        )
        self._safe()

    def _fill_body(self):
        self._body.controls.clear()
        self._line_controls = []
        if not self.data or not self.data.lines:
            self._body.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.LYRICS_OUTLINED, size=48, color=AppTheme.TEXT_SECONDARY),
                            ft.Text("No lyrics yet", size=14, color=AppTheme.TEXT_SECONDARY),
                            ft.Text("Generate with Whisper or import a .lrc file", size=11,
                                    color=AppTheme.TEXT_SECONDARY),
                        ],
                        spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment(0, 0), expand=True, padding=ft.Padding(0, 60, 0, 0),
                )
            )
            return

        for i, line in enumerate(self.data.lines):
            if self._edit:
                ctrl = ft.Row(
                    [
                        ft.Text(_fmt(line.timestamp), size=11, color=AppTheme.TEXT_SECONDARY, width=54),
                        ft.TextField(value=line.text, dense=True, expand=True, border_color=AppTheme.BORDER,
                                     focused_border_color=AppTheme.ACCENT, color=AppTheme.TEXT,
                                     text_size=13, on_change=lambda e, idx=i: self._edit_line(idx, e.control.value)),
                        ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=AppTheme.TEXT_SECONDARY,
                                      on_click=lambda _, idx=i: self._remove_line(idx)),
                    ],
                    spacing=8,
                )
                self._line_controls.append(None)
            else:
                txt = ft.Text(line.text or "♪", size=15, color=AppTheme.TEXT_SECONDARY,
                              text_align=ft.TextAlign.CENTER)
                self._line_controls.append(txt)
                ctrl = ft.Container(content=txt, padding=ft.Padding(0, 4, 0, 4),
                                    on_click=lambda _, t=line.timestamp: player.seek(t))
            self._body.controls.append(ctrl)

        if self._edit:
            self._body.controls.append(
                ft.TextButton("Add line", icon=ft.Icons.ADD, on_click=lambda _: self._add_line())
            )

    # --------------------------------------------------------------- sync tick
    def _on_tick(self):
        if self._edit or not self.data or not self.data.lines:
            return
        pos = player.position + (self.data.offset or 0)
        active = -1
        for i, line in enumerate(self.data.lines):
            if line.timestamp <= pos:
                active = i
            else:
                break
        for i, ctrl in enumerate(self._line_controls):
            if ctrl is None:
                continue
            if i == active:
                ctrl.color = AppTheme.ACCENT
                ctrl.weight = ft.FontWeight.BOLD
                ctrl.size = 17
            else:
                ctrl.color = AppTheme.TEXT_SECONDARY
                ctrl.weight = ft.FontWeight.NORMAL
                ctrl.size = 15
        self._safe()

    # ----------------------------------------------------------------- actions
    def _toggle_edit(self):
        self._edit = not self._edit
        if not self._edit and self.data:
            lyrics_engine.save_lyrics(self.data)
        self._render()

    def _edit_line(self, idx, text):
        lyrics_engine.update_line_text(self.data, idx, text)

    def _remove_line(self, idx):
        lyrics_engine.remove_line(self.data, idx)
        self._fill_body()
        self._safe()

    def _add_line(self):
        if not self.data:
            self.data = lyrics_engine.create_empty(self.song)
        lyrics_engine.add_line(self.data)
        self._fill_body()
        self._safe()

    def _generate(self):
        size = state.settings.get("whisper_model", "base")
        self._body.controls.clear()
        self._body.controls.append(
            ft.Container(
                content=ft.Column(
                    [ft.ProgressRing(width=30, height=30, color=AppTheme.ACCENT),
                     ft.Text("Transcribing with Whisper… this can take a minute", size=12,
                             color=AppTheme.TEXT_SECONDARY)],
                    spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.Alignment(0, 0), expand=True, padding=ft.Padding(0, 60, 0, 0),
            )
        )
        self._safe()

        def work():
            try:
                data = lyrics_engine.generate_with_whisper(self.song, size)
                from src.services.storage import storage
                lrc_path = os.path.join(_lyrics_dir(), f"{self.song.id}.lrc")
                storage.save_lyrics_meta(self.song.id, lrc_path, "whisper", len(data.lines))
                self.data = data
                self.page.run_task(self._after_async)
            except Exception as e:
                self.page.run_task(self._error_async, str(e))

        threading.Thread(target=work, daemon=True).start()

    async def _after_async(self):
        self._fill_body()
        self._safe()
        self._toast("Lyrics generated")

    async def _error_async(self, msg):
        self._fill_body()
        self._safe()
        self._toast(f"Generation failed: {msg}")

    def _import(self):
        path = _pick_lrc_file()
        if not path:
            return
        try:
            self.data = lyrics_engine.import_lrc(self.song, path)
            self._fill_body()
            self._safe()
            self._toast("Lyrics imported")
        except Exception as e:
            self._toast(f"Import failed: {e}")

    def _export(self):
        if not self.data or not self.data.lines:
            self._toast("Nothing to export")
            return
        path = lyrics_engine.save_lyrics(self.data)
        self._toast(f"Saved to {path}")

    # -------------------------------------------------------------- ui helpers
    def _toast(self, msg):
        try:
            self.page.open(ft.SnackBar(ft.Text(msg), bgcolor=AppTheme.CARD))
        except Exception:
            pass

    def _safe(self):
        try:
            self._dialog.update()
        except (RuntimeError, AssertionError):
            pass


def _fmt(seconds):
    seconds = float(seconds or 0)
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def _lyrics_dir():
    from src.utils.file_utils import get_lyrics_dir
    return get_lyrics_dir()


def _pick_lrc_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title="Import .lrc", filetypes=[("Lyrics", "*.lrc *.txt")])
        root.destroy()
        return path or None
    except Exception:
        return None
