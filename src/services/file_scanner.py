"""Standalone file-system scanner & manager engine.

Completely independent of Library, Discovery, SUNO and storage. Provides:
  • drive / volume enumeration (fixed, removable/USB, network, CD-ROM)
  • multi-threaded recursive scanning with pause / resume / cancel
  • per-file metadata records (name, ext, path, size, created, modified, drive)
  • duplicate detection (hash, name, size, date)
  • file operations (move, copy, rename, delete, bulk rename, mkdir, merge, dup)

Designed to stream results so the UI never freezes on huge trees.
"""

import os
import time
import shutil
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, List, Optional


# ───────────────────────────────────────────────────── file categories
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg", ".ico", ".heic"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".aiff", ".alac"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".csv", ".md"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab"}

CATEGORY_EXTS = {
    "images": IMAGE_EXTS,
    "videos": VIDEO_EXTS,
    "audio": AUDIO_EXTS,
    "documents": DOC_EXTS,
    "archives": ARCHIVE_EXTS,
}


@dataclass
class FileRecord:
    path: str
    name: str
    ext: str
    size: int
    created: float
    modified: float
    drive: str
    is_dir: bool = False
    status: str = "Found"

    @property
    def category(self) -> str:
        e = self.ext.lower()
        for cat, exts in CATEGORY_EXTS.items():
            if e in exts:
                return cat
        return "other"


@dataclass
class ScanOptions:
    recursive: bool = True
    include_hidden: bool = False
    include_system: bool = False
    follow_symlinks: bool = False
    include_dirs: bool = False  # also emit folder records


# ───────────────────────────────────────────────────── drives
def _drive_type(root: str) -> str:
    """Return 'fixed' | 'removable' | 'network' | 'cdrom' | 'ramdisk' | 'unknown'."""
    try:
        import ctypes
        t = ctypes.windll.kernel32.GetDriveTypeW(root)
        return {0: "unknown", 1: "unknown", 2: "removable",
                3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}.get(t, "unknown")
    except Exception:
        return "fixed"


def list_drives() -> List[dict]:
    """Enumerate all mounted volumes with type and free/total space."""
    drives = []
    try:
        import string
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        letters = [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if bitmask & (1 << i)]
    except Exception:
        letters = [f"{c}:\\" for c in "CDEFGH" if os.path.exists(f"{c}:\\")]

    for root in letters:
        if not os.path.exists(root):
            continue
        dtype = _drive_type(root)
        total = free = 0
        try:
            usage = shutil.disk_usage(root)
            total, free = usage.total, usage.free
        except Exception:
            pass
        drives.append({
            "root": root,
            "letter": root[0],
            "type": dtype,
            "total": total,
            "free": free,
            "label": _volume_label(root),
        })
    return drives


def _volume_label(root: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), buf, ctypes.sizeof(buf),
            None, None, None, None, 0)
        return buf.value or ""
    except Exception:
        return ""


def _is_hidden_or_system(path: str) -> tuple:
    """(hidden, system) flags via Windows attributes."""
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        if attrs == -1:
            return False, False
        return bool(attrs & 0x2), bool(attrs & 0x4)
    except Exception:
        name = os.path.basename(path)
        return name.startswith("."), False


