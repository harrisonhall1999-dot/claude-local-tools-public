"""Catch-all media downloader behind the files server's fetch_media tool and
the fetch-media command.

Routes a link to whichever tool can handle it:
- a direct file link (an .mp3, .mp4, .pdf, image, zip...) -> plain HTTP download
- a page with video or audio (YouTube, Vimeo, podcasts, news sites, embedded
  HLS players; ~1,800 sites) -> yt-dlp
- an image post or gallery (Instagram, X, Reddit, Imgur, Flickr...) -> gallery-dl
It can also pull just the captions as a clean transcript, or just describe
what's at the link without downloading anything.
"""

import json
import logging
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse

import httpx

# Homebrew tools aren't always on PATH for processes Claude spawns.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

logging.getLogger("httpx").setLevel(logging.WARNING)

KINDS = ("auto", "audio", "video", "images", "file", "subtitles", "info")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
TIMEOUT = 3600
MAX_LISTED = 25
UPDATE_HINT = " (sites change often; if this worked before, try `brew upgrade yt-dlp gallery-dl`)"
MAX_VIDEO_CHOICES = 8
# Left behind by an interrupted yt-dlp / gallery-dl / direct download.
PARTIAL = re.compile(r"(\.part|\.ytdl|\.part-Frag\d+(\.part)?|\.temp\.\w+|^\.fetch-media\.part)$")


def _size(path):
    try:
        return _size_n(os.path.getsize(path))
    except OSError:
        return "?"


def _size_n(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _report(files, out_dir, note=""):
    files = [f for f in dict.fromkeys(files) if f and os.path.isfile(f)]
    if not files:
        return "Error: nothing was downloaded"
    if len(files) == 1:
        return f"Downloaded {files[0]} ({_size(files[0])}){note}"
    lines = [f"Downloaded {len(files)} files to {out_dir}{note}:"]
    lines += [f"- {os.path.basename(f)} ({_size(f)})" for f in files[:MAX_LISTED]]
    if len(files) > MAX_LISTED:
        lines.append(f"- ... and {len(files) - MAX_LISTED} more")
    return "\n".join(lines)


def _hint(text):
    return "" if "unsupported url" in (text or "").lower() else UPDATE_HINT


def _clean_error(line):
    """'ERROR: [youtube] jNQXAC9IVRw: Video unavailable' -> 'Video unavailable (youtube)'."""
    line = re.sub(r"^\[gallery-dl\]\[error\]\s*", "", line.strip())
    # The "<video id>: " after [site] is noise; without a [site] there's no id to strip.
    m = re.match(r"^ERROR:\s*(?:\[([^\]]+)\]\s*(?:[\w-]{4,40}:\s+)?)?(.*)$", line)
    if not m:
        return line
    site, msg = m.group(1), m.group(2).strip()
    msg = re.sub(r"\s*See\s+https?://\S+.*$", "", msg)  # drop yt-dlp's FAQ links
    return f"{msg} ({site})" if site and site.lower() not in msg.lower() else msg


def _last_error(p):
    text = (p.stderr or p.stdout or "").strip() if not isinstance(p, str) else p.strip()
    lines = text.splitlines()
    errs = [l for l in lines if l.startswith("ERROR:") or "[error]" in l] or \
           [l for l in lines if "error" in l.lower()]
    code = getattr(p, "returncode", "?")
    return _clean_error((errs or lines or [f"exit {code}"])[-1])


def _cleanup_partials(out_dir, since):
    """Remove half-written files from a cancelled or timed-out download."""
    removed = 0
    for root, _, names in os.walk(out_dir):
        if root.count(os.sep) - out_dir.count(os.sep) > 2:
            continue
        for n in names:
            path = os.path.join(root, n)
            try:
                if PARTIAL.search(n) and os.path.getmtime(path) >= since - 1:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    return removed


# --- direct files -----------------------------------------------------------

def _is_page(content_type):
    ct = content_type.split(";")[0].strip().lower()
    return ct in ("", "text/html", "application/xhtml+xml") or ct.startswith("text/html")


def _filename(resp, url):
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    name = urllib.parse.unquote(m.group(1).strip()) if m else ""
    if not name:
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(str(resp.url)).path))
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", name).strip(". ") or "download"
    if not os.path.splitext(name)[1]:
        ext = mimetypes.guess_extension(resp.headers.get("content-type", "").split(";")[0].strip())
        name += ext or ""
    return name[:200]


