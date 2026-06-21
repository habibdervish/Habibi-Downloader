"""Auto-extract the SUNO __client cookie from installed Chromium browsers.

Reads the cookie DB directly — no user action required.
Supports Chrome, Edge, Brave, Vivaldi, Opera GX on Windows.

Encryption handling:
  • Chrome 127+: v20 App-Bound Encryption — CANNOT be decrypted externally.
                 Will be skipped gracefully.
  • Edge / Brave: DPAPI-based v10 AES-256-GCM — readable when browser is closed.
  • Chrome < 127 / other: v10/v11 AES-256-GCM via DPAPI key — readable.

Returns (cookie_value, browser_name) or None.
"""

import os
import json
import sqlite3
import shutil
import tempfile
import base64
import ctypes
from typing import Optional


# ─────────────────────────────────── browser profile locations
_PROFILES = [
    (r"%LOCALAPPDATA%\Microsoft\Edge\User Data",            "Edge"),
    (r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data", "Brave"),
    (r"%LOCALAPPDATA%\Vivaldi\User Data",                   "Vivaldi"),
    (r"%APPDATA%\Opera Software\Opera GX Stable",           "Opera GX"),
    (r"%LOCALAPPDATA%\Google\Chrome\User Data",             "Chrome"),  # tried last; v20 blocks it
]

_PROFILE_DIRS = ("Default", "Profile 1", "Profile 2", "Profile 3")


def _expand(path: str) -> str:
    return os.path.expandvars(path)


# ─────────────────────────────────── DPAPI key extraction
def _load_aes_key(user_data_dir: str) -> Optional[bytes]:
    local_state = os.path.join(user_data_dir, "Local State")
    if not os.path.exists(local_state):
        return None
    try:
        with open(local_state, "r", encoding="utf-8") as f:
            ls = json.load(f)
        b64 = ls["os_crypt"].get("encrypted_key", "")
        if not b64:
            return None
        raw = base64.b64decode(b64)
        if raw[:5] != b"DPAPI":
            # app_bound_encrypted_key only — v20, skip
            return None
        encrypted = raw[5:]
        import win32crypt
        _, key = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
        return key
    except Exception:
        return None


# ─────────────────────────────────── cookie file copy (handles locked files)
def _copy_db(src: str) -> Optional[str]:
    """Copy src to a temp file, trying both shutil and win32file for locked files."""
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(src, tmp)
        return tmp
    except Exception:
        pass
    # Try Windows-level file sharing (bypasses some soft locks)
    try:
        import win32file, win32con
        h = win32file.CreateFile(
            src,
            win32con.GENERIC_READ,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
            None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None
        )
        sz = win32file.GetFileSize(h)
        _, data = win32file.ReadFile(h, sz)
        win32file.CloseHandle(h)
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.write(fd, data)
        os.close(fd)
        return tmp
    except Exception:
        return None


# ─────────────────────────────────── AES-GCM cookie decryption
def _decrypt(encrypted_value: bytes, key: bytes) -> Optional[str]:
    try:
        prefix = encrypted_value[:3]
        if prefix in (b"v10", b"v11"):
            from Crypto.Cipher import AES
            nonce      = encrypted_value[3:15]
            ciphertext = encrypted_value[15:-16]
            tag        = encrypted_value[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        elif prefix == b"v20":
            # Chrome App-Bound Encryption — cannot decrypt externally
            return None
        else:
            import win32crypt
            _, plain = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)
            return plain.decode("utf-8")
    except Exception:
        return None


# ─────────────────────────────────── main extraction function
def extract_suno_cookie() -> Optional[tuple]:
    """
    Scan installed browsers for the SUNO __client cookie.

    Returns (cookie_value: str, browser_name: str) or None.
    Never raises — all errors are swallowed.

    Note: Chrome 127+ uses App-Bound Encryption (v20) which cannot be read
    by external processes. Edge / Brave / Vivaldi use DPAPI (v10) which works
    when the browser is closed (file lock released).
    """
    for raw_dir, browser_name in _PROFILES:
        user_data = _expand(raw_dir)
        if not os.path.isdir(user_data):
            continue

        key = _load_aes_key(user_data)
        if not key:
            # No DPAPI key means v20 or unsupported — skip
            continue

        for profile in _PROFILE_DIRS:
            cookies_db = os.path.join(user_data, profile, "Network", "Cookies")
            if not os.path.exists(cookies_db):
                cookies_db = os.path.join(user_data, profile, "Cookies")
            if not os.path.exists(cookies_db):
                continue

            tmp_path = _copy_db(cookies_db)
            if tmp_path is None:
                continue  # file locked (browser running), skip
            try:
                conn = sqlite3.connect(tmp_path)
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT encrypted_value FROM cookies "
                    "WHERE host_key LIKE '%suno%' AND name = '__client' "
                    "ORDER BY last_access_utc DESC LIMIT 1"
                )
                row = cur.fetchone()
                conn.close()

                if row:
                    val = _decrypt(bytes(row["encrypted_value"]), key)
                    if val:
                        return val, f"{browser_name} ({profile})"
            except Exception:
                pass
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    return None
