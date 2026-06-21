import sqlite3
import os
from typing import List, Optional

from src.utils.file_utils import get_db_path
from src.models.song import Song
from src.models.image_asset import ImageAsset


class Storage:
    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        path = get_db_path()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._migrate_db()

    def _init_db(self):
        schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "database", "schema.sql")
        with open(schema_path) as f:
            sql = f.read()
        self._conn.executescript(sql)
        self._conn.commit()

    def _migrate_db(self):
        """Safely add columns introduced after the initial schema."""
        migrations = [
            "ALTER TABLE songs ADD COLUMN suno_id TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN prompt TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN style TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN model_version TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN audio_url TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN image_url TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN lyrics_text TEXT DEFAULT ''",
            "ALTER TABLE songs ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ]
        for sql in migrations:
            try:
                self._conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        try:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_songs_suno_id ON songs(suno_id)"
            )
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str = "") -> str:
        cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def get_all_settings(self) -> dict:
        cur = self._conn.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}

    def set_setting(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        self._conn.commit()

    # ---------------------------------------------------------------- songs
    def save_song(self, song: Song):
        self._conn.execute(
            """INSERT OR REPLACE INTO songs
               (id, title, artist, album, duration, file_path, thumbnail_path,
                source, source_url, is_favorite, download_status, added_at,
                suno_id, prompt, style, model_version, audio_url, image_url,
                lyrics_text, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                song.id, song.title, song.artist, song.album, song.duration,
                song.file_path, song.thumbnail_path, song.source, song.source_url,
                int(song.is_favorite), song.download_status, song.added_at,
                song.suno_id, song.prompt, song.style, song.model_version,
                song.audio_url, song.image_url, song.lyrics_text, song.updated_at,
            ),
        )
        self._conn.commit()

    def save_songs(self, songs: List[Song]):
        for song in songs:
            self.save_song(song)

    def get_all_songs(self) -> List[Song]:
        cur = self._conn.execute("SELECT * FROM songs ORDER BY added_at DESC")
        return [Song.from_dict(dict(row)) for row in cur.fetchall()]

    def get_song(self, song_id: str) -> Optional[Song]:
        cur = self._conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
        row = cur.fetchone()
        return Song.from_dict(dict(row)) if row else None

    def search_songs(self, query: str) -> List[Song]:
        q = f"%{query}%"
        cur = self._conn.execute(
            "SELECT * FROM songs WHERE title LIKE ? OR artist LIKE ? ORDER BY added_at DESC",
            (q, q),
        )
        return [Song.from_dict(dict(row)) for row in cur.fetchall()]

    def toggle_favorite(self, song_id: str):
        self._conn.execute(
            "UPDATE songs SET is_favorite = CASE WHEN is_favorite = 0 THEN 1 ELSE 0 END WHERE id = ?",
            (song_id,),
        )
        self._conn.commit()

    def update_song_status(self, song_id: str, status: str):
        self._conn.execute(
            "UPDATE songs SET download_status = ? WHERE id = ?", (status, song_id)
        )
        self._conn.commit()

    def delete_song(self, song_id: str):
        self._conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        self._conn.commit()

    def update_song_metadata(self, song_id: str, title: str, artist: str, album: str):
        self._conn.execute(
            "UPDATE songs SET title = ?, artist = ?, album = ? WHERE id = ?",
            (title, artist, album, song_id),
        )
        self._conn.commit()

    # ---------------------------------------------------------- lyrics helpers
    def get_lyrics_song_ids(self) -> set:
        try:
            cur = self._conn.execute("SELECT song_id FROM lyrics")
            return {row["song_id"] for row in cur.fetchall()}
        except Exception:
            return set()

    def save_lyrics_meta(self, song_id: str, lrc_path: str, source: str = "manual", line_count: int = 0):
        self._conn.execute(
            """INSERT OR REPLACE INTO lyrics
               (song_id, lrc_path, source, line_count, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (song_id, lrc_path, source, line_count),
        )
        self._conn.commit()

    def get_lyrics_meta(self, song_id: str) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM lyrics WHERE song_id = ?", (song_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def delete_lyrics_meta(self, song_id: str):
        self._conn.execute("DELETE FROM lyrics WHERE song_id = ?", (song_id,))
        self._conn.commit()

    # ----------------------------------------------------------- cache helpers
    def get_cache_size(self) -> int:
        from src.utils.file_utils import get_thumbnails_dir
        total = 0
        try:
            d = get_thumbnails_dir()
            for root, _, files in os.walk(d):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def clear_cache(self):
        import shutil
        from src.utils.file_utils import get_thumbnails_dir
        try:
            d = get_thumbnails_dir()
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------ sync log
    def log_sync(self, service: str, added: int, updated: int, removed: int,
                 status: str, error: str):
        try:
            self._conn.execute(
                """INSERT INTO sync_log
                   (service, songs_added, songs_updated, songs_removed, status, error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (service, added, updated, removed, status, error),
            )
            self._conn.commit()
        except Exception:
            pass

    def get_last_sync_time(self, service: str = "suno") -> Optional[str]:
        """Return ISO timestamp of last successful sync, or None."""
        val = self.get_setting(f"{service}_last_sync", "")
        return val if val else None

    # ---------------------------------------------------------- image assets
    def save_image(self, img: ImageAsset):
        self._conn.execute(
            """INSERT OR REPLACE INTO image_assets
               (id, title, source, thumbnail_url, full_url, page_url,
                author, width, height, local_path, download_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                img.id, img.title, img.source, img.thumbnail_url, img.full_url,
                img.page_url, img.author, img.width, img.height,
                img.local_path, img.download_status,
            ),
        )
        self._conn.commit()

    def save_images(self, images: List[ImageAsset]):
        for img in images:
            self.save_image(img)

    def get_all_images(self) -> List[ImageAsset]:
        cur = self._conn.execute("SELECT * FROM image_assets ORDER BY added_at DESC")
        return [ImageAsset(**dict(row)) for row in cur.fetchall()]

    # ---------------------------------------------------------- accounts
    def save_account(self, service: str, credentials: str, account_id: str = ""):
        if not account_id:
            account_id = service
        self._conn.execute(
            "INSERT OR REPLACE INTO accounts (id, service, credentials, active) VALUES (?, ?, ?, 1)",
            (account_id, service, credentials),
        )
        self._conn.commit()

    def get_accounts(self) -> List[dict]:
        cur = self._conn.execute("SELECT * FROM accounts")
        return [dict(row) for row in cur.fetchall()]

    def delete_account(self, account_id: str):
        self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self._conn.commit()


storage = Storage()
