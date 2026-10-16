#!/usr/bin/env bash
# Sets up Auto-Delete-Post on first run, then opens the dashboard.
set -e
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.10 or newer is required. Get it from https://www.python.org/downloads/"
  read -r -p "Press Enter to close." _
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up (this takes a minute)..."
  "$PYTHON" -m venv .venv
fi
# Reinstall dependencies only when requirements.txt changes.
if ! cmp -s requirements.txt .venv/.installed-requirements; then
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  cp requirements.txt .venv/.installed-requirements
fi

exec .venv/bin/python -m autodelete web --open "$@"
