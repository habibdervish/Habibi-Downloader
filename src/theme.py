import flet as ft


class AppTheme:
    # Clean, Apple-like dark palette with system-blue accent
    BG = "#0E0E12"
    PANEL = "#17171F"
    CARD = "#1E1E27"
    ACCENT = "#0A84FF"
    ACCENT_HOVER = "#3D9BFF"
    ON_ACCENT = "#FFFFFF"   # text/icon color on top of the accent
    TEXT = "#F5F5F7"
    TEXT_SECONDARY = "#9A9AA5"
    DANGER = "#FF453A"
    BORDER = "#2A2A33"
    HOVER = "#24242E"

    sidebar_width = 220
    card_radius = 16
    panel_radius = 12
    button_radius = 10

    transition = ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT)

    @staticmethod
    def glass_container(content, width=None, height=None, expand=False, padding=20):
        return ft.Container(
            content=content,
            width=width,
            height=height,
            expand=expand,
            padding=padding,
            border_radius=AppTheme.panel_radius,
            bgcolor=AppTheme.PANEL,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
        )

    @staticmethod
    def accent_button(text, icon=None, on_click=None, width=None, visible=None):
        btn = ft.Button(
            text,
            icon=icon,
            on_click=on_click,
            width=width,
            style=ft.ButtonStyle(
                color=AppTheme.ON_ACCENT,
                bgcolor=AppTheme.ACCENT,
                shape=ft.RoundedRectangleBorder(radius=AppTheme.button_radius),
                padding=ft.Padding(16, 24, 16, 24),
                text_style=ft.TextStyle(
                    weight=ft.FontWeight.BOLD,
                    size=14,
                ),
            ),
        )
        if visible is not None:
            btn.visible = visible
        return btn

    @staticmethod
    def secondary_button(text, icon=None, on_click=None, visible=None):
        btn = ft.OutlinedButton(
            text,
            icon=icon,
            on_click=on_click,
            style=ft.ButtonStyle(
                color=AppTheme.TEXT,
                side=ft.BorderSide(1, AppTheme.BORDER),
                shape=ft.RoundedRectangleBorder(radius=AppTheme.button_radius),
                padding=ft.Padding(12, 20, 12, 20),
                text_style=ft.TextStyle(size=13),
            ),
        )
        if visible is not None:
            btn.visible = visible
        return btn

    @staticmethod
    def danger_button(text, icon=None, on_click=None, visible=None):
        btn = ft.Button(
            text,
            icon=icon,
            on_click=on_click,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=AppTheme.DANGER,
                shape=ft.RoundedRectangleBorder(radius=AppTheme.button_radius),
                padding=ft.Padding(12, 20, 12, 20),
                text_style=ft.TextStyle(size=13),
            ),
        )
        if visible is not None:
            btn.visible = visible
        return btn

    @staticmethod
    def text_field(label, value="", multiline=False, on_change=None):
        return ft.TextField(
            label=label,
            value=value,
            on_change=on_change,
            multiline=multiline,
            border_radius=AppTheme.button_radius,
            bgcolor=AppTheme.CARD,
            border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT,
            cursor_color=AppTheme.ACCENT,
            color=AppTheme.TEXT,
            label_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            text_style=ft.TextStyle(size=14),
        )
