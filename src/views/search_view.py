"""Discovery — standalone universal media explorer.
Completely disconnected from Library, Scanner, Suno, and local files.
"""

import threading
import webbrowser
import pyperclip

import flet as ft

from src.theme import AppTheme
from src.models.download import DownloadTask
from src.services.download_manager import download_manager
from src.utils.file_utils import generate_id

import src.services.search_engine as _music_svc
import src.services.image_finder  as _image_svc
import src.services.video_search  as _video_svc
import src.services.web_search    as _web_svc
import src.services.url_resolver  as _url_svc
import src.services.movie_search  as _movie_svc

try:
    import flet_video as _fv
    _HAS_VIDEO = True
except Exception:
    _fv = None
    _HAS_VIDEO = False

# Reload provider labels from services (they may have changed)
_image_svc_labels = _image_svc.PROVIDER_LABELS

# ---------------------------------------------------------------------- config
_TAB_KEYS = ["music", "images", "video", "movies", "web", "direct"]

_TAB_META = {
    "music":  {"label": "Music",      "icon": ft.Icons.MUSIC_NOTE_OUTLINED},
    "images": {"label": "Images",     "icon": ft.Icons.IMAGE_OUTLINED},
    "video":  {"label": "Video",      "icon": ft.Icons.VIDEOCAM_OUTLINED},
    "movies": {"label": "Movies",     "icon": ft.Icons.MOVIE_OUTLINED},
    "web":    {"label": "Web",        "icon": ft.Icons.LANGUAGE_OUTLINED},
    "direct": {"label": "Direct URL", "icon": ft.Icons.LINK},
}

_MAX_CARDS = 60  # cap rendered result cards per search to avoid image-load freeze

_PROVIDERS = {
    "music":  _music_svc.PROVIDERS,
    "images": _image_svc.PROVIDERS,
    "video":  _video_svc.PROVIDERS,
    "web":    _web_svc.PROVIDERS,
}

_PROVIDER_LABELS = {
    "music":  _music_svc.PROVIDER_LABELS,
    "images": _image_svc.PROVIDER_LABELS,
    "video":  _video_svc.PROVIDER_LABELS,
    "web":    _web_svc.PROVIDER_LABELS,
}


def _fmt_dur(seconds) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "--:--"
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M views"
    if n >= 1_000:
        return f"{n/1_000:.1f}K views"
    return f"{n} views" if n else ""


_SITES_CACHE = None


def _supported_sites():
    """Sorted list of human-readable site names from the installed yt-dlp.
    Cached after first build (enumerating 1700+ extractors is not free)."""
    global _SITES_CACHE
    if _SITES_CACHE is not None:
        return _SITES_CACHE
    names = set()
    try:
        from yt_dlp.extractor import gen_extractor_classes
        for c in gen_extractor_classes():
            nm = getattr(c, "IE_NAME", "") or ""
            if not nm or nm.lower() == "generic" or ":" in nm and nm.startswith("youtube:"):
                # keep base names; skip noisy internal sub-extractors
                pass
            if nm and not nm.startswith("Generic"):
                names.add(nm)
    except Exception:
        names = {"YouTube", "Vimeo", "SoundCloud", "Dailymotion", "Bandcamp",
                 "Twitter", "TikTok", "Instagram", "Facebook", "Twitch", "Reddit"}
    _SITES_CACHE = sorted(names, key=str.lower)
    return _SITES_CACHE


def _explain_download_error(error: str, url: str = "") -> str:
    """Turn a raw yt-dlp / HTTP error into a clear reason the user can act on."""
    e = (error or "").lower()
    if not e:
        return "✗ Download failed — this site does not allow downloading."
    if "unsupported url" in e or "no video formats" in e or "no media" in e:
        return ("✗ This site is not supported for downloading. The page has no "
                "downloadable media stream (it streams via a protected player).")
    if "drm" in e or "this video is drm" in e:
        return "✗ Blocked: the content is DRM-protected and cannot be downloaded."
    if "sign in" in e or "log in" in e or "login" in e or "account" in e:
        return "✗ Blocked: this site requires you to sign in / a paid account to access the media."
    if "403" in e or "forbidden" in e:
        return "✗ Blocked: the site refused access (HTTP 403). Downloading is restricted."
    if "404" in e or "not found" in e:
        return "✗ Not found (HTTP 404) — the page or media no longer exists."
    if "geo" in e or "not available in your" in e or "region" in e:
        return "✗ Blocked: this content is region-restricted in your location."
    if "timed out" in e or "timeout" in e:
        return "✗ Download timed out — the server did not respond."
    if "ffmpeg" in e:
        return "✗ Failed: FFmpeg is required to convert this media but was not found."
    # Generic fallback — still show the raw reason so it's never silent
    short = (error or "").strip().splitlines()[-1][:160]
    return f"✗ Download failed — {short}"


