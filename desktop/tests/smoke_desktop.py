"""Launch the native UI briefly and verify its primary shell.

Run manually on a machine with a graphical session:
    python tests/smoke_desktop.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from tkinter import Tk
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Never read or alter the user's watchlist during GUI verification.
TEMP_STORAGE = tempfile.TemporaryDirectory(prefix="zfzs-smoke-")
os.environ["ZFZS_DATA_DIR"] = TEMP_STORAGE.name
# Use a file because background worker threads require their own SQLite connections.
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(TEMP_STORAGE.name) / 'smoke.db').as_posix()}"

from scripts.desktop_app import (  # noqa: E402
    Base,
    DesktopApp,
    engine,
    run_lightweight_migrations,
)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    root = Tk()
    root.withdraw()
    app = DesktopApp(root)

    result = {}

    def fail_task():
        raise RuntimeError("simulated network failure")

    def finish() -> None:
        result.update(
            title_ok=root.title() == "ZFZS 追番助手",
            tabs_ok=len(app.notebook.tabs()) == 3,
            default_source_ok=app.search_source.get().startswith("Bangumi"),
            error_reported=error_dialog.call_count == 1,
            recovered=not app.busy and app.status_text.get() == "recovered",
        )
        root.destroy()

    def after_error() -> None:
        if app.busy:
            root.after(50, after_error)
            return
        app.refresh_data("recovered")
        root.after(500, finish)

    def after_load() -> None:
        if app.busy:
            root.after(50, after_load)
            return
        result["data_loaded"] = True
        app._run_task("error test", fail_task)
        root.after(50, after_error)

    with patch("scripts.desktop_app.messagebox.showerror") as error_dialog:
        root.after(50, after_load)
        root.after(10000, root.destroy)
        root.mainloop()
    engine.dispose()
    TEMP_STORAGE.cleanup()
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("recovered") or not all(result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
