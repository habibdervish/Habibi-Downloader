import flet as ft

from src.theme import AppTheme
from src.services.player import player


class PlayerBar(ft.Container):
    """Bottom mini-player: cover, transport, seek, volume, repeat, shuffle."""

    def __init__(self, page: ft.Page, on_expand=None):
        super().__init__(
            height=90,
            bgcolor=AppTheme.PANEL,
            border=ft.Border(top=ft.BorderSide(1, AppTheme.BORDER)),
            padding=ft.Padding(16, 6, 16, 6),
            visible=False,
        )
        self._on_expand = on_expand
        player.attach(page, on_change=self.refresh)
        from src.components.lyrics_panel import LyricsPanel
        self._lyrics = LyricsPanel(page)
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        self._cover = ft.Container(
            width=48, height=48, border_radius=8, bgcolor=AppTheme.CARD,
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.Icons.MUSIC_NOTE, size=22, color=AppTheme.TEXT_SECONDARY),
            tooltip="Now Playing", ink=True,
            on_click=lambda _: (self._on_expand() if self._on_expand else None),
        )
        self._title = ft.Text("Nothing playing", size=13, weight=ft.FontWeight.W_600,
                              color=AppTheme.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._artist = ft.Text("", size=11, color=AppTheme.TEXT_SECONDARY,
                               max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

        self._shuffle_btn = ft.IconButton(ft.Icons.SHUFFLE, icon_size=18,
                                          icon_color=AppTheme.TEXT_SECONDARY, tooltip="Shuffle",
                                          on_click=lambda _: player.toggle_shuffle())
        self._prev_btn = ft.IconButton(ft.Icons.SKIP_PREVIOUS, icon_size=22,
                                       icon_color=AppTheme.TEXT, on_click=lambda _: player.prev())
        # Single button — no Stack, no overlay that could block clicks
        self._play_btn = ft.IconButton(ft.Icons.PLAY_CIRCLE_FILLED, icon_size=36,
                                       icon_color=AppTheme.ACCENT,
                                       on_click=lambda _: player.toggle_play())
        self._next_btn = ft.IconButton(ft.Icons.SKIP_NEXT, icon_size=22,
                                       icon_color=AppTheme.TEXT, on_click=lambda _: player.next())
        self._repeat_btn = ft.IconButton(ft.Icons.REPEAT, icon_size=18,
                                         icon_color=AppTheme.TEXT_SECONDARY, tooltip="Repeat",
                                         on_click=lambda _: player.toggle_repeat())

        self._pos_label = ft.Text("0:00", size=10, color=AppTheme.TEXT_SECONDARY, width=36,
                                  text_align=ft.TextAlign.CENTER)
        self._dur_label = ft.Text("0:00", size=10, color=AppTheme.TEXT_SECONDARY, width=36,
                                  text_align=ft.TextAlign.CENTER)
        self._seek = ft.Slider(min=0, max=100, value=0, active_color=AppTheme.ACCENT,
                               inactive_color=AppTheme.CARD, expand=True,
                               on_change_end=self._on_seek)

        self._volume = ft.Slider(min=0, max=1, value=1, width=90, active_color=AppTheme.ACCENT,
                                 inactive_color=AppTheme.CARD,
                                 on_change=lambda e: player.set_volume(e.control.value))

        left = ft.Row([self._cover, ft.Column([self._title, self._artist], spacing=2)],
                      spacing=12, width=240)
        center = ft.Column(
            [
                ft.Row([self._shuffle_btn, self._prev_btn, self._play_btn, self._next_btn, self._repeat_btn],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                ft.Row([self._pos_label, self._seek, self._dur_label],
                       alignment=ft.MainAxisAlignment.CENTER),
            ],
            spacing=0, expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        right = ft.Row(
            [
                ft.IconButton(ft.Icons.OPEN_IN_FULL, icon_size=16, icon_color=AppTheme.TEXT_SECONDARY,
                              tooltip="Now Playing",
                              on_click=lambda _: (self._on_expand() if self._on_expand else None)),
                ft.IconButton(ft.Icons.LYRICS_OUTLINED, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
                              tooltip="Lyrics", on_click=lambda _: self._lyrics.open_for_current()),
                ft.Icon(ft.Icons.VOLUME_UP, size=16, color=AppTheme.TEXT_SECONDARY),
                self._volume,
            ],
            spacing=4, width=200, alignment=ft.MainAxisAlignment.END,
        )

        self.content = ft.Row([left, center, right],
                              alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                              vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # ----------------------------------------------------------------- events
    def _on_seek(self, e):
        if player.duration:
            player.seek(player.duration * (e.control.value / 100))

    async def refresh(self):
        song = player.current
        if song is None:
            self.visible = False
            self._safe()
            return
        self.visible = True
        self._title.value = song.title
        self._artist.value = song.artist
        if song.thumbnail_path:
            self._cover.content = ft.Image(src=song.thumbnail_path, fit=ft.BoxFit.COVER,
                                           width=48, height=48, border_radius=8)
        else:
            self._cover.content = ft.Icon(ft.Icons.MUSIC_NOTE, size=22, color=AppTheme.TEXT_SECONDARY)

        loading = getattr(player, "is_loading", False)
        if loading:
            self._play_btn.icon = ft.Icons.HOURGLASS_EMPTY
            self._play_btn.disabled = True
        else:
            self._play_btn.icon = ft.Icons.PAUSE_CIRCLE_FILLED if player.is_playing else ft.Icons.PLAY_CIRCLE_FILLED
            self._play_btn.disabled = False

        self._repeat_btn.icon_color = AppTheme.ACCENT if player.repeat else AppTheme.TEXT_SECONDARY
        self._shuffle_btn.icon_color = AppTheme.ACCENT if player.shuffle else AppTheme.TEXT_SECONDARY

        dur = player.duration or 0
        pos = player.position or 0
        self._pos_label.value = _fmt(pos)
        self._dur_label.value = _fmt(dur)
        self._seek.value = (pos / dur * 100) if dur else 0
        self._volume.value = player.volume
        self._safe()

    def _safe(self):
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass


def _fmt(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"
