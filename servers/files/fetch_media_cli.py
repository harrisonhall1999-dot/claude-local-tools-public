#!/usr/bin/env python3
"""Command-line entrypoint for the catch-all media downloader.

Usage:
    fetch-media [<url>] [--kind auto|audio|video|images|file|subtitles|info] [options]

In a terminal, a video link opens a short menu of resolutions (with estimated
sizes), audio-only and captions, and yt-dlp's progress is shown. Run it with no
url to use the link on the clipboard. Piped or with --kind/--max-height/--mp3/-y,
it never asks and prints only the result, as before.
"""

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media import KINDS, _is_page, _probe, _size_n, fetch, format_choices, probe


def _clipboard_url():
    try:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return text if re.match(r"https?://\S+$", text) else ""


def _ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _get_url(given, interactive):
    if given:
        return given
    if not interactive:
        sys.exit("fetch-media: give a url (or run it in a terminal to use the clipboard)")
    copied = _clipboard_url()
    if copied:
        answer = _ask(f"Use the copied link?\n  {copied}\n[Y/n] ")
        if answer.lower() in ("", "y", "yes"):
            return copied
    url = _ask("Link: ")
    if not url:
        sys.exit(1)
    return url


def _pick(url, args):
    """Show the menu for a video/audio link. Returns fetch() kwargs, or None to
    fall back to the plain auto download (direct files, image galleries...)."""
    print("Looking up the link...", file=sys.stderr)
    try:  # a direct file (PDF, image, .mp4...) has nothing to choose
        client, resp = _probe(url)
        direct = resp.status_code < 400 and not _is_page(resp.headers.get("content-type", ""))
        resp.close()
        client.close()
        if direct:
            return None
    except Exception:
        pass
    info, info_json, err = probe(url, args.playlist, args.cookies_from_browser)
    if err or not info:
        return None
    is_list = info.get("_type") == "playlist"
    title = info.get("title") or url
    if is_list:
        n = len(info.get("entries") or [])
        print(f"\n{title}\nPlaylist: {n} items (up to {args.max_items} will be downloaded)\n")
        choices = [{"label": "every item as video (mp4)", "kind": "video", "height": 0, "size": 0},
                   {"label": "every item as audio (m4a)", "kind": "audio", "height": 0, "size": 0}]
        info_json = ""  # a flat playlist listing can't drive the downloads
        args.playlist = True
    else:
        choices = format_choices(info)
        if not choices:
            return None
        if any(c["kind"] == "audio" for c in choices):
            i = next(i for i, c in enumerate(choices) if c["kind"] == "audio")
            choices.insert(i + 1, {"label": "audio only (mp3, plays anywhere)", "kind": "audio",
                                   "height": 0, "size": 0, "mp3": True})
        dur = info.get("duration")
        dur = f" ({int(dur) // 60}:{int(dur) % 60:02d})" if dur else ""
        print(f"\n{title}{dur}\n")
    subs = {**(info.get("subtitles") or {}), **(info.get("automatic_captions") or {})}
    if any(k == args.lang or k.startswith(args.lang + "-") for k in subs):
        choices.append({"label": f"captions only, as a text transcript ({args.lang})", "kind": "subtitles",
                        "height": 0, "size": 0})
    for i, c in enumerate(choices, 1):
        size = f"  ~{_size_n(c['size'])}" if c["size"] else ""
        print(f"  {i}. {c['label']}{size}")
    while True:
        answer = _ask(f"\nPick 1-{len(choices)} [1], or q to quit: ").lower()
        if answer in ("q", "quit"):
            sys.exit(0)
        if answer == "":
            choice = choices[0]
            break
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            choice = choices[int(answer) - 1]
            break
    return {"kind": choice["kind"], "max_height": choice["height"], "info_json": info_json,
            "audio_format": "mp3" if choice.get("mp3") else "m4a"}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fetch-media",
        description="Download the video, audio, images, captions or file behind a web link "
                    "(yt-dlp, gallery-dl, or a plain download, picked automatically). "
                    "With no url, uses the link on the clipboard.",
    )
    parser.add_argument("url", nargs="?", default="", help="Page or file URL (http/https)")
    parser.add_argument("-k", "--kind", choices=KINDS, default="",
                        help="What to get, skipping the menu (default: auto)")
    parser.add_argument("-o", "--out", default="", help="Folder to save into (default ~/Downloads)")
    parser.add_argument("--playlist", action="store_true", help="Fetch the whole playlist/channel")
    parser.add_argument("--max-items", type=int, default=50, help="Cap on playlist items / gallery images")
    parser.add_argument("--max-height", type=int, default=0, help="Cap video resolution, e.g. 720")
    parser.add_argument("--mp3", action="store_true", help="With --kind audio: mp3 instead of m4a")
    parser.add_argument("--lang", default="en", help="Caption language for --kind subtitles")
    parser.add_argument("--cookies-from-browser", default="",
                        help='Use a logged-in browser session, e.g. "chrome"')
    parser.add_argument("-y", "--yes", action="store_true", help="Never ask: take the best format")
    args = parser.parse_args()

    interactive = sys.stdin.isatty() and sys.stderr.isatty() and not args.yes
    url = _get_url(args.url.strip(), interactive)
    opts = {"kind": args.kind or "auto", "max_height": args.max_height,
            "audio_format": "mp3" if args.mp3 else "m4a"}
    if interactive and not args.kind and not args.max_height and not args.mp3:
        opts = _pick(url, args) or opts
    info_json = opts.get("info_json", "")
    try:
        result = fetch(url, opts["kind"], args.out, args.playlist, args.max_items, opts["max_height"],
                       args.lang, args.cookies_from_browser, progress=sys.stderr.isatty(),
                       info_json=info_json, audio_format=opts["audio_format"])
    finally:
        if info_json and os.path.isfile(info_json):
            os.remove(info_json)
    if result.startswith("Error: cancelled"):
        print(file=sys.stderr)  # finish the progress line ^C interrupted
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
