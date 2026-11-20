#!/usr/bin/env python3
"""Wire this project's tools into Claude. Safe to re-run.

- Registers every MCP server below with Claude Code (user scope) and the
  Claude Desktop app (backing up its config first).
- Links every folder in skills/ into ~/.claude/skills/, and ~/.claude/CLAUDE.md to config/global-CLAUDE.md.
- Writes a launcher in ~/.local/bin/ for every command below.

Usage: python3 install.py [--school]   (--school adds Canvas, Outlook and cite)
"""

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(ROOT, ".venv", "bin", "python")

# MCP servers: name -> server script (run with the shared venv).
SERVERS = {
    "ocr": "servers/ocr/server.py",
    "local-llm": "servers/local-llm/server.py",
    "files": "servers/files/server.py",
    "search": "servers/search/server.py",
    "study": "servers/study/server.py",
    "cite": "servers/cite/server.py",
    "gemini": "servers/gemini/server.py",
    "outlook": "servers/outlook/server.py",
    "canvas": "servers/canvas/server.py",
}
_PORT_ORDER = list(SERVERS)  # fixed before the optional groups are dropped, so ports never shift

# Shared servers (scripts/mcp_hub.py): Claude Code connects to one copy of each server over HTTP
# instead of starting its own copies per session. False = every session starts its own (stdio).
SHARED = True
HUB_PORT = 8770


def hub_port(name):
    """Port of a server in the hub: HUB_PORT + its position in SERVERS (so add new servers at the end)."""
    return HUB_PORT + _PORT_ORDER.index(name)


# Commands put on PATH: name -> Python CLI script (run with the shared venv).
COMMANDS = {
    "mcp-hub": "scripts/mcp_hub.py",
    "local-llm": "servers/local-llm/cli.py",
    "setup-keys": "scripts/setup_keys.py",
    "ocr": "servers/ocr/cli.py",
    "read-document": "servers/ocr/read_document_cli.py",
    "fetch-url": "servers/ocr/fetch_url_cli.py",
    "transcribe": "servers/ocr/transcribe_cli.py",
    "index-docs": "servers/search/cli.py",
    "gemini-offload": "servers/gemini/cli.py",
    "fetch-media": "servers/files/fetch_media_cli.py",
    "to-md": "servers/files/tomd_cli.py",
    "outlook": "servers/outlook/cli.py",
    "canvas": "servers/canvas/cli.py",
    "canvas-auth": "servers/canvas/auth_cli.py",
    "localtools": "localtools/cli.py",
}

# Optional "school & law" group: installed only with `python3 install.py --school` (or CLT_SCHOOL=1).
SCHOOL = "--school" in sys.argv or os.environ.get("CLT_SCHOOL") == "1"
if not SCHOOL:
    for _n in ['cite', 'outlook', 'canvas']:
        SERVERS.pop(_n, None)
    for _n in ['outlook', 'canvas', 'canvas-auth']:
        COMMANDS.pop(_n, None)
SCHOOL_SKILLS = ['canvas']
LAUNCHER_MARK = "# Written by Claude Local Tools/install.py"
# Launchers from before this project existed, safe to replace.
LEGACY_MARKS = ("/ocr-mcp/", "/local-llm-mcp/")

HOME = os.path.expanduser("~")
DESKTOP_CONFIG = os.path.join(
    HOME, "Library", "Application Support", "Claude", "claude_desktop_config.json")


def link(target, link_path):
    """Point link_path at target, replacing an old link but never a real file."""
    os.makedirs(os.path.dirname(link_path), exist_ok=True)
    if os.path.islink(link_path):
        os.remove(link_path)
    elif os.path.exists(link_path):
        print(f"  skip {link_path}: a real file/folder is there; move it first")
        return
    os.symlink(target, link_path)
    print(f"  {link_path} -> {target}")


