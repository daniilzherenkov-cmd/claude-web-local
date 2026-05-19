#!/bin/zsh
# Rebuild ClaudeLocal.app as an AppleScript-based launcher.
# Why AppleScript: macOS only re-runs the .app's main executable for proper
# Cocoa apps (which AppleScript applets are). Shell-script .apps get launch
# events coalesced, so a second double-click would silently do nothing.
#
# This script wraps the existing shell launcher in an AppleScript that:
#   - on run    : start the server, then open the browser
#   - on reopen : if server already running, just open the browser
#
# Run after editing the AppleScript or after a fresh clone. Idempotent.

set -e
cd "$(dirname "$0")"

APP=ClaudeLocal.app
SCRIPT=applescript_launcher.applescript

if [ ! -f "$SCRIPT" ]; then
  echo "Missing $SCRIPT" >&2
  exit 1
fi

# Stash assets we want to preserve across the rebuild.
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$TMPDIR/keep"

if [ -d "$APP/Contents/Resources" ]; then
  for f in venv server.py index.html AppIcon.icns; do
    if [ -e "$APP/Contents/Resources/$f" ]; then
      mv "$APP/Contents/Resources/$f" "$TMPDIR/keep/"
    fi
  done
fi
# The shell launcher (formerly Contents/MacOS/run, now Contents/Resources/launcher.sh)
if [ -f "$APP/Contents/Resources/launcher.sh" ]; then
  mv "$APP/Contents/Resources/launcher.sh" "$TMPDIR/keep/launcher.sh"
elif [ -f "$APP/Contents/MacOS/run" ]; then
  mv "$APP/Contents/MacOS/run" "$TMPDIR/keep/launcher.sh"
fi

# Compile AppleScript -> .app
rm -rf "$APP"
osacompile -o "$APP" "$SCRIPT"

# Restore kept assets
mkdir -p "$APP/Contents/Resources"
for f in "$TMPDIR/keep"/*; do
  [ -e "$f" ] && mv "$f" "$APP/Contents/Resources/"
done
chmod +x "$APP/Contents/Resources/launcher.sh"

# osacompile adds an ad-hoc code signature, but we then add files without
# re-signing. A broken/mismatched signature makes macOS show "damaged and
# can't be opened" instead of the bypassable "unidentified developer" dialog.
# Removing the signature entirely gives the latter, which right-click → Open fixes.
codesign --remove-signature "$APP" 2>/dev/null || true

# Patch Info.plist for our identity & icon. osacompile sets generic values.
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName 'Claude Local'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleName string 'Claude Local'" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 'Claude Local'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 'Claude Local'" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier 'com.deliveryhero.claudelocal'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string 'com.deliveryhero.claudelocal'" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile 'AppIcon'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string 'AppIcon'" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString '2.0.0'" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string '2.0.0'" "$PLIST"
# Don't keep the AppleScript icon
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PLIST" 2>/dev/null || true

# Reset Finder's icon cache for this bundle so the new icon shows up.
touch "$APP"

echo "$APP rebuilt as AppleScript launcher."
echo "Try double-clicking it now; subsequent double-clicks will reopen the browser."
