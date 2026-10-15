#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
prepare_only=false
print_python=false
no_install=false
build_dependencies=false
python_path=''
mode=source
fail() { printf '%s\n' "$*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare-only) prepare_only=true ;;
    --print-python) print_python=true; prepare_only=true ;;
    --no-install) no_install=true ;;
    --build-dependencies) build_dependencies=true ;;
    --python|--mode)
      [[ $# -ge 2 && -n "$2" ]] || fail "$1 requires a value"
      if [[ "$1" == --python ]]; then python_path="$2"; else mode="$2"; fi
      shift ;;
    *) fail "Unknown argument: $1" ;;
  esac
  shift
done
case "$mode" in source|packaged|auto) ;; *) fail 'Mode must be source, packaged or auto' ;; esac
if $prepare_only && [[ "$mode" != source ]]; then fail 'Preparation checks source Python only'; fi
bundle="$project_root/dist/ZFZS Anime Tracker.app"
if [[ "$mode" == packaged ]] || { [[ "$mode" == auto ]] && [[ -d "$bundle" ]]; }; then
  [[ "$(uname -s)" == Darwin ]] || fail 'Packaged .app launch requires macOS'
  [[ -x "$bundle/Contents/MacOS/ZFZS Anime Tracker" && -f "$bundle/Contents/Info.plist" ]] || fail "Incomplete app: $bundle"
  exec open "$bundle"
fi

# No Tk() / GUI / project imports: safe on headless CI and before storage setup.
probe() {
  local candidate="$1" scope="${2:-Runtime}" requirements="$project_root/requirements.txt"
  [[ -x "$candidate" ]] || return 1
  if [[ "$scope" == Build ]]; then requirements="$project_root/requirements-dev.txt"; fi
  "$candidate" -I -B - "$scope" "$requirements" <<'PY' >/dev/null 2>&1
import importlib.metadata as metadata
from pathlib import Path
import sys
assert sys.version_info[:2] == (3, 13), 'Python 3.13 is required'
import tkinter
tkinter.Tcl().eval('info patchlevel')
if sys.argv[1] != 'Base':
    import fastapi, uvicorn, sqlalchemy, pydantic, pydantic_settings, requests, playwright
    def check(path):
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('-r '):
                check(path.parent / line[3:].strip())
            else:
                name, expected = line.split('==', 1)
                assert metadata.version(name) == expected, f'{name} must be {expected}'
    check(Path(sys.argv[2]))
    if sys.argv[1] == 'Build':
        import PyInstaller
PY
}

local_python="$project_root/.venv/bin/python"
legacy_python="$(dirname "$project_root")/.venv/bin/python"
if [[ -n "$python_path" ]]; then
  [[ -f "$python_path" ]] || fail "Python path does not exist: $python_path"
  python_path="$(cd "$(dirname "$python_path")" && pwd)/$(basename "$python_path")"
  probe "$python_path" Base || fail 'Explicit Python must be 3.13 with working tkinter/Tcl (pip cannot install Tk)'
elif probe "$local_python"; then
  python_path="$local_python"
elif probe "$legacy_python"; then
  python_path="$legacy_python"
  printf '%s\n' 'Using the migration-compatible repository .venv.' >&2
else
  $no_install && fail 'No ready Python 3.13/Tk environment. Omit --no-install to prepare desktop/.venv.'
  if ! probe "$local_python" Base; then
    base_python=''
    for candidate in python3.13 python3; do
      candidate_path="$(command -v "$candidate" || true)"
      if probe "$candidate_path" Base; then base_python="$candidate_path"; break; fi
    done
    [[ -n "$base_python" ]] || fail 'Install Python 3.13 with Tcl/Tk support. pip cannot install tkinter.'
    if [[ -e "$project_root/.venv" || -L "$project_root/.venv" ]]; then
      backup="$project_root/.venv.backup-$(date +%Y%m%d%H%M%S)-$$"
      [[ ! -e "$backup" && ! -L "$backup" ]] || fail "Backup path already exists: $backup"
      printf 'Preserving old environment at %s\n' "$backup" >&2
      mv "$project_root/.venv" "$backup"
    fi
    "$base_python" -m venv "$project_root/.venv" >&2
    probe "$local_python" Base || fail 'The new environment cannot load Python 3.13/Tk'
  fi
  python_path="$local_python"
fi

scope=Runtime
requirements="$project_root/requirements.txt"
if $build_dependencies; then scope=Build; requirements="$project_root/requirements-dev.txt"; fi
if ! probe "$python_path" "$scope"; then
  $no_install && fail "Missing or mismatched $scope dependencies in $python_path. Omit --no-install to repair."
  "$python_path" -m ensurepip --upgrade >&2
  "$python_path" -m pip install -r "$requirements" >&2
  probe "$python_path" "$scope" || fail 'Python/Tk/dependency verification failed after installation'
fi
if $print_python; then printf '%s\n' "$python_path"; exit 0; fi
printf 'Python: %s\n' "$python_path" >&2
if $prepare_only; then printf '%s\n' 'Desktop environment is ready (no GUI was opened).' >&2; exit 0; fi
cd "$project_root"
exec "$python_path" "$project_root/scripts/desktop_app.py"