def _unique(path):
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base} ({n}){ext}"
        n += 1
    return path


def _probe(url):
    """Open the URL and return (client, response) with the body unread."""
    client = httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": UA})
    try:
        resp = client.send(client.build_request("GET", url), stream=True)
    except Exception:
        client.close()
        raise
    return client, resp


def _save_stream(client, resp, out_dir, progress=False):
    try:
        if resp.status_code >= 400:
            return f"Error: HTTP {resp.status_code} for {resp.url}"
        path = _unique(os.path.join(out_dir, _filename(resp, resp.url)))
        tmp = path + ".part"
        total = int(resp.headers.get("content-length") or 0)
        done, shown = 0, 0.0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress and time.time() - shown > 0.3:
                    shown = time.time()
                    pct = f"{done / total:6.1%} of {_size_n(total)}" if total else _size_n(done)
                    print(f"\r[download] {pct}", end="", file=sys.stderr, flush=True)
        if progress:
            print(file=sys.stderr)
        os.replace(tmp, path)
        return _report([path], out_dir)
    finally:
        resp.close()
        client.close()


def _direct(url, out_dir, progress=False):
    try:
        client, resp = _probe(url)
    except Exception as e:
        return f"Error: could not open {url}: {e}"
    return _save_stream(client, resp, out_dir, progress)


# --- yt-dlp -----------------------------------------------------------------

def _ytdlp_base(cookies_from_browser, playlist, max_items, progress=False):
    # No --user-agent: yt-dlp sends per-site client headers (YouTube's app
    # clients among them), and a forced browser UA can break those.
    cmd = ["yt-dlp", "--no-warnings"] + ([] if progress else ["--no-progress"])
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    if playlist:
        cmd += ["--yes-playlist", "--playlist-items", f"1:{max_items}"]
    else:
        cmd += ["--no-playlist"]
    return cmd


def _template(out_dir, playlist):
    if playlist:
        return os.path.join(out_dir, "%(playlist_title,playlist_id|Playlist).100B",
                            "%(playlist_index&{:03d} |)s%(title).120B [%(id)s].%(ext)s")
    return os.path.join(out_dir, "%(title).150B [%(id)s].%(ext)s")


def _ytdlp_media(url, kind, out_dir, playlist, max_items, max_height, cookies,
                 progress=False, info_json="", audio_format="m4a"):
    cmd = _ytdlp_base(cookies, playlist, max_items, progress)
    with tempfile.TemporaryDirectory() as tmp:
        paths = os.path.join(tmp, "paths.txt")
        # --print would silence yt-dlp's progress output; --print-to-file doesn't.
        cmd += (["--print-to-file", "after_move:filepath", paths] if progress
                else ["--print", "after_move:filepath"])
        cmd += ["-o", _template(out_dir, playlist)]
        if kind == "audio":
            cmd += ["-f", "bestaudio/best", "--extract-audio", "--audio-format", audio_format]
            if audio_format == "mp3":
                cmd += ["--audio-quality", "0"]
        else:
            sort = "ext:mp4:m4a" if not max_height else f"res:{max_height},ext:mp4:m4a"
            cmd += ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4"]
        # Reusing a probe's metadata skips a second extraction, so it starts sooner.
        cmd += ["--load-info-json", info_json] if info_json and os.path.isfile(info_json) else [url]
        if progress:
            p = subprocess.run(cmd, stdout=None, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT)
            out = open(paths, encoding="utf-8").read() if os.path.isfile(paths) else ""
        else:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
            out = p.stdout
    files = [l.strip() for l in out.splitlines() if l.strip()]
    if p.returncode != 0 and not files:
        return None, _last_error(p)
    note = f" (some items failed: {_last_error(p)})" if p.returncode != 0 else ""
    return _report(files, out_dir if not playlist or not files else os.path.dirname(files[0]), note), None


