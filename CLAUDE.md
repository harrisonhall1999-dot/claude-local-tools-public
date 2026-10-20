# Claude Local Tools

@README.md

## Goal
Add tools to a Mac that work *with* Claude: tools that take over work Claude would otherwise
spend context, vision tokens or round trips on (bulk reading, OCR, transcription, local inference,
file conversion), or that give Claude access to local apps and data. A tool earns its place only if
it saves Claude more than it costs to call and check.

## Assumptions
Apple Silicon Mac. The local Ollama model takes about 8 GB of RAM, so on a 16 GB Mac, running it next to
Teams, Outlook and Chrome can push the Mac into heavy swap.
- Prefer tools that load lazily and release memory when they're done.
- Before running anything that loads a model (Ollama, PaddleOCR, Whisper), give the user a one-line
  heads-up with a reminder to close big apps, then proceed.
- Watch disk space: check `df -h /` before downloading models.

## Adding a tool
1. If something good already exists (Homebrew, an official MCP server), install that instead of building it.
2. Otherwise add `servers/<name>/server.py`, an MCP server using `mcp.server.mcpserver.MCPServer`, like
   the existing ones. Add a CLI script too when Claude Code would want to call it from Bash.
3. Use the shared `.venv`: `uv pip install --python .venv/bin/python <pkg>`, then
   `.venv/bin/python -m pip freeze > requirements.txt`. Use `.venv/bin/python -m ...` rather than the venv's entry scripts.
4. Write tool docstrings for Claude: when to use it, when not to, cost/speed, and how to pass files by
   path so their contents stay out of Claude's context.
5. If Claude needs judgment about *when* to use the tool, add `skills/<name>/SKILL.md`.
6. Register the server and any CLI scripts in `install.py` (`SERVERS`, `COMMANDS`), then run
   `python3 install.py` and `.venv/bin/python scripts/check.py`.
7. Update the README table.

## Conventions
- Paths inside the project are relative to the file (`os.path.dirname(__file__)`), never hard-coded
  home paths, so the folder can move.
- Tools return `"Error: ..."` strings instead of raising, so Claude sees what went wrong.
- Test without loading models when possible (`scripts/check.py`). For a real model run, use tiny inputs.
- A Claude Code hook (`.claude/settings.json`) runs `scripts/check.py` before every `git commit` made through Claude and blocks it on failure.