# ───────────────────────────────────────────────────── scanner
class FileScanner:
    """Multi-threaded, pausable, cancellable file-system walker."""

    def __init__(self):
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False
        self.scanned = 0
        self.matched = 0

    # -- control -------------------------------------------------------
    def is_running(self) -> bool:
        return self.running

    def is_paused(self) -> bool:
        return self._pause.is_set()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def cancel(self):
        self._cancel.set()
        self._pause.clear()

    def _wait_if_paused(self):
        while self._pause.is_set() and not self._cancel.is_set():
            time.sleep(0.05)

    # -- scan ----------------------------------------------------------
    def scan(
        self,
        roots: Iterable[str],
        options: ScanOptions,
        on_batch: Callable[[List[FileRecord]], None],
        on_progress: Callable[[int, int, str], None],
        on_done: Callable[[int, int, bool], None],
    ):
        """Start a background scan. Callbacks fire from the worker thread —
        marshal to the UI thread inside them."""
        self._cancel.clear()
        self._pause.clear()
        self.scanned = 0
        self.matched = 0
        self.running = True
        self._thread = threading.Thread(
            target=self._worker,
            args=(list(roots), options, on_batch, on_progress, on_done),
            daemon=True,
        )
        self._thread.start()

    def _worker(self, roots, options, on_batch, on_progress, on_done):
        batch: List[FileRecord] = []
        BATCH = 200
        last_emit = 0.0
        try:
            for root in roots:
                if self._cancel.is_set():
                    break
                self._scan_tree(root, options, batch, on_batch, on_progress)
                if self._cancel.is_set():
                    break

            # flush remaining
            if batch and not self._cancel.is_set():
                on_batch(list(batch))
        finally:
            self.running = False
            on_done(self.scanned, self.matched, self._cancel.is_set())

    def _scan_tree(self, root, options, batch, on_batch, on_progress):
        drive = os.path.splitdrive(root)[0] or root[:2]
        stack = [root]
        last_emit = 0.0

        while stack:
            if self._cancel.is_set():
                return
            self._wait_if_paused()
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except (PermissionError, FileNotFoundError, OSError):
                continue

            for entry in entries:
                if self._cancel.is_set():
                    return
                self._wait_if_paused()
                try:
                    is_dir = entry.is_dir(follow_symlinks=options.follow_symlinks)
                    is_link = entry.is_symlink()
                except OSError:
                    continue

                if is_link and not options.follow_symlinks:
                    # still record the link as a file-ish entry, don't traverse
                    pass

                # attribute filtering
                if not (options.include_hidden and options.include_system):
                    hidden, system = _is_hidden_or_system(entry.path)
                    if hidden and not options.include_hidden:
                        continue
                    if system and not options.include_system:
                        continue

                self.scanned += 1

                if is_dir:
                    if options.include_dirs:
                        rec = self._make_record(entry, drive, is_dir=True)
                        if rec:
                            batch.append(rec)
                            self.matched += 1
                    if options.recursive and not (is_link and not options.follow_symlinks):
                        stack.append(entry.path)
                else:
                    rec = self._make_record(entry, drive, is_dir=False)
                    if rec:
                        batch.append(rec)
                        self.matched += 1

                # emit batches
                if len(batch) >= 200:
                    on_batch(list(batch))
                    batch.clear()

                now = time.time()
                if now - last_emit > 0.1:
                    on_progress(self.scanned, self.matched, current)
                    last_emit = now

    def _make_record(self, entry, drive, is_dir) -> Optional[FileRecord]:
        try:
            st = entry.stat(follow_symlinks=False)
            name = entry.name
            ext = "" if is_dir else os.path.splitext(name)[1]
            return FileRecord(
                path=entry.path,
                name=name,
                ext=ext,
                size=0 if is_dir else st.st_size,
                created=getattr(st, "st_ctime", 0),
                modified=getattr(st, "st_mtime", 0),
                drive=drive,
                is_dir=is_dir,
            )
        except OSError:
            return None


# ───────────────────────────────────────────────────── duplicate detection
def _file_hash(path: str, partial: bool = True, chunk: int = 1 << 20) -> str:
    """MD5 of file. If partial, hash first + last 1 MiB only (fast for big files)."""
    h = hashlib.md5()
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if partial and size > 2 * chunk:
                h.update(f.read(chunk))
                f.seek(-chunk, os.SEEK_END)
                h.update(f.read(chunk))
                h.update(str(size).encode())
            else:
                while True:
                    b = f.read(chunk)
                    if not b:
                        break
                    h.update(b)
        return h.hexdigest()
    except OSError:
        return ""


