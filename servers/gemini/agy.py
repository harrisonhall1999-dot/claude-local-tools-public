"""Send a task to Gemini through the Antigravity CLI (`agy -p`).

Files are read on this Mac (PDF/Office/OCR via the local-llm/ocr helpers) and
inlined into the prompt, so agy never needs file or shell tools. It runs in an
empty scratch folder for the same reason.
"""

import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash-high")
# Search is mostly Google lookups; the low-effort model is ~7x faster there.
SEARCH_MODEL = os.environ.get("GEMINI_SEARCH_MODEL", "gemini-3.8-flash-low")
TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "600"))
# The prompt goes in argv; macOS caps argv + env at 1 MB.
MAX_CHARS = int(os.environ.get("GEMINI_MAX_CHARS", "800000"))

SYSTEM = (
    "You are a worker for another AI assistant. Do exactly the task below using only "
    "the input given in this message. Do not run commands, read files or browse. "
    "Return only the requested output, with no preamble. Quote the source verbatim "
    "where asked. If the input does not contain what is asked for, say NONE rather "
    "than guessing."
)

_llm = None


def _local_llm_core():
    """The local-llm server's core module (path expansion and text extraction)."""
    global _llm
    if _llm is None:
        path = os.path.join(HERE, "..", "local-llm", "core.py")
        spec = importlib.util.spec_from_file_location("local_llm_core", path)
        _llm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_llm)
    return _llm


def _agy():
    for p in (shutil.which("agy"), "/opt/homebrew/bin/agy",
              os.path.expanduser("~/.local/bin/agy")):
        if p and os.path.exists(p):
            return p
    raise FileNotFoundError("agy (Antigravity CLI) not found; brew install --cask antigravity-cli")


def _call(prompt, model=DEFAULT_MODEL, effort=None, timeout=TIMEOUT):
    """One headless agy turn in an empty scratch folder. Returns agy's JSON result."""
    if len(prompt) > MAX_CHARS:
        raise ValueError(f"input is {len(prompt):,} chars, over the {MAX_CHARS:,} limit; "
                         "split it (e.g. use the batch tool, one file per call)")
    cmd = [_agy(), "--model", model, "--output-format", "json",
           "--disable-slash-commands", f"--print-timeout={timeout}s"]
    if effort:
        cmd.append(f"--effort={effort}")
    with tempfile.TemporaryDirectory(prefix="gemini-") as cwd:
        proc = subprocess.run(cmd + [f"--print={prompt}"], cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout + 30)
    out = proc.stdout.strip()
    try:
        data = json.loads(out[out.index("{"):])
    except ValueError:
        msg = (proc.stderr.strip() or out or f"exit code {proc.returncode}")[-1500:]
        if "auth" in msg.lower() or "sign in" in msg.lower():
            msg += "\n(Sign in again: run `agy` in Terminal, finish the browser login, then exit.)"
        raise RuntimeError(msg)
    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"agy status {data.get('status')}: {str(data)[:1500]}")
    return data


def ask(prompt, model=DEFAULT_MODEL):
    """One headless agy turn. Returns the response text; raises on failure."""
    return _call(prompt, model).get("response", "").strip()


def _prompt(instruction, text):
    return f"{SYSTEM}\n\nTASK:\n{instruction}\n\nINPUT:\n{text}" if text else \
        f"{SYSTEM}\n\nTASK:\n{instruction}"


def run(instruction, text="", paths=None, model=DEFAULT_MODEL, output_path=None):
    """One answer over the given text plus all files together."""
    llm = _local_llm_core()
    start = time.time()
    blocks = [text] if text else []
    for p in llm.expand_paths(paths):
        blocks.append(f"=== {os.path.basename(p)} ===\n{llm.extract_text(p)}")
    result = ask(_prompt(instruction, "\n\n".join(blocks)), model)
    tag = f"[Gemini {model} via agy, {time.time() - start:.0f}s]"
    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result + "\n")
        return f"Wrote {len(result):,} chars to {output_path}\n{tag}"
    return f"{result}\n\n{tag}"


