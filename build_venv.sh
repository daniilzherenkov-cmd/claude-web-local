#!/bin/zsh
# Build the bundled Python venv inside ClaudeLocal.app.
# Run this once after cloning, and again whenever Python deps change.
# The venv is ~250MB and is git-ignored.

set -e
cd "$(dirname "$0")"

VENV="ClaudeLocal.app/Contents/Resources/venv"
PY313="/opt/homebrew/opt/python@3.13/bin/python3.13"

if [ ! -x "$PY313" ]; then
  echo "python3.13 not found at $PY313" >&2
  echo "Install with:  brew install python@3.13" >&2
  exit 1
fi

echo "Building venv at $VENV"
rm -rf "$VENV"
"$PY313" -m venv "$VENV"

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet claude-agent-sdk aiohttp

# Trim bytecode caches and tests to shrink the bundle.
find "$VENV" -name '*.pyc' -delete 2>/dev/null || true
find "$VENV" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$VENV" -name 'tests' -type d -prune -exec rm -rf {} + 2>/dev/null || true

SIZE=$(du -sh "$VENV" | cut -f1)
echo ""
echo "Venv built. Size: $SIZE"
echo "Test it:  $VENV/bin/python -c 'import claude_agent_sdk; print(claude_agent_sdk.__name__)'"
