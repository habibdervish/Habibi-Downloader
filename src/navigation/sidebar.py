import flet as ft
from src.theme import AppTheme
from src.state import state


NAV_ITEMS = [
    {"label": "Library", "icon": ft.Icons.LIBRARY_MUSIC_OUTLINED, "view": "library"},
    {"label": "Discovery", "icon": ft.Icons.EXPLORE_OUTLINED, "view": "discovery"},
    {"label": "Scanner", "icon": ft.Icons.DOCUMENT_SCANNER_OUTLINED, "view": "scanner"},
]

LOGO_SRC = "icons/habibi downlaoder.png"


def _hoverable(container: ft.Container, base_bg="transparent", hover_bg=None):
    hover_bg = hover_bg or AppTheme.HOVER

    def on_hover(e):
        container.bgcolor = hover_bg if e.data == "true" else base_bg
        container.update()

    container.on_hover = on_hover
    return container


def build_sidebar(page: ft.Page, on_settings=None) -> ft.Container:
    def _navigate(view: str):
        state.set_view(view)

    nav_controls = []
    for item in NAV_ITEMS:
        view_name = item["view"]
        row = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(item["icon"], size=20, color=AppTheme.TEXT_SECONDARY),
                    ft.Text(item["label"], size=13, color=AppTheme.TEXT_SECONDARY),
                ],
                spacing=12,
            ),
            padding=ft.Padding(12, 14, 12, 14),
            border_radius=10,
            ink=False,
            animate=AppTheme.transition,
            on_click=lambda _, v=view_name: _navigate(v),
        )
        nav_controls.append(_hoverable(row))

    settings_row = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=20, color=AppTheme.TEXT_SECONDARY),
                ft.Text("Settings", size=13, color=AppTheme.TEXT_SECONDARY),
            ],
            spacing=12,
        ),
        padding=ft.Padding(12, 14, 12, 14),
        border_radius=10,
        ink=False,
        animate=AppTheme.transition,
        on_click=lambda _: (on_settings() if on_settings else None),
    )

    sidebar_content = ft.Column(
        [
            ft.Container(
                content=ft.Column(nav_controls, spacing=4),
                expand=True,
                padding=ft.Padding(8, 0, 8, 0),
            ),
            ft.Container(
                content=_hoverable(settings_row),
                padding=ft.Padding(8, 8, 8, 16),
            ),
        ],
        spacing=0,
        expand=True,
    )

    return ft.Container(
        content=sidebar_content,
        width=AppTheme.sidebar_width,
        bgcolor=AppTheme.PANEL,
        border=ft.Border(right=ft.BorderSide(1, AppTheme.BORDER)),
    )
