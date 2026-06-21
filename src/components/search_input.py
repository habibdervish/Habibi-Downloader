import flet as ft
from src.theme import AppTheme


class SearchInput(ft.Container):
    def __init__(self, on_submit=None, hint_text="Search...", width=500):
        self._on_submit = on_submit
        super().__init__(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SEARCH, size=20, color=AppTheme.TEXT_SECONDARY),
                    ft.TextField(
                        hint_text=hint_text,
                        hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=14),
                        border=ft.InputBorder.NONE,
                        color=AppTheme.TEXT,
                        cursor_color=AppTheme.ACCENT,
                        expand=True,
                        text_style=ft.TextStyle(size=14),
                        on_submit=self._handle_submit,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding(4, 16, 4, 16),
            border_radius=AppTheme.button_radius,
            bgcolor=AppTheme.CARD,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
            width=width,
        )

    def _handle_submit(self, e: ft.ControlEvent):
        if self._on_submit:
            self._on_submit(e.control.value)
