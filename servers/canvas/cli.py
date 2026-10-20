#!/usr/bin/env python3
"""canvas: read-only Canvas LMS from the terminal, plus the local course mirror.

Usage:
  canvas courses [--past]                    current courses with running grades
  canvas due [--days 14] [--course X] [--done]
  canvas news [--days 7] [--course X]        recent announcements
  canvas grades [COURSE]
  canvas sync [--course X] [--no-files] [--max-mb 50]   mirror to ~/Documents/Canvas
  canvas changes [--hours 72] [--course X]   what changed between syncs
  canvas status                              sign-in, mirror folder, last sync
  canvas skip COURSE... | canvas unskip COURSE...   leave courses out of full syncs
  canvas schedule on|off|status              sync every 4 hours via launchd
Sign in first: canvas-auth
"""
import json
import os
import plistlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

LABEL = "com.claude-local-tools.canvas-sync"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def _opt(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def schedule(mode: str) -> None:
    if mode == "on":
        exe = os.path.expanduser("~/.local/bin/canvas")
        os.makedirs(core.DATA_DIR, exist_ok=True)
        log = os.path.join(core.DATA_DIR, ".sync.log")
        plistlib.dump({"Label": LABEL, "ProgramArguments": [exe, "sync"], "StartInterval": 4 * 3600,
                       "RunAtLoad": True, "StandardOutPath": log, "StandardErrorPath": log,
                       "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}},
                      open(PLIST, "wb"))
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        subprocess.run(["launchctl", "load", PLIST], check=True)
        print(f"Scheduled: sync every 4 h. Log: {log}")
    elif mode == "off":
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
        print("Schedule removed.")
    else:
        print(json.dumps({"scheduled": os.path.exists(PLIST), **core.status()}, indent=1, default=str))


def main(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, course = a[0], _opt(a, "--course", "")
    try:
        if cmd == "courses":
            for x in core.call(core.courses, "--past" in a):
                g = f"{x['current_score']}% {x['current_grade'] or ''}" if x["current_score"] is not None else ""
                print(f"{x['id']:>8}  {x['code'][:24]:24}  {x['name'][:50]:50}  {g}")
        elif cmd == "due":
            r = core.call(core.due, float(_opt(a, "--days", 14)), course, "--done" in a)
            for it in r["items"]:
                print(f"{it['when']:24} {it['course'][:18]:18} {it['type'][:10]:10} {it['title']}  [{it['status']}]")
            if r["missing"]:
                print("\nMissing:")
                for m in r["missing"]:
                    print(f"  {m['due']:24} {m['course'][:18]:18} {m['title']}")
            if not r["items"] and not r["missing"]:
                print(f"Nothing due in the {r['window']}.")
        elif cmd == "news":
            for n in core.call(core.announcements, course, float(_opt(a, "--days", 7))):
                print(f"\n## {n['course']}: {n['title']}  ({n['posted']}, {n['author']})\n{n['body']}")
        elif cmd == "grades":
            print(json.dumps(core.call(core.grades, a[1] if len(a) > 1 and not a[1].startswith("--") else ""),
                             indent=1, default=str))
        elif cmd == "sync":
            r = core.call(core.sync, course, "--no-files" not in a, float(_opt(a, "--max-mb", 50)))
            print(json.dumps(r, indent=1, default=str))
            if r["errors"]:
                sys.exit(1)
        elif cmd == "changes":
            for ch in core.changes(float(_opt(a, "--hours", 72)), course):
                print(f"{ch['at']:24} {ch['course'][:18]:18} {ch['kind']:12} {ch['what']:18} {ch['title']}"
                      + (f"  ({ch['detail']})" if ch.get("detail") else ""))
        elif cmd in ("skip", "unskip"):
            left = core.call(core.set_skip, a[1:], cmd == "skip")
            print("Full syncs skip:", ", ".join(core.call(lambda c: [core._label(c, i) for i in left])) or "nothing")
        elif cmd == "status":
            print(json.dumps(core.status(), indent=1, default=str))
        elif cmd == "schedule":
            schedule(a[1] if len(a) > 1 else "status")
        else:
            print(__doc__)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
