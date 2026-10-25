#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo 'macOS .app builds must run on macOS.' >&2; exit 1; }
# Forward only preparation options; never accidentally launch a GUI from this script.
options=(--print-python --build-dependencies)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install) options+=("$1") ;;
    --python)
      [[ $# -ge 2 && -n "$2" ]] || { echo '--python requires a path' >&2; exit 1; }
      options+=("$1" "$2"); shift ;;
    *) echo "Unknown build argument: $1" >&2; exit 1 ;;
  esac
  shift
done
python_path="$(bash "$project_root/scripts/run_desktop.sh" "${options[@]}")"
cd "$project_root"

"$python_path" -m PyInstaller --noconfirm --clean --onedir --windowed --paths . \
  --name "ZFZS Anime Tracker" \
  --osx-bundle-identifier "com.gzjbc.zfzs" \
  scripts/desktop_app.py

bundle="$project_root/dist/ZFZS Anime Tracker.app"
"$python_path" -I -B - "$bundle" <<'PY'
import os
import plistlib
import sys
from pathlib import Path
from PyInstaller.utils.hooks.tcl_tk import tcltk_info
bundle = Path(sys.argv[1])
with (bundle / 'Contents/Info.plist').open('rb') as stream:
    info = plistlib.load(stream)
assert info['CFBundleIdentifier'] == 'com.gzjbc.zfzs'
assert info['CFBundlePackageType'] == 'APPL'
executable = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
assert executable.is_file() and os.access(executable, os.X_OK), executable
assert any(p.is_file() for p in (bundle / 'Contents').rglob('_tkinter*.so')), 'Missing _tkinter extension'
assert any(p.is_file() for p in (bundle / 'Contents').rglob('_imaging*.so')), 'Missing Pillow image decoder'
assert any(p.is_file() for p in (bundle / 'Contents').rglob('certifi/cacert.pem')), 'Missing portable TLS certificates'
assert tcltk_info.available and not tcltk_info.tcl_data_missing and not tcltk_info.tk_data_missing
# System frameworks and Tcl/Tk 9 embedded libraries may not have loose .tcl files.
missing = [name for name, _, _ in tcltk_info.data_files if not (bundle / 'Contents/Resources' / name).is_file()]
assert not missing, f'Missing Tcl/Tk resources: {missing}'
broken = [str(p) for p in bundle.rglob('*') if p.is_symlink() and not p.exists()]
assert not broken, f'Broken bundle symlinks: {broken}'
print(f'Verified macOS app structure and executable permission: {executable}')
PY
# Upload a macOS-created archive, not a raw .app: retain symlinks and execute bits.
archive="$project_root/dist/ZFZS-macOS.zip"
ditto -c -k --sequesterRsrc --keepParent "$bundle" "$archive"
test -s "$archive"
echo "Created $archive (unsigned; GUI and Gatekeeper checks still required on Mac)."
