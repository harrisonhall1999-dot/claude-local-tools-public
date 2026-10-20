#!/usr/bin/env python3
"""Claude Code PreToolUse hook: before a `git commit` through Bash, run scripts/check.py; block the commit if it fails."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except ValueError:
    sys.exit(0)
if not re.search(r"\bgit\s+(-C\s+\S+\s+)?commit\b", cmd):
    sys.exit(0)
r = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python"), "scripts/check.py"],
                   cwd=ROOT, capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write("commit blocked: scripts/check.py failed\n" + (r.stdout + r.stderr)[-2000:])
    sys.exit(2)
sys.exit(0)
