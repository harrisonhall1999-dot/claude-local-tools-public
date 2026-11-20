"""setup-keys: set up the API keys the local tools use, from the terminal.

Every key is typed hidden (nothing shows on screen), checked against the real service before it is
saved, and stored in the macOS Keychain, never in a file. Nothing here costs money: each service
listed is free (DeepSeek is the exception and says so).

  setup-keys              menu
  setup-keys status       which keys are set (never prints a key)
  setup-keys providers    Groq, Cerebras, Google AI Studio, OpenRouter keys -> FreeLLMAPI, then its unified key
  setup-keys freellmapi   same as providers
  setup-keys unified      paste FreeLLMAPI's unified key (from its dashboard) and save it
  setup-keys deepseek     DeepSeek key (paid, prepaid balance; optional)

FreeLLMAPI: your dashboard email and password are used only to sign in to your own local
FreeLLMAPI (http://127.0.0.1:3001) for this run; they are not stored.
"""
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser

FREE = "http://127.0.0.1:3001"

# Where to get a free key, by words in the provider's name (matched case-insensitively).
SIGNUP = {
    "groq": "https://console.groq.com/keys",
    "cerebras": "https://cloud.cerebras.ai/platform",
    "google": "https://aistudio.google.com/app/apikey",
    "gemini": "https://aistudio.google.com/app/apikey",
    "openrouter": "https://openrouter.ai/settings/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "github": "https://github.com/settings/personal-access-tokens",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "nvidia": "https://build.nvidia.com/settings/api-keys",
    "sambanova": "https://cloud.sambanova.ai/apis",
}
SUGGESTED = ("groq", "cerebras", "google", "openrouter", "mistral")

# The four free providers set up in order by `setup-keys providers` (and menu item 1).
# match: words in FreeLLMAPI's provider name; check: the provider's own API, to test a pasted key.
CORE = [
    {"name": "Groq", "match": ("groq",), "url": "https://console.groq.com/keys",
     "how": "Sign in, click 'Create API Key', name it, copy it.",
     "check": ("https://api.groq.com/openai/v1/models", "bearer")},
    {"name": "Cerebras", "match": ("cerebras",), "url": "https://cloud.cerebras.ai/platform",
     "how": "Sign in, open 'API Keys', click 'Generate API Key', copy it.",
     "check": ("https://api.cerebras.ai/v1/models", "bearer")},
    {"name": "Google AI Studio", "match": ("google", "gemini"), "url": "https://aistudio.google.com/app/apikey",
     "how": "Sign in with Google, click 'Create API key', copy it.",
     "check": ("https://generativelanguage.googleapis.com/v1beta/models", "goog")},
    {"name": "OpenRouter", "match": ("openrouter",), "url": "https://openrouter.ai/settings/keys",
     "how": "Sign in, click 'Create Key', name it, copy it (it's shown only once).",
     "check": ("https://openrouter.ai/api/v1/key", "bearer")},
]


def check_key(c, key):
    """True if the provider itself accepts the key (a read-only 'list models' style call, free)."""
    url, kind = c["check"]
    h = {"Authorization": f"Bearer {key}"} if kind == "bearer" else {"x-goog-api-key": key}
    h["User-Agent"] = "setup-keys/1.0 (personal)"  # some providers' firewalls refuse Python's default
    r = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status == 200, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)

KEYS = {  # Keychain service -> what it is
    "freellmapi": "FreeLLMAPI unified key (local_llm's first, free tier)",
    "deepseek-api": "DeepSeek key (paid, optional)",
}


# ---------- Keychain ----------
def kc_get(service):
    p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def kc_set(service, secret):
    # -U updates an existing item. The secret goes on the command line of a local, short-lived
    # process; it is not written to any file or log.
    p = subprocess.run(["security", "add-generic-password", "-U", "-s", service, "-a", "local", "-w", secret],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"Error: couldn't save to the Keychain: {p.stderr.strip()}")


# ---------- small helpers ----------
def ask_secret(prompt):
    while True:
        s = getpass.getpass(prompt + " (hidden, Enter to skip): ").strip()
        if not s or len(s) >= 8:
            return s
        print("  That looks too short for a key. Try again, or press Enter to skip.")


def req(method, url, body=None, token=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json", "User-Agent": "setup-keys/1.0 (personal)"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": {"message": str(e)}}


def msg(d):
    return ((d or {}).get("error") or {}).get("message") or ""