def _vtt_to_text(vtt_path):
    """Captions -> one '[mm:ss] text' line per cue, dropping auto-caption repeats."""
    out, seen, stamp, cue = [], set(), "", []

    def flush():
        if cue:
            out.append(f"[{stamp}] {' '.join(cue)}")
            cue.clear()

    with open(vtt_path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            m = re.match(r"(?:(\d+):)?(\d{2}):(\d{2})[.,]\d{3}\s+-->", line)
            if m:
                flush()
                h, mnt, sec = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
                stamp = f"{h}:{mnt:02d}:{sec:02d}" if h else f"{mnt:02d}:{sec:02d}"
                continue
            if not line or line == "WEBVTT" or line.isdigit() or re.match(r"(Kind|Language|NOTE|STYLE)\b", line):
                continue
            text = re.sub(r"<[^>]+>", "", line)
            text = text.replace("&nbsp;", " ").replace("&amp;", "&").strip()
            if text and text not in seen:
                seen.add(text)
                cue.append(text)
    flush()
    return "\n".join(out) + "\n"


def _subtitles(url, out_dir, language, playlist, max_items, cookies, info_json=""):
    cmd = _ytdlp_base(cookies, playlist, max_items)
    cmd += ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", f"{language},{language}-orig,{language}-[A-Z]{{2}}",
            "--ignore-errors",
            "--sub-format", "vtt/best", "--convert-subs", "vtt",
            "--print", "after_video:%(id)s", "-o", _template(out_dir, playlist)]
    cmd += ["--load-info-json", info_json] if info_json and os.path.isfile(info_json) else [url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    ids = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    if not ids:
        return f"Error: yt-dlp: {_last_error(p)}{_hint(p.stderr)}"
    texts = []
    for root, _, names in os.walk(out_dir):
        for vid in ids:
            vtts = sorted((n for n in names if f"[{vid}]." in n and n.endswith(".vtt")),
                          key=lambda n: (not n.endswith(f".{language}.vtt"), "-orig" not in n, n))
            if not vtts:
                continue
            keep = os.path.join(root, vtts[0])
            txt = _unique(re.sub(r"\.[^.]+\.vtt$", ".txt", keep))
            with open(txt, "w", encoding="utf-8") as f:
                f.write(_vtt_to_text(keep))
            texts.append(txt)
            for n in vtts:
                os.remove(os.path.join(root, n))
    if not texts:
        return (f"Error: no '{language}' captions at this link. Download the audio "
                "(kind=\"audio\") and run transcribe instead.")
    missing = len(ids) - len(texts)
    note = f" ({missing} item(s) had no '{language}' captions)" if missing > 0 else ""
    return _report(texts, out_dir, note).replace("Downloaded", "Saved captions as text:", 1)


def probe(url, playlist=False, cookies=""):
    """yt-dlp's metadata for a link: (info dict, path of the saved JSON, error).
    The JSON can be passed back as info_json so the download skips re-extraction."""
    cmd = _ytdlp_base(cookies, playlist, 1000) + ["-J", "--flat-playlist", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        return None, "", _last_error(p)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return None, "", "yt-dlp returned no metadata"
    fd, path = tempfile.mkstemp(prefix="fetch-media-info-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(p.stdout)
    return d, path, None


def _fmt_size(f, duration=0):
    """Bytes: yt-dlp's size, else bitrate (kbit/s) x duration (streamed formats list none)."""
    size = f.get("filesize") or f.get("filesize_approx") or 0
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return int(size)


def format_choices(d):
    """Resolutions (best first) with estimated sizes, then audio-only, as dicts:
    {"label", "kind", "height", "size"}. Sizes are yt-dlp's estimates."""
    fmts = d.get("formats") or []
    dur = d.get("duration") or 0
    audio = [f for f in fmts if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
    best_audio = max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)
    audio_size = _fmt_size(best_audio, dur) if best_audio else 0
    videos = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("height")]
    choices = []
    for h in sorted({f["height"] for f in videos}, reverse=True)[:MAX_VIDEO_CHOICES]:
        cands = [f for f in videos if f["height"] == h]
        best = max(cands, key=lambda f: (f.get("ext") == "mp4", (f.get("vcodec") or "").startswith("avc"), f.get("tbr") or 0))
        muxed = best.get("acodec") not in (None, "none")
        size = _fmt_size(best, dur) + (0 if muxed else audio_size)
        choices.append({"label": f"{h}p video (mp4)", "kind": "video", "height": h, "size": size})
    if not choices and any(f.get("vcodec") not in (None, "none") for f in fmts):
        choices.append({"label": "video, best available (mp4)", "kind": "video", "height": 0, "size": 0})
    if audio:
        choices.append({"label": "audio only (m4a)", "kind": "audio", "height": 0, "size": audio_size})
    return choices


def _ytdlp_info(url, playlist, cookies):
    d, path, err = probe(url, playlist, cookies)
    if err:
        return None, err
    try:
        os.remove(path)
    except OSError:
        pass
    lines = [f"Site: {d.get('extractor_key') or d.get('extractor')}",
             f"Title: {d.get('title')}"]
    if d.get("_type") == "playlist":
        entries = d.get("entries") or []
        lines.append(f"Playlist: {len(entries)} items (download with playlist=True; max_items caps it)")
        lines += [f"  {i + 1}. {e.get('title')}" + (f" ({_dur(e.get('duration'))})" if e.get("duration") else "")
                  for i, e in enumerate(entries[:10])]
        if len(entries) > 10:
            lines.append(f"  ... and {len(entries) - 10} more")
        return "\n".join(lines), None
    for label, key in (("By", "uploader"), ("Date", "upload_date")):
        if d.get(key):
            lines.append(f"{label}: {d[key]}")
    if d.get("duration"):
        lines.append(f"Duration: {_dur(d['duration'])}")
    if d.get("is_live"):
        lines.append("Live stream: yes (downloading records until it ends or times out)")
    choices = format_choices(d)
    if choices:
        lines.append("Formats (max_height picks one; sizes are estimates):")
        lines += [f"  {c['label']}" + (f", ~{_size_n(c['size'])}" if c["size"] else "") for c in choices]
    else:
        lines.append("Media: unknown")
    subs, auto = sorted(d.get("subtitles") or {}), sorted(d.get("automatic_captions") or {})
    subs = [s for s in subs if s != "live_chat"]
    if subs or auto:
        en = any(s.startswith("en") for s in subs + auto)
        lines.append(f"Captions: {len(subs)} manual, {len(auto)} auto languages"
                     + ("; English available (kind=\"subtitles\" gets a transcript without Whisper)" if en else ""))
    else:
        lines.append("Captions: none")
    return "\n".join(lines), None


def _dur(sec):
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --- gallery-dl ---------------------------------------------------------------

def _gallery(url, out_dir, max_items, cookies, simulate=False):
    folder = os.path.join(out_dir, re.sub(r"[^\w.-]+", "_", urllib.parse.urlparse(url).netloc + urllib.parse.urlparse(url).path).strip("_")[:100] or "gallery")
    cmd = ["gallery-dl", "--range", f"1-{max_items}"]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd += ["-g"] if simulate else ["-D", folder]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    if simulate:
        if p.returncode != 0 and not lines:
            return None, _last_error(p)
        return f"Images/gallery: {len(lines)} file(s) (kind=\"images\" downloads them)", None
    # Prints each saved path; "# path" means it was already there.
    files = [l[2:] if l.startswith("# ") else l for l in lines]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        return None, _last_error(p) if p.returncode != 0 else "no images found"
    if len(files) == 1 and os.path.dirname(files[0]) == folder:
        tmp = os.path.join(out_dir, ".fetch-media.part")
        os.replace(files[0], tmp)
        if not os.listdir(folder):
            os.rmdir(folder)
        one = _unique(os.path.join(out_dir, os.path.basename(files[0])))
        os.replace(tmp, one)
        files = [one]
    return _report(files, folder), None


# --- entry point --------------------------------------------------------------

def fetch(url, kind="auto", output_dir="", playlist=False, max_items=50, max_height=0,
          language="en", cookies_from_browser="", progress=False, info_json="", audio_format="m4a"):
    """See the fetch_media tool docstring in server.py. progress shows yt-dlp's
    progress in the terminal (the fetch-media command); info_json reuses a
    probe() result; audio_format is m4a (default) or mp3."""
    url = (url or "").strip()
    if not re.match(r"https?://", url):
        return "Error: url must start with http:// or https://"
    if kind not in KINDS:
        return f"Error: unknown kind '{kind}' (use: {', '.join(KINDS)})"
    out_dir = os.path.expanduser(output_dir) if output_dir else os.path.expanduser("~/Downloads")
    os.makedirs(out_dir, exist_ok=True)
    max_items = max(1, int(max_items or 50))
    cookies = (cookies_from_browser or "").strip()
    audio_format = audio_format if audio_format in ("m4a", "mp3") else "m4a"
    started = time.time()

    try:
        if kind == "file":
            return _direct(url, out_dir, progress)
        if kind == "subtitles":
            return _subtitles(url, out_dir, language or "en", playlist, max_items, cookies, info_json)
        if kind == "images":
            res, err = _gallery(url, out_dir, max_items, cookies)
            return res or f"Error: gallery-dl: {err}{_hint(err)}"
        if kind in ("audio", "video"):
            res, err = _ytdlp_media(url, kind, out_dir, playlist, max_items, max_height, cookies,
                                    progress, info_json, audio_format)
            return res or f"Error: yt-dlp: {err}{_hint(err)}"

        # auto / info: a direct file link skips the extractors entirely.
        try:
            client, resp = _probe(url)
            ctype = resp.headers.get("content-type", "")
        except Exception as e:
            return f"Error: could not open {url}: {e}"
        if resp.status_code < 400 and not _is_page(ctype):
            if kind == "info":
                length = resp.headers.get("content-length")
                resp.close(); client.close()
                size = f", {_size_n(int(length))}" if length and length.isdigit() else ""
                return f"Direct file: {ctype.split(';')[0]}{size} (kind=\"auto\" or \"file\" downloads it)"
            return _save_stream(client, resp, out_dir, progress)
        resp.close(); client.close()

        errors = []
        if kind == "info":
            res, err = _ytdlp_info(url, playlist, cookies)
            if res:
                return res
            errors.append(f"yt-dlp: {err}")
            res, err = _gallery(url, out_dir, max_items, cookies, simulate=True)
            if res:
                return res
            errors.append(f"gallery-dl: {err}")
        else:
            res, err = _ytdlp_media(url, "video", out_dir, playlist, max_items, max_height, cookies,
                                    progress, info_json)
            if res:
                return res
            errors.append(f"yt-dlp: {err}")
            res, err = _gallery(url, out_dir, max_items, cookies)
            if res:
                return res
            errors.append(f"gallery-dl: {err}")
        login = any(w in " ".join(errors).lower() for w in ("login", "log in", "sign in", "cookies", "private", "403"))
        return ("Error: found no downloadable media at this link.\n- " + "\n- ".join(errors)
                + ("\nIt may need a login: retry with cookies_from_browser=\"chrome\" (only if the user agrees)."
                   if login else "\nIf it's an article, use to_markdown for its text.")
                + "".join(dict.fromkeys(_hint(e) for e in errors)))
    except KeyboardInterrupt:
        n = _cleanup_partials(out_dir, started)
        return "Error: cancelled" + (f"; removed {n} half-downloaded file(s)" if n else "")
    except subprocess.TimeoutExpired:
        n = _cleanup_partials(out_dir, started)
        return ("Error: download timed out after an hour" + (f" (removed {n} partial file(s))" if n else "")
                + "; run the fetch-media command in the background instead")
    except Exception as e:
        return f"Error: {e}"

