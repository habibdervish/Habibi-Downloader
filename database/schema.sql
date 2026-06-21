CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT DEFAULT 'Unknown Artist',
    album TEXT DEFAULT '',
    duration REAL DEFAULT 0.0,
    file_path TEXT,
    thumbnail_path TEXT,
    source TEXT DEFAULT 'local',
    source_url TEXT DEFAULT '',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_favorite INTEGER DEFAULT 0,
    download_status TEXT DEFAULT 'none',
    -- SUNO-specific columns (added via ALTER TABLE migration for existing DBs)
    suno_id TEXT DEFAULT '',
    prompt TEXT DEFAULT '',
    style TEXT DEFAULT '',
    model_version TEXT DEFAULT '',
    audio_url TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    lyrics_text TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL DEFAULT 'suno',
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    songs_added INTEGER DEFAULT 0,
    songs_updated INTEGER DEFAULT 0,
    songs_removed INTEGER DEFAULT 0,
    status TEXT DEFAULT 'success',
    error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    song_id TEXT REFERENCES songs(id),
    url TEXT NOT NULL,
    status TEXT DEFAULT 'queued',
    progress REAL DEFAULT 0.0,
    speed TEXT DEFAULT '',
    eta TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    file_path TEXT,
    error TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS image_assets (
    id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    source TEXT DEFAULT '',
    thumbnail_url TEXT DEFAULT '',
    full_url TEXT DEFAULT '',
    page_url TEXT DEFAULT '',
    author TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    local_path TEXT,
    download_status TEXT DEFAULT 'none',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    credentials TEXT DEFAULT '',
    active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lyrics (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    lrc_path TEXT,
    source TEXT DEFAULT 'manual',
    offset REAL DEFAULT 0.0,
    line_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_songs_title    ON songs(title);
CREATE INDEX IF NOT EXISTS idx_songs_artist   ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_songs_source   ON songs(source);
-- idx_songs_suno_id is created by _migrate_db() AFTER the suno_id column is
-- added, so it must NOT be here: on pre-existing DBs the songs table already
-- exists without suno_id, and this index would fail during _init_db().
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
