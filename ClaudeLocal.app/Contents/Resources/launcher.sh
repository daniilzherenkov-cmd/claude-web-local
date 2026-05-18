#!/bin/zsh
# Claude Local — launched by macOS Launch Services when the user
# double-clicks ClaudeLocal.app. Starts the local proxy and opens the browser.

set -u

BUNDLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RES="$BUNDLE_DIR/Resources"
LOG="$HOME/Library/Logs/ClaudeLocal.log"
mkdir -p "$(dirname "$LOG")"

PORT="${CLAUDE_WEB_PORT:-8765}"
URL="http://localhost:${PORT}/"

# Source the user's shell so ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL,
# /opt/homebrew/bin etc. are available. Errors silenced — if env is
# missing, the UI's Settings dialog handles it.
[ -f ~/.zshenv ] && source ~/.zshenv 2>/dev/null || true
[ -f ~/.zprofile ] && source ~/.zprofile 2>/dev/null || true
[ -f ~/.zshrc ] && source ~/.zshrc 2>/dev/null || true
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# ---------- Helper: show a macOS dialog and return the button label ----------
dialog() {
  # $1 = message, $2 = comma-separated button list, $3 = default button, $4 = icon (note|stop|caution)
  local msg="$1" buttons="$2" default="$3" icon="${4:-note}"
  osascript <<APPLESCRIPT 2>/dev/null
try
  set _r to display dialog "${msg}" buttons {${buttons}} default button "${default}" with icon ${icon} with title "Claude Local"
  return button returned of _r
on error
  return "Cancel"
end try
APPLESCRIPT
}

# ---------- Pre-flight: bundled venv ----------
VENV_PY="$RES/venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  dialog "Claude Local's bundled Python environment is missing.\n\nIf you cloned the repo, run:\n\n./build_venv.sh\n\nIf you downloaded a release, the .app bundle is incomplete — try a fresh download." "\"OK\"" "OK" stop >/dev/null
  exit 1
fi

# ---------- Pre-flight: port ----------
# If something already holds the port, distinguish "us" (already running)
# from "someone else". When it's us, just open the browser silently — no
# friction dialog. When it's something else, surface a clear error.
if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fsS --max-time 1 "${URL}api/config" 2>/dev/null | grep -q '"hasToken"'; then
    open "${URL}"
    exit 0
  else
    dialog "Port ${PORT} is already in use by another program.\n\nQuit that program first, or launch with a different port from Terminal:\n\nCLAUDE_WEB_PORT=9000 open '${BUNDLE_DIR%/Contents}'" "\"OK\"" "OK" stop >/dev/null
    exit 1
  fi
fi

# ---------- Run ----------
cd "$RES" || {
  dialog "Could not find Claude Local resources.\nThe app bundle may be damaged — try downloading a fresh copy." "\"OK\"" "OK" stop >/dev/null
  exit 1
}

{
  echo ""
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  echo "PORT=${PORT}"
  echo "ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-(unset)}"
  echo "ANTHROPIC_AUTH_TOKEN=$([ -n "${ANTHROPIC_AUTH_TOKEN:-}" ] && echo "(set)" || echo "(unset)")"
} >> "$LOG"

# server.py opens the browser itself via webbrowser.open. stdout/stderr
# go to the log so the .app stays silent. If startup fails, surface it.
if ! "$VENV_PY" server.py >> "$LOG" 2>&1; then
  TAIL=$(tail -10 "$LOG" | sed 's/"/\\"/g')
  dialog "Claude Local failed to start.\n\nLast lines from the log:\n\n${TAIL}\n\nFull log: ~/Library/Logs/ClaudeLocal.log" "\"OK\"" "OK" stop >/dev/null
  exit 1
fi
