"""Temporary SQLite only; no real subprocess, persistent worker or notification."""

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from backend.app.db.session import Base
from backend.app.model.anime import Anime
from backend.app.schema.anime import AnimeUpdate
from backend.app.schema.crawler import XifanAnimeResult
from backend.app.service import anime_service
from backend.app.service import notification_service as ns
from backend.app.service.reminder_service import _is_due, list_today_due_anime, mark_reminded


class TemporaryDatabaseTest(unittest.TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(prefix="zfzs-reminders-test-")
        self.addCleanup(storage.cleanup)
        self.data_dir = Path(storage.name) / "用户 data #safe"
        self.data_dir.mkdir()
        self.engine = create_engine(URL.create("sqlite", database=str(self.data_dir / "zfzs.db")))
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.now = datetime(2026, 10, 17, 23, 50)  # Saturday -> Sunday=0
        for name, target in (("processes", "subprocess.Popen"), ("native", "_send_windows_notification")):
            guard = patch(f"backend.app.service.notification_service.{target}", side_effect=AssertionError("Real process/notification is forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def add_anime(self, **changes):
        values = dict(title="测试番剧", status="watching", broadcast_day=0, broadcast_time="00:10",
                      reminder_minutes=30, reminder_enabled=True, watched_episodes=0)
        values.update(changes)
        with Session(self.engine) as db:
            anime = Anime(**values)
            db.add(anime)
            db.commit()
            return anime.id

    def last_reminded(self, anime_id):
        with Session(self.engine) as db:
            return db.get(Anime, anime_id).last_reminded_at

    def hold_worker(self, token="a" * 32):
        lock = ns._FileLock(self.data_dir / ns._WORKER_LOCK)
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        ns._write_token(self.data_dir / ns._STATE, token)
        return lock


class ReminderCycleTests(TemporaryDatabaseTest):
    def test_saturday_sunday_advance_notice_deduplicates_and_rearms_next_week(self):
        anime_id = self.add_anime()
        notify = Mock(return_value=True)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now.replace(minute=39), notifier=notify), 0)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now.replace(minute=40), notifier=notify), 1)
        self.assertEqual(ns.run_once(self.data_dir, now=datetime(2026, 10, 18, 0, 11), notifier=notify), 0)
        self.assertEqual(ns.run_once(self.data_dir, now=datetime(2026, 10, 18, 23, 59), notifier=notify), 0)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now + timedelta(days=7), notifier=notify), 1)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(self.last_reminded(anime_id), self.now + timedelta(days=7))

    def test_sunday_monday_boundary_uses_next_broadcast_day(self):
        self.add_anime(broadcast_day=1)
        notify = Mock(return_value=True)
        sunday = datetime(2026, 10, 18, 23, 50)
        self.assertEqual(ns.run_once(self.data_dir, now=sunday, notifier=notify), 1)
        self.assertEqual(ns.run_once(self.data_dir, now=sunday + timedelta(minutes=30), notifier=notify), 0)

    def test_full_day_advance_notice_and_manual_acknowledgement(self):
        anime_id = self.add_anime(reminder_minutes=1440)
        before = datetime(2026, 10, 17, 0, 9)
        with Session(self.engine) as db:
            anime = db.get(Anime, anime_id)
            self.assertFalse(_is_due(anime, before))
            self.assertTrue(_is_due(anime, before + timedelta(minutes=1)))
            mark_reminded(db, anime, before + timedelta(minutes=1))
        notify = Mock(return_value=True)
        self.assertEqual(ns.run_once(self.data_dir, now=datetime(2026, 10, 18, 0, 11), notifier=notify), 0)
        notify.assert_not_called()

    def test_expired_broadcast_is_not_replayed_the_following_day(self):
        self.add_anime(broadcast_time="20:00", reminder_minutes=15)
        with Session(self.engine) as db:
            self.assertEqual(list_today_due_anime(db, datetime(2026, 10, 19, 0, 1)), [])

    def test_failed_submission_is_retried_and_only_success_is_marked(self):
        anime_id = self.add_anime()
        notify = Mock(side_effect=[False, True])
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 0)
        self.assertIsNone(self.last_reminded(anime_id))
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 1)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 0)
        self.assertEqual(notify.call_count, 2)

    def test_notifier_exception_does_not_mark_or_log_private_payload(self):
        anime_id = self.add_anime(title="PRIVATE_TITLE")
        with self.assertLogs(ns._LOG, level="WARNING") as logs:
            self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=Mock(side_effect=RuntimeError("PRIVATE_TITLE API_KEY=secret"))), 0)
        self.assertIsNone(self.last_reminded(anime_id))
        self.assertNotIn("PRIVATE_TITLE", " ".join(logs.output))
        self.assertNotIn("secret", " ".join(logs.output))

    def test_paused_finished_disabled_and_completed_progress_are_not_sent(self):
        for values in ({"status": "paused"}, {"status": "finished"}, {"reminder_enabled": False},
                       {"watched_episodes": 12, "total_episodes": 12}, {"broadcast_day": None}, {"broadcast_day": 7}):
            self.add_anime(**values)
        notify = Mock(return_value=True)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 0)
        notify.assert_not_called()

    def test_reimport_pause_resume_preserve_occurrence_acknowledgement(self):
        anime_id = self.add_anime(source="bangumi", source_id="42")
        notify = Mock(return_value=True)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 1)
        with Session(self.engine) as db:
            anime = anime_service.import_search_result(db, XifanAnimeResult(
                title="更新后的标题", source="bangumi", source_id="42", total_episodes=12,
            ))
            self.assertEqual(anime.id, anime_id)
            anime_service.update_anime(db, anime, AnimeUpdate(status="paused"))
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 0)
        with Session(self.engine) as db:
            anime_service.update_anime(db, db.get(Anime, anime_id), AnimeUpdate(status="watching"))
        self.assertEqual(ns.run_once(self.data_dir, now=self.now + timedelta(hours=1), notifier=notify), 0)
        notify.assert_called_once()

    def test_previous_week_timestamp_does_not_suppress_this_week(self):
        self.add_anime(last_reminded_at=self.now - timedelta(days=7))
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=Mock(return_value=True)), 1)

    def test_reducing_advance_minutes_does_not_repeat_the_same_airing(self):
        anime_id = self.add_anime()
        notify = Mock(return_value=True)
        self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 1)
        with Session(self.engine) as db:
            anime_service.update_anime(db, db.get(Anime, anime_id), AnimeUpdate(reminder_minutes=0))
        self.assertEqual(ns.run_once(self.data_dir, now=datetime(2026, 10, 18, 0, 11), notifier=notify), 0)
        notify.assert_called_once()

    def test_invalid_time_keeps_existing_twenty_hundred_fallback(self):
        anime_id = self.add_anime(broadcast_day=6, broadcast_time="invalid")
        with Session(self.engine) as db:
            anime = db.get(Anime, anime_id)
            self.assertFalse(_is_due(anime, self.now.replace(hour=19, minute=29)))
            self.assertTrue(_is_due(anime, self.now.replace(hour=19, minute=30)))

    def test_dispatch_lock_serializes_manual_poll_and_worker(self):
        self.add_anime()
        lock = ns._FileLock(self.data_dir / ns._DISPATCH_LOCK)
        self.assertTrue(lock.acquire())
        try:
            notify = Mock(return_value=True)
            self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=notify), 0)
            notify.assert_not_called()
        finally:
            lock.release()

    def test_explicit_database_ignores_inherited_url_and_global_sessions(self):
        anime_id = self.add_anime()
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///DO_NOT_TOUCH.db"}), patch("backend.app.db.session.SessionLocal", side_effect=AssertionError("Global DB must not be used")):
            self.assertEqual(ns.run_once(self.data_dir, now=self.now, notifier=Mock(return_value=True)), 1)
        self.assertEqual(self.last_reminded(anime_id), self.now)
        self.assertFalse((self.data_dir / "DO_NOT_TOUCH.db").exists())

    def test_missing_database_is_not_created(self):
        other = self.data_dir / "empty"
        other.mkdir()
        with self.assertRaises(FileNotFoundError):
            ns.run_once(other, now=self.now, notifier=Mock(return_value=True))
        self.assertEqual(list(other.iterdir()), [])


