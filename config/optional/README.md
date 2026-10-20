# Optional extras (off by default)

Built and tested, but nothing here is loaded unless you wire it up.

- `headless-tools.md`: rules telling Claude to prefer cheap local tools and to run `memcheck` before heavy jobs.
  Turn on: copy it to `~/.claude/` and add a line `@headless-tools.md` to your `~/.claude/CLAUDE.md`.
- `hooks/lint-on-edit.sh`: PostToolUse hook; runs ruff / shellcheck / actionlint / yamllint / swiftlint after Claude edits a file and feeds real errors back.
- `hooks/health-check.sh`: SessionStart hook; warns when disk is under 5 GB or memory is under pressure.
  Turn on: copy both scripts to `~/.claude/hooks/` and add them to `~/.claude/settings.json` under `hooks.PostToolUse` (matcher `Edit|Write|MultiEdit`) and `hooks.SessionStart`.