def yes(prompt, default=True):
    a = input(f"{prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not a else a.startswith("y")


# ---------- status ----------
def status():
    for service, what in KEYS.items():
        print(f"  {'✓ set    ' if kc_get(service) else '· not set'}  {what}")
    code, d = req("GET", FREE + "/api/auth/status")
    print(f"  FreeLLMAPI server: {'running' if code == 200 else 'not reachable at ' + FREE}")


# ---------- FreeLLMAPI ----------
def freellmapi():
    code, st = req("GET", FREE + "/api/auth/status")
    if code != 200:
        print(f"FreeLLMAPI isn't answering at {FREE}. It should start at login (launchd: local.freellmapi).")
        return
    if st.get("needsSetup"):
        print("FreeLLMAPI has no login yet. Opening it: create your login there, then run this again.")
        webbrowser.open(FREE)
        return
    print("Sign in to your local FreeLLMAPI (used only for this run, not stored).")
    token = None
    for _ in range(3):
        email = input("  Dashboard email: ").strip()
        pw = getpass.getpass("  Dashboard password (hidden): ")
        code, d = req("POST", FREE + "/api/auth/login", {"email": email, "password": pw})
        if code == 200 and d.get("token"):
            token = d["token"]
            break
        print(f"  Sign-in failed: {msg(d) or code}")
    if not token:
        return

    code, d = req("GET", FREE + "/api/keys/providers", token=token)
    providers = [p for p in (d.get("providers") if isinstance(d, dict) else d) or [] if p.get("kind") == "chat"]
    if not providers:
        print(f"Couldn't list providers ({msg(d) or code}).")
        return
    by_name = lambda c: next((p for p in providers if any(w in (p["name"] + " " + p["platform"]).lower() for w in c["match"])), None)
    for i, c in enumerate(CORE, 1):
        p = by_name(c)
        print(f"\n[{i}/4] {c['name']}")
        if not p:
            print("  FreeLLMAPI doesn't list this provider; skipping.")
            continue
        if p.get("configured") and not yes("  Already has a key in FreeLLMAPI. Add another?", default=False):
            continue
        print(f"  Opening {c['url']}\n  {c['how']}")
        webbrowser.open(c["url"])
        while True:
            key = ask_secret(f"  Paste the {c['name']} key")
            if not key:
                print("  Skipped.")
                break
            ok, why = check_key(c, key)
            if not ok:
                print(f"  {c['name']} didn't accept that key ({why}). Check you copied all of it, then paste again.")
                continue
            code, d = req("POST", FREE + "/api/keys", {"platform": p["platform"], "key": key, "label": "setup-keys"}, token=token)
            print(f"  ✓ {c['name']} accepted it, and it's saved in FreeLLMAPI (encrypted)." if code in (200, 201)
                  else f"  Key works, but FreeLLMAPI didn't save it: {msg(d) or code}")
            break

    others = [p for p in providers if not any(by_name(c) is p for c in CORE)]
    keyless = [p for p in others if p.get("keyless") and not p.get("configured")]
    if keyless and yes(f"\nAlso turn on the {len(keyless)} free providers that need no key at all?"):
        code, d = req("POST", FREE + "/api/keys/keyless-available/enable", {}, token=token)
        print("  Done." if code in (200, 201, 204) else f"  Couldn't: {msg(d) or code}")

    # The unified key goes to the Keychain, where local_llm reads it.
    c, d = req("GET", FREE + "/api/settings/api-key", token=token)
    unified = d.get("apiKey") if c == 200 else ""
    if not unified:
        print(f"\nCouldn't read the unified key ({msg(d) or c}); copy it from the dashboard and run: setup-keys freellmapi")
        return
    kc_set("freellmapi", unified)
    c, d = req("POST", FREE + "/v1/chat/completions",
                {"model": "auto", "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 5},
                token=unified, timeout=60)
    reply = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") if c == 200 else ""
    print("\nUnified key saved to the Keychain (service 'freellmapi'). Test call: " +
          (f"worked ({reply.strip()[:20]!r})." if c == 200 else f"failed ({msg(d) or c}). Add at least one provider key."))
    req("POST", FREE + "/api/auth/logout", {}, token=token)


def unified():
    """Paste FreeLLMAPI's unified key (copied from its dashboard); checked, then saved."""
    key = ask_secret("Paste FreeLLMAPI's unified key")
    if not key:
        return
    c, d = req("GET", FREE + "/v1/models", token=key)
    if c != 200:
        print(f"  FreeLLMAPI didn't accept it ({msg(d) or c}). Not saved.")
        return
    kc_set("freellmapi", key)
    n = len(d.get("data") or [])
    c, d = req("POST", FREE + "/v1/chat/completions",
                {"model": "auto", "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 5},
                token=key, timeout=60)
    print(f"  ✓ Saved (Keychain 'freellmapi'). {n} models available. Test call: " +
          ("worked." if c == 200 else f"failed ({msg(d) or c}): add at least one provider key in the dashboard."))


# ---------- DeepSeek ----------
def deepseek():
    print("DeepSeek is NOT free: it spends a prepaid balance you load at platform.deepseek.com.")
    if not yes("Continue?", default=False):
        return
    key = ask_secret("  Paste the DeepSeek key")
    if not key:
        return
    c, d = req("GET", "https://api.deepseek.com/models", token=key)
    if c != 200:
        print(f"  DeepSeek didn't accept it ({msg(d) or c}). Not saved.")
        return
    kc_set("deepseek-api", key)
    print("  Saved (Keychain 'deepseek-api').")


def main(argv):
    actions = {"status": status, "freellmapi": freellmapi, "providers": freellmapi, "unified": unified,
               "deepseek": deepseek}
    if argv and argv[0] in actions:
        actions[argv[0]]()
        return 0
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    while True:
        print("\nAPI keys for the local tools:")
        status()
        print("\n  1. Free model keys: Groq, Cerebras, Google AI Studio, OpenRouter (into FreeLLMAPI)")
        print("  2. DeepSeek key (paid, optional)")
        print("  q. Quit")
        c = input("Choose: ").strip().lower()
        if c in ("q", ""):
            return 0
        {"1": freellmapi, "2": deepseek}.get(c, lambda: print("Pick 1, 2 or q."))()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing else was changed.")
