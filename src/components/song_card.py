import flet as ft
from src.theme import AppTheme
from src.models.song import Song
from src.state import state


class SongCard(ft.Container):
    def __init__(self, song: Song, on_click=None, card_type="library",
                 on_download=None, on_select=None, on_favorite=None):
        self.song = song
        self._card_type = card_type
        self._on_download = on_download
        self._on_select = on_select
        self._on_favorite = on_favorite
        self._thumbnail_path = None
        super().__init__(
            width=220,
            border_radius=18,
            bgcolor=AppTheme.CARD,
            padding=0,
            ink=False,
            animate=AppTheme.transition,
            animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
            scale=1.0,
            on_click=on_click or (lambda _: None),
            on_hover=self._on_hover,
        )
        self.content = self._build()
        self._load_thumbnail()

    def _build(self) -> ft.Control:
        return ft.Column(
            [ft.Container(content=self._build_artwork(), expand=True), self._build_info()],
            spacing=0, tight=True, expand=True,
        )

    def _build_artwork(self) -> ft.Container:
        is_selected = self.song.id in state.selected_song_ids
        self._artwork_icon = ft.Container(
            content=ft.Icon(ft.Icons.MUSIC_NOTE, size=48, color=AppTheme.TEXT_SECONDARY),
            bgcolor="#2A2A2A", expand=True,
            alignment=ft.Alignment(0, 0),
            border_radius=ft.BorderRadius(18, 18, 0, 0),
        )
        self._artwork_image = ft.Container(
            content=ft.Image(src="", fit=ft.BoxFit.COVER, expand=True),
            expand=True,
            border_radius=ft.BorderRadius(18, 18, 0, 0),
            visible=False,
        )

        overlay_controls = []
        if self._card_type == "search":
            overlay_controls.append(
                ft.Container(
                    content=ft.IconButton(
                        icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                        icon_size=20, icon_color=ft.Colors.WHITE,
                        on_click=self._handle_download,
                    ),
                    bgcolor=AppTheme.ACCENT, border_radius=20,
                    padding=ft.Padding(4, 4, 4, 4),
                    left=8, top=8,
                )
            )
        else:
            self._checkbox = ft.Checkbox(
                value=is_selected,
                on_change=self._on_check,
                check_color=AppTheme.ACCENT,
                fill_color=ft.Colors.WHITE12 if not is_selected else AppTheme.ACCENT,
            )
            overlay_controls.append(
                ft.Container(content=self._checkbox, left=8, top=8)
            )
        if self._card_type != "search":
            self._fav_icon = ft.Icon(
                ft.Icons.FAVORITE if self.song.is_favorite else ft.Icons.FAVORITE_BORDER,
                size=15,
                color=AppTheme.DANGER if self.song.is_favorite else ft.Colors.WHITE70,
            )
            overlay_controls.append(
                ft.Container(
                    content=self._fav_icon,
                    right=8, top=8,
                    bgcolor=ft.Colors.BLACK45,
                    border_radius=20,
                    padding=ft.Padding(5, 5, 5, 5),
                    on_click=self._handle_favorite,
                )
            )
        overlay_controls.append(
            ft.Container(
                content=ft.Container(
                    content=ft.Text(
                        self._format_duration(self.song.duration),
                        size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD,
                    ),
                    bgcolor=ft.Colors.BLACK54, border_radius=6,
                    padding=ft.Padding(6, 4, 6, 4),
                ),
                right=8, bottom=8,
            ),
        )

        return ft.Stack(
            [self._artwork_icon, self._artwork_image] + overlay_controls,
            expand=True,
        )

    def _build_info(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        self.song.title, size=13, weight=ft.FontWeight.W_600,
                        color=AppTheme.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        self.song.artist, size=11, color=AppTheme.TEXT_SECONDARY,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.Padding(12, 10, 12, 10),
        )

    def _load_thumbnail(self):
        path = self.song.thumbnail_path
        if not path:
            return
        if path.startswith("http://") or path.startswith("https://"):
            from src.services.thumbnail import get_thumbnail
            local = get_thumbnail(path, self.song.id)
            if local:
                self._thumbnail_path = local
        else:
            self._thumbnail_path = path

        if self._thumbnail_path:
            self._artwork_image.content.src = self._thumbnail_path
            self._artwork_icon.visible = False
            self._artwork_image.visible = True
            try:
                self.update()
            except RuntimeError:
                pass

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds <= 0:
            return "--:--"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}:{secs:02d}"

    def deselect(self):
        """Reset checkbox to unchecked in-place (no grid rebuild needed)."""
        cb = getattr(self, "_checkbox", None)
        if cb is None:
            return
        cb.value = False
        cb.fill_color = ft.Colors.WHITE12
        try:
            cb.update()
        except (RuntimeError, AssertionError):
            pass

    def _on_hover(self, e: ft.HoverEvent):
        hovering = e.data == "true"
        self.bgcolor = AppTheme.HOVER if hovering else AppTheme.CARD
        self.scale = 1.03 if hovering else 1.0
        self.update()

    def _on_check(self, e: ft.ControlEvent):
        if e.control.value:
            state.selected_song_ids.add(self.song.id)
        else:
            state.selected_song_ids.discard(self.song.id)
        if self._on_select:
            self._on_select()

    def _handle_download(self, e):
        if self._on_download:
            self._on_download(self.song)

    def _handle_favorite(self, e):
        # Optimistic UI: flip the heart immediately, then persist via callback.
        self.song.is_favorite = not self.song.is_favorite
        fav = getattr(self, "_fav_icon", None)
        if fav is not None:
            fav.name = ft.Icons.FAVORITE if self.song.is_favorite else ft.Icons.FAVORITE_BORDER
            fav.color = AppTheme.DANGER if self.song.is_favorite else ft.Colors.WHITE70
            try:
                fav.update()
            except Exception:
                pass
        if self._on_favorite:
            self._on_favorite()
