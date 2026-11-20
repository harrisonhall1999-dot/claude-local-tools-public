"""Shared logic for handing work to the local Ollama model.

The point is to let Claude point a cheap local model at files *by path*,
so the file contents never pass through Claude's context - only the
(much shorter) result does.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# "auto" = try the cloud model first, fall back to the local one. The cloud twin
# (models/cloud-offload.Modelfile) is fast and uses no local RAM; qwen-offload
# (models/qwen-offload.Modelfile) is the abliterated Qwen3.5 9B that runs here.
# Pass an explicit model name (or set LOCAL_LLM_MODEL) to skip the routing.
DEFAULT_MODEL = os.environ.get("LOCAL_LLM_MODEL", "auto")
CLOUD_MODEL = os.environ.get("LOCAL_LLM_CLOUD_MODEL", "cloud-offload")  # "" = never use cloud
LOCAL_MODEL = os.environ.get("LOCAL_LLM_LOCAL_MODEL", "qwen-offload")
# Apple's on-device model (the `fm` command in macOS 27), tried between the cloud
# and qwen-offload: free, ~200 MB of RAM instead of ~6 GB, and it works with the
# Ollama app closed. In our tests it beat qwen-offload (13/16 vs 12/16, ~5x
# faster) but is weaker than the cloud at arithmetic and nuanced labels.
# "" = never use it.
FM_MODEL = os.environ.get("LOCAL_LLM_FM_MODEL", "apple-fm")
# Its context fit ~40k chars of input (68k overflowed); leave room for the prompt.
FM_CHUNK_CHARS = int(os.environ.get("LOCAL_LLM_FM_CHUNK_CHARS", "30000"))
FM_TIMEOUT = int(os.environ.get("LOCAL_LLM_FM_TIMEOUT", "300"))
# fm has no Modelfile, so it gets the same system prompt as the Ollama variants.
_OFFLOAD_MODELFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "..", "models", "qwen-offload.Modelfile")
# Ollama publishes no usage percentage, only a monthly allowance. If you know
# it in tokens, set this and cloud use stops at CLOUD_STOP_AT of it each month;
# 0 = no cap, rely on the error fallback below.
CLOUD_MONTHLY_TOKENS = int(os.environ.get("LOCAL_LLM_CLOUD_MONTHLY_TOKENS", "0"))
CLOUD_STOP_AT = float(os.environ.get("LOCAL_LLM_CLOUD_STOP_AT", "0.75"))
CLOUD_TIMEOUT = int(os.environ.get("LOCAL_LLM_CLOUD_TIMEOUT", "180"))
# The free allowance resets monthly on the ollama.com sign-up day, not the 1st.
CLOUD_RESET_DAY = min(int(os.environ.get("LOCAL_LLM_CLOUD_RESET_DAY", "20")), 28)
# The cloud model has a far bigger context than the local 8k, so long inputs
# are split into fewer, larger pieces when the cloud is up.
CLOUD_CHUNK_CHARS = int(os.environ.get("LOCAL_LLM_CLOUD_CHUNK_CHARS", "100000"))
STATE_PATH = os.path.expanduser("~/.cache/claude-local-tools/local-llm-cloud.json")
# DeepSeek's own API, tried after the Ollama cloud and before Apple's model.
# Not free: a one-time sign-up grant, then pay-as-you-go from a prepaid balance.
# With no balance left the API answers 402 and the chain moves on, so it only
# spends what the user chose to load. The key lives in the macOS Keychain
# (service "deepseek-api"); DEEPSEEK_API_KEY overrides it. "" model = never use it.
DEEPSEEK_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("LOCAL_LLM_DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_THINK_MODEL = os.environ.get("LOCAL_LLM_DEEPSEEK_THINK_MODEL", "deepseek-v4-pro")
DEEPSEEK_KEYCHAIN = os.environ.get("LOCAL_LLM_DEEPSEEK_KEYCHAIN", "deepseek-api")
DEEPSEEK_TIMEOUT = int(os.environ.get("LOCAL_LLM_DEEPSEEK_TIMEOUT", "300"))
DEEPSEEK_STATE_PATH = os.path.expanduser("~/.cache/claude-local-tools/local-llm-deepseek.json")
# FreeLLMAPI (github.com/tashfeenahmed/freellmapi): a free router on this Mac that spreads
# calls over many providers' free tiers behind one OpenAI-style endpoint. Tried first.
# Its unified key lives in the Keychain (service "freellmapi"). "" model = never use it.
FREE_URL = os.environ.get("LOCAL_LLM_FREE_URL", "http://127.0.0.1:3001/v1").rstrip("/")
FREE_MODEL = os.environ.get("LOCAL_LLM_FREE_MODEL", "auto")
FREE_KEYCHAIN = os.environ.get("LOCAL_LLM_FREE_KEYCHAIN", "freellmapi")
FREE_TIMEOUT = int(os.environ.get("LOCAL_LLM_FREE_TIMEOUT", "300"))
FREE_STATE_PATH = os.path.expanduser("~/.cache/claude-local-tools/local-llm-free.json")
# Ollama on the user's PCs over Tailscale, tried after Apple's model and before
# qwen-offload, so the ~6 GB model rarely loads on this Mac. One "host=model" per
# line in this file (or comma-separated in LOCAL_LLM_PCS), e.g. "old-pc=qwen3:8b".
PCS_PATH = os.path.expanduser("~/.config/claude-local-tools/pc-ollama.txt")
PC_PORT = int(os.environ.get("LOCAL_LLM_PC_PORT", "11434"))
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


_USED = []  # models that answered during the current run (for the footer)


class OllamaDown(RuntimeError):
    """Ollama itself is unreachable, so neither cloud nor local can run."""


class OllamaHTTPError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class FellBack(Exception):
    """A model failed on a prompt too long for the next model down the chain."""

    def __init__(self):
        super().__init__("every model failed or the input piece was too long for the fallback model")


class FmError(RuntimeError):
    """Apple's model refused (safety filter), overflowed, or is unavailable."""