class WorkerControlTests(TemporaryDatabaseTest):
    def simulate_launch(self, command, **kwargs):
        self.hold_worker(kwargs["env"][ns._TOKEN_ENV])
        return Mock(poll=Mock(return_value=None))

    def test_status_is_read_only_and_never_starts_a_process(self):
        nonexistent = self.data_dir / "not-created"
        self.assertFalse(ns.background_status(nonexistent))
        self.assertFalse(nonexistent.exists())
        self.assertFalse(ns.background_status(self.data_dir))
        self.assertFalse((self.data_dir / ns._WORKER_LOCK).exists())

    def test_stale_state_or_pid_is_not_running_and_is_never_killed(self):
        (self.data_dir / ns._STATE).write_text(json.dumps({"token": "a" * 32, "pid": 12345}), encoding="utf-8")
        with patch.object(os, "kill") as kill:
            self.assertFalse(ns.background_status(self.data_dir))
            self.assertTrue(ns.stop_background_worker(self.data_dir))
            kill.assert_not_called()

    def test_live_lock_and_generation_qualified_stop_never_kill_a_pid(self):
        lock = self.hold_worker()
        self.assertTrue(ns.background_status(self.data_dir))
        with patch.object(os, "kill") as kill:
            self.assertTrue(ns.stop_background_worker(self.data_dir))
            kill.assert_not_called()
        self.assertEqual(ns._read_token(self.data_dir / ns._STOP), "a" * 32)
        self.assertTrue(ns.background_status(self.data_dir))  # stop is cooperative
        lock.release()
        self.assertFalse(ns.background_status(self.data_dir))

    def test_source_start_waits_for_ready_and_is_idempotent(self):
        with patch("backend.app.db.session.engine", self.engine), patch.object(ns.subprocess, "Popen", side_effect=self.simulate_launch) as launch, patch.dict(os.environ, {"DATABASE_URL": "sqlite:///WRONG.db", "DASHSCOPE_API_KEY": "secret"}):
            self.assertTrue(ns.start_background_worker(self.data_dir))
            self.assertTrue(ns.start_background_worker(self.data_dir))
        launch.assert_called_once()
        command, options = launch.call_args.args[0], launch.call_args.kwargs
        self.assertEqual(Path(command[1]).name, "reminder_worker.py")
        # macOS /var symlinks and Windows short temp paths must compare canonically.
        self.assertEqual(command[2:], ["--data-dir", str(self.data_dir.resolve())])
        self.assertEqual(options["env"]["DATABASE_URL"], f"sqlite:///{(self.data_dir.resolve() / 'zfzs.db').as_posix()}")
        self.assertNotIn("DASHSCOPE_API_KEY", options["env"])
        self.assertEqual(options["stdout"], subprocess.DEVNULL)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", options)

    def test_frozen_start_uses_worker_flag_not_the_python_script(self):
        with patch("backend.app.db.session.engine", self.engine), patch.object(ns.sys, "frozen", True, create=True), patch.object(ns.subprocess, "Popen", side_effect=self.simulate_launch) as launch:
            self.assertTrue(ns.start_background_worker(self.data_dir))
        self.assertEqual(launch.call_args.args[0], [ns.sys.executable, "--reminder-worker", "--data-dir", str(self.data_dir.resolve())])

    def test_custom_memory_database_is_explicitly_refused(self):
        custom = create_engine("sqlite:///:memory:")
        self.addCleanup(custom.dispose)
        with patch("backend.app.db.session.engine", custom), patch.object(ns.subprocess, "Popen") as launch, self.assertLogs(ns._LOG, level="WARNING") as logs:
            self.assertFalse(ns.start_background_worker(self.data_dir))
        launch.assert_not_called()
        self.assertIn("custom DATABASE_URL is unsupported", " ".join(logs.output))

    def test_another_sqlite_file_is_not_silently_replaced(self):
        custom = create_engine(URL.create("sqlite", database=str(self.data_dir / "custom.db")))
        self.addCleanup(custom.dispose)
        with patch("backend.app.db.session.engine", custom), patch.object(ns.subprocess, "Popen") as launch:
            self.assertFalse(ns.start_background_worker(self.data_dir))
        launch.assert_not_called()
        self.assertFalse((self.data_dir / "custom.db").exists())

    def test_stopping_worker_is_not_started_again_until_it_exits(self):
        self.hold_worker()
        ns._write_token(self.data_dir / ns._STOP, "a" * 32)
        with patch("backend.app.db.session.engine", self.engine), patch.object(ns.subprocess, "Popen") as launch:
            self.assertFalse(ns.start_background_worker(self.data_dir))
        launch.assert_not_called()

    def test_timeout_cancels_a_worker_that_has_not_imported_yet(self):
        with patch("backend.app.db.session.engine", self.engine), patch.object(ns, "_START_TIMEOUT", 0), patch.object(ns.subprocess, "Popen", return_value=Mock(poll=Mock(return_value=None))) as launch:
            self.assertFalse(ns.start_background_worker(self.data_dir))
        token = launch.call_args.kwargs["env"][ns._TOKEN_ENV]
        self.assertEqual(ns._read_token(self.data_dir / ns._STOP), token)
        notify = Mock(return_value=True)
        with patch.dict(os.environ, {ns._TOKEN_ENV: token}):
            ns.run_worker(self.data_dir, notifier=notify, wait=Mock(side_effect=AssertionError("No real waits")))
        notify.assert_not_called()
        self.assertFalse(ns.background_status(self.data_dir))

    def test_early_child_failure_is_not_reported_as_success(self):
        with patch("backend.app.db.session.engine", self.engine), patch.object(ns.subprocess, "Popen", return_value=Mock(poll=Mock(return_value=1))):
            self.assertFalse(ns.start_background_worker(self.data_dir))

    def test_worker_is_injectable_and_stops_and_cleans_state(self):
        anime_id = self.add_anime()
        notify = Mock(return_value=True)

        def stop_during_wait(seconds):
            self.assertLessEqual(seconds, 0.25)
            self.assertTrue(ns.background_status(self.data_dir))
            self.assertTrue(ns.stop_background_worker(self.data_dir))

        ns.run_worker(self.data_dir, notifier=notify, clock=lambda: self.now, wait=stop_during_wait)
        notify.assert_called_once()
        self.assertEqual(self.last_reminded(anime_id), self.now)
        self.assertFalse(ns.background_status(self.data_dir))
        self.assertFalse((self.data_dir / ns._STATE).exists())
        self.assertFalse((self.data_dir / ns._STOP).exists())
        self.assertTrue((self.data_dir / "reminder-worker.log").is_file())

    def test_worker_retries_failure_on_the_next_injected_poll(self):
        anime_id = self.add_anime()
        notify = Mock(side_effect=[False, True])

        def stop_after_retry(seconds):
            if notify.call_count == 2:
                ns.stop_background_worker(self.data_dir)

        ns.run_worker(self.data_dir, 1, notifier=notify, clock=lambda: self.now, wait=stop_after_retry)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(self.last_reminded(anime_id), self.now)

    def test_duplicate_worker_cannot_send_or_delete_the_owners_state(self):
        self.add_anime()
        self.hold_worker()
        notify = Mock(return_value=True)
        ns.run_worker(self.data_dir, notifier=notify, clock=lambda: self.now, wait=Mock(side_effect=AssertionError("No waits")))
        notify.assert_not_called()
        self.assertEqual(ns._read_token(self.data_dir / ns._STATE), "a" * 32)

    def test_stale_stop_generation_cannot_stop_a_new_worker(self):
        self.add_anime()
        ns._write_token(self.data_dir / ns._STOP, "a" * 32)
        notify = Mock(return_value=True)
        ns._write_token(self.data_dir / ns._LAUNCH, "b" * 32)
        with patch.dict(os.environ, {ns._TOKEN_ENV: "b" * 32}):
            ns.run_worker(self.data_dir, notifier=notify, clock=lambda: self.now, wait=lambda seconds: ns.stop_background_worker(self.data_dir))
        notify.assert_called_once()

    def test_old_timed_out_launch_is_revoked_even_when_stop_file_is_replaced(self):
        self.add_anime()
        ns._write_token(self.data_dir / ns._STOP, "b" * 32)
        ns._write_token(self.data_dir / ns._LAUNCH, "b" * 32)
        notify = Mock(return_value=True)
        with patch.dict(os.environ, {ns._TOKEN_ENV: "a" * 32}):
            ns.run_worker(self.data_dir, notifier=notify, clock=lambda: self.now, wait=Mock(side_effect=AssertionError("Revoked launch must never poll")))
        notify.assert_not_called()
        self.assertEqual(ns._read_token(self.data_dir / ns._STOP), "b" * 32)
        self.assertEqual(ns._read_token(self.data_dir / ns._LAUNCH), "b" * 32)
        self.assertFalse(ns.background_status(self.data_dir))

    def test_source_entry_dispatches_to_explicit_directory_and_never_opens_ui(self):
        from scripts import reminder_worker

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///WRONG.db"}), patch.object(ns, "run_worker") as worker:
            reminder_worker.main(["--data-dir", str(self.data_dir), "--poll-seconds", "2"])
            self.assertEqual(os.environ["DATABASE_URL"], f"sqlite:///{(self.data_dir.resolve() / 'zfzs.db').as_posix()}")
        worker.assert_called_once_with(self.data_dir.resolve(), 2)

    def test_stop_during_dispatch_prevents_the_rest_of_the_batch(self):
        self.add_anime()
        self.add_anime(title="第二部")

        def notify_and_stop(title, message):
            self.assertTrue(ns.stop_background_worker(self.data_dir))
            return True

        notify = Mock(side_effect=notify_and_stop)
        ns.run_worker(self.data_dir, notifier=notify, clock=lambda: self.now, wait=Mock(side_effect=AssertionError("No wait after stopping")))
        notify.assert_called_once()
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(Anime).where(Anime.last_reminded_at.is_not(None))).all()), 1)

    def test_invalid_poll_interval_does_not_start_anything(self):
        for interval in (0, -1, True, 1.5):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                ns.run_worker(self.data_dir, interval)
        self.assertFalse((self.data_dir / ns._WORKER_LOCK).exists())

    def test_missing_schema_never_reports_readiness(self):
        Base.metadata.drop_all(self.engine)
        notify = Mock(return_value=True)
        with self.assertLogs(ns._LOG, level="WARNING") as logs:
            ns.run_worker(self.data_dir, notifier=notify, wait=Mock(side_effect=AssertionError("No waits")))
        notify.assert_not_called()
        self.assertIn("worker failed", " ".join(logs.output))
        self.assertFalse(ns.background_status(self.data_dir))
        self.assertFalse((self.data_dir / ns._STATE).exists())