# ================================================================= main view
class SearchView(ft.Container):

    def __init__(self):
        super().__init__(
            expand=True,
            padding=ft.Padding(28, 20, 28, 20),
            bgcolor=AppTheme.BG,
        )
        self._active_tab = "music"
        self._cancel_events: dict = {k: threading.Event() for k in _TAB_KEYS}
        self._active_providers: dict = {k: "all" for k in _TAB_KEYS}
        self._last_queries: dict = {k: {} for k in _TAB_KEYS}
        self._pending_counts: dict = {k: 0 for k in _TAB_KEYS}
        self._pending_lock = threading.Lock()
        self._result_counts: dict = {k: 0 for k in _TAB_KEYS}
        self._rendered_counts: dict = {k: 0 for k in _TAB_KEYS}
        self._favorites: set = set()
        self._preview_dialog = None

        self._build_tab_bodies()
        self.content = self._build_root()

    # ---------------------------------------------------------------- root
    def _build_root(self):
        self._tab_bar = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self._render_tab_bar()
        self._tab_content = ft.Container(
            content=self._tab_bodies["music"], expand=True,
        )
        return ft.Column(
            [
                ft.Text("Discovery", size=26, weight=ft.FontWeight.BOLD,
                        color=AppTheme.TEXT),
                self._tab_bar,
                ft.Divider(height=1, color=AppTheme.BORDER),
                self._tab_content,
            ],
            spacing=12, expand=True,
        )

    def _render_tab_bar(self):
        self._tab_bar.controls.clear()
        for key in _TAB_KEYS:
            meta = _TAB_META[key]
            active = key == self._active_tab
            self._tab_bar.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(meta["icon"], size=15,
                                    color=AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY),
                            ft.Text(meta["label"], size=13,
                                    color=AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY,
                                    weight=ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL),
                        ],
                        spacing=6, tight=True,
                    ),
                    padding=ft.Padding(14, 8, 14, 8),
                    border_radius=AppTheme.button_radius,
                    bgcolor=(AppTheme.ACCENT + "1A") if active else AppTheme.CARD,
                    border=ft.Border(
                        left=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                        top=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                        right=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                        bottom=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                    ),
                    on_click=lambda _, k=key: self._switch_tab(k),
                    ink=True,
                )
            )

    def _switch_tab(self, key: str):
        self._active_tab = key
        self._render_tab_bar()
        self._tab_content.content = self._tab_bodies[key]
        self._safe_update(self._tab_bar)
        self._safe_update(self._tab_content)

    # --------------------------------------------------------------- bodies
    def _build_tab_bodies(self):
        self._tab_bodies = {
            "music":  self._build_music_body(),
            "images": self._build_images_body(),
            "video":  self._build_video_body(),
            "movies": self._build_movies_body(),
            "web":    self._build_web_body(),
            "direct": self._build_direct_body(),
        }

    # ============================================================ MUSIC TAB
    def _build_music_body(self):
        self._music_provider_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self._music_field = ft.TextField(
            hint_text="Search music across all providers…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True,
            on_submit=lambda e: self._start_search("music", e.control.value),
        )
        self._music_cancel = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Cancel", visible=False,
            on_click=lambda _: self._cancel_search("music"),
        )
        self._music_grid = ft.GridView(
            runs_count=0, max_extent=220, spacing=12, run_spacing=12,
            child_aspect_ratio=0.86, expand=True, padding=ft.Padding(0, 4, 0, 4),
        )
        self._music_status = self._make_status(
            ft.Icons.MUSIC_NOTE_OUTLINED, "Search for music across all providers"
        )
        self._render_provider_chips("music")
        return ft.Column(
            [
                self._music_provider_row,
                self._search_bar(self._music_field, self._music_cancel, "music"),
                ft.Stack([self._music_status, self._music_grid], expand=True),
            ],
            spacing=12, expand=True,
        )

    # =========================================================== IMAGES TAB
    def _build_images_body(self):
        self._images_provider_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self._images_field = ft.TextField(
            hint_text="Search images across all providers…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True,
            on_submit=lambda e: self._start_search("images", e.control.value),
        )
        self._images_cancel = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Cancel", visible=False,
            on_click=lambda _: self._cancel_search("images"),
        )
        self._images_grid = ft.GridView(
            runs_count=0, max_extent=260, spacing=8, run_spacing=8,
            expand=True, padding=ft.Padding(0, 4, 0, 4),
        )
        self._images_status = self._make_status(
            ft.Icons.IMAGE_OUTLINED, "Search for images across all providers"
        )
        self._render_provider_chips("images")
        return ft.Column(
            [
                self._images_provider_row,
                self._search_bar(self._images_field, self._images_cancel, "images"),
                ft.Stack([self._images_status, self._images_grid], expand=True),
            ],
            spacing=12, expand=True,
        )

    # ============================================================ VIDEO TAB
    def _build_video_body(self):
        self._video_provider_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self._video_field = ft.TextField(
            hint_text="Search videos across all providers…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True,
            on_submit=lambda e: self._start_search("video", e.control.value),
        )
        self._video_cancel = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Cancel", visible=False,
            on_click=lambda _: self._cancel_search("video"),
        )
        self._video_grid = ft.GridView(
            runs_count=0, max_extent=260, spacing=12, run_spacing=12,
            child_aspect_ratio=0.80, expand=True, padding=ft.Padding(0, 4, 0, 4),
        )
        self._video_status = self._make_status(
            ft.Icons.VIDEOCAM_OUTLINED, "Search for videos across all providers"
        )
        self._render_provider_chips("video")
        return ft.Column(
            [
                self._video_provider_row,
                self._search_bar(self._video_field, self._video_cancel, "video"),
                ft.Stack([self._video_status, self._video_grid], expand=True),
            ],
            spacing=12, expand=True,
        )

    # ============================================================ MOVIES TAB
    def _build_movies_body(self):
        self._movies_field = ft.TextField(
            hint_text="Describe a scene, theme or place — e.g. \"war movie set in Afghanistan\"…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True, multiline=False,
            on_submit=lambda e: self._search_movies(e.control.value),
        )
        self._movies_cancel = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Clear", visible=False,
            on_click=lambda _: self._clear_movies(),
        )
        search_btn = ft.IconButton(
            ft.Icons.SEARCH, icon_size=18, icon_color=AppTheme.ACCENT, tooltip="Find movies",
            on_click=lambda _: self._search_movies(self._movies_field.value or ""),
        )
        bar = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.MOVIE_FILTER_OUTLINED, size=18, color=AppTheme.TEXT_SECONDARY),
                self._movies_field, self._movies_cancel, search_btn], spacing=8),
            bgcolor=AppTheme.CARD,
            border=ft.Border(left=ft.BorderSide(1, AppTheme.BORDER),
                             top=ft.BorderSide(1, AppTheme.BORDER),
                             right=ft.BorderSide(1, AppTheme.BORDER),
                             bottom=ft.BorderSide(1, AppTheme.BORDER)),
            border_radius=AppTheme.button_radius, padding=ft.Padding(14, 8, 8, 8))

        self._movies_grid = ft.GridView(
            runs_count=0, max_extent=180, spacing=14, run_spacing=14,
            child_aspect_ratio=0.52, expand=True, padding=ft.Padding(0, 4, 0, 4))
        self._movies_status = self._make_status(
            ft.Icons.MOVIE_OUTLINED,
            "Describe a movie scene, theme, or place to find matching films\n"
            "(works out of the box — add a TMDb key in Settings for richer results)")
        return ft.Column([bar, ft.Stack([self._movies_status, self._movies_grid], expand=True)],
                         spacing=12, expand=True)

    def _search_movies(self, query: str):
        query = (query or "").strip()
        if not query:
            return
        self._movies_cancel.visible = True
        self._set_status_msg(self._movies_status, ft.Icons.HOURGLASS_EMPTY, "Searching movies…")
        self._movies_grid.controls.clear()
        self._safe_update(self._movies_grid)
        self._safe_update(self._movies_cancel)
        self._safe_update(self._movies_status)
        threading.Thread(target=self._movies_worker, args=(query,), daemon=True).start()

    def _movies_worker(self, query):
        try:
            data = _movie_svc.smart_search(query, max_results=30)
        except Exception:
            data = {"results": [], "ai_used": False}
        if self.page:
            self.page.run_task(self._render_movies, data)

    async def _render_movies(self, data):
        results = data.get("results", [])
        self._movies_cancel.visible = bool(results)
        self._movies_grid.controls.clear()
        for mv in results:
            self._movies_grid.controls.append(self._movie_card(mv))
        if results:
            self._movies_status.visible = False
        else:
            self._set_status_msg(self._movies_status, ft.Icons.SEARCH_OFF,
                                 "No movies found — try different words")
            self._movies_status.visible = True
        self._safe_update(self._movies_grid)
        self._safe_update(self._movies_status)
        self._safe_update(self._movies_cancel)

    def _movie_card(self, mv):
        poster = (ft.Image(src=mv["poster"], fit=ft.BoxFit.COVER, expand=True,
                           error_content=ft.Container(
                               bgcolor=AppTheme.PANEL, alignment=ft.Alignment(0, 0),
                               content=ft.Icon(ft.Icons.MOVIE, size=40, color=AppTheme.TEXT_SECONDARY)))
                  if mv["poster"] else
                  ft.Container(bgcolor=AppTheme.PANEL, alignment=ft.Alignment(0, 0),
                               content=ft.Icon(ft.Icons.MOVIE, size=40, color=AppTheme.TEXT_SECONDARY)))
        rating = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.STAR, size=11, color="#FFC542"),
                            ft.Text(f"{mv['rating']}", size=10, color=ft.Colors.WHITE)],
                           spacing=2, tight=True),
            bgcolor="#000000AA", border_radius=6, padding=ft.Padding(5, 2, 5, 2),
            right=6, top=6) if mv["rating"] else ft.Container()
        title = f"{mv['title']}" + (f"  ({mv['year']})" if mv["year"] else "")
        return ft.Container(
            content=ft.Column([
                ft.Container(content=ft.Stack([poster, rating]), expand=True,
                             border_radius=10, clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
                ft.Text(title, size=12, weight=ft.FontWeight.W_600, color=AppTheme.TEXT,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([
                    ft.IconButton(ft.Icons.INFO_OUTLINE, icon_size=16,
                                  icon_color=AppTheme.TEXT_SECONDARY, tooltip="Details",
                                  on_click=lambda _, m=mv: self._movie_details(m)),
                    ft.IconButton(ft.Icons.OPEN_IN_NEW, icon_size=16,
                                  icon_color=AppTheme.TEXT_SECONDARY, tooltip="Open page",
                                  on_click=lambda _, u=mv["tmdb_url"]: self._open(u)),
                    ft.IconButton(ft.Icons.PLAY_CIRCLE_OUTLINE, icon_size=16,
                                  icon_color=AppTheme.ACCENT, tooltip="Find trailer on YouTube",
                                  on_click=lambda _, m=mv: self._open(
                                      f"https://www.youtube.com/results?search_query="
                                      f"{m['title']} {m['year']} trailer")),
                ], spacing=0, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=6),
            bgcolor=AppTheme.CARD, border_radius=12, padding=8)

    def _movie_details(self, mv):
        meta_line = ft.Text("", size=12, color=AppTheme.TEXT_SECONDARY)
        overview = ft.Text(mv["overview"] or "Loading details…",
                           size=13, color=AppTheme.TEXT, selectable=True)
        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Text(f"{mv['title']}" + (f" ({mv['year']})" if mv['year'] else ""),
                          color=AppTheme.TEXT, size=17),
            content=ft.Container(width=460, content=ft.Column(
                [meta_line, overview], tight=True, spacing=12, scroll=ft.ScrollMode.AUTO)),
            actions=[
                ft.TextButton("Open on IMDb", on_click=lambda _: self._open(mv["tmdb_url"])),
                ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog()),
            ])
        self.page.show_dialog(dlg)
        # Fetch full plot/rating/genres on demand (keyless Cinemeta list is sparse)
        imdb = mv.get("imdb_id")
        if imdb:
            threading.Thread(target=self._fetch_details,
                             args=(imdb, meta_line, overview), daemon=True).start()

    def _fetch_details(self, imdb, meta_line, overview):
        d = _movie_svc.get_details(imdb)
        def _apply():
            bits = []
            if d.get("rating"):
                bits.append(f"⭐ {d['rating']}")
            if d.get("runtime"):
                bits.append(d["runtime"])
            if d.get("genres"):
                bits.append(d["genres"])
            meta_line.value = "   ·   ".join(bits)
            if d.get("overview"):
                overview.value = d["overview"]
            elif not overview.value or overview.value == "Loading details…":
                overview.value = "No description available."
            for c in (meta_line, overview):
                try:
                    c.update()
                except Exception:
                    pass
        try:
            if self.page:
                self.page.run_task(self._async_apply, _apply)
        except Exception:
            pass

    def _clear_movies(self):
        self._movies_field.value = ""
        self._movies_grid.controls.clear()
        self._movies_cancel.visible = False
        self._movies_status.visible = True
        self._set_status_msg(self._movies_status, ft.Icons.MOVIE_OUTLINED,
                             "Describe a movie scene, theme, or place to find matching films")
        self._safe_update(self._movies_field)
        self._safe_update(self._movies_grid)
        self._safe_update(self._movies_cancel)
        self._safe_update(self._movies_status)

    # ============================================================== WEB TAB
    def _build_web_body(self):
        self._web_provider_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
        self._web_field = ft.TextField(
            hint_text="Search the web…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True,
            on_submit=lambda e: self._start_search("web", e.control.value),
        )
        self._web_cancel = ft.IconButton(
            ft.Icons.CLOSE, icon_size=18, icon_color=AppTheme.TEXT_SECONDARY,
            tooltip="Cancel", visible=False,
            on_click=lambda _: self._cancel_search("web"),
        )
        self._web_list = ft.ListView(
            expand=True, spacing=2, padding=ft.Padding(0, 4, 0, 4),
        )
        self._web_status = self._make_status(
            ft.Icons.LANGUAGE_OUTLINED, "Search the web across all providers"
        )
        self._render_provider_chips("web")
        return ft.Column(
            [
                self._web_provider_row,
                self._search_bar(self._web_field, self._web_cancel, "web"),
                ft.Stack([self._web_status, self._web_list], expand=True),
            ],
            spacing=12, expand=True,
        )

    # =========================================================== DIRECT TAB
    def _build_direct_body(self):
        self._direct_field = ft.TextField(
            hint_text="Paste any URL — audio, video, image, document…",
            hint_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=13),
            border=ft.InputBorder.NONE, color=AppTheme.TEXT,
            text_style=ft.TextStyle(size=13), expand=True,
            on_submit=lambda e: self._resolve_url(e.control.value),
        )
        detect_btn = ft.FilledButton(
            "Detect", icon=ft.Icons.SEARCH,
            style=ft.ButtonStyle(bgcolor=AppTheme.ACCENT, color=AppTheme.ON_ACCENT),
            on_click=lambda _: self._resolve_url(self._direct_field.value or ""),
        )
        sites_btn = ft.TextButton(
            "Supported sites", icon=ft.Icons.VERIFIED_OUTLINED,
            style=ft.ButtonStyle(color=AppTheme.TEXT_SECONDARY),
            on_click=lambda _: self._show_supported_sites(),
        )
        self._direct_result = ft.Container(
            visible=False, expand=True,
            content=ft.Column([], spacing=0),
        )
        self._direct_status = self._make_status(
            ft.Icons.LINK, "Paste a URL to auto-detect and download"
        )
        return ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.LINK, size=18, color=AppTheme.TEXT_SECONDARY),
                            self._direct_field,
                            detect_btn,
                        ],
                        spacing=10,
                    ),
                    bgcolor=AppTheme.CARD,
                    border=ft.Border(
                        left=ft.BorderSide(1, AppTheme.BORDER),
                        top=ft.BorderSide(1, AppTheme.BORDER),
                        right=ft.BorderSide(1, AppTheme.BORDER),
                        bottom=ft.BorderSide(1, AppTheme.BORDER),
                    ),
                    border_radius=AppTheme.button_radius,
                    padding=ft.Padding(14, 10, 10, 10),
                ),
                ft.Row([sites_btn], alignment=ft.MainAxisAlignment.END),
                ft.Stack([self._direct_result, self._direct_status], expand=True),
            ],
            spacing=8, expand=True,
        )

    # --------------------------------------------- supported sites dialog
    def _show_supported_sites(self):
        results = ft.ListView(expand=True, spacing=2, padding=ft.Padding(0, 4, 0, 4))
        count_lbl = ft.Text("", size=11, color=AppTheme.TEXT_SECONDARY)
        all_sites = _supported_sites()

        def render(items):
            results.controls.clear()
            for name in items[:400]:
                results.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=14, color=AppTheme.ACCENT),
                        ft.Text(name, size=12, color=AppTheme.TEXT),
                    ], spacing=8),
                    padding=ft.Padding(8, 4, 8, 4)))
            shown = min(len(items), 400)
            extra = f" (showing {shown})" if len(items) > 400 else ""
            count_lbl.value = f"{len(items)} of {len(all_sites)} sites{extra}"
            try:
                results.update(); count_lbl.update()
            except Exception:
                pass

        def on_search(e):
            q = (e.control.value or "").lower().strip()
            items = [s for s in all_sites if q in s.lower()] if q else all_sites
            render(items)

        search = ft.TextField(
            hint_text="Search sites — e.g. youtube, vimeo, tiktok…",
            prefix_icon=ft.Icons.SEARCH, height=44, autofocus=True,
            bgcolor=AppTheme.CARD, border_color=AppTheme.BORDER,
            focused_border_color=AppTheme.ACCENT, color=AppTheme.TEXT,
            on_change=on_search)

        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Row([
                ft.Icon(ft.Icons.VERIFIED, color=AppTheme.ACCENT, size=20),
                ft.Text("Supported download sites", color=AppTheme.TEXT, size=16),
            ], spacing=8),
            content=ft.Container(
                width=520, height=520,
                content=ft.Column([
                    ft.Text("Any URL from these sites can be pasted in Direct URL. "
                            "Plus any direct .mp4 / .mp3 / image link.",
                            size=12, color=AppTheme.TEXT_SECONDARY),
                    search, count_lbl, results,
                ], spacing=10, expand=True)),
            actions=[ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog())],
        )
        self.page.show_dialog(dlg)
        render(all_sites)

    # --------------------------------------------------- provider chips
    def _render_provider_chips(self, tab: str):
        row_map = {
            "music":  getattr(self, "_music_provider_row", None),
            "images": getattr(self, "_images_provider_row", None),
            "video":  getattr(self, "_video_provider_row", None),
            "web":    getattr(self, "_web_provider_row", None),
        }
        row = row_map.get(tab)
        if row is None:
            return
        labels = _PROVIDER_LABELS.get(tab, [])
        row.controls.clear()
        current = self._active_providers.get(tab, "all")

        all_active = current == "all"
        row.controls.append(self._chip("All", "all", all_active, tab))
        for p in labels:
            active = p["key"] == current
            row.controls.append(self._chip(p["label"], p["key"], active, tab))

    def _chip(self, label: str, key: str, active: bool, tab: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(
                label, size=12,
                color=AppTheme.ACCENT if active else AppTheme.TEXT_SECONDARY,
                weight=ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL,
            ),
            padding=ft.Padding(12, 7, 12, 7),
            border_radius=AppTheme.button_radius,
            bgcolor=(AppTheme.ACCENT + "1A") if active else AppTheme.CARD,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.ACCENT if active else AppTheme.BORDER),
            ),
            on_click=lambda _, k=key, t=tab: self._set_provider(t, k),
            ink=True,
        )

    def _set_provider(self, tab: str, key: str):
        self._active_providers[tab] = key
        self._render_provider_chips(tab)
        row_map = {
            "music": self._music_provider_row,
            "images": self._images_provider_row,
            "video": self._video_provider_row,
            "web": self._web_provider_row,
        }
        row = row_map.get(tab)
        if row:
            self._safe_update(row)
        field_map = {
            "music": self._music_field, "images": self._images_field,
            "video": self._video_field, "web": self._web_field,
        }
        field = field_map.get(tab)
        # Restore last query for this provider
        last = self._last_queries.get(tab, {}).get(key, "")
        if field and last:
            field.value = last
            self._safe_update(field)
        # Auto-search if there is an active query in the field
        current_query = (field.value or "").strip() if field else ""
        if current_query:
            self._start_search(tab, current_query)

    # --------------------------------------------------- search bar
    def _search_bar(self, field: ft.TextField, cancel_btn: ft.IconButton,
                    tab: str) -> ft.Container:
        search_btn = ft.IconButton(
            ft.Icons.SEARCH, icon_size=18, icon_color=AppTheme.ACCENT,
            tooltip="Search",
            on_click=lambda _: self._start_search(tab, field.value or ""),
        )
        return ft.Container(
            content=ft.Row([field, cancel_btn, search_btn], spacing=4),
            bgcolor=AppTheme.CARD,
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
            border_radius=AppTheme.button_radius,
            padding=ft.Padding(14, 8, 8, 8),
        )

    # --------------------------------------------------- search engine
    def _start_search(self, tab: str, query: str):
        query = (query or "").strip()
        if not query:
            return

        # Cancel previous search
        old_evt = self._cancel_events.get(tab)
        if old_evt:
            old_evt.set()
        cancel_evt = threading.Event()
        self._cancel_events[tab] = cancel_evt

        # Save last query
        provider = self._active_providers.get(tab, "all")
        self._last_queries.setdefault(tab, {})[provider] = query

        # Determine which providers to run
        if tab == "direct":
            return
        all_fns = _PROVIDERS.get(tab, {})
        if provider == "all":
            fns = list(all_fns.values())
        else:
            fn = all_fns.get(provider)
            fns = [fn] if fn else []

        if not fns:
            return

        # Clear UI and show loading
        self._clear_results(tab)
        self._show_loading(tab, True)
        self._result_counts[tab] = 0
        self._rendered_counts[tab] = 0

        with self._pending_lock:
            self._pending_counts[tab] = len(fns)

        def run_one(fn, evt):
            try:
                results = fn(query)
            except Exception:
                results = []
            if not evt.is_set() and results:
                try:
                    self.page.run_task(self._append_results, tab, results, evt)
                except Exception:
                    pass
            with self._pending_lock:
                self._pending_counts[tab] -= 1
                done = self._pending_counts[tab] <= 0
            if done and not evt.is_set():
                try:
                    self.page.run_task(self._finish_search, tab, evt)
                except Exception:
                    pass

        for fn in fns:
            threading.Thread(target=run_one, args=(fn, cancel_evt), daemon=True).start()

    def _cancel_search(self, tab: str):
        evt = self._cancel_events.get(tab)
        if evt:
            evt.set()
        self._show_loading(tab, False)
        cancel_map = {
            "music": self._music_cancel, "images": self._images_cancel,
            "video": self._video_cancel, "web": self._web_cancel,
        }
        btn = cancel_map.get(tab)
        if btn:
            btn.visible = False
            self._safe_update(btn)

    async def _append_results(self, tab: str, results: list, cancel_evt):
        if cancel_evt.is_set():
            return
        # Cap how many cards (and thus simultaneous remote image loads) render.
        # Loading 100+ network thumbnails at once is what freezes the UI.
        rendered = self._rendered_counts.get(tab, 0)
        room = _MAX_CARDS - rendered
        self._result_counts[tab] = self._result_counts.get(tab, 0) + len(results)
        if room > 0:
            batch = results[:room]
            self._rendered_counts[tab] = rendered + len(batch)
            self._add_cards(tab, batch)
            self._update_results_area(tab)

    async def _finish_search(self, tab: str, cancel_evt):
        if cancel_evt.is_set():
            return
        self._show_loading(tab, False)
        cancel_map = {
            "music": self._music_cancel, "images": self._images_cancel,
            "video": self._video_cancel, "web": self._web_cancel,
        }
        btn = cancel_map.get(tab)
        if btn:
            btn.visible = False
            self._safe_update(btn)
        if self._result_counts.get(tab, 0) == 0:
            self._show_empty(tab, "No results found — try a different query or provider")

    def _clear_results(self, tab: str):
        grid_map = {
            "music": self._music_grid, "images": self._images_grid,
            "video": self._video_grid,
        }
        list_map = {"web": self._web_list}
        if tab in grid_map:
            grid_map[tab].controls.clear()
        if tab in list_map:
            list_map[tab].controls.clear()
        # Show cancel button
        cancel_map = {
            "music": self._music_cancel, "images": self._images_cancel,
            "video": self._video_cancel, "web": self._web_cancel,
        }
        btn = cancel_map.get(tab)
        if btn:
            btn.visible = True
            self._safe_update(btn)

    def _show_loading(self, tab: str, loading: bool):
        status_map = {
            "music": self._music_status, "images": self._images_status,
            "video": self._video_status, "web": self._web_status,
        }
        grid_map = {
            "music": self._music_grid, "images": self._images_grid,
            "video": self._video_grid, "web": self._web_list,
        }
        status = status_map.get(tab)
        grid = grid_map.get(tab)
        if loading:
            if status:
                status.content = ft.Column(
                    [
                        ft.ProgressRing(width=32, height=32, color=AppTheme.ACCENT),
                        ft.Text("Searching…", size=13, color=AppTheme.TEXT_SECONDARY),
                    ],
                    spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
                status.visible = True
                self._safe_update(status)
            if grid:
                grid.visible = False
                self._safe_update(grid)
        else:
            if status:
                status.visible = False
                self._safe_update(status)
            if grid and (self._result_counts.get(tab, 0) > 0):
                grid.visible = True
                self._safe_update(grid)

    def _show_empty(self, tab: str, msg: str):
        status_map = {
            "music": self._music_status, "images": self._images_status,
            "video": self._video_status, "web": self._web_status,
        }
        status = status_map.get(tab)
        if status:
            icon_map = {
                "music": ft.Icons.SEARCH_OFF, "images": ft.Icons.IMAGE_NOT_SUPPORTED,
                "video": ft.Icons.VIDEOCAM_OFF, "web": ft.Icons.WEB_ASSET_OFF,
            }
            status.content = ft.Column(
                [
                    ft.Icon(icon_map.get(tab, ft.Icons.SEARCH_OFF), size=48,
                            color=AppTheme.TEXT_SECONDARY),
                    ft.Text(msg, size=13, color=AppTheme.TEXT_SECONDARY,
                            text_align=ft.TextAlign.CENTER),
                ],
                spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            status.visible = True
            self._safe_update(status)

    def _update_results_area(self, tab: str):
        grid_map = {
            "music": self._music_grid, "images": self._images_grid,
            "video": self._video_grid, "web": self._web_list,
        }
        grid = grid_map.get(tab)
        if grid:
            grid.visible = True
            self._safe_update(grid)

    def _add_cards(self, tab: str, results: list):
        if tab == "music":
            for song in results:
                self._music_grid.controls.append(self._music_card(song))
        elif tab == "images":
            for img in results:
                self._images_grid.controls.append(self._image_card(img))
        elif tab == "video":
            for v in results:
                self._video_grid.controls.append(self._video_card(v))
        elif tab == "web":
            for w in results:
                self._web_list.controls.append(self._web_card(w))

    # ============================================================= CARDS

    # ---- Music card
    def _music_card(self, song) -> ft.Container:
        dur_badge = ft.Container(
            content=ft.Text(_fmt_dur(song.duration), size=10,
                            color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.BLACK54,
            padding=ft.Padding(5, 2, 5, 2), border_radius=4,
            right=6, bottom=6,
        ) if song.duration else ft.Container()
        src_badge = ft.Container(
            content=ft.Text(song.source, size=9, color=ft.Colors.WHITE),
            bgcolor=AppTheme.ACCENT + "CC",
            padding=ft.Padding(5, 2, 5, 2), border_radius=4,
            left=6, top=6,
        )
        thumb_stack = ft.Stack(
            [
                ft.Image(
                    src=song.thumbnail_path or "",
                    fit=ft.BoxFit.COVER, width=220, height=130,
                    error_content=ft.Container(
                        content=ft.Icon(ft.Icons.MUSIC_NOTE, size=36,
                                        color=AppTheme.TEXT_SECONDARY),
                        bgcolor="#1E1E1E", alignment=ft.Alignment(0, 0),
                    ),
                ),
                src_badge, dur_badge,
            ],
            height=130,
        )
        action_row = ft.Row(
            [
                ft.IconButton(
                    ft.Icons.PLAY_CIRCLE_FILL, icon_size=22, icon_color=AppTheme.ACCENT,
                    tooltip="Play here", width=34,
                    on_click=lambda _, s=song: self._play_media(
                        s.source_url or s.audio_url or "", s.title,
                        audio_only=True, thumb=s.thumbnail_path or ""),
                ),
                ft.ElevatedButton(
                    "Download", icon=ft.Icons.DOWNLOAD_ROUNDED,
                    bgcolor=AppTheme.ACCENT, color=ft.Colors.WHITE,
                    height=32, style=ft.ButtonStyle(padding=ft.Padding(8,0,8,0)),
                    on_click=lambda _, s=song: self._download_music(s),
                ),
                ft.IconButton(
                    ft.Icons.OPEN_IN_NEW, icon_size=18,
                    icon_color=AppTheme.TEXT_SECONDARY,
                    tooltip="Open in browser",
                    on_click=lambda _, s=song: self._open(s.source_url),
                ),
                ft.IconButton(
                    ft.Icons.COPY, icon_size=18,
                    icon_color=AppTheme.TEXT_SECONDARY,
                    tooltip="Copy URL",
                    on_click=lambda _, s=song: self._copy(s.source_url),
                ),
            ],
            spacing=2,
        )
        return ft.Container(
            content=ft.Column(
                [
                    thumb_stack,
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(song.title, size=12,
                                        weight=ft.FontWeight.W_600,
                                        color=AppTheme.TEXT, max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(song.artist, size=11,
                                        color=AppTheme.TEXT_SECONDARY, max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                action_row,
                            ],
                            spacing=4,
                        ),
                        padding=ft.Padding(10, 8, 10, 10),
                    ),
                ],
                spacing=0,
            ),
            bgcolor=AppTheme.CARD,
            border_radius=AppTheme.card_radius,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    # ---- Image card
    def _image_card(self, img) -> ft.Container:
        overlay = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        ft.Icons.DOWNLOAD, icon_size=16,
                        icon_color=ft.Colors.WHITE, bgcolor=AppTheme.ACCENT,
                        tooltip="Download",
                        on_click=lambda _, i=img: self._download_image(i),
                    ),
                    ft.IconButton(
                        ft.Icons.COPY, icon_size=16,
                        icon_color=ft.Colors.WHITE, bgcolor=ft.Colors.BLACK54,
                        tooltip="Copy URL",
                        on_click=lambda _, i=img: self._copy(i.full_url),
                    ),
                    ft.IconButton(
                        ft.Icons.OPEN_IN_NEW, icon_size=16,
                        icon_color=ft.Colors.WHITE, bgcolor=ft.Colors.BLACK54,
                        tooltip="Open source",
                        on_click=lambda _, i=img: self._open(i.page_url or i.full_url),
                    ),
                    ft.IconButton(
                        ft.Icons.FAVORITE_BORDER, icon_size=16,
                        icon_color=ft.Colors.WHITE, bgcolor=ft.Colors.BLACK54,
                        tooltip="Favorite",
                        on_click=lambda _, i=img: self._fav_image(i),
                    ),
                ],
                spacing=4,
            ),
            right=4, top=4,
            visible=False,
        )
        src_badge = ft.Container(
            content=ft.Text(img.source, size=9, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.BLACK54,
            padding=ft.Padding(5, 2, 5, 2), border_radius=4,
            left=6, bottom=6,
        )
        card = ft.Container(
            content=ft.Stack(
                [
                    ft.Image(
                        src=img.thumbnail_url or img.full_url or " ", fit=ft.BoxFit.COVER,
                        width=260, height=200,
                        error_content=ft.Container(
                            content=ft.Icon(ft.Icons.BROKEN_IMAGE, size=32,
                                            color=AppTheme.TEXT_SECONDARY),
                            bgcolor=AppTheme.CARD, alignment=ft.Alignment(0, 0),
                        ),
                    ),
                    overlay,
                    src_badge,
                ],
            ),
            height=200,
            border_radius=AppTheme.card_radius,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            on_click=lambda _, i=img: self._show_image_preview(i),
        )

        def on_hover(e):
            overlay.visible = e.data == "true"
            try:
                overlay.update()
            except Exception:
                pass

        card.on_hover = on_hover
        return card

    # ---- Video card
    def _video_card(self, v) -> ft.Container:
        dur_badge = ft.Container(
            content=ft.Text(_fmt_dur(v.duration), size=10,
                            color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.BLACK54,
            padding=ft.Padding(5, 2, 5, 2), border_radius=4,
            right=6, bottom=6,
        ) if v.duration else ft.Container()
        src_badge = ft.Container(
            content=ft.Text(v.source, size=9, color=ft.Colors.WHITE),
            bgcolor=AppTheme.ACCENT + "CC",
            padding=ft.Padding(5, 2, 5, 2), border_radius=4,
            left=6, top=6,
        )
        views_text = _fmt_views(v.views)
        action_row = ft.Row(
            [
                ft.IconButton(
                    ft.Icons.PLAY_CIRCLE_FILL, icon_size=26, icon_color=AppTheme.ACCENT,
                    tooltip="Play here",
                    on_click=lambda _, item=v: self._play_media(item.source_url, item.title),
                ),
                ft.ElevatedButton(
                    "Download", icon=ft.Icons.DOWNLOAD_ROUNDED,
                    bgcolor=AppTheme.ACCENT, color=ft.Colors.WHITE,
                    height=32, style=ft.ButtonStyle(padding=ft.Padding(8,0,8,0)),
                    on_click=lambda _, item=v: self._download_video(item),
                ),
                ft.IconButton(
                    ft.Icons.OPEN_IN_NEW, icon_size=18,
                    icon_color=AppTheme.TEXT_SECONDARY,
                    tooltip="Open in browser",
                    on_click=lambda _, item=v: self._open(item.source_url),
                ),
                ft.IconButton(
                    ft.Icons.COPY, icon_size=18,
                    icon_color=AppTheme.TEXT_SECONDARY,
                    tooltip="Copy URL",
                    on_click=lambda _, item=v: self._copy(item.source_url),
                ),
            ],
            spacing=2,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Stack(
                        [
                            ft.Image(
                                src=v.thumbnail_url, fit=ft.BoxFit.COVER,
                                width=260, height=146,
                                error_content=ft.Container(
                                    content=ft.Icon(ft.Icons.VIDEOCAM_OFF, size=36,
                                                    color=AppTheme.TEXT_SECONDARY),
                                    bgcolor="#1E1E1E",
                                    alignment=ft.Alignment(0, 0),
                                ),
                            ),
                            dur_badge, src_badge,
                        ],
                        height=146,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(v.title, size=12, weight=ft.FontWeight.W_600,
                                        color=AppTheme.TEXT, max_lines=2,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(v.channel, size=11,
                                        color=AppTheme.TEXT_SECONDARY, max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(views_text, size=10,
                                        color=AppTheme.TEXT_SECONDARY)
                                if views_text else ft.Container(),
                                action_row,
                            ],
                            spacing=3,
                        ),
                        padding=ft.Padding(10, 8, 10, 10),
                    ),
                ],
                spacing=0,
            ),
            bgcolor=AppTheme.CARD,
            border_radius=AppTheme.card_radius,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    # ---- Web card
    def _web_card(self, w) -> ft.Container:
        favicon = ft.Image(
            src=w.favicon_url, width=16, height=16,
            error_content=ft.Icon(ft.Icons.LANGUAGE, size=16,
                                  color=AppTheme.TEXT_SECONDARY),
        ) if w.favicon_url else ft.Icon(ft.Icons.LANGUAGE, size=16,
                                        color=AppTheme.TEXT_SECONDARY)
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            favicon,
                            ft.Text(
                                w.url, size=11, color=AppTheme.TEXT_SECONDARY,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                            ft.Text(f"· {w.source}", size=10,
                                    color=AppTheme.TEXT_SECONDARY),
                        ],
                        spacing=6,
                    ),
                    ft.Text(
                        w.title, size=14, color=AppTheme.ACCENT,
                        weight=ft.FontWeight.W_600,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        w.description, size=12, color=AppTheme.TEXT_SECONDARY,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ) if w.description else ft.Container(),
                ],
                spacing=4,
            ),
            bgcolor=AppTheme.CARD,
            border_radius=8,
            padding=ft.Padding(14, 12, 14, 12),
            border=ft.Border(
                left=ft.BorderSide(1, AppTheme.BORDER),
                top=ft.BorderSide(1, AppTheme.BORDER),
                right=ft.BorderSide(1, AppTheme.BORDER),
                bottom=ft.BorderSide(1, AppTheme.BORDER),
            ),
            on_click=lambda _, item=w: self._open(item.url),
            ink=True,
        )

    # ================================================== IMAGE PREVIEW MODAL
    def _show_image_preview(self, img):
        def close(_):
            try:
                self.page.pop_dialog()
            except Exception:
                pass

        fav_icon = (ft.Icons.FAVORITE if img.id in self._favorites
                    else ft.Icons.FAVORITE_BORDER)
        dl_status = ft.Text("", size=12, color=AppTheme.ACCENT,
                            text_align=ft.TextAlign.CENTER)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=AppTheme.PANEL,
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Image(
                            src=img.full_url, fit=ft.BoxFit.CONTAIN,
                            width=700, height=440,
                            error_content=ft.Container(
                                content=ft.Icon(ft.Icons.BROKEN_IMAGE, size=64,
                                                color=AppTheme.TEXT_SECONDARY),
                                alignment=ft.Alignment(0, 0),
                            ),
                        ),
                        ft.Text(
                            img.title or "Image", size=13, color=AppTheme.TEXT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            f"{img.source}  ·  {img.author}" if img.author
                            else img.source,
                            size=11, color=AppTheme.TEXT_SECONDARY,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        dl_status,
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                padding=ft.Padding(16, 16, 16, 8), width=720,
            ),
            # Buttons live in `actions` — the reliably-clickable location in this Flet build
            actions=[
                ft.ElevatedButton(
                    "Download", icon=ft.Icons.DOWNLOAD,
                    bgcolor=AppTheme.ACCENT, color=AppTheme.ON_ACCENT,
                    on_click=lambda _, i=img, s=dl_status: self._download_image(i, s)),
                ft.ElevatedButton(
                    "Copy URL", icon=ft.Icons.COPY,
                    bgcolor=AppTheme.CARD, color=AppTheme.TEXT,
                    on_click=lambda _, i=img: self._copy(i.full_url)),
                ft.ElevatedButton(
                    "Open Source", icon=ft.Icons.OPEN_IN_NEW,
                    bgcolor=AppTheme.CARD, color=AppTheme.TEXT,
                    on_click=lambda _, i=img: self._open(i.page_url or i.full_url)),
                ft.IconButton(fav_icon, icon_color=ft.Colors.RED_400, tooltip="Favorite",
                              on_click=lambda _, i=img: self._fav_image(i)),
                ft.ElevatedButton("Close", bgcolor=AppTheme.CARD, color=AppTheme.TEXT,
                                  on_click=close),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        self.page.show_dialog(dlg)

    # ============================================= DIRECT URL
    def _resolve_url(self, url: str):
        url = (url or "").strip()
        if not url:
            return
        self._direct_status.content = ft.Column(
            [
                ft.ProgressRing(width=28, height=28, color=AppTheme.ACCENT),
                ft.Text("Detecting…", size=13, color=AppTheme.TEXT_SECONDARY),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self._direct_status.visible = True
        self._direct_result.visible = False
        self._safe_update(self._direct_status)
        self._safe_update(self._direct_result)

        def work():
            info = _url_svc.resolve(url)
            try:
                self.page.run_task(self._show_direct_result, info, url)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    async def _show_direct_result(self, info: dict, url: str):
        self._direct_status.visible = False
        self._safe_update(self._direct_status)

        kind = info.get("type", "unknown")
        title = info.get("title") or url
        thumb = info.get("thumbnail") or ""
        duration = info.get("duration") or 0
        author = info.get("author") or ""
        error = info.get("error")

        if kind == "playlist":
            self._show_playlist_result(info)
            return

        if error and kind == "unknown":
            self._direct_status.content = ft.Column(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=40, color=AppTheme.TEXT_SECONDARY),
                    ft.Text(f"Could not resolve: {error}", size=13,
                            color=AppTheme.TEXT_SECONDARY),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            self._direct_status.visible = True
            self._safe_update(self._direct_status)
            return

        type_icon = {
            "audio":    ft.Icons.MUSIC_NOTE,
            "video":    ft.Icons.VIDEOCAM,
            "image":    ft.Icons.IMAGE,
            "document": ft.Icons.DESCRIPTION,
        }.get(kind, ft.Icons.LINK)

        thumb_widget = ft.Image(
            src=thumb, width=160, height=120, fit=ft.BoxFit.COVER,
            border_radius=8,
            error_content=ft.Container(
                content=ft.Icon(type_icon, size=48, color=AppTheme.TEXT_SECONDARY),
                width=160, height=120, bgcolor=AppTheme.CARD,
                border_radius=8, alignment=ft.Alignment(0, 0),
            ),
        ) if thumb else ft.Container(
            content=ft.Icon(type_icon, size=48, color=AppTheme.TEXT_SECONDARY),
            width=160, height=120, bgcolor=AppTheme.CARD,
            border_radius=8, alignment=ft.Alignment(0, 0),
        )

        meta_rows = [
            ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=AppTheme.TEXT,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Row([
                ft.Container(
                    content=ft.Text(kind.upper(), size=10, color=ft.Colors.WHITE),
                    bgcolor=AppTheme.ACCENT, border_radius=4,
                    padding=ft.Padding(6, 2, 6, 2),
                ),
                ft.Text(author, size=12, color=AppTheme.TEXT_SECONDARY) if author
                else ft.Container(),
                ft.Text(_fmt_dur(duration), size=12, color=AppTheme.TEXT_SECONDARY)
                if duration else ft.Container(),
            ], spacing=8),
            ft.Text(url, size=11, color=AppTheme.TEXT_SECONDARY,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ]

        dl_status = ft.Text("", size=12, color=AppTheme.ACCENT)

        def _do_download(_):
            dl_status.value = "Starting download…"
            dl_status.color = AppTheme.TEXT_SECONDARY
            try:
                dl_status.update()
            except Exception:
                pass
            self._download_direct(url, title, kind, dl_status)

        meta_rows.append(ft.Row([
            ft.ElevatedButton(
                "Download", icon=ft.Icons.DOWNLOAD,
                bgcolor=AppTheme.ACCENT, color=ft.Colors.WHITE,
                on_click=_do_download,
            ),
            ft.ElevatedButton(
                "Open", icon=ft.Icons.OPEN_IN_NEW,
                on_click=lambda _, u=url: self._open(u),
            ),
            ft.ElevatedButton(
                "Copy URL", icon=ft.Icons.COPY,
                on_click=lambda _, u=url: self._copy(u),
            ),
        ], spacing=8))
        meta_rows.append(dl_status)

        self._direct_result.content = ft.Container(
            content=ft.Row(
                [
                    thumb_widget,
                    ft.Container(
                        content=ft.Column(meta_rows, spacing=10),
                        expand=True, padding=ft.Padding(16, 0, 0, 0),
                    ),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=AppTheme.CARD,
            border_radius=AppTheme.card_radius,
            padding=ft.Padding(16, 16, 16, 16),
        )
        self._direct_result.visible = True
        self._safe_update(self._direct_result)

    # --------------------------------------------------- playlist result
    def _show_playlist_result(self, info: dict):
        entries = info.get("entries", [])
        title = info.get("title") or "Playlist"
        count = info.get("count", len(entries))

        self._pl_entries = entries
        self._pl_selected = set()          # indices selected via checkbox
        self._pl_status: dict = {}         # task_id -> status Text control
        self._pl_checks: dict = {}         # index -> Checkbox

        self._pl_sel_btn = ft.ElevatedButton(
            "Download selected (0)", icon=ft.Icons.DOWNLOAD_OUTLINED,
            bgcolor=AppTheme.CARD, color=AppTheme.TEXT, disabled=True,
            on_click=lambda _: self._download_selected_entries())
        header = ft.Row([
            ft.Icon(ft.Icons.PLAYLIST_PLAY, size=22, color=AppTheme.ACCENT),
            ft.Column([
                ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=AppTheme.TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{count} items", size=12, color=AppTheme.TEXT_SECONDARY),
            ], spacing=0, expand=True),
            self._pl_sel_btn,
            ft.ElevatedButton(
                f"Download all ({count})", icon=ft.Icons.DOWNLOAD_ROUNDED,
                bgcolor=AppTheme.ACCENT, color=AppTheme.ON_ACCENT,
                on_click=lambda _: self._download_entries(list(range(len(entries))))),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        select_all = ft.Checkbox(
            label="Select all", value=False, active_color=AppTheme.ACCENT,
            label_style=ft.TextStyle(color=AppTheme.TEXT_SECONDARY, size=12),
            on_change=lambda e: self._pl_toggle_all(e.control.value))

        rows = []
        for i, e in enumerate(entries):
            status = ft.Text("", size=10, color=AppTheme.ACCENT, width=92,
                             text_align=ft.TextAlign.RIGHT)
            cb = ft.Checkbox(value=False, active_color=AppTheme.ACCENT,
                             on_change=lambda ev, idx=i: self._pl_toggle_one(idx, ev.control.value))
            self._pl_checks[i] = cb
            self._pl_status[i] = status
            thumb = e.get("thumbnail") or ""
            thumb_w = ft.Container(
                width=48, height=32, border_radius=5, bgcolor=AppTheme.PANEL,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=thumb, width=48, height=32, fit=ft.BoxFit.COVER,
                                 error_content=ft.Icon(ft.Icons.MUSIC_NOTE, size=15,
                                                       color=AppTheme.TEXT_SECONDARY))
                ) if thumb else ft.Container(
                    width=48, height=32, border_radius=5, bgcolor=AppTheme.PANEL,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.MUSIC_NOTE, size=15, color=AppTheme.TEXT_SECONDARY))
            rows.append(ft.Container(
                content=ft.Row([
                    cb,
                    ft.Text(f"{i+1}", size=11, color=AppTheme.TEXT_SECONDARY, width=26),
                    thumb_w,
                    ft.Text(e["title"], size=12, color=AppTheme.TEXT, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(_fmt_dur(e.get("duration", 0)), size=10,
                            color=AppTheme.TEXT_SECONDARY) if e.get("duration") else ft.Container(),
                    status,
                    ft.IconButton(ft.Icons.PLAY_CIRCLE_OUTLINE, icon_size=18,
                                  icon_color=AppTheme.ACCENT, tooltip="Play",
                                  on_click=lambda _, it=e: self._play_media(
                                      it["url"], it.get("title", ""),
                                      audio_only=True, thumb=it.get("thumbnail", ""))),
                    ft.IconButton(ft.Icons.DOWNLOAD, icon_size=16, icon_color=AppTheme.ACCENT,
                                  tooltip="Download this",
                                  on_click=lambda _, idx=i: self._download_entries([idx])),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding(8, 4, 8, 4),
                border=ft.Border(bottom=ft.BorderSide(0.5, AppTheme.BORDER))))

        self._direct_result.content = ft.Container(
            content=ft.Column([
                header,
                ft.Row([select_all], alignment=ft.MainAxisAlignment.START),
                ft.Divider(height=6, color=AppTheme.BORDER),
                ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO, expand=True),
            ], spacing=8, expand=True),
            bgcolor=AppTheme.CARD, border_radius=AppTheme.card_radius,
            padding=ft.Padding(16, 16, 16, 12), expand=True)
        self._direct_result.visible = True
        self._safe_update(self._direct_result)

    def _pl_toggle_one(self, idx, checked):
        if checked:
            self._pl_selected.add(idx)
        else:
            self._pl_selected.discard(idx)
        n = len(self._pl_selected)
        self._pl_sel_btn.text = f"Download selected ({n})"
        self._pl_sel_btn.disabled = n == 0
        self._pl_sel_btn.bgcolor = AppTheme.ACCENT if n else AppTheme.CARD
        self._pl_sel_btn.color = AppTheme.ON_ACCENT if n else AppTheme.TEXT
        self._safe_update(self._pl_sel_btn)

    def _pl_toggle_all(self, checked):
        for idx, cb in self._pl_checks.items():
            cb.value = checked
            self._safe_update(cb)
            if checked:
                self._pl_selected.add(idx)
            else:
                self._pl_selected.discard(idx)
        self._pl_toggle_one(-1, False)  # refresh button label
        self._pl_selected.discard(-1)

    def _download_selected_entries(self):
        if self._pl_selected:
            self._download_entries(sorted(self._pl_selected))

    def _download_entries(self, indices):
        for idx in indices:
            e = self._pl_entries[idx]
            task = DownloadTask(id=generate_id(), url=e["url"],
                                title=e.get("title", "audio"),
                                kind="youtube", skip_library=True)
            status = self._pl_status.get(idx)
            if status:
                status.value = "Queued…"
                status.color = AppTheme.TEXT_SECONDARY
                self._safe_update(status)
            download_manager.enqueue(task)
            threading.Thread(target=self._watch_pl_task, args=(task, status),
                             daemon=True).start()
        self._toast(f"Downloading {len(indices)} item(s) → Downloads folder")

    def _watch_pl_task(self, task, status):
        import time
        if status is None:
            return
        last = None
        for _ in range(2400):
            st = task.status
            if st == "downloading":
                txt = f"{int(task.progress*100)}%"
            elif st in ("complete", "failed", "cancelled"):
                break
            else:
                txt = "Queued…"
            if txt != last:
                last = txt
                self._set_status(status, txt, AppTheme.TEXT_SECONDARY)
            time.sleep(0.5)
        if task.status == "complete":
            self._set_status(status, "✓ Done", AppTheme.ACCENT)
        elif task.status == "failed":
            self._set_status(status, "✗ Failed", AppTheme.DANGER)
        elif task.status == "cancelled":
            self._set_status(status, "Cancelled", AppTheme.TEXT_SECONDARY)

    # ===================================================== IN-APP PLAYER
    def _play_media(self, url: str, title: str, audio_only: bool = False, thumb: str = ""):
        """Play a Discovery stream in-app via flet-video (libmpv) in a dialog —
        the Video control only renders/plays when actually visible, so a dialog
        is required. Falls back to the browser if the engine isn't available."""
        if not url:
            return
        if not _HAS_VIDEO:
            self._toast("Opening in browser (in-app player unavailable)")
            self._open(url)
            return

        body = ft.Column(
            [ft.ProgressRing(width=30, height=30, color=AppTheme.ACCENT),
             ft.Text("Loading stream…", size=12, color=AppTheme.TEXT_SECONDARY)],
            spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER)
        holder = ft.Container(content=body, width=760, height=440,
                              alignment=ft.Alignment(0, 0), bgcolor="#000000",
                              border_radius=10)
        dlg = ft.AlertDialog(
            modal=True, bgcolor=AppTheme.PANEL,
            title=ft.Text(title[:70], color=AppTheme.TEXT, size=14),
            content=holder,
            actions=[
                ft.TextButton("Open in browser", on_click=lambda _: self._open(url)),
                ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog()),
            ])
        self.page.show_dialog(dlg)
        threading.Thread(target=self._resolve_and_play,
                         args=(url, audio_only, holder, thumb), daemon=True).start()

    def _resolve_and_play(self, url, audio_only, holder, thumb=""):
        stream = None
        try:
            from yt_dlp import YoutubeDL
            fmt = ("bestaudio/best" if audio_only
                   else "best[ext=mp4][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/best")
            with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                            "format": fmt}) as ydl:
                info = ydl.extract_info(url, download=False)
            stream = info.get("url")
            if not stream and info.get("requested_formats"):
                stream = info["requested_formats"][0].get("url")
        except Exception:
            stream = None

        def _apply():
            if not stream:
                holder.content = ft.Column(
                    [ft.Icon(ft.Icons.ERROR_OUTLINE, size=40, color=AppTheme.TEXT_SECONDARY),
                     ft.Text("Couldn't load this stream — try Open in browser",
                             size=12, color=AppTheme.TEXT_SECONDARY)],
                    spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER)
            else:
                try:
                    video = _fv.Video(
                        expand=True, autoplay=True, show_controls=True,
                        playlist=[_fv.VideoMedia(resource=stream)],
                        muted=False, volume=100)
                    if audio_only and thumb:
                        # Audio has no picture — show the cover art over the frame,
                        # leaving the bottom control strip visible.
                        holder.content = ft.Stack([
                            video,
                            ft.Container(
                                bottom=64, left=0, right=0, top=0,
                                bgcolor="#000000", alignment=ft.Alignment(0, 0),
                                content=ft.Image(src=thumb, fit=ft.BoxFit.CONTAIN,
                                                 expand=True)),
                        ])
                    else:
                        holder.content = video
                except Exception:
                    holder.content = ft.Column(
                        [ft.Icon(ft.Icons.MOVIE_OUTLINED, size=40, color=AppTheme.TEXT_SECONDARY),
                         ft.Text("In-app video engine unavailable — Open in browser",
                                 size=12, color=AppTheme.TEXT_SECONDARY)],
                        spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER)
            try:
                holder.update()
            except Exception:
                pass

        try:
            if self.page:
                self.page.run_task(self._async_apply, _apply)
        except Exception:
            pass

    # ======================================================= ACTIONS
    def _download_music(self, song):
        url = song.source_url or song.audio_url or ""
        if not url:
            self._toast("No URL available for this track")
            return
        # yt-dlp handles YouTube, SoundCloud, Bandcamp, Archive.org, etc.
        direct_only = url.lower().endswith((".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac"))
        kind = "direct" if direct_only else "youtube"
        task = DownloadTask(
            id=generate_id(), url=url,
            title=song.title, artist=song.artist,
            thumbnail=song.thumbnail_path or "",
            song_id=song.id, kind=kind,
            skip_library=True,
        )
        download_manager.enqueue(task)
        self._toast(f"Downloading: {song.title}")

    def _download_video(self, v):
        if not v.source_url:
            self._toast("No URL available")
            return
        task = DownloadTask(
            id=generate_id(), url=v.source_url,
            title=v.title, artist=v.channel,
            kind="video", skip_library=True,
        )
        download_manager.enqueue(task)
        self._toast(f"Downloading: {v.title}")

    def _download_image(self, img, status_text=None):
        from src.models.download import DownloadTask
        url = img.full_url or img.thumbnail_url
        if not url:
            if status_text is not None:
                self._set_status(status_text, "No URL available", AppTheme.DANGER)
            else:
                self._toast("No URL available")
            return
        task = DownloadTask(
            id=generate_id(), url=url,
            title=img.title or "image",
            image_id=img.id, kind="image", skip_library=True,
        )
        if status_text is not None:
            self._set_status(status_text, "Downloading…", AppTheme.TEXT_SECONDARY)
        download_manager.enqueue(task)
        if status_text is not None:
            threading.Thread(target=self._watch_image_dl, args=(task, status_text),
                             daemon=True).start()
        else:
            self._toast("Image queued — saving to Downloads\\Habibi\\Images")

    def _watch_image_dl(self, task, status_text):
        import time, os
        for _ in range(240):
            if task.status in ("complete", "failed", "cancelled"):
                break
            time.sleep(0.5)
        if task.status == "complete":
            folder = os.path.dirname(task.file_path or "") or "Downloads\\Habibi\\Images"
            self._set_status(status_text, f"✓ Saved to {folder}", AppTheme.ACCENT)
        elif task.status == "failed":
            self._set_status(status_text, f"✗ Failed: {task.error[:60]}", AppTheme.DANGER)
        else:
            self._set_status(status_text, "Cancelled", AppTheme.TEXT_SECONDARY)

    def _download_direct(self, url: str, title: str, kind: str, status_text=None):
        if kind == "image":
            dl_kind = "image"
        elif kind == "video":
            dl_kind = "video"
        elif url.lower().endswith((".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac")):
            dl_kind = "direct"
        else:
            dl_kind = "youtube"
        task = DownloadTask(id=generate_id(), url=url, title=title, kind=dl_kind, skip_library=True)
        download_manager.enqueue(task)
        # Watch this task and report the REAL outcome (success or the reason it
        # failed) back into the card, instead of a fire-and-forget "queued".
        if status_text is not None:
            threading.Thread(target=self._watch_download, args=(task, status_text),
                             daemon=True).start()

    def _watch_download(self, task, status_text):
        import time
        # Poll the task until it reaches a terminal state (max ~10 min)
        for _ in range(1200):
            st = task.status
            if st in ("complete", "failed", "cancelled"):
                break
            if st == "downloading" and task.progress:
                self._set_status(status_text,
                                 f"Downloading… {int(task.progress * 100)}%",
                                 AppTheme.TEXT_SECONDARY)
            time.sleep(0.5)

        if task.status == "complete":
            self._set_status(status_text, "✓ Saved to Downloads folder", AppTheme.ACCENT)
        elif task.status == "cancelled":
            self._set_status(status_text, "Download cancelled", AppTheme.TEXT_SECONDARY)
        else:
            reason = _explain_download_error(task.error, task.url)
            self._set_status(status_text, reason, AppTheme.DANGER)

    def _set_status(self, control, text, color):
        def _apply():
            control.value = text
            control.color = color
            try:
                control.update()
            except Exception:
                pass
        try:
            if self.page:
                self.page.run_task(self._async_apply, _apply)
        except Exception:
            pass

    async def _async_apply(self, fn):
        fn()

    def _fav_image(self, img):
        if img.id in self._favorites:
            self._favorites.discard(img.id)
            self._toast("Removed from favorites")
        else:
            self._favorites.add(img.id)
            self._toast("Added to favorites")

    def _open(self, url: str):
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _copy(self, text: str):
        try:
            pyperclip.copy(text)
            self._toast("Copied to clipboard")
        except Exception:
            self._toast("Could not copy")

    # ======================================================= UI HELPERS
    def _make_status(self, icon, text: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=52, color=AppTheme.TEXT_SECONDARY),
                    ft.Text(text, size=13, color=AppTheme.TEXT_SECONDARY,
                            text_align=ft.TextAlign.CENTER),
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
        )

    def _set_status_msg(self, status: ft.Container, icon, text: str):
        """Update an existing status container's icon + message in place."""
        try:
            col = status.content
            col.controls[0].name = icon
            col.controls[1].value = text
        except Exception:
            pass

    def _toast(self, msg: str):
        try:
            self.page.show_dialog(ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE),
                bgcolor=AppTheme.ACCENT,
                duration=3000,
                open=True,
            ))
        except Exception:
            pass

    def _safe_update(self, ctl):
        try:
            ctl.update()
        except (RuntimeError, AssertionError):
            pass
