"""Verify native discovery, rating, AI handoff and migration with isolated SQLite.

Run manually on a machine with a graphical session:
    python tests/smoke_desktop.py

AI, Bangumi HTTP, notification and process services are simulated. No network,
real background worker, OS configuration changes or user databases are used.
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
from backend.app.service.recommendation_service import Recommendation  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    with SessionLocal() as db:
        unrelated = anime_service.create_anime(db, AnimeCreate(title="已有本地番剧", watched_episodes=3, score=8.1, tags="日常,治愈"))
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
    export_path = Path(TEMP_STORAGE.name) / "migration.json"
    backup_dir = Path(TEMP_STORAGE.name) / "backups"

    def fake_generate(db, preference="", provider="auto", api_key=None):
        request_threads.append(threading.get_ident())
        rated = anime_service.get_anime(db, unrelated_id)
        result["ai_received_rated_finished_history"] = (
            rated.user_rating == 9 and rated.status == "finished" and rated.tags == "日常,治愈"
            and preference == "偏爱治愈日常" and provider == "qwen" and api_key == "smoke-only-key"
        )
        return [Recommendation(title="模型未核验的名称", reason="符合治愈偏好", search_keyword="真实番剧检索词")]

    def fake_post(url, **kwargs):
        request_threads.append(threading.get_ident())
        if not url.endswith("/v0/search/subjects") or kwargs.get("json", {}).get("keyword") != "真实番剧检索词":
            raise AssertionError(f"Unexpected HTTP POST: {url}")
        response = Mock()
        response.json.return_value = {"data": [{"id": 404, "name_cn": "Bangumi 确认条目", "date": "2026-10-01", "total_episodes": 12}]}
        return response

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
            tabs_ok=[app.notebook.tab(tab, "text") for tab in app.notebook.tabs()] == ["我的追番", "今日提醒", "搜索结果", "发现番剧", "AI 推荐"],
            default_source_ok=app.search_source.get().startswith("Bangumi"),
            error_reported=error_dialog.call_count == 1,
            recovered=not app.busy and "已加入追番" in app.status_text.get(),
            season_imported=len(app.items) == 3 and any(item["title"] == "季度新番测试" for item in app.items.values()),
            watch_tab_selected=app.notebook.select() == str(app.watch_tab),
            network_off_ui_thread=bool(request_threads) and all(thread != main_thread for thread in request_threads),
            unexpected_dialogs_absent=info_dialog.call_count == 0,
        )
        app.watch_tree.selection_set(str(unrelated_id))
        app.mark_finished()
        root.after(20, lambda: when_idle(rate_finished))

    def rate_finished() -> None:
        app.watch_tree.selection_set(str(unrelated_id))
        app.open_rating_dialog()
        dialog = next(widget for widget in root.winfo_children() if widget.winfo_class() == "Toplevel")
        frame = dialog.winfo_children()[0]
        entry = next(widget for widget in frame.winfo_children() if widget.winfo_class() == "TEntry")
        entry.insert(0, "9")
        buttons = [widget for row in frame.winfo_children() for widget in row.winfo_children() if widget.winfo_class() == "TButton"]
        next(button for button in buttons if button.cget("text") == "保存").invoke()
        root.after(20, lambda: when_idle(after_rating))

    def after_rating() -> None:
        result["personal_rating_saved_independently"] = (
            app.items[unrelated_id]["user_rating"] == 9 and app.items[unrelated_id]["score"] == 8.1
            and app.watch_tree.heading("score", "text") == "网站评分"
            and app.watch_tree.heading("user_rating", "text") == "我的评分"
        )
        result["ai_not_called_before_click"] = ai_generate.call_count == 0
        result["no_automatic_backup"] = not backup_dir.exists() and not export_path.exists()
        result["session_key_masked"] = app.ai_key_entry.cget("show") == "*"
        app.ai_provider.set("qwen")
        app.ai_preference.set("偏爱治愈日常")
        app.ai_api_key.set("smoke-only-key")
        app.generate_ai_recommendations()
        root.after(20, lambda: when_idle(after_recommendation))

    def after_recommendation() -> None:
        result["ai_cannot_auto_import"] = len(app.items) == 3 and len(app.recommendation_results) == 1
        app.ai_tree.selection_set("recommendation-0")
        app.search_source.set("稀饭动漫")
        app.search_selected_recommendation()
        root.after(20, lambda: when_idle(after_ai_search))

    def after_ai_search() -> None:
        result["ai_handoff_to_bangumi"] = (
            app.keyword.get() == "真实番剧检索词" and app.search_source.get().startswith("Bangumi")
            and app.search_results["result-0"].source_id == "404" and len(app.items) == 3
            and app.notebook.select() == str(app.search_tab)
        )
        app.search_tree.selection_set("result-0")
        app.import_selected()
        root.after(20, lambda: when_idle(after_verified_import))

    def after_verified_import() -> None:
        result["only_verified_result_imported"] = (
            len(app.items) == 4 and any(item["title"] == "Bangumi 确认条目" for item in app.items.values())
            and not any(item["title"] == "模型未核验的名称" for item in app.items.values())
        )
        app.export_data()
        root.after(20, lambda: when_idle(after_export))

    def after_export() -> None:
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        rated = next(item for item in exported["items"] if item["title"] == "已有本地番剧")
        result["real_json_export_includes_rating_tags"] = rated["user_rating"] == 9 and rated["tags"] == "日常,治愈" and len(exported["items"]) == 4
        result["session_key_not_exported"] = "smoke-only-key" not in export_path.read_text(encoding="utf-8")
        app.save_user_rating(unrelated_id, "4")
        root.after(20, lambda: when_idle(delete_exported_item))

    def delete_exported_item() -> None:
        confirmed = next(item["id"] for item in app.items.values() if item["title"] == "Bangumi 确认条目")
        app.watch_tree.selection_set(str(confirmed))
        confirm_dialog.return_value = True
        app.delete_selected()
        root.after(20, lambda: when_idle(import_keep_local))

    def import_keep_local() -> None:
        confirm_dialog.reset_mock()
        confirm_dialog.return_value = False
        app.import_data()
        root.after(20, lambda: when_idle(after_keep_local))

    def after_keep_local() -> None:
        result["default_import_preserves_local_rating"] = len(app.items) == 4 and app.items[unrelated_id]["user_rating"] == 4
        result["default_import_does_not_request_replace"] = confirm_dialog.call_count == 0
        result["import_summary_and_backup_path"] = (
            "新增 1 条 / 更新 0 条 / 跳过 3 条" in info_dialog.call_args.args[1]
            and "备份路径：" in info_dialog.call_args.args[1] and len(list(backup_dir.glob("*.json"))) == 1
        )
        app.import_data(True)
        result["cancelled_replace_does_nothing"] = not app.busy and app.items[unrelated_id]["user_rating"] == 4 and len(list(backup_dir.glob("*.json"))) == 1
        confirm_dialog.return_value = True
        app.import_data(True)
        root.after(20, lambda: when_idle(after_replace))

    def after_replace() -> None:
        result["confirmed_replace_restores_rating"] = (
            app.items[unrelated_id]["user_rating"] == 9 and app.items[unrelated_id]["score"] == 8.1
            and "新增 0 条 / 更新 1 条 / 跳过 3 条" in info_dialog.call_args.args[1]
            and len(list(backup_dir.glob("*.json"))) == 2
        )
        app.backup_data()
        root.after(20, lambda: when_idle(after_backup))

    def after_backup() -> None:
        result["manual_backup_created"] = len(list(backup_dir.glob("*.json"))) == 3 and "备份路径：" in info_dialog.call_args.args[1]
        app.check_background_reminders()
        root.after(20, lambda: when_idle(complete))

    def complete() -> None:
        result["background_status_queried_without_start"] = app.background_status_text.get() == "后台提醒：已停止" and start_worker.call_count == 0 and stop_worker.call_count == 0
        result["no_extra_errors"] = error_dialog.call_count == 1
        result["all_network_off_ui_thread"] = all(thread != main_thread for thread in request_threads)
        root.destroy()
        result["gui_close_does_not_stop_worker"] = stop_worker.call_count == 0

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
        app.notebook.select(app.ai_tab)
        root.update_idletasks()
        result["ai_minimum_window_usable"] = (
            app.ai_tree.winfo_height() >= 70
            and all(button.winfo_ismapped() and button.winfo_width() >= button.winfo_reqwidth()
                    and button.winfo_height() >= button.winfo_reqheight()
                    for button in (app.ai_generate_button, app.ai_search_button))
        )
        app.notebook.select(app.watch_tab)
        root.update_idletasks()
        watch_buttons = [widget for frame in app.watch_tab.winfo_children()
                         for widget in frame.winfo_children() if widget.winfo_class() == "TButton"]
        result["watch_minimum_window_usable"] = app.watch_tree.winfo_height() >= 70 and len(watch_buttons) == 8 and all(
            button.winfo_ismapped() and button.winfo_width() >= button.winfo_reqwidth() for button in watch_buttons
        )
        if not result["watch_minimum_window_usable"]:
            print(f"Watch layout: tree height={app.watch_tree.winfo_height()}, "
                  f"buttons={[(str(button.cget('text')), button.winfo_ismapped(), button.winfo_width(), button.winfo_reqwidth()) for button in watch_buttons]}", file=sys.stderr)
        app.notebook.select(app.reminder_tab)
        root.update_idletasks()
        reminder_buttons = [widget for frame in app.reminder_tab.winfo_children()
                            for widget in frame.winfo_children() if widget.winfo_class() == "TButton"]
        result["reminder_minimum_window_usable"] = app.reminder_tree.winfo_height() >= 70 and len(reminder_buttons) == 5 and all(
            button.winfo_ismapped() and button.winfo_width() >= button.winfo_reqwidth() for button in reminder_buttons
        )
        app.open_transfer_dialog()
        transfer_dialog = next(widget for widget in root.winfo_children() if widget.winfo_class() == "Toplevel")
        transfer_frame = transfer_dialog.winfo_children()[0]
        checkbox = next(widget for widget in transfer_frame.winfo_children() if widget.winfo_class() == "TCheckbutton")
        result["replace_checkbox_defaults_off"] = not transfer_dialog.getvar(str(checkbox.cget("variable")))
        result["opening_transfer_dialog_does_not_touch_files"] = not backup_dir.exists() and not export_path.exists()
        transfer_dialog.destroy()
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
            patch("scripts.desktop_app.messagebox.askyesno", return_value=False) as confirm_dialog, \
            patch("scripts.desktop_app.filedialog.asksaveasfilename", return_value=str(export_path)), \
            patch("scripts.desktop_app.filedialog.askopenfilename", return_value=str(export_path)), \
            patch("backend.app.service.recommendation_service.generate_recommendations", side_effect=fake_generate) as ai_generate, \
            patch("backend.app.service.notification_service.background_status", return_value=False), \
            patch("backend.app.service.notification_service.start_background_worker") as start_worker, \
            patch("backend.app.service.notification_service.stop_background_worker") as stop_worker, \
            patch("backend.app.service.notification_service.send_system_notification", side_effect=AssertionError("Real notifications are forbidden")), \
            patch("subprocess.Popen", side_effect=AssertionError("Real background processes are forbidden")), \
            patch("requests.Session.get", side_effect=fake_get), \
            patch("requests.Session.post", side_effect=fake_post), \
            patch("requests.sessions.Session.request", side_effect=AssertionError("Real network is forbidden in smoke tests")):
        root.after(20, lambda: when_idle(after_load))
        root.after(20000, root.destroy)
        root.mainloop()
    engine.dispose()
    TEMP_STORAGE.cleanup()
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("gui_close_does_not_stop_worker") or not all(result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
