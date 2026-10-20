# Claude Local Tools (public edition)

Tools on this Mac that make Claude cheaper, faster or more private. They do heavy or bulk work locally,
so Claude spends its context on judgment instead of raw reading.

## Easiest: let Claude Code install it for you

If you use Claude Code, you can hand it the whole setup (or just the pieces you pick) with one prompt. It follows this README, asks what you want,
shows a plan before changing anything, checks each step, and stops instead of guessing when something fails.

**Do these by hand first** (they need your password or a window):
1. Install Apple's command-line tools and Homebrew: `xcode-select --install`, then the Homebrew installer from https://brew.sh.
2. Install Claude Code and sign in (see Anthropic's Claude Code docs).
3. Clone this repo and open it in Claude Code with the recommended settings:
```bash
git clone https://github.com/harrisonhall1999-dot/claude-local-tools-public.git ~/Documents/claude-local-tools
cd ~/Documents/claude-local-tools
claude --model sonnet --effort medium --permission-mode manual
```

**Recommended settings, and why**
| Setting | Use | Why |
|---|---|---|
| Model | `sonnet` | Installing is mostly running listed commands and checking results; Sonnet is fast, and it costs about a fifth of the top-tier model (Fable 5.1 is priced at 5x Sonnet and adds nothing for installs). |
| Effort | `medium` | Enough to follow the checklist and read errors. Raise it only to debug a failure. |
| Permission mode | `manual` | Claude asks before each command, so nothing runs that you haven't seen. Never use `bypassPermissions` or `--dangerously-skip-permissions` for an install: it changes your system. When it asks about a harmless read-only command (like `df -h /` or `scripts/memcheck`) you can allow it for the session. |
| If something breaks | `claude --continue --model opus --effort high` | Resumes the same conversation with a stronger model for diagnosis. Switch back to Sonnet afterwards. |
| Before you start | Quit Chrome, Teams and Outlook | The install downloads a lot and the local model needs RAM. A Mac with 16 GB can freeze under load. |

**Paste this prompt** (edit the first line if you already know what you want, for example "Install only the core tools and the school group"):

```text
Set up Claude Local Tools on this Mac, from this repo folder. Install what I choose, nothing else. Follow these rules exactly.

SOURCE OF TRUTH
Read README.md ("Start here") and docs/dev-stack.md first. Use only the commands and scripts they name. Do not add installs, tweaks or "improvements".

STEP 0 - PREFLIGHT (read-only)
Run: sw_vers; uname -m; df -h /; memory_pressure | head -3; command -v brew uv ollama claude. Report it in five lines.
Stop and tell me if: the Mac is not Apple Silicon, free disk is under 15 GB, or Homebrew is missing (print the install command; do not run it).

STEP 1 - ASK WHAT I WANT, then wait for my answer (default A)
A. Core tools: OCR, local model offload, search, file conversion, study cards (README steps 4-8; about 12 GB).
B. School & law group (needs A): Canvas, Outlook, citation checker (python3 install.py --school).
C. Gemini connector (needs A): cloud Gemini through the Antigravity CLI; needs my own Google AI plan.
D. Developer stack, all or pieces (needs only Homebrew): D1 token savers (rtk, Headroom); D2 headless browsing (browser39, chrome-devtools, Playwright); D3 reverse engineering (REA + Ghidra); D4 linters; D5 mitmproxy.
For each choice tell me the disk it needs and whether it is already installed (check with command -v and brew list; skip what exists).

STEP 2 - PLAN
Before changing anything, print the exact commands in order with download sizes and wait for me to say "go". For D, run scripts/setup-dev-stack.sh --dry-run and show the output first.

SAFETY RULES
- Never run sudo and never ask for my password. When a step needs sudo (README step 10: Java link for Ghidra), print the command and wait until I say I ran it.
- Run only the steps I chose. Never run brew upgrade or brew uninstall, never pip install outside .venv, never npm install -g anything the README does not name.
- Before editing any config (~/.claude/settings.json, ~/.claude.json, the Claude Desktop config, ~/.zprofile), copy it to <name>.bak-<timestamp>, then edit in place.
- Symlinks: run ls -l first. Never mv or overwrite ~/.claude/CLAUDE.md or any symlink. install.py links ~/.claude/CLAUDE.md only if I have none; if I already have one, leave mine and tell me.
- One heavy job at a time (brew bundle, pip install, model download). Run scripts/memcheck before each: RED means stop; YELLOW means tell me to close Chrome, Teams and Outlook first.
- Never ask for, read or store passwords, tokens or API keys. I do every sign-in myself (Claude, agy, canvas-auth).
- Do not create repos, push to GitHub or publish anything.
- If a step fails: stop, show the last 20 lines of the error, say what you think happened, propose ONE fix, and retry at most once. Do not skip a check to keep going.

AFTER EACH STEP
Run that step's "Check" from the README and report PASS or FAIL in one line before moving on.

FINISH
Run .venv/bin/python scripts/check.py (prefix CLT_SCHOOL=1 if I chose B) and, if I chose D, scripts/verify-dev-stack.sh. Then tell me in plain words: what is installed, what failed, and what I still must do by hand (fully quit and reopen Claude Desktop with Cmd+Q; any sudo step; the Local Network permission; sign-ins; for D3, the Claude Desktop REA refresh). Start a new Claude Code session afterwards, because MCP servers load only at session start. Finally list how to undo each piece I installed.
```

**À la carte tips**
- You can re-run the prompt any time to add pieces later; it skips what is already installed.
- If you only want one tool, say so on the first line (for example "Only install the Gemini connector"); Claude will still do the core steps it depends on.
- Everything except the core is optional, and nothing here touches your accounts, your files or your existing Claude settings without a backup first.

## Start here: set everything up, in order

This is the whole path from a fresh Mac to every tool in this repo. Do the steps in order; each one ends with a check so you know it worked.
Steps 1-8 give you the core tools. Steps 9-10 are optional add-ons. Step 11 is the daily routine.

**What you need**
- An Apple Silicon Mac (M1 or newer) on a recent macOS. **16 GB of RAM is the practical minimum** for the local model.
- About **12 GB free disk** for the core (measured: Python packages 2.3 GB, local model 7.5 GB, speech models 1.6 GB). The dev stack adds more; Xcode, if you want it, is separate and large. Check with `df -h /`.
- Claude Desktop and/or Claude Code, signed in. You'll need your Mac password for a few steps.
- Optional accounts: a Google AI plan (only for the `gemini` tool), your school's Canvas and classic Outlook (only for the school group).

**1. Install Apple's command-line tools and Homebrew** (skip what you have)
```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Follow the "Next steps" Homebrew prints (it adds `brew` to your shell). Check: `brew --version`.

**2. Install Claude** (Claude Desktop and/or Claude Code) from Anthropic and sign in. Check: open it and send a message.

**3. Get this repo**
```bash
git clone https://github.com/harrisonhall1999-dot/claude-local-tools-public.git ~/Documents/claude-local-tools
cd ~/Documents/claude-local-tools
```
Keep the folder where it is; the tools point back to it.

**4. Install the system packages**
```bash
brew bundle --file config/Brewfile.local-tools
open -a Ollama     # start the Ollama app once so the local model service runs
```
Check: `ollama --version` and `pandoc --version`. (`antigravity-cli` in that file is only for the optional `gemini` tool.)

**5. Create the Python environment** (about 2.3 GB, a few minutes)
```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```
Check: `.venv/bin/python -c "import mcp; print('ok')"`.

**6. Download and build the local models** (about 7.5 GB; this is the slow step)
```bash
ollama pull gemma4:12b
ollama pull nomic-embed-text
ollama create gemma4-offload -f models/offload.Modelfile
ollama create gemma4-direct -f models/direct.Modelfile
```
Check: `ollama list` shows all four. The speech models (about 1.6 GB) and speaker models (about 50 MB) download by themselves the first time you transcribe something.

**7. Connect everything to Claude**
```bash
python3 install.py            # core tools
# or: python3 install.py --school    # also the school & law group (Canvas, Outlook, cite)
```
This registers the tools with Claude Code and Claude Desktop, links the skills, and puts commands such as `ocr` and `to-md` on your PATH. It is safe to re-run.
**Then fully quit Claude Desktop (Cmd+Q) and reopen it.** A running Desktop can overwrite its config.
Make sure `~/.local/bin` is on your PATH (`echo $PATH`); if not, add `export PATH="$PATH:$HOME/.local/bin"` to `~/.zprofile`.

**8. Check the install**
```bash
.venv/bin/python scripts/check.py            # add CLT_SCHOOL=1 in front if you used --school
```
It starts every tool and lists what it offers; it never loads the model. Then ask Claude: "use the local model to summarize this file" with a text file to try the offload.

**9. Optional connectors** (only what you want)
- **gemini** (cloud Gemini via Google's Antigravity CLI): run `agy` once and sign in with a Google AI plan. Never send confidential material through it.
- **canvas** (school group): run `canvas-auth`, then see its row in the table below. Classic Outlook is needed for **outlook** (not "New Outlook"); allow macOS Automation when asked.
- **cite** (school group) looks cases up through the CourtListener or Descrybe connectors in Claude, which you add in Claude's connector settings.

**10. Optional developer stack** (token savers, headless browsing, reverse engineering, linters)
```bash
scripts/setup-dev-stack.sh --dry-run     # read the plan first
scripts/setup-dev-stack.sh               # then run it (re-runnable)
```
It installs the packages in `config/Brewfile.dev-stack`, registers the MCP servers, and wires up REA and Ghidra. A few steps need you:
1. Link Java for Ghidra (asks for your password): `sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-21.jdk`
2. System Settings > Privacy & Security > **Local Network**: allow Claude (and Terminal if you scan networks from it).
3. For Claude Desktop's REA registration: quit Claude Desktop fully, then in a plain Terminal run `rea setup --client claude_desktop --yes`, then reopen it.
4. Check everything: `scripts/verify-dev-stack.sh`. Details are in `docs/dev-stack.md`.

**11. Daily routine on a Mac with limited RAM**
- Before a heavy job (big transcription, a batch through the local model, a large download, Ghidra), run `memcheck`. GREEN: go. YELLOW: one heavy job at a time and quit Chrome, Teams and Outlook first. RED: don't start; free memory or disk first.
- The local model unloads itself after 30 seconds, so it only uses RAM while working.
- After changing anything in this repo: `python3 install.py`, then `.venv/bin/python scripts/check.py`, then restart Claude Desktop.

**If something goes wrong**
| Symptom | Fix |
|---|---|
| Tools missing in Claude Desktop | Quit it fully (Cmd+Q), run `python3 install.py`, reopen. Run `scripts/check.py`. |
| "Is the Ollama app running?" | `open -a Ollama`, then retry. |
| Command not found (`ocr`, `to-md`) | Add `~/.local/bin` to PATH (step 7), open a new Terminal. |
| `install.py` says "skip ... a real file is there" | That path already holds your own file. Move it aside and re-run. |
| Mac is slow or frozen during a job | Quit big apps, run `memcheck`, and run one heavy job at a time. |
| Out of disk | `df -h /`; the model (7.5 GB) and Python packages (2.3 GB) are the big pieces. |

## What's here

| Tool | Kind | What it does for Claude |
|---|---|---|
| `ocr` | MCP server + `ocr`, `read-document`, `fetch-url`, `transcribe` commands + `transcribe` skill | Pulls text from PDFs, images (OCR), Word/PowerPoint/Excel files and web pages on this Mac, instead of spending vision tokens or a web fetch. Transcribes audio/video with Whisper large-v3-turbo into a timestamped transcript with speakers labelled (sherpa-onnx diarization), after asking for speaker count, names and key terms; names speakers with `rename_speakers`; offline, ~2-3 GB of RAM while running, can save long transcripts to a file. |
| `local-llm` | MCP server + `local-llm` command + skill | Hands bulk, mechanical reading (summaries, extraction, sorting) to the local Ollama model (`gemma4-offload`), so long documents never enter Claude's context. |
| `search` | MCP server (`index_docs`, `search_docs`) + `index-docs` command | Local hybrid search over your documents. Embeds a folder (Ollama `nomic-embed-text`) into a SQLite index with an FTS5 keyword index alongside, then ranks each query both by meaning and by exact words (BM25), fused with Reciprocal Rank Fusion. Exact section cites, case names and docket numbers that embeddings blur still come up, and Claude fetches what matters instead of reading whole folders. Falls back to keyword-only if Ollama is down. Indexing skips OCR (run `pdf_ocr` on scanned PDFs first). |
| `files` | MCP server (`convert`, `pdf_ocr`, `pdf_tool`, `to_markdown`, `fetch_media`) + `fetch-media` command | Local file/media utilities wrapping pandoc, ImageMagick, ocrmypdf, PyMuPDF, yt-dlp and gallery-dl: convert documents between Markdown/Word/HTML/PDF and images between HEIC/PNG/JPG/WebP/AVIF/SVG and more (a folder at a time, with resizing, or photos into one PDF), add a searchable text layer to scanned PDFs, split/merge/extract PDF pages, and download whatever is behind a link. `fetch_media` routes the URL itself: direct files are downloaded as-is, video/audio pages go to yt-dlp (~1,800 sites, playlists, resolution cap), image posts and galleries to gallery-dl. It can also save just the captions as a timestamped transcript (no Whisper), describe a link without downloading (each resolution with an estimated size), and use a logged-in browser session for login-walled media. Run in a terminal, `fetch-media` shows a menu of resolutions with sizes, audio (m4a or mp3) and captions, shows live progress, uses the copied link when run with no URL, and removes half-written files on Ctrl-C; `-y` or any `--kind` skips the menu. |
| `to_markdown` | `files` server tool + `to-md` command | Turns PDFs, Word/PowerPoint/Excel, EPUB, HTML and web pages into Markdown files on disk, keeping what legal accuracy depends on: headings, (a)/(1)/(A) paragraph markers, block quotes, italics, tables, Word footnotes, star paging, and `<!-- page N -->` markers for PDF pin cites. Each file gets a fidelity score (the share of the source's words that made it into the Markdown, checked against an independent text read), so a dropped passage shows up as a number. Text stays out of Claude's context; batches take folders and globs. Uses pandoc, pymupdf4llm, and curl_cffi to get past basic bot blocks. |
| `study` | MCP server (`make_anki`) | Builds an Anki deck (`.apkg`) from a list of cards, for bar/exam prep. |
| `cite` | MCP server (`extract_citations`, `verify_quotes`, `format_case`) | For journal tech edits. `extract_citations` parses every citation with eyecite (cases, short forms, id., supra, statutes, law reviews), reading Word footnotes directly, groups each short form under its authority, and flags likely R4.1/R10.9 and bad `supra note N` problems. `verify_quotes` checks every quotation in a draft word for word against the source PDFs/files and reports exact, near (with each difference) or not found, with the page. No model. Looking cases up needs the CourtListener or Descrybe connector. |
| `gemini` | MCP server (`gemini`, `gemini_batch`, `gemini_search`, `gemini_image`) + `gemini-offload` command + skill | Hands work to Gemini 3.8 Flash in the cloud via the Antigravity CLI (`agy`, Google AI Pro sign-in): bulk reading of **public** material (faster and stronger than the local model, no local RAM), multi-query Google search sweeps that come back as a compact list of links (not the default search; its quotes need checking), and image generation saved to a folder. The text leaves the Mac, so never confidential or unpublished work. |
| `canvas` | MCP server (`canvas_due`, `canvas_announcements`, `canvas_grades`, `canvas_course`, `canvas_read`, `canvas_files`, `canvas_sync`, `canvas_changes`, `canvas_status`, `canvas_api`) + `canvas` and `canvas-auth` commands + skill | Read-only Canvas LMS with your own sign-in (your Canvas session in Chrome, read fresh each run, for schools that block student tokens; or a personal access token): what's due across courses with submission status and missing work, announcements, grades per assignment group, module outlines, and any syllabus/page/assignment/discussion/quiz/file by URL or title as Markdown. `canvas_sync` mirrors each current course to `~/Documents/Canvas/<course>/` (Markdown + downloaded files, incl. files linked from pages) and logs changes between syncs (new announcements, due-date changes, grades posted, new files); `canvas schedule on` syncs every 4 h via launchd. Canvas text is fenced as untrusted data. Ideas from vishalsachdev/canvas-mcp and DMontgomery40/mcp-canvas-lms; no code copied. |
| `outlook` | MCP server (`ol_briefing`, `ol_search`, `ol_read`, `ol_thread`, `ol_attachments`, `ol_calendar`, `ol_free`, `ol_changes`, `ol_sync`) + `outlook` command | Read-only school mail and calendar from classic Outlook for Mac, for when the Microsoft 365 connector is blocked. Mail search reads Outlook's own database (read-only, works with Outlook closed); full messages, attachments and calendar details come over AppleScript. Calendar syncs expand recurring series (shared calendars included) into a local store and log added/moved/cancelled events. `outlook schedule on` syncs every 30 min via launchd and writes a daily Markdown briefing (events, changes, unread Focused mail, flagged). Store and briefings in `~/Library/Application Support/claude-local-tools/outlook/` (owner-only). Cannot send, move or delete. |

All are available in Claude Code and in the Claude Desktop app.

The **school & law group** (`canvas`, `outlook`, `cite`) installs only with `python3 install.py --school`; everything else is the core.

## Dev stack: token economy, headless tools, reverse engineering

Installed third-party tools (not built here) that cut Claude's token use and support the native-app and reverse-engineering builds.
Rebuild or check them with `scripts/setup-dev-stack.sh --dry-run` and `scripts/verify-dev-stack.sh`; packages are in `config/Brewfile.dev-stack`.
Details and manual steps: `docs/dev-stack.md`.

| Group | Tools | What it does for Claude |
|---|---|---|
| Token economy | `rtk`, Headroom | `rtk` is a Claude Code hook that condenses noisy shell output (`ls -la` 35k to 2.5k characters in testing). Headroom adds on-demand `headroom_compress` / `headroom_retrieve` MCP tools for big JSON and logs (about 42% smaller on a 300-row result). Its proxy stays off so prompt caching isn't broken. |
| Headless web and UI | browser39, chrome-devtools-mcp, Playwright MCP + `@playwright/cli` | Read web pages and debug UIs as text instead of screenshots: browser39 returns a table of contents with per-section token sizes, then only the section you ask for; DevTools returns computed CSS, network and console data as JSON; Playwright returns an accessibility snapshot with click handles. |
| Code and data navigation | `ast-grep`, `ripgrep`, `repomix --compress`, `duckdb`, `jq`, `markitdown`, `pdfcpu`, `pdftotext` | Find and skim code, data and documents without reading whole files (a 156k-character project packs to 46k). |
| Reverse engineering | **REA** (`rea-agents`), **Ghidra**, Hopper (free demo), `radare2`, `frida-tools`, `mitmproxy` | REA is an MCP server and skill that lets Claude inspect binaries, Electron/JS bundles, web captures and mobile packages; Ghidra (with Java 21) is the free decompiler it drives. Registered for Claude Code, Claude Desktop, Antigravity, Gemini CLI and Hermes. Use only on software you own or may analyze. |
| Quality | `ruff`, `shellcheck`, `actionlint`, `yamllint`, `swiftlint`, `xcbeautify`, `difftastic` | Free linters and build-output filters that catch bugs without spending tokens. Their auto-run hooks are built but off (`config/optional/`). |
| Mac guard | `memcheck` | GREEN/YELLOW/RED check of disk, RAM pressure and swap before heavy jobs (this Mac: 16 GB RAM, little free disk). |

## Ollama model variants

All layer the same `gemma4:12b` weights (built from `models/*.Modelfile`), so they add no real disk.
None touch the weights, so each keeps the base model's safety training; they only change tone and format.

| Model | For | Built from |
|---|---|---|
| `gemma4:12b` | the plain base model | — |
| `gemma4-direct` | talking to the model yourself — direct, no moralizing or boilerplate caveats on legitimate work | `models/direct.Modelfile` |
| `gemma4-offload` | the `local-llm` tool — returns only the requested artifact, invents nothing, says `NONE` when empty, low temperature for faithful extraction | `models/offload.Modelfile` |

Rebuild one after editing its Modelfile: `ollama create <name> -f models/<name>.Modelfile`.

## Layout

```
servers/<tool>/      one folder per MCP server (server.py, plus optional CLI scripts)
skills/<skill>/      Claude Code skills (SKILL.md) that say when and how to use the tools
config/global-CLAUDE.md  starter global Claude Code instructions (install.py links ~/.claude/CLAUDE.md here only if you have none)
models/*.Modelfile   Ollama model variants (system prompt + generation settings over gemma4:12b)
scripts/check.py     starts every server and lists its tools (never loads the model), checks skill headers
scripts/hooks/       Claude Code hook (.claude/settings.json): blocks a commit if check.py fails
install.py           connects everything to Claude Code, Claude Desktop, ~/.claude/skills and ~/.local/bin (command launchers)
requirements.txt     packages in the shared .venv
config/Brewfile.local-tools  system packages for the core tools (step 4 of the setup guide)
docs/dev-stack.md    the optional developer stack: what is installed and the manual steps (rebuild: scripts/setup-dev-stack.sh, config/Brewfile.dev-stack)
scripts/setup-dev-stack.sh   rebuilds the dev stack (idempotent; --dry-run shows the steps); config/Brewfile.dev-stack lists its packages
scripts/verify-dev-stack.sh  read-only check that the dev stack (incl. REA + Ghidra) is installed and healthy
scripts/memcheck     one-command disk/RAM/swap check with a GREEN/YELLOW/RED verdict (copy to ~/.local/bin)
config/optional/     built-but-off extras: lint/health hooks and headless-tools rules
```

## After you change something

```bash
python3 install.py
.venv/bin/python scripts/check.py
```
Then restart Claude Desktop. Claude Code picks up changes in new sessions.

Rebuilding the venv from scratch:
```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

## Outside this folder
- **Ollama app** (Homebrew cask `ollama-app`) with the `gemma4:12b` model and the variants above.
- **Whisper models** in `~/.cache/huggingface/hub` (`whisper-large-v3-turbo`, `whisper-base-mlx`), plus
  Homebrew `ffmpeg` for decoding audio.
- **Embedding model** `nomic-embed-text` in Ollama (~300 MB), for the `search` server.
- **The search index** at `~/.cache/claude-local-tools/search.db` (rebuild with `index-docs <folder>`).
- **Classic Outlook for Mac** (not New Outlook, which keeps no readable local database). The `outlook` tools need macOS Automation permission to control Outlook (asked on first use).
- **Canvas sign-in** at `~/.config/claude-local-tools/canvas.json` (owner-only). In the default Chrome mode it holds only the address and profile name: the tools read the Canvas cookies from Chrome on each run (Keychain "Chrome Safe Storage" prompt once; choose Always Allow), so if they say the session expired, sign in to Canvas in Chrome again. `--token` / `--cookie` modes store that secret here instead.
- **Canvas mirror** at `~/Documents/Canvas/` (override with `CANVAS_DATA`), with its change log in `.canvas.db` there.
- **Antigravity CLI** (`agy`, Homebrew cask `antigravity-cli`), signed in with the user's Google account (session in the macOS Keychain; re-run `agy` to sign in again). Used by the `gemini` server.
- **CLI tools** via Homebrew: `pandoc`, `imagemagick`, `ocrmypdf`, `yt-dlp`, `gallery-dl`, `qpdf`, `tesseract` (used by the `files` server).
  Sites change often, so if `fetch_media` starts failing on a site that used to work, `brew upgrade yt-dlp gallery-dl`.
- **Speaker-diarization models** in `~/.cache/sherpa-onnx` (pyannote segmentation 3.0, NeMo TitaNet small;
  ~50 MB, downloaded on first use).
- **`~/.claude/CLAUDE.md`** (a link to `config/global-CLAUDE.md`) has a "Local model offloading" section: when to offload, and to give a
  heads-up with a close-apps reminder first.
- **REA** (`npm i -g rea-agents`, v6.7.0) with its registration in each client's MCP config (`rea setup --client <name> --yes`; Claude Desktop must be fully quit first) and its skill in `~/.claude/skills/reverse-engineer-anything`. The registration carries `GHIDRA_INSTALL_DIR`, `HOPPER_LAUNCHER_PATH` and a versioned `JAVA_HOME`, so re-run `rea setup` after `brew upgrade openjdk@21`. Check with `rea doctor --client claude_code --json`.
- **Ghidra** 12.1.4 (Homebrew `ghidra`) at `/opt/homebrew/opt/ghidra/libexec`, exported as `GHIDRA_INSTALL_DIR` in `~/.zprofile`. It needs the one-time Java link: `sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-21.jdk`.
- **rtk hook** in `~/.claude/settings.json` (`PreToolUse` on Bash) and `~/.claude/RTK.md`, referenced from `config/global-CLAUDE.md`. Remove with `rtk init -g --uninstall`.
- **Headless MCP servers** (browser39, chrome-devtools, playwright, headroom) registered at user scope in `~/.claude.json`; the Headroom proxy is deliberately not running.
- **Scraping venv** `~/.venvs/scraping` (`curl_cffi`, `cryptography`), **mitmproxy** CA in `~/.mitmproxy` (trusted only while capturing; remove with `security delete-certificate -c mitmproxy`), and **Xcode** from the App Store (`sudo xcode-select -s /Applications/Xcode.app`).
