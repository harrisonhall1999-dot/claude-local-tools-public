#!/usr/bin/env python3
"""outlook: read-only mail and calendar from classic Outlook on this Mac.

Usage:
  outlook sync [--briefing]            refresh calendar (if Outlook is open); write today's briefing once
  outlook briefing                     rebuild and print today's briefing
  outlook search [WORDS] [--from X] [--folder Inbox] [--days 30] [--unread] [--limit 25] [--out F.csv]
  outlook read ID [--full]             print one message (--full keeps quoted replies)
  outlook calendar [today|tomorrow|YYYY-MM-DD] [--days 7]
  outlook schedule on|off|status       background sync every 30 min via launchd
"""
import json
import os
import plistlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

LABEL = "com.claude-local-tools.outlook-sync"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def _opt(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def _words(args):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("--"):
            skip = a not in ("--unread", "--full", "--briefing")
        else:
            out.append(a)
    return out


def schedule(mode: str) -> None:
    if mode == "on":
        exe = os.path.expanduser("~/.local/bin/outlook")
        core._private_dir(core.DATA_DIR)
        log = os.path.join(core.DATA_DIR, "sync.log")
        with open(PLIST, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": [exe, "sync"], "StartInterval": 1800,
                           "RunAtLoad": True, "StandardOutPath": log, "StandardErrorPath": log}, f)
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        subprocess.run(["launchctl", "load", PLIST], check=True)
        print(f"Scheduled: sync every 30 min; briefing on the first run after {core.BRIEF_HOUR}:00.\n"
              f"Log: {log}\nBriefings: {core.BRIEF_DIR}")
    elif mode == "off":
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
        print("Schedule removed.")
    else:
        print("scheduled:", os.path.exists(PLIST), "| last sync:", core._meta(core.store(), "last_sync"))


def main(a):
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = a[0], a[1:]
    try:
        if cmd == "sync":
            print(json.dumps(core.sync("--briefing" in rest), indent=1))
        elif cmd == "briefing":
            print(core.briefing())
        elif cmd == "search":
            rows = core.search_mail(" ".join(_words(rest)), _opt(rest, "--from", ""), _opt(rest, "--folder", ""),
                                    0, float(_opt(rest, "--days", 30)), "--unread" in rest,
                                    limit=int(_opt(rest, "--limit", 25)))
            if "--out" in rest:
                print(core.write_csv(rows, _opt(rest, "--out")))
            for m in rows:
                print(f"{m['received']}  {m['id']:>7}  {m['from'][:28]:28}  {m['subject'][:70]}")
        elif cmd == "read":
            m = core.read_mail(int(rest[0]), strip_quoted="--full" not in rest, max_chars=0)
            print(f"Subject: {m['subject']}\nFrom: {m['from']}\nTo: {m['to']}\nCc: {m['cc']}\n"
                  f"Date: {m['received']}\nAttachments: {', '.join(m['attachments'])}\n\n{m['body']}")
        elif cmd == "calendar":
            words = _words(rest)
            print(f"({core.ensure_fresh(30)})")
            for e in core.calendar(words[0] if words else "today", int(_opt(rest, "--days", 7))):
                when = "all day    " if e["all_day"] else f"{e['start'][11:]}-{e['end'][11:]}"
                print(f"{e['start'][:10]}  {when}  {e['summary']}  {e['location']}")
        elif cmd == "schedule":
            schedule(rest[0] if rest else "status")
        else:
            print(__doc__)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