def _period_start():
    t = time.localtime()
    y, m = t.tm_year, t.tm_mon
    if t.tm_mday < CLOUD_RESET_DAY:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}-{CLOUD_RESET_DAY:02d}"


def _state():
    try:
        with open(STATE_PATH) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    period = _period_start()
    if st.get("period") != period:  # allowance reset: fresh tally
        st = {"period": period, "tokens": 0, "blocked_until": 0, "reason": ""}
    return st


def _save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(st, f)
    except OSError:
        pass


def cloud_available():
    """False when cloud is off, cooling down after an error, or over budget."""
    if not CLOUD_MODEL:
        return False
    st = _state()
    if st["blocked_until"] > time.time():
        return False
    return not (CLOUD_MONTHLY_TOKENS and st["tokens"] >= CLOUD_STOP_AT * CLOUD_MONTHLY_TOKENS)


_EXHAUSTED = ("limit", "quota", "credit", "usage", "plan", "allowance", "upgrade")


def _block_cloud(reason, code=None):
    # Allowance/plan errors: retry in 6 h; busy, timeout or server errors: 10 min.
    long = code == 402 or any(w in reason.lower() for w in _EXHAUSTED)
    st = _state()
    st["blocked_until"] = time.time() + (6 * 3600 if long else 600)
    st["reason"] = reason[:200]
    _save_state(st)


def _post(model, prompt, think, timeout, base=None):
    base = base or OLLAMA_URL
    options = {} if model == CLOUD_MODEL else {"num_ctx": NUM_CTX}
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "keep_alive": KEEP_ALIVE,
        "options": options,
    }).encode()
    req = urllib.request.Request(f"{base}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise OllamaHTTPError(e.code, f"Ollama error {e.code} for {model}: {detail}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, OSError)) and "timed out" in str(e.reason):
            raise TimeoutError(f"{model} timed out after {timeout}s")
        raise OllamaDown(
            f"could not reach Ollama at {base} ({e}). Is the Ollama app running?")
    return data


_PC_DOWN = {}  # host -> time it last failed; skipped for 10 minutes after


