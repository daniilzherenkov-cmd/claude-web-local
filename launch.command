#!/bin/zsh
# Double-click to launch the local Claude web UI.
# Starts the local proxy server (server.py) and opens the browser.

set -e
cd "$(dirname "$0")"

# Source the same env Claude Code uses, so ANTHROPIC_AUTH_TOKEN /
# ANTHROPIC_BASE_URL are picked up automatically. Errors are ignored —
# if the env vars aren't set, the user will see a Settings dialog.
[ -f ~/.zshrc ] && source ~/.zshrc 2>/dev/null || true
[ -f ~/.zprofile ] && source ~/.zprofile 2>/dev/null || true

# Pick a python3 — macOS ships one at /usr/bin/python3 (Xcode CLT).
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed. Install Xcode Command Line Tools:"
  echo "    xcode-select --install"
  echo "Then double-click this file again."
  read -k 1 "?Press any key to close..."
  exit 1
fi

echo "Starting Claude web UI on http://localhost:${CLAUDE_WEB_PORT:-8765}/"
echo "Close this Terminal window to stop the server."
echo ""

exec python3 server.py
