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
    # Drawn with the same margin as other Mac app icons, then used in place of the AppleScript scroll icon.
    TMP="$(mktemp -d)"
    # Chrome (via Playwright, which employMint already uses) draws it with transparent corners.
    "$PY_ABS" - "$TMP/icon.svg.png" <<'PYICON' >/dev/null 2>&1 || true
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
svg = Path("site/favicon.svg").read_text().replace('viewBox="0 0 24 24"', 'viewBox="-2.4 -2.4 28.8 28.8" width="1024" height="1024"')
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1024, "height": 1024})
    page.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
    page.screenshot(path=sys.argv[1], omit_background=True)
    browser.close()
PYICON
    if [ -f "$TMP/icon.svg.png" ]; then
      mkdir "$TMP/applet.iconset"
      for s in 16 32 128 256 512; do
        sips -z "$s" "$s" "$TMP/icon.svg.png" --out "$TMP/applet.iconset/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$TMP/icon.svg.png" --out "$TMP/applet.iconset/icon_${s}x${s}@2x.png" >/dev/null
      done
      if iconutil -c icns "$TMP/applet.iconset" -o "$APP/Contents/Resources/applet.icns" 2>/dev/null; then
        rm -f "$APP/Contents/Resources/Assets.car"  # newer macOS reads this icon catalog first; it holds the scroll
        /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
      fi
    fi
    rm -rf "$TMP"
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.github.employmint.review" "$APP/Contents/Info.plist" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.github.employmint.review" "$APP/Contents/Info.plist"
    codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true  # re-sign after adding files, so macOS remembers "Allow"
    touch "$APP"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" \
      >/dev/null 2>&1 || true  # refresh the icon Finder and the Dock show
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
