#!/usr/bin/env bash
# One-time setup for employMint on macOS or Linux (on Windows, run it inside WSL).
# Installs the one Python package it needs, checks for Google Chrome, and creates profile/ from the sample.
# Safe to run again: it never overwrites an existing profile/.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

say "Checking Python (3.9 or newer)"
command -v python3 >/dev/null || fail "python3 not found. Install Python 3.9+ from python.org, then run ./install.sh again."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "Python $(python3 -V 2>&1) is too old; 3.9 or newer is needed."
python3 -V

say "Installing Python packages"
PY=python3
PIP_LOG="$(mktemp)"
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import playwright' 2>/dev/null; then
  echo "playwright already installed in .venv"
  PY=.venv/bin/python
elif python3 -c 'import playwright' 2>/dev/null; then
  echo "playwright already installed"
elif python3 -m pip install --user --quiet -r requirements.txt 2>"$PIP_LOG"; then
  echo "installed for your user"
else
  echo "A user install didn't work, so using a project virtual environment (.venv)."
  if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv 2>>"$PIP_LOG" || {
      rm -rf .venv  # only the half-built folder this step just tried to create
      cat "$PIP_LOG" >&2
      fail "Couldn't create a virtual environment. On Debian/Ubuntu: sudo apt install python3-venv, then run ./install.sh again."
    }
  fi
  .venv/bin/python -m pip install --quiet --upgrade pip 2>/dev/null || true
  .venv/bin/python -m pip install --quiet -r requirements.txt || { cat "$PIP_LOG" >&2; fail "pip couldn't install requirements.txt (see above). Check your internet connection and run ./install.sh again."; }
  PY=.venv/bin/python
fi
rm -f "$PIP_LOG"

say "Looking for Google Chrome"
"$PY" -c 'import sys; sys.path.insert(0, "src"); import me; print(me.chrome_path())' \
  || fail "Install Google Chrome (not Chromium) from google.com/chrome, then run ./install.sh again."

say "Setting up your profile folder"
if [ -d profile ]; then
  echo "profile/ already exists; leaving it alone."
else
  cp -R examples/profile profile
  rm -f profile/README.md
  echo "Created profile/ from the sample applicant. Your AI assistant will replace it with your details."
fi
"$PY" src/profile_check.py || echo "(The profile check found problems; your AI assistant fixes them during setup.)"

say "Done. Next:"
if [ "$PY" != python3 ]; then
  echo "  0. Packages are in .venv/: use .venv/bin/python in place of python3 (AGENTS.md tells your assistant)."
fi
cat <<'EOF'
  1. Open this folder in your AI assistant (Claude Code: run `claude` here; Codex and others read AGENTS.md).
  2. Say: "Set me up" and give it your resume. It builds profile/ with you.
  3. Then say: "Run today's batch" to find and tailor internships.
     It fills forms but never submits: you review and click Submit yourself.
EOF
