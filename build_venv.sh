#!/bin/zsh
# Build the bundled Python venv inside ClaudeLocal.app.
# Run this once after cloning, and again whenever Python deps change.
# The venv is ~250MB and is git-ignored.

set -e
cd "$(dirname "$0")"

VENV="ClaudeLocal.app/Contents/Resources/venv"

# Find Python 3.10+ — try common locations for Homebrew installs.
PY=""
for candidate in \
    /opt/homebrew/opt/python@3.13/bin/python3.13 \
    /opt/homebrew/opt/python@3.12/bin/python3.12 \
    /opt/homebrew/opt/python@3.11/bin/python3.11 \
    /opt/homebrew/opt/python@3.10/bin/python3.10 \
    /usr/local/opt/python@3.13/bin/python3.13 \
    /usr/local/opt/python@3.12/bin/python3.12 \
    python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  elif [ -x "$candidate" ]; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "" >&2
  echo "Python 3.10 or newer is required but not found." >&2
  echo "Install with Homebrew:" >&2
  echo "    brew install python@3.13" >&2
  echo "" >&2
  echo "If you don't have Homebrew:" >&2
  echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" >&2
  echo "" >&2
  exit 1
fi

echo "Using Python: $PY ($(${PY} --version))"
echo "Building venv at $VENV"
rm -rf "$VENV"
"$PY" -m venv "$VENV"

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
