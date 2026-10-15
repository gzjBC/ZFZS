"""Headless UI-controller tests: no network, user storage, or Tk display needed."""

import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.crawlers.bangumi import BangumiError
from backend.app.schema.anime import AnimeCreate, AnimeUpdate
from backend.app.schema.crawler import XifanAnimeResult

# Importing the entry point normally prepares desktop storage and changes cwd.
# Neither side effect belongs in a unit test; every DB operation below is patched
# to a fresh temporary SQLite file, including background-thread connections.
with patch("backend.app.core.desktop_runtime.prepare_desktop_storage", return_value=Path("unused-test-storage")), patch("os.chdir"):
    from scripts import desktop_app as ui


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Tree:
    def __init__(self):
        self.rows = {}
        self.selected = ()

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(item, None)
        self.selected = ()

    def insert(self, parent, position, iid, values):
        self.rows[iid] = values

    def selection(self):
        return self.selected


class DesktopDiscoveryTests(unittest.TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(prefix="zfzs-ui-unit-")
        self.addCleanup(storage.cleanup)
        self.engine = create_engine(
            f"sqlite:///{(Path(storage.name) / 'test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        ui.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patch(ui, "SessionLocal", self.sessions)
        self.errors = self.patch(ui.messagebox, "showerror")
        self.infos = self.patch(ui.messagebox, "showinfo")
        no_network = patch("requests.sessions.Session.request", side_effect=AssertionError("Real network is forbidden in UI tests"))
        no_network.start()
        self.addCleanup(no_network.stop)
        client_patch = patch("backend.app.crawlers.bangumi_discovery.BangumiDiscoveryClient", autospec=True)
        self.client_factory = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client = self.client_factory.return_value
        self.client.calendar.return_value = []
        self.client.season.return_value = []

        self.app = ui.DesktopApp.__new__(ui.DesktopApp)
        self.app.root = Mock()
        self.app.notebook = Mock()
        self.app.watch_tab = object()
        self.app.search_tab = object()
        self.app.discovery_tab = object()
        self.app.items = {}
        self.app.reminder_items = {}
        self.app.search_results = {}
        self.app.discovery_results = {}
        self.app.discovery_result_context = "尚未加载"
        self.app.busy = False
        self.app.task_results = queue.Queue()
        for name, value in {
            "calendar_date": "2026-10-18",
            "season_year": "2026",
            "season_month": "10 月（秋季）",
            "discovery_status": "尚未加载",
            "status_text": "",
            "filter_status": "全部",
            "watching_count": "0",
            "finished_count": "0",
            "reminder_count": "0",
            "keyword": "测试番剧",
            "search_source": "Bangumi（推荐）",
        }.items():
            setattr(self.app, name, Variable(value))
        for name in ("watch_tree", "reminder_tree", "search_tree", "discovery_tree"):
            setattr(self.app, name, Tree())

    def patch(self, obj, name, *args, **kwargs):
        patcher = patch.object(obj, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def drain(self):
        """Run the real completion/error queue callbacks on the test/UI thread."""
        deadline = time.monotonic() + 5
        while self.app.busy or not self.app.task_results.empty():
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, "UI task failed to finish")
            try:
                outcome = self.app.task_results.get(timeout=remaining)
            except queue.Empty:
                self.fail("UI task failed to produce a result")
            self.app.task_results.put(outcome)
            self.app._poll_tasks()

    def result(self, source_id="100", **updates):
        return XifanAnimeResult(
            title="发现测试番剧",
            source="bangumi",
            source_id=source_id,
            source_url=f"https://bgm.tv/subject/{source_id}",
            total_episodes=12,
            year=2026,
        ).model_copy(update=updates)

    def test_calendar_maps_dates_to_sunday_zero_and_preserves_search_results(self):
        self.app.search_results["search-only"] = self.result("999")
        self.client.calendar.return_value = [self.result()]
        for selected_date, weekday in (("2026-10-18", 0), ("2026-10-19", 1), ("2026-10-24", 6)):
            with self.subTest(selected_date=selected_date):
                self.app.calendar_date.set(selected_date)
                self.app.load_calendar()
                self.drain()
                self.client.calendar.assert_called_with(weekday=weekday, limit=50)
                self.assertEqual(len(self.app.discovery_tree.rows), 1)
                self.assertIn(selected_date, self.app.discovery_status.get())
        self.assertIn("search-only", self.app.search_results)
        self.errors.assert_not_called()

    def test_whole_week_does_not_require_valid_date(self):
        self.app.calendar_date.set("invalid")
        self.app.load_calendar(whole_week=True)
        self.drain()
        self.client.calendar.assert_called_once_with(weekday=None, limit=50)
        self.infos.assert_not_called()
        self.assertIn("整周", self.app.discovery_status.get())

    def test_all_seasons_use_start_month_and_selected_year(self):
        self.client.season.return_value = [self.result()]
        self.app.season_year.set("2025")
        for label, month in ui.SEASON_MONTHS.items():
            with self.subTest(month=month):
                self.app.season_month.set(label)
                self.app.load_season()
                self.drain()
                self.client.season.assert_called_with(year=2025, month=month, limit=50)
                self.assertIn(f"2025 年 {month} 月", self.app.discovery_status.get())

    def test_invalid_date_or_season_never_starts_network_task(self):
        for value in ("", "2026-02-30", "not-a-date"):
            self.app.calendar_date.set(value)
            self.app.load_calendar()
        for value in ("", "20x6", "0", "10000"):
            self.app.season_year.set(value)
            self.app.load_season()
        self.app.season_year.set("2026")
        self.app.season_month.set("2 月")
        self.app.load_season()
        self.assertEqual(self.infos.call_count, 8)
        self.client_factory.assert_not_called()
        self.assertFalse(self.app.busy)

    def test_network_worker_returns_without_blocking_and_rejects_overlap(self):
        started, release = threading.Event(), threading.Event()
        worker_threads = []

        def delayed_calendar(**kwargs):
            worker_threads.append(threading.get_ident())
            started.set()
            if not release.wait(3):
                raise RuntimeError("test worker was not released")
            return [self.result()]

        self.client.calendar.side_effect = delayed_calendar
        try:
            self.app.load_calendar()
            self.assertTrue(started.wait(1))
            self.assertTrue(self.app.busy)
            self.assertNotEqual(worker_threads, [threading.get_ident()])
            self.assertEqual(self.app.discovery_results, {})
            original_status = self.app.discovery_status.get()
            self.app.load_season()
            self.assertEqual(self.app.discovery_status.get(), original_status)
            self.client.season.assert_not_called()
            self.assertIn("已有任务", self.app.status_text.get())
            # Request parameters and result labels must be a snapshot, not Tk
            # variables read by the network thread after the user edits a field.
            self.app.calendar_date.set("2026-10-19")
        finally:
            release.set()
            self.drain()
        self.assertIn("2026-10-18", self.app.discovery_status.get())

    def test_failures_keep_prior_results_and_allow_retry(self):
        self.client.calendar.return_value = [self.result()]
        self.app.load_calendar()
        self.drain()
        original_results = dict(self.app.discovery_results)
        original_rows = dict(self.app.discovery_tree.rows)
        self.client.season.side_effect = BangumiError("Bangumi 请求超时，请重试。")
        for _ in range(2):
            self.app.load_season()
            self.drain()
            self.assertEqual(self.app.discovery_results, original_results)
            self.assertEqual(self.app.discovery_tree.rows, original_rows)
            self.assertIn("加载失败", self.app.discovery_status.get())
            self.assertFalse(self.app.busy)
        self.assertEqual(self.errors.call_count, 2)
        self.client.season.side_effect = None
        self.client.season.return_value = [self.result("200", title="恢复后的季度新番")]
        self.app.load_season()
        self.drain()
        self.assertEqual(self.app.discovery_results["result-0"].source_id, "200")
        self.assertIn("加载完成", self.app.status_text.get())

    def test_empty_results_do_not_clear_watchlist(self):
        with self.sessions() as db:
            existing = ui.anime_service.create_anime(db, AnimeCreate(title="本地追番", watched_episodes=4))
            existing_id = existing.id
        self.app.refresh_data()
        self.drain()
        self.app.discovery_results["old"] = self.result()
        self.app.load_calendar()
        self.drain()
        self.assertEqual(self.app.discovery_results, {})
        self.assertIn("暂无条目", self.app.discovery_status.get())
        self.assertEqual(self.app.items[existing_id]["watched_episodes"], 4)
        with self.sessions() as db:
            self.assertEqual(len(ui.anime_service.list_anime(db)), 1)

    def test_discovery_import_deduplicates_and_preserves_progress_and_reminders(self):
        result = self.result()
        with self.sessions() as db:
            unrelated = ui.anime_service.create_anime(db, AnimeCreate(title="手动记录", watched_episodes=3))
            unrelated_id = unrelated.id
            existing = ui.anime_service.import_search_result(db, result)
            ui.anime_service.update_anime(db, existing, AnimeUpdate(
                watched_episodes=5, status="paused", broadcast_day=1,
                broadcast_time="21:30", reminder_enabled=True, reminder_minutes=30,
            ))
            existing_id = existing.id
        self.client.calendar.return_value = [result.model_copy(update={"title": "发现后更新标题", "score": 8.5})]
        self.app.load_calendar()
        self.drain()
        self.app.discovery_tree.selected = ("result-0",)
        for _ in range(2):
            self.app.import_selected(self.app.discovery_tree)
            self.drain()
        with self.sessions() as db:
            self.assertEqual(len(ui.anime_service.list_anime(db)), 2)
            saved = ui.anime_service.get_anime(db, existing_id)
            self.assertEqual(saved.watched_episodes, 5)
            self.assertEqual(saved.status, "paused")
            self.assertEqual(saved.title, "发现后更新标题")
            self.assertEqual(saved.score, 8.5)
            self.assertEqual((saved.broadcast_day, saved.broadcast_time, saved.reminder_minutes), (1, "21:30", 30))
            self.assertTrue(saved.reminder_enabled)
            self.assertEqual(ui.anime_service.get_anime(db, unrelated_id).watched_episodes, 3)
        self.assertEqual(len(self.app.items), 2)
        self.app.notebook.select.assert_called_with(self.app.watch_tab)

    def test_import_failure_keeps_results_and_can_retry(self):
        self.app.filter_status.set("已看完")
        self.client.season.return_value = [self.result()]
        self.app.load_season()
        self.drain()
        self.app.discovery_tree.selected = ("result-0",)
        with patch.object(ui.anime_service, "import_search_result", side_effect=RuntimeError("临时写入失败")):
            self.app.import_selected(self.app.discovery_tree)
            self.drain()
        self.errors.assert_called_once()
        self.assertEqual(len(self.app.discovery_results), 1)
        self.app.import_selected(self.app.discovery_tree)
        self.drain()
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(self.app.filter_status.get(), "全部")
        self.assertEqual(len(self.app.watch_tree.rows), 1)
        self.assertIn("已加入追番", self.app.status_text.get())

    def test_search_results_still_import_without_using_discovery_results(self):
        self.app.discovery_results["result-0"] = self.result("200")
        with patch.object(ui, "BangumiClient", autospec=True) as search_client:
            search_client.return_value.search.return_value = [self.result("300", title="搜索条目")]
            self.app.search_xifan()
            self.drain()
        self.app.search_tree.selected = ("result-0",)
        self.app.import_selected()
        self.drain()
        with self.sessions() as db:
            saved = ui.anime_service.list_anime(db)
            self.assertEqual([(item.source_id, item.title) for item in saved], [("300", "搜索条目")])

    def test_discovery_details_link_and_missing_selection(self):
        self.app.import_selected(self.app.discovery_tree)
        self.infos.assert_called_once()
        self.app.discovery_results["result-0"] = self.result()
        self.app.discovery_tree.selected = ("result-0",)
        with patch.object(ui.webbrowser, "open") as open_browser:
            self.app.open_selected_link(self.app.discovery_tree)
        open_browser.assert_called_once_with("https://bgm.tv/subject/100")


if __name__ == "__main__":
    unittest.main()
