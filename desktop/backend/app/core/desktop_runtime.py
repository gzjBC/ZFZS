"""Writable desktop paths and one-time migration from the development database."""

import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def desktop_data_dir() -> Path:
    override = os.environ.get("ZFZS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ZFZS"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/ZFZS"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "zfzs"


def prepare_desktop_storage(project_root: Path) -> Path:
    data_dir = desktop_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "zfzs.db"
    if not os.environ.get("DATABASE_URL"):
        legacy = project_root / "data/zfzs.db"
        if legacy.is_file() and not target.exists() and legacy.resolve() != target.resolve():
            # SQLite backup also includes any committed WAL contents. Leave the original intact.
            with closing(sqlite3.connect(f"{legacy.as_uri()}?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
        os.environ["DATABASE_URL"] = f"sqlite:///{target.as_posix()}"
    return data_dir
