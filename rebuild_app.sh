#!/bin/zsh
# Sync the latest server.py + index.html into ClaudeLocal.app/Contents/Resources.
# Run after editing either file.

set -e
cd "$(dirname "$0")"

if [ ! -d ClaudeLocal.app ]; then
  echo "ClaudeLocal.app not found here." >&2
  exit 1
fi

cp server.py index.html ClaudeLocal.app/Contents/Resources/
[ -f AppIcon.icns ] && cp AppIcon.icns ClaudeLocal.app/Contents/Resources/AppIcon.icns
chmod +x ClaudeLocal.app/Contents/MacOS/run

# Reset the quarantine bit so Gatekeeper doesn't re-flag it after edits.
# macOS xattr has no recursive flag; iterate via find.
find ClaudeLocal.app -exec xattr -d com.apple.quarantine {} \; 2>/dev/null || true

# Bump the bundle's mtime so Finder refreshes its icon cache.
touch ClaudeLocal.app

echo "ClaudeLocal.app rebuilt."
