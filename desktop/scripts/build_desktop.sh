#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --paths . \
  --name "ZFZS Anime Tracker" \
  --osx-bundle-identifier "com.gzjbc.zfzs" \
  scripts/desktop_app.py

echo "Desktop build created in dist/. On macOS, open 'ZFZS Anime Tracker.app'."
