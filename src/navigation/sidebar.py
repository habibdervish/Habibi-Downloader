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

    nav_rows = {}   # view -> (container, icon, text)

    def _restyle():
        current = getattr(state, "current_view", None) or "library"
        for v, (cont, icon, txt) in nav_rows.items():
            active = v == current
            cont.bgcolor = (AppTheme.ACCENT + "1A") if active else "transparent"
            icon.color = AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY
            txt.color = AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY
            txt.weight = ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL
            try:
                cont.update()
            except (RuntimeError, AssertionError):
                pass

    nav_controls = []
    for item in NAV_ITEMS:
        view_name = item["view"]
        icon = ft.Icon(item["icon"], size=20, color=AppTheme.TEXT_SECONDARY)
        txt = ft.Text(item["label"], size=13, color=AppTheme.TEXT_SECONDARY)
        row = ft.Container(
            content=ft.Row([icon, txt], spacing=12),
            padding=ft.Padding(12, 14, 12, 14),
            border_radius=10,
            ink=False,
            animate=AppTheme.transition,
            on_click=lambda _, v=view_name: _navigate(v),
        )
        nav_rows[view_name] = (row, icon, txt)
        # Hover only changes bg when not active
        def _mk_hover(c, v):
            def on_hover(e):
                if (getattr(state, "current_view", None) or "library") == v:
                    return
                c.bgcolor = AppTheme.HOVER if e.data == "true" else "transparent"
                c.update()
            return on_hover
        row.on_hover = _mk_hover(row, view_name)
        nav_controls.append(row)

    # Keep the active highlight in sync with navigation
    state.subscribe(_restyle)
    _restyle()

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