class PlatformAdapterTests(unittest.TestCase):
    def test_windows_passes_text_to_native_api_not_script_source(self):
        title = '番剧 "; Start-Process unwanted; $()'
        with patch.object(ns.sys, "platform", "win32"), patch.object(ns, "_send_windows_notification", return_value=True) as native, patch.object(ns.subprocess, "run") as run:
            self.assertTrue(ns.send_system_notification(title, "message"))
        native.assert_called_once_with(title, "message")
        run.assert_not_called()

    def test_windows_failure_remains_failure(self):
        with patch.object(ns.sys, "platform", "win32"), patch.object(ns, "_send_windows_notification", return_value=False):
            self.assertFalse(ns.send_system_notification("title", "message"))

    def test_mac_uses_fixed_script_and_environment_data(self):
        title, message = '-e "malicious"', '中文\n" & do shell script "bad"'
        with patch.object(ns.sys, "platform", "darwin"), patch.object(ns.shutil, "which", return_value="/usr/bin/osascript"), patch.object(ns.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertTrue(ns.send_system_notification(title, message))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/osascript", "-e", ns._MAC_SCRIPT])
        self.assertEqual(run.call_args.kwargs["env"]["ZFZS_NOTIFICATION_TITLE"], title)
        self.assertEqual(run.call_args.kwargs["env"]["ZFZS_NOTIFICATION_MESSAGE"], message)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_missing_mac_command_is_readable_and_false(self):
        with patch.object(ns.sys, "platform", "darwin"), patch.object(ns.shutil, "which", return_value=None), self.assertLogs(ns._LOG, level="WARNING") as logs:
            self.assertFalse(ns.send_system_notification("title", "message"))
        self.assertIn("osascript was not found", " ".join(logs.output))

    def test_linux_terminates_options_and_escapes_body_markup(self):
        with patch.object(ns.sys, "platform", "linux"), patch.object(ns.shutil, "which", return_value="/usr/bin/notify-send"), patch.object(ns.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertTrue(ns.send_system_notification("--title", "<b>文字</b> & more"))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/notify-send", "--app-name=ZFZS", "--", "--title", "&lt;b&gt;文字&lt;/b&gt; &amp; more"])

    def test_linux_without_tool_is_unsupported_not_stdout_success(self):
        with patch.object(ns.sys, "platform", "linux"), patch.object(ns.shutil, "which", return_value=None), patch.object(ns.subprocess, "run") as run:
            self.assertFalse(ns.send_system_notification("title", "message"))
        run.assert_not_called()

    def test_nonzero_exit_and_timeout_do_not_log_payload_or_secrets(self):
        for result in (Mock(returncode=1), subprocess.TimeoutExpired("secret-key", 15)):
            options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
            with patch.object(ns.sys, "platform", "darwin"), patch.object(ns.shutil, "which", return_value="osascript"), patch.object(ns.subprocess, "run", **options), self.assertLogs(ns._LOG, level="WARNING") as logs:
                self.assertFalse(ns.send_system_notification("PRIVATE_TITLE", "secret-key"))
            self.assertNotIn("PRIVATE_TITLE", " ".join(logs.output))
            self.assertNotIn("secret-key", " ".join(logs.output))

    def test_invalid_text_and_unsupported_platform_return_false(self):
        with patch.object(ns.subprocess, "run") as run:
            self.assertFalse(ns.send_system_notification("nul\0", "message"))
            self.assertFalse(ns.send_system_notification(1, "message"))
            with patch.object(ns.sys, "platform", "unsupported"):
                self.assertFalse(ns.send_system_notification("title", "message"))
        run.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Win32 ABI mock is only meaningful on Windows")
    def test_win32_structure_success_failure_and_cleanup_without_real_api(self):
        for results, expected in (([1, 1, 1, 1], True), ([0], False), ([1, 0, 1], False), ([1, 1, 0, 1], False)):
            with self.subTest(results=results):
                user, shell = Mock(), Mock()
                user.CreateWindowExW.return_value = 123
                user.LoadIconW.return_value = 456
                shell.Shell_NotifyIconW.side_effect = results
                with patch.object(ns.ctypes, "WinDLL", side_effect=[user, shell]), patch.object(ns.time, "monotonic", side_effect=[0, 11]):
                    self.assertEqual(ns._send_windows_notification("📺" * 100, "消息" * 200), expected)
                user.DestroyWindow.assert_called_once_with(123)
                operations = [call.args[0] for call in shell.Shell_NotifyIconW.call_args_list]
                self.assertEqual(operations, [0, 4, 1, 2] if len(results) == 4 else ([0] if len(results) == 1 else [0, 4, 2]))


if __name__ == "__main__":
    unittest.main()
