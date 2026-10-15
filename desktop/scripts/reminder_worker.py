"""Explicit background-reminder entry point (never opens the main window)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run opt-in ZFZS reminders for this login session.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    data_dir = args.data_dir.expanduser().resolve()
    # Set storage before importing any backend model/session. The service also
    # uses an independent explicit connection, never the global SessionLocal.
    os.environ["ZFZS_DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{(data_dir / 'zfzs.db').as_posix()}"
    project = Path(__file__).resolve().parents[1]
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    from backend.app.service.notification_service import run_worker

    run_worker(data_dir, args.poll_seconds)


if __name__ == "__main__":
    main()
