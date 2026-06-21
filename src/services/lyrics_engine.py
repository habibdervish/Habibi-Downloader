import os
from typing import List, Optional
from src.models.lyrics import LyricsData, LyricLine
from src.models.song import Song
from src.utils.file_utils import get_lyrics_dir


class LyricsEngine:
    def __init__(self):
        self._cache: dict = {}

    def get_lyrics(self, song: Song) -> Optional[LyricsData]:
        if song.id in self._cache:
            return self._cache[song.id]

        lrc_path = self._find_lrc_file(song)
        if lrc_path and os.path.exists(lrc_path):
            try:
                with open(lrc_path, encoding="utf-8") as f:
                    data = LyricsData.from_lrc(f.read(), song_id=song.id)
                self._cache[song.id] = data
                return data
            except Exception:
                pass
        return None

    def save_lyrics(self, data: LyricsData) -> str:
        lrc_path = os.path.join(get_lyrics_dir(), f"{data.song_id}.lrc")
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(data.to_lrc())
        self._cache[data.song_id] = data
        return lrc_path

    def delete_lyrics(self, song_id: str):
        self._cache.pop(song_id, None)
        lrc_path = os.path.join(get_lyrics_dir(), f"{song_id}.lrc")
        if os.path.exists(lrc_path):
            os.remove(lrc_path)

    def create_empty(self, song: Song) -> LyricsData:
        data = LyricsData(
            song_id=song.id,
            title=song.title,
            artist=song.artist,
            lines=[],
        )
        self._cache[song.id] = data
        return data

    def generate_from_text(self, song: Song, text: str, duration: float = 0.0) -> LyricsData:
        raw_lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        total_lines = len(raw_lines)
        if total_lines == 0:
            return self.create_empty(song)

        line_duration = (duration or 30.0) / total_lines
        lines = []
        for i, raw in enumerate(raw_lines):
            ts = i * line_duration
            lines.append(LyricLine(timestamp=round(ts, 2), text=raw, duration=line_duration))

        data = LyricsData(
            song_id=song.id,
            title=song.title,
            artist=song.artist,
            lines=lines,
        )
        self._cache[song.id] = data
        return data

    def generate_with_whisper(self, song: Song, model_size: str = "base") -> LyricsData:
        """Transcribe the song's audio into timestamped lyric lines via faster-whisper."""
        if not song.file_path or not os.path.exists(song.file_path):
            raise FileNotFoundError("Song has no audio file on disk")

        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(song.file_path, beam_size=5, vad_filter=True)

        lines = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            lines.append(LyricLine(
                timestamp=round(seg.start, 2),
                text=text,
                duration=round(max(0.5, seg.end - seg.start), 2),
            ))

        data = LyricsData(
            song_id=song.id, title=song.title, artist=song.artist,
            lines=lines, source="whisper",
        )
        self._cache[song.id] = data
        self.save_lyrics(data)
        return data

    def import_lrc(self, song: Song, path: str) -> LyricsData:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = LyricsData.from_lrc(f.read(), song_id=song.id)
        if not data.title:
            data.title = song.title
        if not data.artist:
            data.artist = song.artist
        self._cache[song.id] = data
        self.save_lyrics(data)
        return data

    def shift_timestamps(self, data: LyricsData, delta: float) -> LyricsData:
        for line in data.lines:
            line.timestamp = max(0, round(line.timestamp + delta, 2))
        return data

    def set_line_timestamp(self, data: LyricsData, line_index: int, timestamp: float) -> LyricsData:
        if 0 <= line_index < len(data.lines):
            data.lines[line_index].timestamp = max(0, round(timestamp, 2))
        return data

    def add_line(self, data: LyricsData, after_index: int = -1) -> LyricsData:
        new_line = LyricLine()
        if after_index >= 0 and after_index < len(data.lines):
            ts = data.lines[after_index].timestamp + 2.0
            new_line.timestamp = round(ts, 2)
            data.lines.insert(after_index + 1, new_line)
        else:
            if data.lines:
                ts = data.lines[-1].timestamp + 2.0
                new_line.timestamp = round(ts, 2)
            data.lines.append(new_line)
        return data

    def remove_line(self, data: LyricsData, line_index: int) -> LyricsData:
        if 0 <= line_index < len(data.lines):
            data.lines.pop(line_index)
        return data

    def update_line_text(self, data: LyricsData, line_index: int, text: str) -> LyricsData:
        if 0 <= line_index < len(data.lines):
            data.lines[line_index].text = text
        return data

    def _find_lrc_file(self, song: Song) -> Optional[str]:
        expected = os.path.join(get_lyrics_dir(), f"{song.id}.lrc")
        if os.path.exists(expected):
            return expected

        if song.file_path:
            base = os.path.splitext(song.file_path)[0]
            for ext in [".lrc", ".txt"]:
                path = base + ext
                if os.path.exists(path):
                    return path
        return None


lyrics_engine = LyricsEngine()