def run_batch(instruction, paths, model=DEFAULT_MODEL, output_dir=None):
    """Apply instruction to each file separately (one agy call per file)."""
    llm = _local_llm_core()
    start = time.time()
    files = llm.expand_paths(paths)
    if output_dir:
        output_dir = os.path.expanduser(output_dir)
        os.makedirs(output_dir, exist_ok=True)
    lines = []
    for p in files:
        name = os.path.basename(p)
        try:
            result = ask(_prompt(instruction, llm.extract_text(p)), model)
        except Exception as e:  # keep going; report per-file failures
            lines.append(f"=== {name} ===\nError: {e}")
            continue
        if output_dir:
            out = os.path.join(output_dir, os.path.splitext(name)[0] + ".md")
            with open(out, "w", encoding="utf-8") as f:
                f.write(result + "\n")
            lines.append(f"{name} -> {out} ({len(result)} chars)")
        else:
            lines.append(f"=== {name} ===\n{result}")
    lines.append(f"\n[Gemini {model} via agy, {len(files)} files, {time.time() - start:.0f}s]")
    return "\n".join(lines) if output_dir else "\n\n".join(lines)


# --- Web search -----------------------------------------------------------

SEARCH = (
    "Run live web searches with your Google Search tool for the query below; do not "
    "answer from memory, and do not open or read pages (page reads are blocked). If it contains search operators (quotes, OR, AND, -, site:, filetype:, "
    "intitle:, before:/after:, parentheses), run it exactly as written first, then "
    "close variants only if results are thin. Prefer primary sources (court opinions, "
    "statutes, regulations, agency documents, official sites), then law firm and "
    "academic analysis, then reputable news. Ignore AI-generated overviews and content "
    "farms. Return raw results only, no preamble or conversational filler: a numbered "
    "list where each item has the source title, publisher, date, URL, and the "
    "relevant passage quoted verbatim from the search result. Do not add analysis or conclusions. Mark anything "
    "you could not confirm in a source as UNCONFIRMED; if nothing relevant is found, "
    "write NONE."
)

_REDIRECT = re.compile(r"https://vertexaisearch\.cloud\.google\.com/grounding-api-redirect/[\w-]+=*")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _resolve_links(text):
    """Swap Google's grounding redirect links for the real page URLs."""
    opener = urllib.request.build_opener(_NoRedirect)
    cache = {}
    for url in set(_REDIRECT.findall(text)):
        try:
            opener.open(urllib.request.Request(url, method="HEAD"), timeout=10)
        except urllib.error.HTTPError as e:
            if e.headers.get("Location"):
                cache[url] = e.headers["Location"]
        except Exception:
            pass
    for url, real in cache.items():
        text = text.replace(url, real)
    return text


def web_search(query, model=SEARCH_MODEL, output_path=None):
    """Live web search on Gemini (Google Search grounding); returns sourced results."""
    start = time.time()
    data = _call(f"{SEARCH}\n\nQUERY:\n{query}", model)
    result = _resolve_links(data.get("response", "").strip())
    tag = f"[Gemini {model} web search via agy, {time.time() - start:.0f}s; unverified]"
    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result + "\n")
        return f"Wrote {len(result):,} chars to {output_path}\n{tag}"
    return f"{result}\n\n{tag}"


# --- Image generation -----------------------------------------------------

BRAIN = os.path.expanduser("~/.gemini/antigravity-cli/brain")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def image(prompt, output_dir, count=1, model=DEFAULT_MODEL):
    """Generate images with agy's image-generator and copy them into output_dir."""
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    start = time.time()
    data = _call(
        f"Use the image-generator to create {count} image(s) for this brief. Do not run "
        f"commands or copy files; just generate and reply with the saved paths.\n\n"
        f"BRIEF:\n{prompt}", model, timeout=900)
    # agy saves into its own brain/<conversation>/ folders (one per subagent), so
    # collect every image written there during this call.
    found = [p for p in glob.glob(os.path.join(BRAIN, "*", "*"))
             if p.lower().endswith(IMAGE_EXTS) and os.path.getmtime(p) >= start - 1]
    if not found:
        raise RuntimeError(f"no image was generated. agy said: {data.get('response', '')[:800]}")
    saved = []
    for src in sorted(found, key=os.path.getmtime):
        dst = os.path.join(output_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        saved.append(dst)
    return "\n".join(saved) + f"\n[Gemini image-generator via agy, {time.time() - start:.0f}s]"
