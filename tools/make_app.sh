#!/usr/bin/env bash
# Adds an "employMint" app that opens the daily review page: no terminal, no commands to remember.
#   macOS: ~/Applications/employMint.app (find it with Spotlight or Launchpad; drag it to the Dock)
#   Linux: an "employMint" entry in your applications menu
# The app starts the review page in the background if it isn't running, then opens it in your browser.
# install.sh runs this. Run it again if you move the employMint folder.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"
PY="${1:-python3}"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
PY_ABS="$(command -v "$PY")"
mkdir -p data

case "$(uname)" in
  Darwin)
    # An AppleScript app (osacompile), so macOS can ask once for access to the folder employMint lives in
    # (Documents, Desktop and Downloads are protected) and remember the answer. It runs launch.sh, kept inside the app.
    APP="$HOME/Applications/employMint.app"
    rm -rf "$APP"
    mkdir -p "$HOME/Applications"
    osacompile -o "$APP" -e \
      'do shell script "/bin/bash " & quoted form of (POSIX path of (path to me) & "Contents/Resources/launch.sh")'
    LAUNCH="$APP/Contents/Resources/launch.sh"
    {
      echo '#!/bin/bash'
      echo 'LOG="$HOME/Library/Logs/employMint.log"  # outside Documents, so it can always be written'
      printf 'export PATH=%q\n' "$PATH"  # so "Find today's jobs" can find the claude command
      printf 'cd %q 2>>"$LOG" || exit 1\n' "$ROOT"
      printf 'exec %q src/review.py --detach </dev/null >>"$LOG" 2>&1\n' "$PY_ABS"
    } > "$LAUNCH"
    chmod +x "$LAUNCH"
    # Icon: the website's leaf favicon at app-icon sizes. Skipped quietly if a tool is missing.
    TMP="$(mktemp -d)"
    if qlmanage -t -s 1024 -o "$TMP" site/favicon.svg >/dev/null 2>&1 && [ -f "$TMP/favicon.svg.png" ]; then
      mkdir "$TMP/applet.iconset"
      for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$TMP/favicon.svg.png" --out "$TMP/applet.iconset/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$TMP/favicon.svg.png" --out "$TMP/applet.iconset/icon_${s}x${s}@2x.png" >/dev/null
      done
      iconutil -c icns "$TMP/applet.iconset" -o "$APP/Contents/Resources/applet.icns" 2>/dev/null || true
    fi
    rm -rf "$TMP"
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.github.employmint.review" "$APP/Contents/Info.plist" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.github.employmint.review" "$APP/Contents/Info.plist"
    codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true  # re-sign after adding files, so macOS remembers "Allow"
    touch "$APP"
    echo "Added $APP. Open it from Spotlight or Launchpad, or drag it to your Dock."
    echo "The first time, macOS may ask to let employMint use this folder: click Allow."
    ;;
  Linux)
    DESK="$HOME/.local/share/applications/employmint.desktop"
    mkdir -p "$(dirname "$DESK")"
    cat > "$DESK" <<DESKTOP
[Desktop Entry]
Type=Application
Name=employMint
Comment=Open your daily internship review
Exec=bash -c 'cd "$ROOT" && "$PY_ABS" src/review.py --detach'
Icon=$ROOT/site/favicon.svg
Terminal=false
Categories=Office;
DESKTOP
    echo "Added employMint to your applications menu."
    ;;
  *)
    echo "No app for this system; open the review page with: python3 src/review.py"
    ;;
esac
