#!/bin/zsh
# First-time installer for Claude Local.
# Right-click this file → Open → click "Open" in the security dialog.
# The script removes the macOS quarantine flag from ClaudeLocal.app and
# launches it. After this, you can double-click ClaudeLocal.app directly.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/ClaudeLocal.app"

if [ ! -d "$APP" ]; then
  osascript -e 'display dialog "ClaudeLocal.app not found.\n\nMake sure Install.command and ClaudeLocal.app are in the same folder." buttons {"OK"} default button "OK" with icon stop with title "Claude Local"'
  exit 1
fi

echo "Removing macOS quarantine flag from ClaudeLocal.app..."
xattr -d com.apple.quarantine "$APP" 2>/dev/null || true
find "$APP" -exec xattr -d com.apple.quarantine {} \; 2>/dev/null || true

echo "Done. Launching Claude Local..."
open "$APP"
