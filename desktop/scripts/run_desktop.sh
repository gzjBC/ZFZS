#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import tkinter, sqlalchemy, pydantic_settings, requests, playwright' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python scripts/desktop_app.py
