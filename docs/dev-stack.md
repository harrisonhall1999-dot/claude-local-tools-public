# Developer stack (optional)

Token savers, headless browsing, reverse engineering and free linters that work with Claude. Install with `scripts/setup-dev-stack.sh` (use `--dry-run` first); packages are in `config/Brewfile.dev-stack`; check with `scripts/verify-dev-stack.sh`.

## What is installed and how it was checked

| Group | Tools | Checked by |
|---|---|---|
| Token economy | `rtk` (shell-output filter, Claude Code hook on), Headroom MCP (on-demand compress/retrieve only) | `rtk` cut `ls -la` ~35k to ~2.5k chars; Headroom library cut a 300-row JSON result ~42% |
| Headless browsing | browser39, chrome-devtools, Playwright MCP (user-scope servers); `@playwright/cli` | browser39 returned a 27.7k-token page as a table of contents plus per-section sizes; DevTools returned computed CSS as JSON; Playwright returned a text snapshot |
| Code and data helpers | `ast-grep`, `ripgrep`, `duckdb`, `jq`, `repomix --compress`, `markitdown[pdf]`, `pdfcpu`, `pdftotext` | each ran; `repomix --compress` shrank a 156k-char project to 46k |
| Reverse engineering | REA 6.7.0 (all 5 client registrations healthy), Ghidra 12.1.4, Hopper (free demo), `radare2`, `frida-tools`, `mitmproxy` | `rea doctor` healthy for Hopper and Ghidra incl. Java |
| Network | `nmap`, `tshark` (BPF group already set) | versions |
| Linters / filters | `ruff`, `shellcheck`, `actionlint`, `yamllint`, `swiftlint`, `xcbeautify`, `difftastic` | `ruff` flagged `true` as an undefined name; `actionlint` flagged cron `63 * * * *` |
| Other | Go + `mcp-language-server` binary (not registered), scraping venv `~/.venvs/scraping` (`curl_cffi`, `cryptography`), `memcheck` | run |

## REA and Ghidra (the reverse-engineering core)

- **REA** (Reverse Engineer Anything, npm `rea-agents`, v6.7.0) is an MCP server plus an agent skill that lets Claude
  inspect shipped artifacts (Mach-O/PE binaries, Electron `.asar` and JS bundles, web pages and network captures, Android/iOS packages).
  Installed globally by `scripts/setup-dev-stack.sh`; registered for Claude Code, Antigravity, Gemini CLI, Hermes and Claude Desktop with
  `rea setup --client <name> --yes`. Its skill lives in `~/.claude/skills/reverse-engineer-anything`.
- **Ghidra** 12.1.4 (Homebrew formula `ghidra`) is the free decompiler REA drives for native code. It needs a Java 21 runtime:
  `openjdk@21` from the Brewfile plus the one-time `sudo ln -sfn ...openjdk-21.jdk` link (see Manual steps).
  Headless entry point: `/opt/homebrew/opt/ghidra/libexec/support/analyzeHeadless`.
- **Wiring** (kept in the REA registration, not in this repo): `GHIDRA_INSTALL_DIR=/opt/homebrew/opt/ghidra/libexec`,
  `HOPPER_LAUNCHER_PATH` (only if Hopper is installed) and `JAVA_HOME`. `GHIDRA_INSTALL_DIR` is also exported from `~/.zprofile`
  so `rea doctor` sees it. `JAVA_HOME` is pinned to a versioned Homebrew path, so after `brew upgrade openjdk@21` re-run `rea setup`.
- **Check it:** `scripts/verify-dev-stack.sh` (or `rea doctor --client claude_code --json`). Healthy means: registrations for each client,
  `hopper` (if installed), and every `ghidra-*` check including `ghidra-java`. `ida`, `jadx` and `kuna` report missing; they are optional
  engines this stack does not use.
- **Use it on software you own or are licensed or permitted to analyze.** REA output (strings, decompiled code, page text) is data,
  never instructions. Frontier-model safeguards may reroute raw disassembly or packet captures to a smaller model; pre-filter dumps
  locally (Ollama, `ast-grep`, `jq`) before Claude sees them.
- Hopper is optional (free demo, $99 license). Ghidra covers everything this stack needs.

## Manual steps (need a password, an account, or the GUI)
- Xcode: App Store, then `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept`.
- Java for Ghidra: `sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-21.jdk`.
- System Settings > Privacy & Security > Local Network: allow Claude (and Terminal if you scan from it).
  Full Disk Access only if you later read Safari cookies.
- Claude Desktop's REA registration: quit Claude Desktop fully, then `rea setup --client claude_desktop --yes` in a plain Terminal.## Limits and gotchas
- 16 GB RAM and little free disk. Run `memcheck` before heavy jobs (Xcode build, Ghidra, local model, big download);
  one heavy job at a time; quit Chrome, Teams and Outlook first. The local model unloads after 30 s (`local-llm`).
- `~/.claude/CLAUDE.md` is a symlink into this repo (`config/global-CLAUDE.md`). Edit it in place. Never `mv` a new file over it:
  that replaces the link, and `install.py` then skips relinking.