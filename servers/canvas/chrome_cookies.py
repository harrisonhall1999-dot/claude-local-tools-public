"""Read one site's cookies from Chrome on this Mac, so the canvas tools can use the Canvas session
you're already signed in to (for schools that block student access tokens).

Only cookies for the Canvas host (and its parent domains, as Chrome itself would send) are
read and decrypted; nothing is written to disk. The first run triggers a macOS prompt for
"Chrome Safe Storage": choose Always Allow so scheduled syncs don't stall.
Chrome on macOS: AES-128-CBC, key = PBKDF2-SHA1(Keychain password, "saltysalt", 1003), values
prefixed "v10"; from cookie DB version 24 the plaintext starts with SHA-256(host_key).
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

CHROME_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
_key_cache: dict[str, bytes] = {}
best_profile_holder = [""]  # profile the last read() used


class ChromeCookieError(RuntimeError):
    pass


def _key(password: bytes | None = None) -> bytes:
    if "k" in _key_cache and password is None:
        return _key_cache["k"]
    if password is None:
        p = subprocess.run(["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise ChromeCookieError("macOS didn't release Chrome's cookie key (Keychain prompt denied "
                                    "or Chrome not installed). Run `canvas-auth --chrome` and choose Always Allow.")
        password = p.stdout.strip().encode()
    k = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
    _key_cache["k"] = k
    return k


def _decrypt(enc: bytes, key: bytes, host_key: str, db_version: int) -> str:
    from Crypto.Cipher import AES

    if enc[:3] not in (b"v10", b"v11"):
        return enc.decode("utf-8", "replace")
    raw = AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(enc[3:])
    raw = raw[: -raw[-1]] if raw and 1 <= raw[-1] <= 16 else raw
    if db_version >= 24 and raw[:32] == hashlib.sha256(host_key.encode()).digest():
        raw = raw[32:]
    return raw.decode("utf-8", "replace")


def profiles() -> list[str]:
    found = [os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(CHROME_DIR, "*", "Cookies"))]
    return sorted(found, key=lambda n: (n != "Default", n))


def _matches(host: str, host_key: str) -> bool:
    hk = host_key.lower()
    return host == hk or (hk.startswith(".") and (host == hk[1:] or host.endswith(hk)))


SESSION_NAMES = ("canvas_session", "_legacy_normandy_session", "_normandy_session")


def _signed_in(jar: dict) -> bool:
    return any(n in jar for n in SESSION_NAMES)


def read(host: str, profile: str = "", cookies_db: str = "", password: bytes | None = None) -> dict[str, str]:
    """{name: value} of unexpired cookies Chrome would send to https://host/. Without a profile,
    uses the first Chrome profile that holds a Canvas session cookie."""
    host = host.lower().split(":")[0]
    dbs = [cookies_db] if cookies_db else [os.path.join(CHROME_DIR, p, "Cookies") for p in ([profile] if profile else profiles())]
    best: dict[str, str] = {}
    best_profile = ""
    for path in dbs:
        if not os.path.exists(path):
            continue
        tmpdir = tempfile.mkdtemp(prefix="cc-")
        os.chmod(tmpdir, 0o700)
        try:
            copy = os.path.join(tmpdir, "Cookies")
            shutil.copy2(path, copy)  # Chrome keeps the live file locked
            for side in ("-wal", "-journal"):
                if os.path.exists(path + side):
                    shutil.copy2(path + side, copy + side)
            con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
            try:
                ver = int((con.execute("SELECT value FROM meta WHERE key='version'").fetchone() or [0])[0])
            except sqlite3.Error:
                ver = 0
            parts = host.split(".")
            cands = {host} | {"." + ".".join(parts[i:]) for i in range(len(parts) - 1)}
            q = ("SELECT host_key, name, value, encrypted_value, expires_utc FROM cookies WHERE host_key IN (%s) "
                 "ORDER BY length(host_key)" % ",".join("?" * len(cands)))
            # expires_utc: microseconds since 1601; 0 = session cookie
            now = int((time.time() + 11644473600) * 1_000_000)
            jar = {}
            for hk, name, value, enc, exp in con.execute(q, sorted(cands)):
                if exp and exp < now or not _matches(host, hk):
                    continue
                jar[name] = value or (_decrypt(enc, _key(password), hk, ver) if enc else "")
            con.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        if _signed_in(jar) or (jar and not best):
            best, best_profile = jar, os.path.basename(os.path.dirname(path))
            if _signed_in(jar):
                break
    if not _signed_in(best):
        raise ChromeCookieError(f"Chrome isn't signed in to {host}. Open https://{host} in Chrome, sign in, then retry.")
    best_profile_holder[0] = best_profile
    return best


def header(host: str, profile: str = "") -> str:
    return "; ".join(f"{k}={v}" for k, v in read(host, profile).items())
