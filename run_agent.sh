#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if [ ! -x venv/bin/python ]; then
  echo "Creating a virtual environment..."
  "$PYTHON" -m venv venv
fi
venv/bin/python -m pip install --quiet --disable-pip-version-check -r backend/requirements.txt

URL="http://127.0.0.1:8000"
echo
echo "NetLens agent running at $URL"
echo "Press Ctrl+C to stop."
echo
( sleep 1.5; if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL"; fi ) >/dev/null 2>&1 &
cd backend
exec ../venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