def write_launcher(name, script):
    """Write ~/.local/bin/<name>, replacing only launchers we own (or old ones)."""
    path = os.path.join(HOME, ".local", "bin", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.islink(path):
        os.remove(path)
    elif os.path.exists(path):
        with open(path, errors="replace") as f:
            old = f.read()
        if LAUNCHER_MARK not in old and not any(m in old for m in LEGACY_MARKS):
            print(f"  skip {path}: not ours; move it first")
            return
    with open(path, "w") as f:
        f.write(f'#!/bin/sh\n{LAUNCHER_MARK}\nexec "{PYTHON}" "{os.path.join(ROOT, script)}" "$@"\n')
    os.chmod(path, 0o755)
    print(f"  {path}")


def register_claude_code():
    hub = os.path.join(ROOT, "scripts", "mcp_hub.py")
    if SHARED:
        print("Shared servers (launchd):")
        subprocess.run([PYTHON, hub, "install"], check=True,
                       env={**os.environ, "CLT_SCHOOL": "1" if SCHOOL else "0"})
    else:
        subprocess.run([PYTHON, hub, "uninstall"], capture_output=True)
    print(f"Claude Code (user scope, {'shared over HTTP' if SHARED else 'one copy per session'}):")
    for name, script in SERVERS.items():
        subprocess.run(["claude", "mcp", "remove", name, "-s", "user"],
                       capture_output=True)
        how = (["--transport", "http", name, f"http://127.0.0.1:{hub_port(name)}/mcp"] if SHARED
               else [name, "--", PYTHON, os.path.join(ROOT, script)])
        subprocess.run(["claude", "mcp", "add", "-s", "user", *how], check=True, capture_output=True)
        print(f"  {name}")


def prune_backups(keep=3):
    """Keep only the newest `keep` Desktop config backups (they hold any tokens the config holds)."""
    folder, base = os.path.split(DESKTOP_CONFIG)
    old = sorted(f for f in os.listdir(folder) if f.startswith(base + ".bak-"))
    for f in old[:-keep]:
        os.remove(os.path.join(folder, f))
    if len(old) > keep:
        print(f"  removed {len(old) - keep} old config backups (kept {keep})")


def register_desktop():
    print("Claude Desktop:")
    cfg = {}
    if os.path.exists(DESKTOP_CONFIG):
        backup = f"{DESKTOP_CONFIG}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(DESKTOP_CONFIG, backup)
        os.chmod(backup, 0o600)
        print(f"  backed up config to {os.path.basename(backup)}")
        prune_backups(keep=3)
        with open(DESKTOP_CONFIG) as f:
            cfg = json.load(f)
    servers = cfg.setdefault("mcpServers", {})
    for name, script in SERVERS.items():
        servers[name] = {"command": PYTHON, "args": [os.path.join(ROOT, script)]}
        print(f"  {name}")
    with open(DESKTOP_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    print("  quit Claude Desktop fully (Cmd+Q) and reopen it to pick up changes;")
    print("  while it runs it can write its old config back, so run scripts/check.py after")


def main():
    if not os.path.exists(PYTHON):
        raise SystemExit(f"Missing {PYTHON}. Create it first:\n"
                         f"  uv venv --python 3.13 .venv && "
                         f"uv pip install --python .venv/bin/python -r requirements.txt")
    print("Skills:")
    for name in sorted(os.listdir(os.path.join(ROOT, "skills"))):
        if name in SCHOOL_SKILLS and not SCHOOL:
            continue
        if os.path.isfile(os.path.join(ROOT, "skills", name, "SKILL.md")):
            link(os.path.join(ROOT, "skills", name), os.path.join(HOME, ".claude", "skills", name))
    print("Hooks (config/hooks -> ~/.claude/hooks; enable each in ~/.claude/settings.json):")
    hooks_dir = os.path.join(ROOT, "config", "hooks")
    for name in sorted(os.listdir(hooks_dir)) if os.path.isdir(hooks_dir) else []:
        if name.endswith((".sh", ".py")):
            link(os.path.join(hooks_dir, name), os.path.join(HOME, ".claude", "hooks", name))
    print("Global instructions:")
    link(os.path.join(ROOT, "config", "global-CLAUDE.md"), os.path.join(HOME, ".claude", "CLAUDE.md"))
    print("Commands:")
    for name, script in COMMANDS.items():
        write_launcher(name, script)
    register_claude_code()
    register_desktop()


if __name__ == "__main__":
    main()
