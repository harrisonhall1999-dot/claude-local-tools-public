"""Minimal read-only Canvas LMS REST client (GET only).

Auth is a personal access token (Bearer) or, where a school blocks student tokens, the browser's
Canvas session cookie. Pagination follows the Link header; throttling (429, or Canvas's
"403 Rate Limit Exceeded") and 5xx responses are retried with backoff. Ideas taken from
vishalsachdev/canvas-mcp and DMontgomery40/mcp-canvas-lms; no code copied.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import urljoin, urlparse

import httpx

MAX_RETRIES = 4
MAX_PAGES = 200
UA = "claude-local-tools-canvas/1.0"


class CanvasError(RuntimeError):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class CanvasAuthError(CanvasError):
    pass


def normalize_base(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1"):
        return f"http://{p.netloc}"  # local test server only
    if p.scheme != "https" or not p.netloc:
        raise ValueError(f"not an https Canvas address: {url}")
    return f"https://{p.netloc}"


class Canvas:
    def __init__(self, base_url: str, token: str = "", cookie: str = "", timeout: float = 30):
        self.base = normalize_base(base_url)
        self.host = urlparse(self.base).netloc
        headers = {"User-Agent": UA, "Accept": "application/json+canvas-string-ids"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif cookie:
            headers["Cookie"] = cookie
        else:
            raise CanvasAuthError("no token or cookie")
        # Redirects are followed by hand so credentials never leave the Canvas host.
        self.http = httpx.Client(headers=headers, timeout=timeout, follow_redirects=False)
        self.bare = httpx.Client(headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True)

    def close(self):
        self.http.close()
        self.bare.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # --- requests ---------------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            if urlparse(path).netloc != self.host:
                raise CanvasError(f"refusing to send Canvas credentials to {urlparse(path).netloc}")
            return path
        if not path.startswith("/api/"):
            path = "/api/v1/" + path.lstrip("/")
        return self.base + path

    def _send(self, url: str, params=None) -> httpx.Response:
        delay = 2.0
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.http.get(url, params=params)
            except httpx.TransportError as e:
                if attempt == MAX_RETRIES:
                    raise CanvasError(f"network error: {e}") from e
                time.sleep(delay)
                delay *= 2
                continue
            throttled = r.status_code == 429 or (r.status_code == 403 and "rate limit" in r.text[:300].lower())
            if (throttled or r.status_code >= 500) and attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
                continue
            return r
        return r  # pragma: no cover

    @staticmethod
    def _check(r: httpx.Response, url: str) -> None:
        if r.status_code < 300:
            return
        path = urlparse(url).path
        if r.status_code == 401:
            if "www-authenticate" in {k.lower() for k in r.headers} or "unauthenticated" in r.text[:400]:
                raise CanvasAuthError("Canvas rejected the sign-in (token expired or revoked)", 401)
            raise CanvasError(f"not available to you: {path} (401; the course may hide this section)", 401)
        if r.status_code in (403, 404):
            raise CanvasError(f"not available to you: {path} ({r.status_code})", r.status_code)
        if 300 <= r.status_code < 400:
            loc = r.headers.get("location", "")
            if "/login" in loc:
                raise CanvasAuthError("Canvas session expired (redirected to login)", 401)
            raise CanvasError(f"unexpected redirect from {path} to {loc[:120]}", r.status_code)
        raise CanvasError(f"HTTP {r.status_code} from {path}", r.status_code)

    def get(self, path: str, params=None):
        url = self._url(path)
        r = self._send(url, params)
        self._check(r, url)
        return r.json()

    def get_any(self, path: str, params=None, limit: int = 200):
        """GET that returns a dict as-is, or a list with its later pages followed (up to limit)."""
        url = self._url(path)
        params = dict(params or {})
        params.setdefault("per_page", 100)
        r = self._send(url, params)
        self._check(r, url)
        data = r.json()
        nxt = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("link", ""))
        if not isinstance(data, list) or not nxt or len(data) >= limit:
            return data[:limit] if isinstance(data, list) else data
        return data + self.paginate(nxt.group(1), None, limit - len(data))

    def paginate(self, path: str, params=None, limit: int = 0) -> list:
        url, out = self._url(path), []
        if "?" in url:
            params = None  # a next-page URL already carries its query; httpx params would replace it
        else:
            params = dict(params or {})
            params.setdefault("per_page", 100)
        for _ in range(MAX_PAGES):
            r = self._send(url, params)
            self._check(r, url)
            data = r.json()
            # A few endpoints wrap the list in an object.
            out.extend(data if isinstance(data, list) else next(
                (v for v in data.values() if isinstance(v, list)), [data]))
            if limit and len(out) >= limit:
                return out[:limit]
            nxt = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("link", ""))
            if not nxt:
                return out
            url, params = self._url(nxt.group(1)), None  # next URL carries the query
        return out

    def download(self, url: str, dest: str, max_bytes: int = 0) -> int:
        """Stream a file (Canvas file `url`, which redirects to storage) to dest. Returns bytes."""
        hops = 0
        while True:
            same_host = urlparse(url).netloc == self.host
            client = self.http if same_host else self.bare
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and hops < 6:
                    url, hops = urljoin(url, r.headers["location"]), hops + 1
                    continue
                self._check(r, url)
                n, tmp = 0, dest + ".part"
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        n += len(chunk)
                        if max_bytes and n > max_bytes:
                            f.close()
                            os.remove(tmp)
                            raise CanvasError(f"file larger than {max_bytes // 1_000_000} MB, skipped")
                        f.write(chunk)
                os.replace(tmp, dest)
                return n