def find_duplicates(records: List[FileRecord], method: str = "hash",
                    on_progress: Optional[Callable[[int, int], None]] = None) -> List[List[FileRecord]]:
    """Group records that are duplicates of each other. method:
    'hash' | 'filename' | 'size' | 'date'. Returns list of groups (len >= 2)."""
    files = [r for r in records if not r.is_dir]
    groups: dict = {}

    if method == "filename":
        for r in files:
            groups.setdefault(r.name.lower(), []).append(r)
    elif method == "size":
        for r in files:
            groups.setdefault(r.size, []).append(r)
    elif method == "date":
        for r in files:
            groups.setdefault(int(r.modified), []).append(r)
    else:  # hash — pre-bucket by size, then hash only same-size candidates
        by_size: dict = {}
        for r in files:
            by_size.setdefault(r.size, []).append(r)
        candidates = [r for grp in by_size.values() if len(grp) > 1 for r in grp]
        total = len(candidates)
        for i, r in enumerate(candidates):
            if on_progress and i % 25 == 0:
                on_progress(i, total)
            digest = _file_hash(r.path)
            if digest:
                groups.setdefault(digest, []).append(r)

    return [grp for grp in groups.values() if len(grp) > 1]


# ───────────────────────────────────────────────────── file operations
def move_file(src: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    target = _unique_path(os.path.join(dest_dir, os.path.basename(src)))
    shutil.move(src, target)
    return target


def copy_file(src: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    target = _unique_path(os.path.join(dest_dir, os.path.basename(src)))
    if os.path.isdir(src):
        shutil.copytree(src, target)
    else:
        shutil.copy2(src, target)
    return target


def rename_path(src: str, new_name: str) -> str:
    target = os.path.join(os.path.dirname(src), new_name)
    os.rename(src, target)
    return target


def delete_path(path: str, to_trash: bool = True) -> bool:
    if to_trash:
        try:
            from send2trash import send2trash
            send2trash(path)
            return True
        except Exception:
            pass
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    except OSError:
        return False


def create_folder(parent: str, name: str) -> str:
    target = _unique_path(os.path.join(parent, name))
    os.makedirs(target, exist_ok=True)
    return target


def duplicate_path(src: str) -> str:
    base, ext = os.path.splitext(src)
    target = _unique_path(f"{base} - Copy{ext}")
    if os.path.isdir(src):
        shutil.copytree(src, target)
    else:
        shutil.copy2(src, target)
    return target


def merge_folders(src: str, dest: str) -> int:
    """Move every file from src into dest (recursively), return count moved."""
    moved = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out = os.path.join(dest, rel) if rel != "." else dest
        os.makedirs(out, exist_ok=True)
        for f in files:
            try:
                shutil.move(os.path.join(root, f), _unique_path(os.path.join(out, f)))
                moved += 1
            except OSError:
                pass
    try:
        shutil.rmtree(src)
    except OSError:
        pass
    return moved


def bulk_rename(paths: List[str], pattern: str, start: int = 1) -> List[str]:
    """Rename files using {n} (index), {name} (orig stem), {ext} tokens."""
    out = []
    for i, p in enumerate(paths, start):
        stem, ext = os.path.splitext(os.path.basename(p))
        new = (pattern
               .replace("{n}", str(i))
               .replace("{name}", stem)
               .replace("{ext}", ext.lstrip(".")))
        if not os.path.splitext(new)[1] and ext:
            new += ext
        try:
            out.append(rename_path(p, new))
        except OSError:
            out.append(p)
    return out


def open_in_explorer(path: str):
    """Open the containing folder and select the file."""
    try:
        if os.path.isdir(path):
            os.startfile(path)  # noqa
        else:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except Exception:
        try:
            os.startfile(os.path.dirname(path))  # noqa
        except Exception:
            pass


def open_default(path: str):
    try:
        os.startfile(path)  # noqa
    except Exception:
        pass


def open_with(path: str, app_path: str):
    try:
        import subprocess
        subprocess.Popen([app_path, path])
    except Exception:
        pass


def _unique_path(path: str) -> str:
    """Avoid clobbering: foo.txt → foo (1).txt if it exists."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


# ───────────────────────────────────────────────────── formatting helpers
def fmt_size(n: int) -> str:
    if n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_date(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


# Module-level singleton scanner (one active scan at a time)
scanner = FileScanner()
