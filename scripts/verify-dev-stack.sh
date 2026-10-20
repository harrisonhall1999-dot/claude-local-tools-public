#!/bin/bash
# Checks that the dev stack from docs/dev-stack.md is installed and healthy. Read-only; changes nothing.
# Exit code = number of problems found.
bad=0
ok()   { printf '  ok    %s\n' "$1"; }
miss() { printf '  MISS  %s\n' "$1"; bad=$((bad+1)); }
for c in rtk headroom ast-grep rg duckdb jq repomix pdfcpu markitdown ruff shellcheck actionlint yamllint swiftlint xcbeautify difft \
         ghidraRun r2 cmake pkg-config go rea playwright-cli frida nmap tshark mitmdump claude; do
  command -v "$c" >/dev/null 2>&1 && ok "$c" || miss "$c not on PATH"
done
[ -n "${GHIDRA_INSTALL_DIR:-}" ] || export GHIDRA_INSTALL_DIR="/opt/homebrew/opt/ghidra/libexec"
if command -v rea >/dev/null 2>&1; then
  echo "REA doctor:"
  rea doctor --client claude_code --json 2>/dev/null | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("  MISS  rea doctor gave no JSON"); sys.exit(3)
want = ("registration:claude_code", "ghidra", "ghidra-java", "ghidra-headless", "ghidra-native_decompiler")
bad = 0
for c in d.get("scope_checks", []) + d.get("informational_checks", []):
    if c["name"] in want:
        print("  %-5s %s" % ("ok" if c["ok"] else "MISS", c["name"]))
        bad += 0 if c["ok"] else 1
sys.exit(bad)'
  bad=$((bad + $?))
fi
echo; [ "$bad" -eq 0 ] && echo "All good." || echo "$bad problem(s) found."
exit "$bad"
