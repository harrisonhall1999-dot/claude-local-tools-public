"""Start each MCP server the way Claude does and list its tools, check that
Claude Desktop's config still points at them (a running Desktop app can write its
old copy of the config back over install.py's changes), and check that every
skill's SKILL.md has the name/description header Claude needs to find it.

Does not call any tool, so it never loads the Ollama model.
Usage: .venv/bin/python scripts/check.py
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from install import DESKTOP_CONFIG, PYTHON, SERVERS, SHARED, hub_port  # noqa: E402


async def check(name, script):
    params = StdioServerParameters(command=PYTHON, args=[os.path.join(ROOT, script)])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print(f"ok    {name}: {', '.join(tools)}")


async def check_hub():
    """True if every shared server answers over HTTP with the same tools as its script (skipped if SHARED is off)."""
    if not SHARED:
        return True
    from mcp.client.streamable_http import streamable_http_client

    async def one(name):
        async with streamable_http_client(f"http://127.0.0.1:{hub_port(name)}/mcp") as (r, w, *_):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return len((await s.list_tools()).tools)

    down = []
    for name in SERVERS:
        try:
            await asyncio.wait_for(one(name), timeout=10)
        except Exception:
            down.append(name)
    if down:
        print(f"FAIL  shared servers down: {', '.join(down)} (mcp-hub status; logs/mcp-hub/<name>.log; "
              "launchctl kickstart -k gui/$(id -u)/com.claude-local-tools.mcp-hub)")
        return False
    print(f"ok    shared servers ({len(SERVERS)} on 127.0.0.1)")
    return True


def check_desktop():
    """True if Claude Desktop's config runs every server the way install.py wrote it."""
    try:
        with open(DESKTOP_CONFIG) as f:
            servers = json.load(f).get("mcpServers", {})
    except (OSError, ValueError) as e:
        print(f"FAIL  Claude Desktop config: {e!r}")
        return False
    ok = True
    for name, script in SERVERS.items():
        want = {"command": PYTHON, "args": [os.path.join(ROOT, script)]}
        got = servers.get(name)
        if got is None or {k: got.get(k) for k in want} != want:
            ok = False
            print(f"FAIL  Claude Desktop config, {name}: {got} "
                  "(quit Claude Desktop, re-run install.py, then reopen it)")
    if ok:
        print("ok    Claude Desktop config")
    return ok


def check_skills():
    """True if every skills/*/SKILL.md and claude-ai-skills/*/SKILL.md names its folder and has a description."""
    ok = True
    for top in ("skills", "claude-ai-skills"):
        base = os.path.join(ROOT, top)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            path = os.path.join(base, name, "SKILL.md")
            if not os.path.isfile(path):
                continue
            with open(path) as f:
                text = f.read()
            head = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
            fields = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
            fields = {k.strip(): v.strip().strip('"') for k, v in fields.items()}
            problem = ("no --- header" if not head
                       else f"name is {fields.get('name')!r}, folder is {name!r}" if fields.get("name") != name
                       else "no description" if not fields.get("description") else "")
            if problem:
                ok = False
                print(f"FAIL  skill {top}/{name}: {problem}")
    if ok:
        print("ok    skills")
    return ok


async def main():
    failed = False
    for name, script in SERVERS.items():
        try:
            await asyncio.wait_for(check(name, script), timeout=60)
        except Exception as e:
            failed = True
            print(f"FAIL  {name}: {e!r}")
    if not await check_hub():
        failed = True
    if not check_desktop():
        failed = True
    if not check_skills():
        failed = True
    sys.exit(1 if failed else 0)


asyncio.run(main())
