# Habibi Downloader X

A desktop music downloader and library manager built with [Flet](https://flet.dev).

## Features

- **Library** — local music library with grid/list views, search, sort (name/artist/date/duration),
  multi-select delete, reveal-in-Explorer, favorites, and click-to-play.
- **Discovery** — tabbed search:
  - **Music** — YouTube search (real, via yt-dlp) and Direct-URL downloads. *Suno / DuckDuckGo are stubbed.*
  - **Images** — Openverse (Creative Commons, no API key needed) with download/open.
  - **Video** — YouTube video download (mp4).
- **Scanner** — pick a folder, recursively scan for audio/images/lyrics, see flags
  (artwork / no cover / lyrics / duplicate), import selected or all.
- **Download manager** — top-right popup with badge, live progress, pause/resume/cancel/retry/clear.
  Downloads run concurrently (configurable) and auto-add to the library.
- **Audio player** — bottom mini-player: play/pause, next/prev, seek, volume, repeat, shuffle.
- **Lyrics** — generate synced LRC with Whisper, view with line highlighting, edit, import/export `.lrc`.
- **Settings drawer** — download folder, concurrency (1/2/4/8), cover/lyrics/auto-add toggles,
  theme (dark/light/system), accent colour, and an About panel with version info.
- **Global search** — `Ctrl+K` focuses the top search bar and filters the library.

## Requirements

- Python 3.10+
- **FFmpeg** on your `PATH` (required for MP3 conversion and Whisper). Install via
  `winget install Gyan.FFmpeg` on Windows, or from https://ffmpeg.org.

## Setup

```bash
pip install -r requirements.txt
python main.py
```

## Notes

- **YouTube bot wall:** YouTube sometimes returns *"Sign in to confirm you're not a bot."*
  The app uses the android/web player clients to avoid this. If a specific video still blocks,
  set a `cookies_browser` value (e.g. `chrome`, `edge`, `firefox`) so yt-dlp authenticates with
  your browser cookies.
- **Whisper lyrics** download a model on first use and run on CPU; transcription can take a minute.
- Data (library DB, downloads, thumbnails, lyrics) lives under `~/.habibi`.
