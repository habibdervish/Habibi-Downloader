import flet as ft
from src.theme import AppTheme
from src.state import state
from src.services.download_manager import download_manager


_STATUS_COLOR = {
    "downloading": AppTheme.ACCENT,
    "queued": AppTheme.TEXT_SECONDARY,
    "paused": "#E0B341",
    "complete": AppTheme.ACCENT,
    "failed": AppTheme.DANGER,
    "cancelled": AppTheme.TEXT_SECONDARY,
}


class QueuePanel(ft.Container):
    """Top-right download popup: badge count, progress, pause/resume/cancel/retry/clear."""

    def __init__(self):
        self._visible = False
        super().__init__(
            width=380,
            height=520,
            bgcolor="#121212",
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
            border_radius=AppTheme.panel_radius,
            padding=16,
            right=20,
            top=64,
            visible=False,
            shadow=ft.BoxShadow(blur_radius=24, color=ft.Colors.BLACK54),
        )
        self._list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self._badge = ft.Text("0", size=11, color=AppTheme.BG, weight=ft.FontWeight.BOLD)
        self.content = self._build()
        self._render_list()

    # ----------------------------------------------------------------- build
    def _build(self):
        header = ft.Row(
            [
                ft.Row(
                    [
                        ft.Text("Downloads", size=16, weight=ft.FontWeight.BOLD, color=AppTheme.TEXT),
                        ft.Container(
                            content=self._badge,
                            bgcolor=AppTheme.ACCENT,
                            border_radius=10,
                            padding=ft.Padding(7, 2, 7, 2),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        ft.TextButton(
                            "Clear",
                            on_click=lambda _: self._clear(),
                            style=ft.ButtonStyle(color=AppTheme.TEXT_SECONDARY),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, icon_size=18,
                            icon_color=AppTheme.TEXT_SECONDARY,
                            on_click=lambda _: self.hide(),
                        ),
                    ],
                    spacing=0,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        return ft.Column(
            [header, ft.Divider(height=10, color=AppTheme.BORDER), self._list],
            spacing=0, expand=True,
        )

    def _render_list(self):
        tasks = list(state.download_queue)
        active = len([t for t in tasks if t.status in ("downloading", "queued", "paused")])
        self._badge.value = str(active)

        self._list.controls.clear()
        if not tasks:
            self._list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.DOWNLOAD_DONE, size=40, color=AppTheme.TEXT_SECONDARY),
                            ft.Text("No downloads yet", size=13, color=AppTheme.TEXT_SECONDARY),
                            ft.Text("Download songs from Discovery", size=11, color=AppTheme.TEXT_SECONDARY),
                        ],
                        spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment(0, 0), expand=True, padding=ft.Padding(0, 40, 0, 0),
                )
            )
            return
        for task in reversed(tasks):
            self._list.controls.append(self._task_row(task))

    def _task_row(self, task) -> ft.Container:
        color = _STATUS_COLOR.get(task.status, AppTheme.TEXT_SECONDARY)
        pct = int((task.progress or 0) * 100)

        if task.status == "complete":
            sub = "Completed"
        elif task.status == "failed":
            sub = task.error or "Failed"
        elif task.status == "paused":
            sub = "Paused"
        elif task.status == "queued":
            sub = "Queued"
        elif task.status == "cancelled":
            sub = "Cancelled"
        else:
            sub = " · ".join(p for p in [f"{pct}%", task.speed, task.eta] if p)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                task.title, size=12, weight=ft.FontWeight.W_600,
                                color=AppTheme.TEXT, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                            ),
                            self._row_actions(task),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.ProgressBar(
                        value=task.progress if task.status not in ("queued",) else None,
                        color=color, bgcolor="#2A2A2A", height=4,
                    ),
                    ft.Text(sub, size=10, color=color),
                ],
                spacing=6,
            ),
            bgcolor=AppTheme.CARD,
            border_radius=10,
            padding=ft.Padding(12, 10, 8, 10),
        )

    def _row_actions(self, task) -> ft.Row:
        btns = []

        def icon(name, tip, handler, col=AppTheme.TEXT_SECONDARY):
            return ft.IconButton(
                icon=name, icon_size=16, icon_color=col, tooltip=tip,
                on_click=lambda _, h=handler, t=task.id: h(t),
            )

        if task.status == "downloading":
            btns.append(icon(ft.Icons.PAUSE, "Pause", download_manager.pause))
            btns.append(icon(ft.Icons.CLOSE, "Cancel", download_manager.cancel))
        elif task.status == "paused":
            btns.append(icon(ft.Icons.PLAY_ARROW, "Resume", download_manager.resume, AppTheme.ACCENT))
            btns.append(icon(ft.Icons.CLOSE, "Cancel", download_manager.cancel))
        elif task.status == "queued":
            btns.append(icon(ft.Icons.CLOSE, "Cancel", download_manager.cancel))
        elif task.status in ("failed", "cancelled"):
            btns.append(icon(ft.Icons.REFRESH, "Retry", download_manager.retry, AppTheme.ACCENT))
        elif task.status == "complete":
            btns.append(ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=AppTheme.ACCENT))
        return ft.Row(btns, spacing=0, tight=True)

    # --------------------------------------------------------------- actions
    def _clear(self):
        download_manager.clear_completed()
        self._render_list()
        self._safe_update()

    async def refresh(self):
        """Async UI refresh registered with the download manager."""
        self._render_list()
        self._safe_update()

    def _safe_update(self):
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass

    # -------------------------------------------------------------- show/hide
    def show(self):
        self._visible = True
        self.visible = True
        self._render_list()
        self._safe_update()

    def hide(self):
        self._visible = False
        self.visible = False
        self._safe_update()

    def toggle(self):
        self.hide() if self._visible else self.show()
