#!/usr/bin/env python3
"""mcp-hub: run each local-tools MCP server once, shared by every Claude Code session.

Without it, every Claude Code session starts its own copy of all the servers (one Python process per
server per session). With it, launchd keeps one copy of each running on 127.0.0.1 (streamable HTTP,
stateless) and install.py registers them with Claude Code by URL. Claude Desktop (Chat, Cowork) still
starts its own copies: its config file only takes local commands.

  mcp-hub run            supervise all servers (what launchd runs)
  mcp-hub serve <name>   run one server over HTTP (the supervisor runs this for each server)
  mcp-hub install        write and load the launchd agent (starts at login, restarts on crash)
  mcp-hub uninstall      unload and remove it
  mcp-hub status         port, pid and memory of each server

Memory: a server over MEM_LIMIT_MB (an OCR or Whisper model loaded in it) exits once it has been idle
for IDLE_S seconds, and the supervisor restarts it fresh, so models don't stay loaded all day.
Shared servers run in the home folder, so tools should get absolute paths, not session-relative ones.
Ports: HUB_PORT + the server's position in install.SERVERS; add new servers at the end of that list.
Logs: logs/mcp-hub/<name>.log
"""
import os
import plistlib
import runpy
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from install import HUB_PORT, PYTHON, SCHOOL, SERVERS, hub_port  # noqa: E402

HOME = os.path.expanduser("~")
LABEL = "com.claude-local-tools.mcp-hub"
PLIST = os.path.join(HOME, "Library", "LaunchAgents", f"{LABEL}.plist")
LOGDIR = os.path.join(ROOT, "logs", "mcp-hub")
MEM_LIMIT_MB = 600
IDLE_S = 120
CRASH_LIMIT = 5          # this many exits within CRASH_WINDOW_S -> wait for the window to pass
CRASH_WINDOW_S = 300
PATH = f"/opt/homebrew/bin:/usr/local/bin:{HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def rss_mb(pid):
    try:
        return int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
                                  text=True, timeout=5).stdout.strip() or 0) // 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def serve(name):
    import uvicorn
    from mcp.server.mcpserver import MCPServer

    script = os.path.join(ROOT, SERVERS[name])
    sys.path.insert(0, os.path.dirname(script))
    os.chdir(HOME)
    ns = runpy.run_path(script, run_name="mcp_hub_child")
    server = next(v for v in ns.values() if isinstance(v, MCPServer))
    app = server.streamable_http_app(stateless_http=True, host="127.0.0.1")
    state = {"busy": 0, "last": time.time()}

    async def tracked(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        state["busy"] += 1
        try:
            await app(scope, receive, send)
        finally:
            state["busy"] -= 1
            state["last"] = time.time()

    def watch_memory():
        while True:
            time.sleep(30)
            mb = rss_mb(os.getpid())
            if mb > MEM_LIMIT_MB and state["busy"] == 0 and time.time() - state["last"] > IDLE_S:
                print(f"{time.strftime('%F %T')} {name}: {mb} MB while idle, exiting to free memory", flush=True)
                os._exit(0)

    threading.Thread(target=watch_memory, daemon=True).start()
    uvicorn.run(tracked, host="127.0.0.1", port=hub_port(name), log_level="warning")


def run():
    os.makedirs(LOGDIR, exist_ok=True)
    procs, exits = {}, {n: [] for n in SERVERS}

    def start(n):
        path = os.path.join(LOGDIR, f"{n}.log")
        if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            os.replace(path, path + ".old")
        with open(path, "ab") as log:
            procs[n] = subprocess.Popen([PYTHON, os.path.abspath(__file__), "serve", n], stdout=log,
                                        stderr=subprocess.STDOUT, cwd=HOME, start_new_session=True)

    def stop(*_):
        for p in procs.values():
            p.terminate()
        deadline = time.time() + 5
        for p in procs.values():
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for n in SERVERS:
        start(n)
    while True:
        time.sleep(5)
        now = time.time()
        for n, p in list(procs.items()):
            if p.poll() is None:
                continue
            exits[n] = [t for t in exits[n] if now - t < CRASH_WINDOW_S]
            if len(exits[n]) >= CRASH_LIMIT:
                continue  # crash loop: try again once the window has passed
            exits[n].append(now)
            start(n)


def install():
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(LOGDIR, exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": [PYTHON, os.path.abspath(__file__), "run"],
                       "RunAtLoad": True, "KeepAlive": True, "WorkingDirectory": HOME,
                       "EnvironmentVariables": {"PATH": PATH, "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1",
                                               "CLT_SCHOOL": "1" if SCHOOL else "0"},
                       "StandardErrorPath": os.path.join(LOGDIR, "hub.log"),
                       "StandardOutPath": os.path.join(LOGDIR, "hub.log")}, f)
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    subprocess.run(["launchctl", "load", PLIST], check=True)
    print(f"  loaded {LABEL} ({len(SERVERS)} servers from port {HUB_PORT})")


def uninstall():
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    if os.path.exists(PLIST):
        os.remove(PLIST)
    print(f"removed {LABEL}")


def listening(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def status():
    total = 0
    for n in SERVERS:
        port = hub_port(n)
        pid = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                             text=True).stdout.split()
        mb = rss_mb(pid[0]) if pid else 0
        total += mb
        print(f"{'ok  ' if listening(port) else 'DOWN'}  {n:<10} :{port}  {'pid ' + pid[0] if pid else '':<10} {mb} MB")
    print(f"total {total} MB")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "serve" and len(sys.argv) == 3 and sys.argv[2] in SERVERS:
        serve(sys.argv[2])
    elif cmd in ("run", "install", "uninstall", "status"):
        {"run": run, "install": install, "uninstall": uninstall, "status": status}[cmd]()
    else:
        sys.exit(__doc__)
