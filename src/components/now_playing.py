"""Full-screen Now Playing overlay — big artwork, transport, seek, and up-next queue.

Expands from the mini player bar. Reflects the global `player` singleton and lets
the user jump to any track in the play queue.
"""

import flet as ft

from src.theme import AppTheme
from src.services.player import player

try:
    import flet_video as fv
except Exception:
    fv = None


class NowPlaying(ft.Container):
    def __init__(self, page: ft.Page):
        self._page = page
        self._open = False
        super().__init__(
            expand=True, bgcolor="#0B0B0F", visible=True,
            padding=ft.Padding(40, 28, 40, 28),
            animate_offset=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
            offset=ft.Offset(0, 1),  # parked off-screen but stays mounted (audio keeps playing)
        )
        # Note: flet-video's Video control only plays when actually visible, so
        # a persistent off-screen surface can't drive background playback.
        # Library audio uses just_playback; Discovery video plays in its dialog.
        self._video = None
        self._build()
        player.add_listener(self.refresh)

    # ------------------------------------------------------------------ build
    def _build(self):
        # Artwork shown over the video surface for audio (no picture otherwise)
        self._art = ft.Container(
            expand=True, bgcolor=AppTheme.CARD, alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.Icons.MUSIC_NOTE, size=90, color=AppTheme.TEXT_SECONDARY),
        )
        cover_inner = ft.Stack([self._video, self._art]) if self._video else self._art
        self._cover = ft.Container(
            width=480, height=300, border_radius=14,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=cover_inner, bgcolor="#000000",
            shadow=ft.BoxShadow(blur_radius=40, color=ft.Colors.BLACK87),
        )
        self._title = ft.Text("Nothing playing", size=24, weight=ft.FontWeight.BOLD,
                              color=AppTheme.TEXT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self._artist = ft.Text("", size=15, color=AppTheme.TEXT_SECONDARY,
                               max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

        self._pos = ft.Text("0:00", size=11, color=AppTheme.TEXT_SECONDARY, width=40)
        self._dur = ft.Text("0:00", size=11, color=AppTheme.TEXT_SECONDARY, width=40)
        self._seek = ft.Slider(min=0, max=100, value=0, expand=True,
                               active_color=AppTheme.ACCENT, inactive_color=AppTheme.CARD,
                               on_change_end=self._on_seek)

        self._shuffle = ft.IconButton(ft.Icons.SHUFFLE, icon_size=22,
                                      icon_color=AppTheme.TEXT_SECONDARY,
                                      on_click=lambda _: player.toggle_shuffle())
        self._prev = ft.IconButton(ft.Icons.SKIP_PREVIOUS, icon_size=34,
                                   icon_color=AppTheme.TEXT, on_click=lambda _: player.prev())
        self._play = ft.IconButton(ft.Icons.PLAY_CIRCLE_FILLED, icon_size=64,
                                   icon_color=AppTheme.ACCENT, on_click=lambda _: player.toggle_play())
        self._next = ft.IconButton(ft.Icons.SKIP_NEXT, icon_size=34,
                                   icon_color=AppTheme.TEXT, on_click=lambda _: player.next())
        self._repeat = ft.IconButton(ft.Icons.REPEAT, icon_size=22,
                                     icon_color=AppTheme.TEXT_SECONDARY,
                                     on_click=lambda _: player.toggle_repeat())
        self._volume = ft.Slider(min=0, max=1, value=1, width=140,
                                 active_color=AppTheme.ACCENT, inactive_color=AppTheme.CARD,
                                 on_change=lambda e: player.set_volume(e.control.value))

        left = ft.Column(
            [
                self._cover,
                ft.Container(height=18),
                self._title, self._artist,
                ft.Container(height=14),
                ft.Row([self._pos, self._seek, self._dur],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER, width=420),
                ft.Container(height=6),
                ft.Row([self._shuffle, self._prev, self._play, self._next, self._repeat],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=10, width=420),
                ft.Row([ft.Icon(ft.Icons.VOLUME_UP, size=16, color=AppTheme.TEXT_SECONDARY),
                        self._volume], alignment=ft.MainAxisAlignment.CENTER, width=420),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
        )

        self._queue_list = ft.Column([], spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        right = ft.Container(
            content=ft.Column([
                ft.Text("Up Next", size=14, weight=ft.FontWeight.W_700, color=AppTheme.TEXT),
                ft.Divider(height=10, color=AppTheme.BORDER),
                self._queue_list,
            ], spacing=0, expand=True),
            expand=True, padding=ft.Padding(24, 0, 0, 0),
        )

        collapse = ft.IconButton(ft.Icons.KEYBOARD_ARROW_DOWN, icon_size=28,
                                 icon_color=AppTheme.TEXT_SECONDARY, tooltip="Close",
                                 on_click=lambda _: self.hide())

        self.content = ft.Column([
            ft.Row([ft.Text("Now Playing", size=13, weight=ft.FontWeight.W_600,
                            color=AppTheme.TEXT_SECONDARY),
                    ft.Container(expand=True), collapse]),
            ft.Container(height=8),
            ft.Row([left, right], expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, spacing=0)

    # ----------------------------------------------------------------- events
    def _on_seek(self, e):
        if player.duration:
            player.seek(player.duration * (e.control.value / 100))

    def _jump_to(self, song):
        player.play(song, queue=list(player.queue))

    # ----------------------------------------------------------------- refresh
    async def refresh(self):
        if not self._open:
            return
        song = player.current
        if song is None:
            self._title.value = "Nothing playing"
            self._artist.value = ""
            self._safe()
            return
        self._title.value = song.title
        self._artist.value = song.artist
        # Video playing -> show the frame; audio -> overlay artwork on top
        has_video = getattr(player, "has_video", False)
        self._art.visible = not has_video
        if not has_video:
            if song.thumbnail_path:
                self._art.content = ft.Image(src=song.thumbnail_path, fit=ft.BoxFit.COVER,
                                             expand=True)
            else:
                self._art.content = ft.Icon(ft.Icons.MUSIC_NOTE, size=90,
                                            color=AppTheme.TEXT_SECONDARY)

        self._play.icon = (ft.Icons.PAUSE_CIRCLE_FILLED if player.is_playing
                           else ft.Icons.PLAY_CIRCLE_FILLED)
        self._repeat.icon_color = AppTheme.ACCENT if player.repeat else AppTheme.TEXT_SECONDARY
        self._shuffle.icon_color = AppTheme.ACCENT if player.shuffle else AppTheme.TEXT_SECONDARY

        dur = player.duration or 0
        pos = player.position or 0
        self._pos.value = _fmt(pos)
        self._dur.value = _fmt(dur)
        self._seek.value = (pos / dur * 100) if dur else 0
        self._volume.value = player.volume

        self._render_queue()
        self._safe()

    def _render_queue(self):
        self._queue_list.controls.clear()
        q = player.queue or []
        idx = player.index
        for i, s in enumerate(q):
            playing = i == idx
            row = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.VOLUME_UP if playing else ft.Icons.MUSIC_NOTE,
                            size=14, color=AppTheme.ACCENT if playing else AppTheme.TEXT_SECONDARY),
                    ft.Column([
                        ft.Text(s.title, size=12,
                                color=AppTheme.ACCENT if playing else AppTheme.TEXT,
                                weight=ft.FontWeight.W_600 if playing else ft.FontWeight.NORMAL,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(s.artist, size=10, color=AppTheme.TEXT_SECONDARY,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=0, expand=True),
                ], spacing=10),
                padding=ft.Padding(10, 7, 10, 7), border_radius=8,
                bgcolor=(AppTheme.ACCENT + "1A") if playing else None,
                on_click=(None if playing else (lambda _, sng=s: self._jump_to(sng))),
                ink=not playing,
            )
            self._queue_list.controls.append(row)

    # -------------------------------------------------------------- show/hide
    def show(self):
        self._open = True
        self.visible = True
        self.offset = ft.Offset(0, 0)   # slide in
        self._safe()
        if self._page:
            self._page.run_task(self.refresh)

    def hide(self):
        # Park off-screen but keep mounted so background audio keeps playing
        self._open = False
        self.offset = ft.Offset(0, 1)
        self._safe()

    def toggle(self):
        self.hide() if self._open else self.show()

    def _safe(self):
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass


def _fmt(seconds):
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"