def pcs():
    """[(host, model)] from LOCAL_LLM_PCS or the PCS_PATH file; empty when none are set up."""
    raw = os.environ.get("LOCAL_LLM_PCS", "")
    if not raw:
        try:
            with open(PCS_PATH, encoding="utf-8") as f:
                raw = ",".join(l.split("#")[0].strip() for l in f)
        except OSError:
            return []
    return [tuple(p.strip().split("=", 1)) for p in raw.split(",") if "=" in p]


def pcs_up():
    """The PCs answering right now (2-second check each), skipping any that failed in the last 10 min."""
    up = []
    for host, model in pcs():
        if time.time() - _PC_DOWN.get(host, 0) < 600:
            continue
        try:
            urllib.request.urlopen(f"http://{host}:{PC_PORT}/api/tags", timeout=2).close()
            up.append((host, model))
        except (urllib.error.URLError, OSError, ValueError):
            _PC_DOWN[host] = time.time()
    return up


_FM_STATE = {"available": None, "system": None, "note": ""}


def fm_available():
    """True when the `fm` command exists, its license is agreed and the model is ready."""
    if not FM_MODEL:
        return False
    if _FM_STATE["available"] is None:
        ok = False
        if shutil.which("fm"):
            try:
                p = subprocess.run(["fm", "available"], capture_output=True, text=True, timeout=30)
                ok = p.returncode == 0 and "available" in p.stdout.lower() and "not" not in p.stdout.lower()
            except (OSError, subprocess.TimeoutExpired):
                pass
        _FM_STATE["available"] = ok
    return _FM_STATE["available"]


def _offload_system():
    if _FM_STATE["system"] is None:
        with open(_OFFLOAD_MODELFILE, encoding="utf-8") as f:
            m = re.search(r'SYSTEM """(.*?)"""', f.read(), re.S)
        _FM_STATE["system"] = m.group(1).strip() if m else ""
    return _FM_STATE["system"]


def _fm(prompt, timeout=FM_TIMEOUT):
    # Greedy sampling for repeatable extraction; the permissive guardrail level
    # stops refusals on case facts (e.g. a drug-lab summary) that the default blocks.
    cmd = ["fm", "respond", "--no-stream", "-g",
           "--guardrails", "permissive-content-transformations",
           "-i", _offload_system(), prompt]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise FmError(f"{FM_MODEL} timed out after {timeout}s")
    out = p.stdout.strip()
    if p.returncode != 0 or not out:
        err = re.sub(r"\x1b\[[0-9;]*m", "", p.stderr or p.stdout).strip()
        raise FmError(f"{FM_MODEL}: {err[:200] or 'no output'}")
    return out


def _cloud(prompt, think):
    """One cloud call; a busy/queue-full reply (free plan = 1 request at a time) gets one retry."""
    try:
        return _post(CLOUD_MODEL, prompt, think, CLOUD_TIMEOUT)
    except OllamaHTTPError as e:
        if e.code not in (429, 503) or any(w in str(e).lower() for w in _EXHAUSTED):
            raise
    time.sleep(8)
    return _post(CLOUD_MODEL, prompt, think, CLOUD_TIMEOUT)


_DS = {"key": None}


class DeepSeekError(RuntimeError):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def _keychain(service, env):
    """An API key from the environment or the macOS Keychain, cached; "" when there is none."""
    if service not in _DS:
        key = os.environ.get(env, "")
        if not key:
            try:
                p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                                   capture_output=True, text=True, timeout=15)
                key = p.stdout.strip() if p.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                key = ""
        _DS[service] = key
    return _DS[service]


def _deepseek_key():
    return _keychain(DEEPSEEK_KEYCHAIN, "DEEPSEEK_API_KEY")


def _free_key():
    return _keychain(FREE_KEYCHAIN, "FREELLMAPI_KEY")


