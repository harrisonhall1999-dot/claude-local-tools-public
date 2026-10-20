#!/bin/bash
# PostToolUse hook: after Claude edits a file, run the matching free linter.
# Silent when clean. On real errors, prints them to stderr and exits 2 so Claude sees and fixes them.
f=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -n "$f" ] && [ -f "$f" ] || exit 0
out=""
case "$f" in
  *.py)    out=$(ruff check --select E9,F --output-format concise --no-cache "$f" 2>&1 | grep -v '^All checks passed' | grep -v '^Found ') ;;
  *.sh|*.bash) out=$(shellcheck -f gcc -S warning "$f" 2>&1) ;;
  */.github/workflows/*.yml|*/.github/workflows/*.yaml) out=$(actionlint "$f" 2>&1) ;;
  *.yml|*.yaml) out=$(yamllint -d '{extends: relaxed, rules: {line-length: disable}}' -f parsable "$f" 2>&1 | grep -i ' error') ;;
  *.swift) out=$(swiftlint lint --quiet --no-cache "$f" 2>&1 | grep ' error: ') ;;
  *) exit 0 ;;
esac
[ -z "$out" ] && exit 0
printf 'Linter found problems in %s (fix them):\n%s\n' "$f" "$(printf '%s\n' "$out" | head -n 25)" >&2
exit 2
