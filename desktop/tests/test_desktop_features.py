"""Desktop feature contracts: isolated SQLite, fake providers/processes, no Tk."""

import os
import runpy
import sys
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_desktop_ui as discovery_tests


ui = discovery_tests.ui


class UIOnlyVariable(discovery_tests.Variable):
    def __init__(self, value=""):
        super().__init__(value)
        self.thread = threading.get_ident()

    def get(self):
        if threading.get_ident() != self.thread:
            raise AssertionError("Background task accessed a Tk variable")
        return super().get()

    def set(self, value):
        if threading.get_ident() != self.thread:
            raise AssertionError("Background task changed a Tk variable")
        super().set(value)


class DesktopFeatureTests(unittest.TestCase):
    patch = discovery_tests.DesktopDiscoveryTests.patch
    drain = discovery_tests.DesktopDiscoveryTests.drain
    result = discovery_tests.DesktopDiscoveryTests.result

    def setUp(self):
        discovery_tests.DesktopDiscoveryTests.setUp(self)
        self.data_dir = Path(self.engine.url.database).parent
        self.patch(ui, "DESKTOP_DATA_DIR", self.data_dir)
        self.patch(ui.filedialog, "askopenfilename", return_value="")
        self.patch(ui.filedialog, "asksaveasfilename", return_value="")
        self.confirm = self.patch(ui.messagebox, "askyesno", return_value=False)
        for name, variable in vars(self.app).copy().items():
            if isinstance(variable, discovery_tests.Variable):
                setattr(self.app, name, UIOnlyVariable(variable.get()))
        for name, value in {
            "ai_provider": "auto", "ai_preference": "喜欢日常", "ai_api_key": "",
            "ai_status": "尚未生成", "background_status_text": "待查询",
        }.items():
            setattr(self.app, name, UIOnlyVariable(value))
        self.app.ai_tree = discovery_tests.Tree()
        self.app.ai_tab = object()
        self.app.recommendation_results = {}
        import subprocess
        self.patch(subprocess, "Popen", side_effect=AssertionError("Real processes are forbidden"))
        # Only tests supply protocol doubles; production lazily imports services.
        self.transfer = self.fake_service("transfer_service", {
            "save_export": Mock(return_value=2),
            "create_backup": Mock(return_value=self.data_dir / "backups/test.json"),
            "load_import": Mock(return_value=SimpleNamespace(created=1, updated=0, skipped=1, backup_path=self.data_dir / "backups/before.json")),
        })
        self.recommendation = self.fake_service("recommendation_service", {
            "RecommendationError": type("RecommendationError", (RuntimeError,), {}),
            "generate_recommendations": Mock(return_value=[self.recommendation_item()]),
        })
        self.notification = self.fake_service("notification_service", {
            "background_status": Mock(return_value=False),
            "start_background_worker": Mock(return_value=True),
            "stop_background_worker": Mock(return_value=True), "run_worker": Mock(),
        })

    def fake_service(self, name, members):
        name = f"backend.app.service.{name}"
        module = types.ModuleType(name)
        module.__dict__.update(members)
        patcher = patch.dict(sys.modules, {name: module})
        patcher.start()
        self.addCleanup(patcher.stop)
        return module

    def recommendation_item(self):
        return SimpleNamespace(title="模型编造的未核验名称", reason="适合你的日常偏好", search_keyword="真实番剧检索词")

    def create_anime(self, **values):
        with self.sessions() as db:
            anime = ui.anime_service.create_anime(db, discovery_tests.AnimeCreate(title="本地已看完", score=8.2, tags="日常,治愈", status="finished", **values))
            item_id = anime.id
        self.app.refresh_data()
        self.drain()
        self.app.watch_tree.selected = (str(item_id),)
        return item_id

    def test_personal_rating_and_tags_snapshot_website_score_unchanged(self):
        item_id = self.create_anime()
        for value, expected in (("0", 0), ("9.5", 9.5), ("10", 10), ("  ", None)):
            self.assertTrue(self.app.save_user_rating(item_id, value))
            self.drain()
            self.assertEqual(self.app.items[item_id]["user_rating"], expected)
            self.assertEqual(self.app.items[item_id]["score"], 8.2)
            self.assertEqual(self.app.items[item_id]["tags"], "日常,治愈")
            self.assertEqual(self.app.watch_tree.rows[str(item_id)][-1], expected if expected is not None else "—")

    def test_invalid_personal_rating_does_not_modify_database(self):
        item_id = self.create_anime(user_rating=7)
        for value in ("-1", "10.1", "nan", "inf", "abc"):
            self.assertFalse(self.app.save_user_rating(item_id, value))
        self.assertEqual(self.infos.call_count, 5)
        with self.sessions() as db:
            self.assertEqual(ui.anime_service.get_anime(db, item_id).user_rating, 7)
        self.assertFalse(self.app.busy)

    def test_rating_deleted_record_reports_failure_and_allows_retry(self):
        self.app.save_user_rating(999, "7")
        self.drain()
        self.errors.assert_called_once()
        self.assertFalse(self.app.busy)
        self.assertTrue(self.app.save_user_rating(self.create_anime(), "8"))
        self.drain()

    def test_transfer_cancellation_never_reads_or_writes_a_file(self):
        self.app.export_data()
        self.app.import_data()
        self.transfer.save_export.assert_not_called()
        self.transfer.load_import.assert_not_called()
        self.transfer.create_backup.assert_not_called()
        self.confirm.assert_not_called()
        self.assertFalse(self.app.busy)

    def test_export_and_backup_execute_off_ui_thread_and_report_path(self):
        threads = []
        self.transfer.save_export.side_effect = lambda db, path: threads.append(threading.get_ident()) or 2
        self.patch(ui.filedialog, "asksaveasfilename", return_value=str(self.data_dir / "export.json"))
        self.app.export_data()
        self.drain()
        self.assertIn("2", self.infos.call_args.args[1])
        self.assertIn("export.json", self.infos.call_args.args[1])
        self.assertNotEqual(threads, [threading.get_ident()])
        self.app.backup_data()
        self.drain()
        self.assertEqual(self.transfer.create_backup.call_args.args[1], self.data_dir / "backups")
        self.assertIn("test.json", self.infos.call_args.args[1])

    def test_import_defaults_to_keep_local_and_reports_full_summary(self):
        self.create_anime(user_rating=9)
        self.patch(ui.filedialog, "askopenfilename", return_value=str(self.data_dir / "input.json"))
        self.app.import_data()
        self.drain()
        self.assertEqual(self.transfer.load_import.call_args.kwargs, {"conflict": "keep_local", "backup_dir": self.data_dir / "backups"})
        self.confirm.assert_not_called()
        self.assertIn("新增 1 条 / 更新 0 条 / 跳过 1 条", self.infos.call_args.args[1])
        self.assertIn("before.json", self.infos.call_args.args[1])
        self.assertIn("导入完成", self.app.status_text.get())

    def test_replace_import_requires_additional_explicit_confirmation(self):
        self.patch(ui.filedialog, "askopenfilename", return_value=str(self.data_dir / "input.json"))
        self.app.import_data(True)
        self.transfer.load_import.assert_not_called()
        self.confirm.assert_called_once()
        self.assertEqual(self.confirm.call_args.kwargs["default"], "no")
        self.confirm.return_value = True
        self.app.import_data(True)
        self.drain()
        self.assertEqual(self.transfer.load_import.call_args.kwargs["conflict"], "replace_existing")

    def test_import_error_preserves_current_list_and_releases_busy_state(self):
        self.create_anime(user_rating=8)
        original = self.app.items.copy()
        self.patch(ui.filedialog, "askopenfilename", return_value=str(self.data_dir / "input.json"))
        self.transfer.load_import.side_effect = ValueError("不支持的格式")
        self.app.import_data()
        self.drain()
        self.assertEqual(self.app.items, original)
        self.errors.assert_called_once()
        self.assertFalse(self.app.busy)

    def test_ai_never_runs_during_refresh_and_snapshots_inputs_on_ui_thread(self):
        item_id = self.create_anime(user_rating=9)
        self.recommendation.generate_recommendations.assert_not_called()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def generate(db, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test worker was not released")
            record = ui.anime_service.get_anime(db, item_id)
            calls.append((threading.get_ident(), kwargs, record.user_rating, record.status, record.tags))
            return [self.recommendation_item()]

        self.recommendation.generate_recommendations.side_effect = generate
        self.app.ai_provider.set("qwen")
        self.app.ai_api_key.set("test-secret-only")
        try:
            self.app.generate_ai_recommendations()
            self.assertTrue(entered.wait(1))
            self.app.ai_provider.set("deepseek")
            self.app.ai_api_key.set("edited-key")
            self.app.ai_preference.set("edited preference")
            self.app.generate_ai_recommendations()
            self.assertEqual(self.recommendation.generate_recommendations.call_count, 1)
        finally:
            release.set()
            self.drain()
        self.assertEqual(calls[0][1], {"preference": "喜欢日常", "provider": "qwen", "api_key": "test-secret-only"})
        self.assertNotEqual(calls[0][0], threading.get_ident())
        self.assertEqual(calls[0][2:], (9, "finished", "日常,治愈"))
        self.assertEqual(len(self.app.recommendation_results), 1)
        self.assertEqual(len(self.app.items), 1)
        self.assertIn("未核验", self.app.ai_status.get())

    def test_ai_blank_key_and_invalid_provider(self):
        self.app.ai_provider.set("invalid")
        self.app.generate_ai_recommendations()
        self.recommendation.generate_recommendations.assert_not_called()
        self.app.ai_provider.set("auto")
        self.app.generate_ai_recommendations()
        self.drain()
        self.assertEqual(self.recommendation.generate_recommendations.call_args.kwargs["api_key"], None)

    def test_ai_failure_keeps_previous_results_and_redacts_session_key(self):
        self.app.generate_ai_recommendations()
        self.drain()
        previous = self.app.recommendation_results.copy()
        self.app.ai_api_key.set("test-secret-only")
        self.recommendation.generate_recommendations.side_effect = self.recommendation.RecommendationError("拒绝访问 test-secret-only")
        self.app.generate_ai_recommendations()
        self.drain()
        self.assertEqual(self.app.recommendation_results, previous)
        self.assertNotIn("test-secret-only", self.errors.call_args.args[1])
        self.assertNotIn("test-secret-only", self.app.status_text.get())
        self.assertIn("失败", self.app.ai_status.get())
        self.recommendation.generate_recommendations.side_effect = None
        self.app.generate_ai_recommendations()
        self.drain()
        self.assertIn("生成 1 条", self.app.ai_status.get())

    def test_ai_unexpected_error_never_exposes_provider_response(self):
        self.recommendation.generate_recommendations.side_effect = RuntimeError("Authorization: unknown-configured-key")
        self.app.generate_ai_recommendations()
        self.drain()
        self.assertNotIn("unknown-configured-key", self.errors.call_args.args[1])

    def test_rating_to_recommendation_to_bangumi_then_explicit_import(self):
        self.create_anime(user_rating=9)
        self.app.search_selected_recommendation()
        self.infos.assert_called_once()
        self.app.generate_ai_recommendations()
        self.drain()
        self.app.ai_tree.selected = ("recommendation-0",)
        self.app.search_source.set("稀饭动漫")
        with patch.object(ui, "BangumiClient", autospec=True) as client:
            client.return_value.search.return_value = [self.result("400", title="已确认的真实条目")]
            self.app.search_selected_recommendation()
            self.drain()
            client.return_value.search.assert_called_once_with("真实番剧检索词", limit=12)
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(self.app.keyword.get(), "真实番剧检索词")
        self.app.notebook.select.assert_called_with(self.app.search_tab)
        self.app.search_tree.selected = ("result-0",)
        self.app.import_selected()
        self.drain()
        with self.sessions() as db:
            saved = ui.anime_service.list_anime(db)
            self.assertEqual(len(saved), 2)
            self.assertIn(("400", "已确认的真实条目"), [(item.source_id, item.title) for item in saved])
            self.assertNotIn("模型编造的未核验名称", [item.title for item in saved])

    def test_background_controls_only_call_services_after_explicit_actions(self):
        self.create_anime()
        self.notification.start_background_worker.assert_not_called()
        self.notification.stop_background_worker.assert_not_called()
        threads = []

        def start(data_dir):
            threads.append(threading.get_ident())
            self.notification.background_status.return_value = True
            return True

        self.notification.start_background_worker.side_effect = start
        self.app.set_background_reminders(True)
        self.drain()
        self.assertIn("运行中", self.app.background_status_text.get())
        self.notification.start_background_worker.assert_called_once_with(self.data_dir)
        self.assertNotEqual(threads, [threading.get_ident()])
        self.notification.background_status.return_value = False
        self.app.set_background_reminders(False)
        self.drain()
        self.notification.stop_background_worker.assert_called_once_with(self.data_dir)
        self.app.check_background_reminders()
        self.drain()
        self.assertIn("已停止", self.app.background_status_text.get())

    def test_background_status_mismatch_is_reported(self):
        self.app.set_background_reminders(True)
        self.drain()
        self.errors.assert_called_once()
        self.assertIn("已停止", self.app.background_status_text.get())

    def test_stop_request_may_be_accepted_before_worker_exits(self):
        self.notification.background_status.return_value = True
        self.app.set_background_reminders(False)
        self.drain()
        self.errors.assert_not_called()
        self.assertIn("正在停止", self.app.background_status_text.get())

    def test_worker_arguments_dispatch_before_single_instance_and_tk(self):
        arguments = ui._parse_arguments(["--reminder-worker", "--data-dir", str(self.data_dir)])
        self.assertTrue(arguments.reminder_worker)
        self.assertEqual(arguments.data_dir, self.data_dir)
        with patch.object(ui, "_ENTRY_ARGUMENTS", arguments), patch.object(ui, "_claim_single_instance") as claim, patch.object(ui, "Tk") as tk:
            ui.main()
        self.notification.run_worker.assert_called_once_with(self.data_dir.resolve())
        claim.assert_not_called()
        tk.assert_not_called()

    def test_worker_script_entry_skips_storage_preparation_and_gui_initialization(self):
        with patch.object(sys, "argv", [str(ui.__file__), "--reminder-worker", "--data-dir", str(self.data_dir)]), \
                patch.dict(os.environ), patch("os.chdir"), \
                patch("backend.app.core.desktop_runtime.prepare_desktop_storage", side_effect=AssertionError("Worker must not prepare/migrate desktop storage")), \
                patch.object(ui.Base.metadata, "create_all", side_effect=AssertionError("Worker must not initialize a database")), \
                patch("tkinter.Tk", side_effect=AssertionError("Worker must not create Tk")):
            runpy.run_path(str(ui.__file__), run_name="__main__")
            self.assertEqual(os.environ["ZFZS_DATA_DIR"], str(self.data_dir.resolve()))
            self.assertEqual(os.environ["DATABASE_URL"], f"sqlite:///{(self.data_dir / 'zfzs.db').as_posix()}")
        self.notification.run_worker.assert_called_once_with(self.data_dir.resolve())

    def test_busy_guard_does_not_open_file_dialog_or_send_ai_or_spawn_worker(self):
        self.app.busy = True
        self.app.export_data()
        self.app.import_data(True)
        self.app.generate_ai_recommendations()
        self.app.set_background_reminders(True)
        ui.filedialog.askopenfilename.assert_not_called()
        ui.filedialog.asksaveasfilename.assert_not_called()
        self.recommendation.generate_recommendations.assert_not_called()
        self.notification.start_background_worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
