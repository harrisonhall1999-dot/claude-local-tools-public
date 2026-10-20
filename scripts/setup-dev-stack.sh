#!/bin/bash
# Rebuild the developer stack on this Mac (see docs/dev-stack.md). Safe to re-run: each step skips what exists.
#   scripts/setup-dev-stack.sh --dry-run   shows every step without running it
# Does NOT do: Xcode (App Store), sudo steps, accounts/secrets, REA refresh for Claude Desktop (quit it first).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }
have() { command -v "$1" >/dev/null 2>&1; }
step() { echo; echo "== $*"; }
GHIDRA="/opt/homebrew/opt/ghidra/libexec"

step "1. Homebrew packages"
run brew bundle --file "$ROOT/config/Brewfile.dev-stack"

step "2. Headroom (on-demand MCP tools only; do NOT start its proxy or set ANTHROPIC_BASE_URL)"
have headroom || run uv tool install --python 3.13 "headroom-ai[all]"
run headroom mcp install --agent claude

step "3. Python CLI tools (pipx)"
for p in "markitdown[pdf]" frida-tools; do
  pipx list --short 2>/dev/null | grep -qi "^${p%%[*}" || run pipx install "$p"
done

step "4. npm globals"
have rea || run npm install -g rea-agents@latest
have playwright-cli || run npm install -g @playwright/cli

step "5. Go language-server MCP binary (not registered; needs a project and a language server)"
have mcp-language-server || run env GOBIN="$HOME/.local/bin" go install github.com/isaacphi/mcp-language-server@latest

step "6. Scraping venv (curl_cffi for Chrome-like TLS, cryptography)"
[ -d "$HOME/.venvs/scraping" ] || run uv venv --python 3.13 "$HOME/.venvs/scraping"
run uv pip install --python "$HOME/.venvs/scraping/bin/python" curl_cffi cryptography

step "7. User-scope MCP servers for Claude Code"
existing="$(claude mcp list 2>/dev/null)"
add_mcp() { echo "$existing" | grep -q "^$1:" || run claude mcp add --scope user "$@"; }
add_mcp browser39 -- npx -y @aquintanar/browser39 mcp
add_mcp chrome-devtools -- npx -y chrome-devtools-mcp@latest
add_mcp playwright -- npx -y @playwright/mcp@latest

step "8. Ghidra location for REA"
grep -q GHIDRA_INSTALL_DIR "$HOME/.zprofile" 2>/dev/null || { echo "+ add GHIDRA_INSTALL_DIR to ~/.zprofile"; [ "$DRY" = 1 ] || printf '\n# Ghidra for REA\nexport GHIDRA_INSTALL_DIR="%s"\n' "$GHIDRA" >> "$HOME/.zprofile"; }

step "9. REA registrations (Claude Desktop is separate: quit it fully, then run rea setup --client claude_desktop --yes)"
export GHIDRA_INSTALL_DIR="$GHIDRA"
have rea && run rea setup --client claude_code --client antigravity --client gemini_cli --client hermes --yes

step "10. rtk hook for Claude Code (writes through the ~/.claude/CLAUDE.md symlink into config/global-CLAUDE.md)"
have rtk && run rtk init -g --auto-patch --no-trust-filters

step "11. Word add-in inspector (for inspecting Office.js add-ins)"
run defaults write com.microsoft.Word OfficeWebAddinDeveloperExtras -bool true

step "12. memcheck command"
run mkdir -p "$HOME/.local/bin"
run cp "$ROOT/scripts/memcheck" "$HOME/.local/bin/memcheck"

cat <<'MSG'

Still manual (see docs/dev-stack.md):
  - Xcode from the App Store, then: sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept
  - Link Java for Ghidra: sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-21.jdk
  - Privacy settings: Local Network for Claude (and Terminal if you scan from it)
  - Check anything that is already set up: scripts/verify-dev-stack.sh
MSG
[ "$DRY" = 1 ] || { echo; echo "== Verifying"; "$ROOT/scripts/verify-dev-stack.sh"; }
