"""Call this project's MCP tools from Python ("code execution with MCP").

A script can chain several tools, filter and join their results, and loop, and only what it
prints reaches Claude. Use it when a job needs more than ~2 tool calls or a big intermediate
result that Claude doesn't need to see. For a single lookup, the MCP tool is just as cheap.

    from localtools import outlook, canvas
    print(outlook.ol_briefing())
    due = canvas.core.call(canvas.core.due, 7)      # structured data instead of tool text

- Each server loads on first use only, with its own `core` module, so `canvas` never loads the
  Ollama model. A tool takes the same arguments and returns the same text as the MCP tool.
- `localtools.<server>.core` is that server's core module, for dicts and lists instead of text.
- Find tools without loading every definition: `tools("calendar", detail="summary")`, or
  `localtools tools calendar` in Bash. Detail is "name", "summary" or "full".
- Reusable scripts live in localtools/recipes/ and run with `localtools run <name>`.
"""
import ast
import asyncio
import functools
import importlib.util
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVERS_DIR = os.path.join(ROOT, "servers")
RECIPES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recipes")
_loaded: dict[str, types.ModuleType] = {}


def _dirs() -> dict[str, str]:
    """Python name (local_llm) -> server folder, for every servers/*/server.py."""
    return {d.replace("-", "_"): os.path.join(SERVERS_DIR, d) for d in sorted(os.listdir(SERVERS_DIR))
            if os.path.isfile(os.path.join(SERVERS_DIR, d, "server.py"))}


def names() -> list[str]:
    return list(_dirs())


def _wrap(tool):
    fn = tool.fn
    if not tool.is_async:
        return fn

    @functools.wraps(fn)
    def run(*args, **kw):
        return asyncio.run(fn(*args, **kw))
    return run


def server(name: str) -> types.ModuleType:
    """Load one server (once) and return a module whose attributes are its tools, plus `core`."""
    name = name.replace("-", "_")
    if name in _loaded:
        return _loaded[name]
    path = _dirs().get(name)
    if not path:
        raise AttributeError(f"No server named {name!r}. Servers: {', '.join(names())}")
    # Every server does `import core`; give each its own so they don't collide in sys.modules.
    shadow = sys.modules.pop("core", None)
    sys.path.insert(0, path)
    try:
        spec = importlib.util.spec_from_file_location(f"localtools._servers.{name}", os.path.join(path, "server.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        own = sys.modules.pop("core", None)
        if own is not None:
            sys.modules[f"localtools._servers.{name}.core"] = own
        if shadow is not None:
            sys.modules["core"] = shadow
        while path in sys.path:
            sys.path.remove(path)
        sys.path.append(path)  # sibling modules a tool imports later (e.g. canvas_api) still resolve
    ns = types.ModuleType(f"localtools.{name}", (mod.__doc__ or "").strip())
    tools = mod.mcp._tool_manager.list_tools()
    for t in tools:
        setattr(ns, t.name, _wrap(t))
    ns.TOOLS = [t.name for t in tools]
    ns.core = own
    _loaded[name] = ns
    return ns


def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    return server(name)


def _scan(path: str) -> list[dict]:
    """Tool names, signatures and docstrings from a server.py, read with ast (nothing imported)."""
    src = open(path).read()
    out = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                "tool" in ast.unparse(d) for d in node.decorator_list):
            doc = ast.get_docstring(node) or ""
            out.append({"name": node.name, "args": ast.unparse(node.args), "doc": doc,
                        "summary": doc.split("\n\n")[0].replace("\n", " ")[:160]})
    return out


def tools(query: str = "", detail: str = "summary") -> str:
    """Find tools by words in their name or docstring without loading any server.
    detail: "name" (server.tool), "summary" (+ first sentence), "full" (+ signature and docstring)."""
    words = query.lower().split()
    lines = []
    for srv, path in _dirs().items():
        for t in _scan(os.path.join(path, "server.py")):
            hay = f"{srv} {t['name']} {t['doc']}".lower()
            if words and not all(w in hay for w in words):
                continue
            if detail == "name":
                lines.append(f"{srv}.{t['name']}")
            elif detail == "full":
                lines.append(f"## {srv}.{t['name']}({t['args']})\n{t['doc']}\n")
            else:
                lines.append(f"{srv}.{t['name']}: {t['summary']}")
    return "\n".join(lines) or f"No tools match {query!r}."


def list_recipes() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(RECIPES_DIR) if f.endswith(".py") and not f.startswith("_"))


def parse(text: str):
    """Tool text -> Python data when it is JSON; otherwise the text unchanged."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text
