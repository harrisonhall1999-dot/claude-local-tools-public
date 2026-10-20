# Token economy and Mac limits (applies automatically)

Assume a low-RAM, low-disk Mac and a beginner user. Keep this short and act on it without asking.

## Use cheap local tools before reading or reasoning
- Find code with `rg` or `ast-grep` before opening files; read only the lines needed.
- Big data (JSON/CSV over ~100 lines): use `jq` or `duckdb -c`; never paste it into context.
- Web pages: browser39 (headings first, then one section) instead of WebFetch or screenshots. Debug front ends with chrome-devtools or the Playwright snapshot, not screenshots.
- PDFs and Office files: `pdftotext`, `markitdown` or the `to_markdown` tool, then grep.
- Noisy commands: `rtk` filters automatically; pipe Xcode builds through `xcbeautify -q`; use quiet flags on tests.
- Bulk summarizing or classifying of non-confidential text: `local_llm`; spot-check the result and say it came from the local model.
- Linters run automatically after each edit (Python, shell, workflow YAML, Swift). Fix what they report; don't re-run them by hand.
- Do not turn on the Headroom proxy or set ANTHROPIC_BASE_URL (it breaks prompt caching). Headroom MCP tools are on demand only.

## Protect the machine (swap and disk)
- Before any heavy job (xcodebuild, Ghidra or REA binary analysis, local-model batch, transcription, big download), run `memcheck`.
  - GREEN: go ahead. YELLOW: one heavy job only, and tell the user to quit Chrome, Teams and Outlook first. RED: do not start; tell the user exactly what to close or free.
- Never run two heavy jobs at once. The local model unloads itself after 30 seconds; do not change that.
- If a session-start note says disk or memory is low, tell the user in one sentence before starting work.
- Tell the user before anything that downloads more than about 1 GB.
