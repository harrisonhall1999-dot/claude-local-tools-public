#!/usr/bin/env python3
"""Sign the canvas tools in, once.

Usage: canvas-auth            use your Canvas session in Chrome (default; nothing to copy)
       canvas-auth --token    personal access token, if your school allows them
       canvas-auth --cookie   paste a Cookie header by hand (other browsers)

Chrome (default):
  1. Sign in to Canvas in Chrome as usual (any profile).
  2. Run this and enter your Canvas address. macOS asks to let `security` use "Chrome Safe Storage":
     enter your Mac password and choose Always Allow (otherwise scheduled syncs can't run).
  The tools then read only the Canvas cookies from Chrome on each run, so they keep working as long
  as you stay signed in to Canvas in Chrome. If they say the session expired, open Canvas in Chrome.
  Nothing secret is saved by this tool.

Token: Canvas -> Account -> Settings -> Approved Integrations -> "+ New Access Token".
  Many schools turn this off for students; if so, use the default Chrome mode.

Settings are saved to ~/.config/claude-local-tools/canvas.json (readable only by you).
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    mode = "token" if "--token" in args else "cookie" if "--cookie" in args else "chrome"
    print(__doc__)
    prev = ""
    try:
        prev = core.load_auth().get("base_url", "")
    except RuntimeError:
        pass
    url = input(f"Your Canvas address, as in Chrome's address bar (e.g. canvas.myschool.edu)"
                f"{f' [{prev}]' if prev else ''}: ").strip() or prev
    if not url:
        sys.exit("No address given.")
    try:
        if mode == "chrome":
            print("Reading your Canvas session from Chrome (approve the macOS prompt if it appears)...")
            who = core.set_auth(url, chrome=True)
        else:
            secret = getpass.getpass("Paste the Cookie value: " if mode == "cookie" else "Paste the access token: ").strip()
            if not secret:
                sys.exit("Nothing pasted.")
            if secret.lower().startswith("cookie:"):
                secret = secret.split(":", 1)[1].strip()
            who = core.set_auth(url, cookie=secret) if mode == "cookie" else core.set_auth(url, token=secret)
    except Exception as e:
        hint = ("\nTip: the address must match the one Chrome shows when you're in Canvas "
                "(e.g. myschool.instructure.com vs canvas.myschool.edu).") if mode == "chrome" else ""
        sys.exit(f"Couldn't sign in: {e}{hint}")
    n = len(core.call(core.courses))
    print(f"Signed in as {who}. {n} current courses visible. Next: `canvas sync` (mirrors to {core.DATA_DIR}).")


if __name__ == "__main__":
    main()
