"""Verify the native discovery/import flow with real Tk and isolated SQLite.

Run manually on a machine with a graphical session:
    python tests/smoke_desktop.py

Bangumi HTTP responses are simulated; this never contacts the network.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from tkinter import Tk
from unittest.mock import Mock, patch

import requests


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
    SessionLocal,
    anime_service,
    engine,
    run_lightweight_migrations,
)
from backend.app.schema.anime import AnimeCreate, AnimeUpdate  # noqa: E402
from backend.app.schema.crawler import XifanAnimeResult  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    with SessionLocal() as db:
        unrelated = anime_service.create_anime(db, AnimeCreate(title="已有本地番剧", watched_episodes=3))
        unrelated_id = unrelated.id
        existing = anime_service.import_search_result(db, XifanAnimeResult(
            title="已有 Bangumi 番剧", source="bangumi", source_id="101", total_episodes=12,
        ))
        anime_service.update_anime(db, existing, AnimeUpdate(
            watched_episodes=5, status="paused", broadcast_day=1,
            broadcast_time="21:30", reminder_enabled=True, reminder_minutes=30,
        ))
        existing_id = existing.id
    root = Tk()
    root.withdraw()
    app = DesktopApp(root)
    # Briefly map the real window to verify the discovery actions remain visible
    # at its minimum supported size; withdrawn widgets have no usable geometry.
    root.geometry("900x700")
    app.notebook.select(app.discovery_tab)
    root.deiconify()

    result = {}
    release_calendar = threading.Event()
    state = {"season_fails": True}
    request_threads = []
    main_thread = threading.get_ident()

    def fake_get(url, **kwargs):
        request_threads.append(threading.get_ident())
        if url.endswith("/calendar"):
            if not release_calendar.wait(3):
                raise RuntimeError("Tk event loop did not release the mock request")
            payload = [
                {"weekday": {"id": 7}, "items": [{
                    "id": 101, "name_cn": "日历更新标题", "type": 2,
                    "air_date": "2026-10-18", "eps_count": 12,
                }]},
                {"weekday": {"id": 1}, "items": [{"id": 303, "name_cn": "不应出现的周一条目"}]},
            ]
        elif url.endswith("/v0/subjects"):
            if state["season_fails"]:
                raise requests.Timeout("simulated timeout")
            params = kwargs["params"]
            if params["year"] != 2026 or params["month"] not in (10, 11, 12):
                raise AssertionError(f"Unexpected season parameters: {params}")
            items = [{"id": 202, "name_cn": "季度新番测试", "type": 2, "date": "2026-10-10", "total_episodes": 12}] if params["month"] == 10 else []
            payload = {"data": items, "total": len(items), "offset": params["offset"], "limit": params["limit"]}
        else:
            raise AssertionError(f"Unexpected HTTP call: {url}")
        response = Mock()
        response.json.return_value = payload
        return response

    def when_idle(callback):
        if app.busy:
            root.after(20, lambda: when_idle(callback))
        else:
            callback()

    def finish() -> None:
        with SessionLocal() as db:
            saved = anime_service.get_anime(db, existing_id)
            unrelated = anime_service.get_anime(db, unrelated_id)
            result["database_preserved"] = (
                len(anime_service.list_anime(db)) == 3
                and saved.watched_episodes == 5 and saved.status == "paused"
                and saved.broadcast_day == 1 and saved.broadcast_time == "21:30"
                and saved.reminder_enabled and saved.reminder_minutes == 30
                and unrelated.watched_episodes == 3
            )
        result.update(
            title_ok=root.title() == "ZFZS 追番助手",
            tabs_ok=[app.notebook.tab(tab, "text") for tab in app.notebook.tabs()] == ["我的追番", "今日提醒", "搜索结果", "发现番剧"],
            default_source_ok=app.search_source.get().startswith("Bangumi"),
            error_reported=error_dialog.call_count == 1,
            recovered=not app.busy and "已加入追番" in app.status_text.get(),
            season_imported=len(app.items) == 3 and any(item["title"] == "季度新番测试" for item in app.items.values()),
            watch_tab_selected=app.notebook.select() == str(app.watch_tab),
            network_off_ui_thread=bool(request_threads) and all(thread != main_thread for thread in request_threads),
            unexpected_dialogs_absent=info_dialog.call_count == 0,
        )
        root.destroy()

    def after_season() -> None:
        result["season_loaded"] = (
            len(app.discovery_results) == 1
            and app.discovery_results["result-0"].source_id == "202"
            and "2026 年 10 月" in app.discovery_status.get()
        )
        app.discovery_tree.selection_set("result-0")
        app.import_selected(app.discovery_tree)
        root.after(20, lambda: when_idle(finish))

    def after_error() -> None:
        result["error_kept_results"] = (
            error_dialog.call_count == 1
            and "加载失败" in app.discovery_status.get()
            and app.discovery_results["result-0"].source_id == "101"
            and len(app.items) == 2
        )
        state["season_fails"] = False
        app.load_season()
        root.after(20, lambda: when_idle(after_season))

    def after_calendar_import() -> None:
        result["calendar_reimport_preserved_progress"] = (
            len(app.items) == 2
            and app.items[existing_id]["watched_episodes"] == 5
            and app.items[existing_id]["status"] == "paused"
            and app.items[existing_id]["title"] == "日历更新标题"
        )
        app.season_year.set("2026")
        app.season_month.set("10 月（秋季）")
        app.load_season()
        root.after(20, lambda: when_idle(after_error))

    def after_calendar() -> None:
        result["calendar_loaded"] = (
            len(app.discovery_results) == 1
            and app.discovery_results["result-0"].source_id == "101"
            and "周日" in app.discovery_status.get()
            and len(app.discovery_tree.get_children()) == 1
        )
        app.discovery_tree.selection_set("result-0")
        app.import_selected(app.discovery_tree)
        root.after(20, lambda: when_idle(after_calendar_import))

    def release_request() -> None:
        result["ui_responsive_during_request"] = app.busy and not app.discovery_results
        release_calendar.set()

    def after_load() -> None:
        result["data_loaded"] = len(app.items) == 2
        root.update_idletasks()
        buttons = [widget for frame in app.discovery_tab.winfo_children()
                   for widget in frame.winfo_children() if widget.winfo_class() == "TButton"]
        result["minimum_window_usable"] = (
            len(buttons) == 5 and app.discovery_tree.winfo_height() >= 80
            and all(button.winfo_ismapped() and button.winfo_height() >= button.winfo_reqheight()
                    and button.winfo_width() >= button.winfo_reqwidth() for button in buttons)
        )
        if not result["minimum_window_usable"]:
            print(f"Discovery layout: tree height={app.discovery_tree.winfo_height()}, "
                  f"buttons={[(str(button.cget('text')), button.winfo_ismapped(), button.winfo_width(), button.winfo_height()) for button in buttons]}", file=sys.stderr)
        root.withdraw()
        app.calendar_date.set("2026-10-18")
        app.load_calendar()
        root.after(20, release_request)
        root.after(20, lambda: when_idle(after_calendar))

    def callback_error(exception_type, exception, traceback) -> None:
        result["callback_error"] = False
        print(f"UI callback failed: {exception_type.__name__}: {exception}", file=sys.stderr)
        release_calendar.set()
        root.destroy()

    root.report_callback_exception = callback_error
    with patch("scripts.desktop_app.messagebox.showerror") as error_dialog, \
            patch("scripts.desktop_app.messagebox.showinfo") as info_dialog, \
            patch("requests.Session.get", side_effect=fake_get), \
            patch("requests.sessions.Session.request", side_effect=AssertionError("Real network is forbidden in smoke tests")):
        root.after(20, lambda: when_idle(after_load))
        root.after(10000, root.destroy)
        root.mainloop()
    engine.dispose()
    TEMP_STORAGE.cleanup()
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("recovered") or not all(result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
