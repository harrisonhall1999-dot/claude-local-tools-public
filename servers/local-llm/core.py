"""Shared logic for handing work to the local Ollama model.

The point is to let Claude point a cheap local model at files *by path*,
so the file contents never pass through Claude's context - only the
(much shorter) result does.
"""

import glob
import json
import os
import sys
import time
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# gemma4-offload = gemma4:12b with an offload-worker system prompt and low
# temperature (see models/offload.Modelfile). Falls back to plain gemma4:12b
# via LOCAL_LLM_MODEL if the variant hasn't been built.
DEFAULT_MODEL = os.environ.get("LOCAL_LLM_MODEL", "gemma4-offload")
# Kept modest: this Mac has 16 GB of RAM and a bigger context means more
# memory pressure (it has frozen the machine before).
NUM_CTX = int(os.environ.get("LOCAL_LLM_NUM_CTX", "8192"))
# ~5k tokens of input per call, leaving room for the instruction and output.
CHUNK_CHARS = int(os.environ.get("LOCAL_LLM_CHUNK_CHARS", "20000"))
# Unload the model soon after a job instead of Ollama's default 5 minutes,
# to give the RAM back quickly.
KEEP_ALIVE = os.environ.get("LOCAL_LLM_KEEP_ALIVE", "30s")

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html",
             ".htm", ".xml", ".rtf", ".log", ".yaml", ".yml", ".py", ".js"}
OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"}

# Reuse the PDF/Office/OCR extractors from the sibling ocr server.
_OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ocr")
_ocr = None


def _ocr_server():
    global _ocr
    if _ocr is None:
        sys.path.insert(0, _OCR_DIR)
        import server as ocr_server  # noqa: E402

        _ocr = ocr_server
    return _ocr


def expand_paths(paths):
    """Expand ~ and glob patterns; keep order, drop duplicates."""
    out, seen = [], set()
    for p in paths or []:
        p = os.path.expanduser(p)
        matches = sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]
        if not matches:
            raise FileNotFoundError(f"no files match: {p}")
        for m in matches:
            if m not in seen and os.path.isfile(m):
                seen.add(m)
                out.append(m)
            elif not os.path.isfile(m):
                raise FileNotFoundError(f"file not found: {m}")
    return out


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _ocr_server()._extract_pdf(path)
    if ext in OFFICE_EXTS:
        return _ocr_server().read_document(path)
    if ext in IMAGE_EXTS:
        return _ocr_server().ocr(path)
    if ext in TEXT_EXTS or ext == "":
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    raise ValueError(f"unsupported file type '{ext}': {path}")


def chunk(text, size=CHUNK_CHARS):
    """Split on paragraph boundaries into pieces of at most ~size chars."""
    if len(text) <= size:
        return [text]
    pieces, cur = [], ""
    for para in text.split("\n\n"):
        while len(para) > size:
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(para[:size])
            para = para[size:]
        if len(cur) + len(para) + 2 > size:
            pieces.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        pieces.append(cur)
    return pieces


def chat(prompt, model=DEFAULT_MODEL, think=False, timeout=900):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "keep_alive": KEEP_ALIVE,
        "options": {"num_ctx": NUM_CTX},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"could not reach Ollama at {OLLAMA_URL} ({e}). Is the Ollama app running?")
    return data["message"]["content"].strip()


def run_on_text(instruction, text, model=DEFAULT_MODEL, think=False):
    """Apply instruction to text, map-reducing over chunks if it is long."""
    if not text.strip():
        return chat(instruction, model, think)
    parts = chunk(text)
    if len(parts) == 1:
        return chat(f"{instruction}\n\n<input>\n{text}\n</input>", model, think)
    partials = [
        chat(f"{instruction}\n\nThe input is long, so you are seeing part {i} of "
             f"{len(parts)}. Work only from this part.\n\n<input>\n{p}\n</input>",
             model, think)
        for i, p in enumerate(parts, 1)
    ]
    joined = "\n\n".join(f"<part {i}>\n{r}\n</part {i}>" for i, r in enumerate(partials, 1))
    return chat(f"{instruction}\n\nBelow are your results for each part of a long "
                f"input. Combine them into one final result, removing repetition.\n\n"
                f"{joined}", model, think)


def run(instruction, text="", paths=None, model=DEFAULT_MODEL, think=False):
    """One answer over the given text plus all files together."""
    start = time.time()
    blocks = [text] if text else []
    for p in expand_paths(paths):
        blocks.append(f"=== {os.path.basename(p)} ===\n{extract_text(p)}")
    result = run_on_text(instruction, "\n\n".join(blocks), model, think)
    return f"{result}\n\n[local model {model}, {time.time() - start:.0f}s]"


def run_batch(instruction, paths, model=DEFAULT_MODEL, think=False, output_dir=None):
    """Apply instruction to each file separately.

    With output_dir, each result is written to <output_dir>/<file>.md and only
    a short index is returned, so the results need not enter Claude's context.
    """
    start = time.time()
    files = expand_paths(paths)
    if output_dir:
        output_dir = os.path.expanduser(output_dir)
        os.makedirs(output_dir, exist_ok=True)
    lines = []
    for p in files:
        name = os.path.basename(p)
        try:
            result = run_on_text(instruction, extract_text(p), model, think)
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
    lines.append(f"\n[local model {model}, {len(files)} files, {time.time() - start:.0f}s]")
    return "\n".join(lines) if output_dir else "\n\n".join(lines)
