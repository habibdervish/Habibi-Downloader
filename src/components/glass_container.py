import flet as ft
from src.theme import AppTheme


class GlassContainer(ft.Container):
    def __init__(
        self,
        content: ft.Control = None,
        width=None,
        height=None,
        expand=False,
        padding=20,
        border_radius=None,
    ):
        super().__init__(
            content=content,
            width=width,
            height=height,
            expand=expand,
            padding=padding,
            border_radius=border_radius or AppTheme.panel_radius,
            bgcolor=AppTheme.PANEL,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
        )