def _ds_state(path=DEEPSEEK_STATE_PATH):
    try:
        with open(path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("tokens", 0)
    st.setdefault("blocked_until", 0)
    st.setdefault("reason", "")
    return st


def _ds_save(st, path=DEEPSEEK_STATE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(st, f)
    except OSError:
        pass


def free_available():
    """False when FreeLLMAPI is off, has no key, or is cooling down after an error."""
    if not FREE_MODEL or not _free_key():
        return False
    return _ds_state(FREE_STATE_PATH)["blocked_until"] <= time.time()


def _block_free(reason, code=None):
    # Bad key: retry in 6 h; every provider busy, service not running, timeout: 10 min.
    st = _ds_state(FREE_STATE_PATH)
    st["blocked_until"] = time.time() + (6 * 3600 if code in (401, 403) else 600)
    st["reason"] = reason[:200]
    _ds_save(st, FREE_STATE_PATH)


def _oai_chat(url, key, model, prompt, think, timeout, label, state_path):
    """One call to an OpenAI-style chat API with the offload system prompt."""
    body = {"model": model, "stream": False,
            "messages": [{"role": "system", "content": _offload_system()},
                         {"role": "user", "content": prompt}]}
    if not think:
        body["temperature"] = 0.2  # faithful extraction, like the Ollama variants
    req = urllib.request.Request(f"{url}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise DeepSeekError(f"{label} error {e.code} for {model}: {detail}", e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DeepSeekError(f"could not reach {label} ({e})")
    st = _ds_state(state_path)
    st["tokens"] += (data.get("usage") or {}).get("total_tokens") or 0
    st["reason"] = ""
    _ds_save(st, state_path)
    _mark_used(f"{label}:{data.get('model') or model}")
    return (data["choices"][0]["message"].get("content") or "").strip()


def _free(prompt, think=False):
    return _oai_chat(FREE_URL, _free_key(), FREE_MODEL, prompt, think, FREE_TIMEOUT,
                     "freellmapi", FREE_STATE_PATH)


def deepseek_available():
    """False when DeepSeek is off, has no key, or is cooling down after an error."""
    if not DEEPSEEK_MODEL or not _deepseek_key():
        return False
    return _ds_state()["blocked_until"] <= time.time()


def _block_deepseek(reason, code=None):
    # No balance or bad key: retry in 6 h; busy, timeout or server errors: 10 min.
    long = code in (401, 402) or "balance" in reason.lower()
    st = _ds_state()
    st["blocked_until"] = time.time() + (6 * 3600 if long else 600)
    st["reason"] = reason[:200]
    _ds_save(st)


def _deepseek(prompt, think=False, timeout=DEEPSEEK_TIMEOUT):
    """One call to DeepSeek's OpenAI-style chat API with the offload system prompt."""
    model = DEEPSEEK_THINK_MODEL if think else DEEPSEEK_MODEL
    return _oai_chat(DEEPSEEK_URL, _deepseek_key(), model, prompt, think, timeout,
                     "deepseek", DEEPSEEK_STATE_PATH)


def status():
    """Where the next local_llm call will run, without loading any model."""
    st = _state()
    used = f"{st['tokens']:,} cloud tokens since the allowance reset on {st['period']}"
    if CLOUD_MONTHLY_TOKENS:
        used += f" ({100 * st['tokens'] / CLOUD_MONTHLY_TOKENS:.0f}% of {CLOUD_MONTHLY_TOKENS:,}; stops at {CLOUD_STOP_AT:.0%})"
    fm = fm_available()
    ds = deepseek_available()
    dst = _ds_state()
    if ds:
        ds_note = f"DeepSeek up ({dst['tokens']:,} tokens used so far)"
    elif not DEEPSEEK_MODEL or not _deepseek_key():
        ds_note = "DeepSeek off (no key in Keychain)"
    else:
        until = time.strftime("%H:%M", time.localtime(dst["blocked_until"]))
        ds_note = f"DeepSeek paused until {until} after: {dst['reason']}"
    # Only qwen-offload loads ~6 GB; Apple's model is on-device but light, so no heads-up.
    nxt = (f"next calls run on {FM_MODEL} (Apple on-device, ~200 MB RAM; "
           f"LOCAL {LOCAL_MODEL} only if it refuses)" if fm else
           f"next calls run LOCAL ({LOCAL_MODEL}, ~6 GB RAM)")
    low = f"{FM_MODEL}, then {LOCAL_MODEL}" if fm else LOCAL_MODEL
    if ds:
        nxt = f"next calls run on DeepSeek {DEEPSEEK_MODEL} (cloud, no local RAM; fallback {low})"
    fst = _ds_state(FREE_STATE_PATH)
    if free_available():
        free_note = f"FreeLLMAPI up ({fst['tokens']:,} tokens used so far)"
    elif not FREE_MODEL or not _free_key():
        free_note = f"FreeLLMAPI off (no key in Keychain service '{FREE_KEYCHAIN}')"
    else:
        free_note = (f"FreeLLMAPI paused until {time.strftime('%H:%M', time.localtime(fst['blocked_until']))}"
                     f" after: {fst['reason']}")
    configured = pcs()
    pc_note = (f"PCs set up: {', '.join(f'{m}@{h}' for h, m in configured)} (used before {LOCAL_MODEL}, if awake)"
               if configured else f"no PCs set up ({PCS_PATH})")
    ds_note = f"{free_note}. {ds_note}. {pc_note}"
    if free_available():
        return f"FreeLLMAPI up: next calls run on it (free cloud router, no local RAM). {ds_note}. {used}."
    if not CLOUD_MODEL:
        return f"Cloud off: {nxt}. {ds_note}. {used}."
    if cloud_available():
        fb = f"DeepSeek, then {low}" if ds else low
        return f"Cloud up: next calls run on {CLOUD_MODEL} (no local RAM; fallback {fb}). {ds_note}. {used}."
    if st["blocked_until"] > time.time():
        until = time.strftime("%H:%M", time.localtime(st["blocked_until"]))
        why = f"paused until {until} after: {st['reason']}"
    else:
        why = "monthly budget reached"
    return f"Cloud {why}. {nxt[0].upper()}{nxt[1:]}. {ds_note}. {used}."


def _mark_used(model):
    if model not in _USED:
        _USED.append(model)


def chat(prompt, model=DEFAULT_MODEL, think=False, timeout=900):
    if model == FM_MODEL:
        out = _fm(prompt)
        _mark_used(FM_MODEL)
        return out
    if model in ("deepseek", DEEPSEEK_MODEL):
        if not _deepseek_key():
            raise DeepSeekError(f"no DeepSeek key: add it to the Keychain as service '{DEEPSEEK_KEYCHAIN}'")
        return _deepseek(prompt, think)
    if model in ("free", "freellmapi"):
        if not _free_key():
            raise DeepSeekError(f"no FreeLLMAPI key: add it to the Keychain as service '{FREE_KEYCHAIN}'")
        return _free(prompt, think)
    if model == "pc":
        for host, pc_model in pcs_up():
            data = _post(pc_model, prompt, think, timeout, base=f"http://{host}:{PC_PORT}")
            _mark_used(f"{pc_model}@{host}")
            return data["message"]["content"].strip()
        raise OllamaDown("no PC answered (is it awake and on Tailscale?)")
    if model != "auto":
        data = _post(model, prompt, think, timeout)
        _mark_used(model)
        return data["message"]["content"].strip()
    fm = fm_available()
    fits_fm = fm and len(prompt) <= FM_CHUNK_CHARS + 4000
    ds = deepseek_available()  # takes the same big pieces as the Ollama cloud
    if free_available():
        try:
            return _free(prompt, think)
        except DeepSeekError as e:  # every provider busy, bad key, service off: drop to the next model
            _block_free(str(e), e.code)
            if not (cloud_available() or ds) and len(prompt) > (FM_CHUNK_CHARS if fm else CHUNK_CHARS) + 4000:
                raise FellBack()
    if cloud_available():
        try:
            data = _cloud(prompt, think)
            st = _state()
            st["tokens"] += (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
            st["reason"] = ""
            _save_state(st)
            _mark_used(CLOUD_MODEL)
            return data["message"]["content"].strip()
        except OllamaDown:
            if not (fm or ds):
                raise  # Ollama app not running, no DeepSeek, no Apple model: nothing else can run
            if not (fits_fm or ds):
                raise FellBack()  # redo in pieces Apple's model can take
        except Exception as e:  # allowance, plan, busy, timeout: drop to the next model
            _block_cloud(str(e), getattr(e, "code", None))
            if not ds and len(prompt) > (FM_CHUNK_CHARS if fm else CHUNK_CHARS) + 4000:
                raise FellBack()
    if ds:
        try:
            return _deepseek(prompt, think)
        except DeepSeekError as e:  # no balance, bad key, busy, timeout: drop to the next model
            _block_deepseek(str(e), e.code)
            if len(prompt) > (FM_CHUNK_CHARS if fm else CHUNK_CHARS) + 4000:
                raise FellBack()
    if fits_fm:
        try:
            out = _fm(prompt)
            _mark_used(FM_MODEL)
            return out
        except FmError as e:  # refusal or overflow: qwen-offload takes this piece
            _FM_STATE["note"] = str(e)
            if len(prompt) > CHUNK_CHARS + 4000:
                raise FellBack()
    if len(prompt) <= CHUNK_CHARS + 4000:
        for host, pc_model in pcs_up():  # a PC takes it so the 6 GB model stays off this Mac
            try:
                data = _post(pc_model, prompt, think, timeout, base=f"http://{host}:{PC_PORT}")
                _mark_used(f"{pc_model}@{host}")
                return data["message"]["content"].strip()
            except Exception:
                _PC_DOWN[host] = time.time()
    data = _post(LOCAL_MODEL, prompt, think, timeout)
    _mark_used(LOCAL_MODEL)
    return data["message"]["content"].strip()


def run_on_text(instruction, text, model=DEFAULT_MODEL, think=False):
    """Apply instruction to text, map-reducing over chunks if it is long.

    In auto mode, pieces are sized for the best model up: cloud, then Apple's
    model, then qwen-offload. If a model fails on a piece too big for the next
    one down, the whole job is redone in that model's piece size.
    """
    if model == FM_MODEL:
        return _map_reduce(instruction, text, model, think, FM_CHUNK_CHARS)
    if model in ("deepseek", DEEPSEEK_MODEL, "free", "freellmapi"):
        return _map_reduce(instruction, text, model, think, CLOUD_CHUNK_CHARS)
    if model != "auto":
        return _map_reduce(instruction, text, model, think, CHUNK_CHARS)
    sizes = []
    if free_available() or cloud_available() or deepseek_available():
        sizes.append(CLOUD_CHUNK_CHARS)
    if fm_available():
        sizes.append(FM_CHUNK_CHARS)
    for size in sizes:
        try:
            return _map_reduce(instruction, text, model, think, size)
        except FellBack:
            continue
    return _map_reduce(instruction, text, model, think, CHUNK_CHARS)


def _map_reduce(instruction, text, model, think, size):
    if not text.strip():
        return chat(instruction, model, think)
    parts = chunk(text, size)
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


def _used(model):
    note = "model " + (", ".join(_USED) if _USED else model)
    if model == "auto" and CLOUD_MODEL and CLOUD_MODEL not in _USED:
        st = _state()
        if st["reason"]:
            note += f"; cloud paused: {st['reason'][:120]}"
    if model == "auto" and LOCAL_MODEL in _USED and _FM_STATE["note"]:
        note += f"; {_FM_STATE['note'][:120]}"
    return note


def run(instruction, text="", paths=None, model=DEFAULT_MODEL, think=False):
    """One answer over the given text plus all files together."""
    start = time.time()
    _USED.clear()
    _FM_STATE["note"] = ""
    blocks = [text] if text else []
    for p in expand_paths(paths):
        blocks.append(f"=== {os.path.basename(p)} ===\n{extract_text(p)}")
    result = run_on_text(instruction, "\n\n".join(blocks), model, think)
    return f"{result}\n\n[{_used(model)}, {time.time() - start:.0f}s]"


def run_batch(instruction, paths, model=DEFAULT_MODEL, think=False, output_dir=None):
    """Apply instruction to each file separately.

    With output_dir, each result is written to <output_dir>/<file>.md and only
    a short index is returned, so the results need not enter Claude's context.
    """
    start = time.time()
    _USED.clear()
    _FM_STATE["note"] = ""
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
    lines.append(f"\n[{_used(model)}, {len(files)} files, {time.time() - start:.0f}s]")
    return "\n".join(lines) if output_dir else "\n\n".join(lines)
