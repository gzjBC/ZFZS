import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import URL, create_engine, event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
from backend.app.model.anime import Anime
from backend.app.service import transfer_service as transfer


class TransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zfzs transfer tests ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.backups = self.root / "explicit backups"
        self.input = self.root / "input.json"

    def seed(self, **overrides):
        values = dict(title="本机番剧", source="bangumi", source_id="42",
                      watched_episodes=8, total_episodes=12, user_rating=9.5)
        values.update(overrides)
        anime = Anime(**values)
        self.db.add(anime)
        self.db.commit()
        return anime

    def document(self, items=None, **overrides):
        result = dict(format=transfer.FORMAT, version=transfer.VERSION,
                      exported_at="2026-10-15T08:30:00.123456+00:00",
                      items=items if items is not None else [
                          dict(title="外部番剧", source="bangumi", source_id="42")])
        result.update(overrides)
        return result

    def write_document(self, document):
        self.input.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return self.input

    def import_items(self, items=None, *, conflict="keep_local", **overrides):
        self.write_document(self.document(items, **overrides))
        return transfer.load_import(self.db, self.input, conflict, self.backups)

    def rows(self):
        return list(self.db.scalars(select(Anime).order_by(Anime.id)))

    def snapshot(self):
        return [dict(row) for row in self.db.execute(select(Anime.__table__)).mappings()]

    def test_export_allowlist_and_no_settings_access(self):
        anime = self.seed(score=7.2, title_cn="中文标题", tags="科幻,成长")
        anime.fake_secret = "must-not-export"
        destination = self.root / "export with spaces.json"
        before = self.snapshot()
        with patch("backend.app.core.config.get_settings", side_effect=AssertionError("settings read")), \
                patch.dict(os.environ, {"DASHSCOPE_API_KEY": "private-key"}):
            self.assertEqual(transfer.save_export(self.db, destination), 1)
        content = destination.read_text(encoding="utf-8")
        document = json.loads(content)
        self.assertEqual((document["format"], document["version"]), (transfer.FORMAT, 1))
        self.assertEqual(set(document["items"][0]), set(transfer.EXPORT_FIELDS))
        self.assertNotIn("id", document["items"][0])
        for secret in ("private-key", "must-not-export", "database_url"):
            self.assertNotIn(secret, content)
        self.assertIn("中文标题", content)
        self.assertEqual(document["items"][0]["score"], 7.2)
        self.assertEqual(document["items"][0]["user_rating"], 9.5)
        self.assertEqual(self.snapshot(), before)

    def test_empty_export_import_and_backup(self):
        destination = self.root / "new folder" / "empty.json"
        self.assertEqual(transfer.save_export(self.db, destination), 0)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["items"], [])
        self.assertEqual(transfer.load_import(self.db, destination), transfer.ImportSummary())
        backup = transfer.create_backup(self.db, self.backups)
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["items"], [])

    def test_full_cross_computer_roundtrip_preserves_fields_not_row_ids(self):
        stamp = datetime(2026, 9, 2, 17, 11, 22, 123456)
        original = self.seed(
            id=9999, title="番剧 Ａ", title_cn="完整中文名", cover_url="https://example.test/cover.png",
            summary="第一行\n第二行", status="finished", broadcast_day=0, broadcast_time="00:01",
            reminder_enabled=False, reminder_minutes=0, watched_episodes=12, total_episodes=12,
            play_url="https://example.test/watch?a=1&b=2", source_url="https://example.test/subject/42",
            source_status="全12集", year=2026, score=7.6, user_rating=0, tags="日常,科幻",
            last_reminded_at=stamp - timedelta(days=2), completed_at=stamp,
            created_at=stamp - timedelta(days=10), updated_at=stamp,
        )
        destination = self.root / "export.json"
        transfer.save_export(self.db, destination)
        expected = {field: getattr(original, field) for field in transfer.EXPORT_FIELDS}
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as target:
            summary = transfer.load_import(target, destination)
            self.assertEqual((summary.created, summary.updated, summary.skipped), (1, 0, 0))
            self.assertIsNone(summary.backup_path)
            restored = target.scalar(select(Anime))
            self.assertNotEqual(restored.id, original.id)
            self.assertEqual({field: getattr(restored, field) for field in transfer.EXPORT_FIELDS}, expected)
            repeated = transfer.load_import(target, destination, backup_dir=self.backups)
            self.assertEqual((repeated.created, repeated.updated, repeated.skipped), (0, 0, 1))

    def test_keep_local_preserves_all_fields_and_backs_up_original(self):
        self.seed()
        before = self.snapshot()
        summary = self.import_items([dict(title="旧标题", source="bangumi", source_id="42",
                                          watched_episodes=1, user_rating=3, reminder_enabled=False)])
        self.assertEqual((summary.created, summary.updated, summary.skipped), (0, 0, 1))
        self.assertEqual(self.snapshot(), before)
        backup = json.loads(summary.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backup["items"][0]["watched_episodes"], 8)
        self.assertEqual(backup["items"][0]["user_rating"], 9.5)

    def test_replace_only_matches_and_is_idempotent(self):
        local = self.seed()
        other = self.seed(title="不可删除", source_id="other", watched_episodes=2)
        result = self.import_items([
            dict(title="新标题", source="bangumi", source_id="42", watched_episodes=3,
                 user_rating=6.2, score=7.9, reminder_enabled=False),
            dict(title="新番", source="bangumi", source_id="43"),
        ], conflict="replace_existing")
        self.assertEqual((result.created, result.updated, result.skipped), (1, 1, 0))
        self.assertEqual(self.db.get(Anime, local.id).watched_episodes, 3)
        self.assertEqual(self.db.get(Anime, local.id).user_rating, 6.2)
        self.assertEqual(self.db.get(Anime, local.id).score, 7.9)
        self.assertEqual(self.db.get(Anime, other.id).watched_episodes, 2)
        before = self.snapshot()
        repeated = transfer.load_import(self.db, self.input, "replace_existing", self.backups)
        self.assertEqual((repeated.created, repeated.updated, repeated.skipped), (0, 0, 2))
        self.assertEqual(self.snapshot(), before)

    def test_replace_keeps_timestamp_even_when_equal_to_previous_timestamp(self):
        stamp = datetime(2026, 10, 1, 1, 2, 3, 456789)
        self.seed(created_at=stamp, updated_at=stamp)
        result = self.import_items([dict(
            title="修改进度", source="bangumi", source_id="42", watched_episodes=2,
            created_at=stamp.isoformat(), updated_at=stamp.isoformat(),
        )], conflict="replace_existing")
        self.assertEqual(result.updated, 1)
        self.assertEqual(self.rows()[0].updated_at, stamp)
        repeated = transfer.load_import(self.db, self.input, "replace_existing", self.backups)
        self.assertEqual((repeated.updated, repeated.skipped), (0, 1))

    def test_source_identity_ignores_title_but_scopes_id_to_source(self):
        self.seed()
        result = self.import_items([
            dict(title="改名", source=" Bangumi ", source_id=" 42 "),
            dict(title="另一来源", source="xifan", source_id="42"),
            dict(title="大写ID", source="bangumi", source_id="A"),
            dict(title="小写ID", source="bangumi", source_id="a"),
        ])
        self.assertEqual((result.created, result.skipped), (3, 1))

    def test_manual_identity_normalizes_name_and_primary_url(self):
        self.seed(title=" Ａ  Show ", source=None, source_id=None,
                  source_url="https://EXAMPLE.test:443/watch#old")
        result = self.import_items([
            dict(title="a show", play_url="https://example.test/watch#new"),
            dict(title="a show", play_url="https://example.test/other"), dict(title="a show"),
        ])
        self.assertEqual((result.created, result.skipped), (2, 1))
        repeated = transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual((repeated.created, repeated.skipped), (0, 3))

    def test_manual_source_url_precedes_play_url(self):
        self.seed(title="同名", source="manual", source_id=None,
                  source_url="https://example.test/show", play_url="https://example.test/old-player")
        result = self.import_items([dict(title="同名", source_url="https://example.test/show",
                                         play_url="https://example.test/new-player")])
        self.assertEqual(result.skipped, 1)

    def test_duplicate_incoming_identities_reject_before_backup(self):
        self.seed()
        before = self.snapshot()
        for items in (
            [dict(title="一", source="bangumi", source_id="42"),
             dict(title="二", source="BANGUMI", source_id="42")],
            [dict(title="Ａ  show"), dict(title="a show")],
        ):
            with self.subTest(items=items), self.assertRaises(transfer.TransferError):
                self.import_items(items)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(self.backups.exists())

    def test_ambiguous_local_match_rejects_all_changes(self):
        self.seed()
        self.seed(title="已有重复", watched_episodes=1)
        before = self.snapshot()
        with self.assertRaisesRegex(transfer.TransferError, "Multiple local"):
            self.import_items([
                dict(title="不应先写入", source="bangumi", source_id="new"),
                dict(title="冲突", source="bangumi", source_id="42"),
            ], conflict="replace_existing")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.backups.exists())

    def test_entire_input_is_validated_before_database_access(self):
        self.write_document(self.document([dict(title="有效"), dict(title="无效", watched_episodes=-1)]))
        with patch.object(self.db, "connection", side_effect=AssertionError("DB access")), \
                patch.object(self.db, "get_bind", side_effect=AssertionError("DB access")):
            with self.assertRaises(transfer.TransferError):
                transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(self.rows(), [])

    def test_invalid_record_fields_reject_strictly_without_coercion(self):
        invalid = [
            dict(title=""), dict(title=" "), dict(title=7), dict(title=None),
            dict(title="x" * 256), dict(title="bad\x00title"),
            dict(title_cn=1), dict(summary=[]), dict(source=""), dict(source_id=""),
            dict(source_id="42"), dict(source="x" * 65), dict(source_id=42),
            dict(status="completed"), dict(status=[]), dict(status=None),
            dict(broadcast_day=True), dict(broadcast_day=-1), dict(broadcast_day=7),
            dict(broadcast_time="24:00"), dict(broadcast_time="8:30"), dict(broadcast_time=800),
            dict(reminder_enabled="false"), dict(reminder_enabled=1), dict(reminder_enabled=None),
            dict(reminder_minutes=-1), dict(reminder_minutes=1441), dict(reminder_minutes="15"),
            dict(watched_episodes=-1), dict(watched_episodes=True), dict(watched_episodes=1.5),
            dict(watched_episodes="2"), dict(watched_episodes=transfer.MAX_EPISODES + 1),
            dict(total_episodes=-1), dict(total_episodes=False),
            dict(watched_episodes=3, total_episodes=2), dict(watched_episodes=1, total_episodes=0),
            dict(year=1899), dict(year=2201), dict(year=2026.0),
            dict(score=-0.1), dict(score=10.1), dict(score=True), dict(score="9"),
            dict(user_rating=-1), dict(user_rating=11), dict(user_rating=False),
            dict(user_rating=10 ** 1000), dict(tags=["x"]),
            dict(created_at=None), dict(updated_at=123),
            dict(completed_at="2026-02-30T01:02:03"), dict(last_reminded_at="2026-10-15"),
            dict(created_at="2026-10-15T00:00:00+08:60"),
            dict(id=42), dict(dashscope_api_key="secret"), dict(unknown="field"),
        ]
        for update in invalid:
            with self.subTest(update=update):
                self.write_document(self.document([{"title": "valid", **update}]))
                with self.assertRaises(transfer.TransferError):
                    transfer.load_import(self.db, self.input, backup_dir=self.backups)
                self.assertEqual(self.rows(), [])

    def test_url_validation_rejects_unsafe_and_malformed_values_for_all_url_fields(self):
        invalid = [
            "javascript:alert(1)", "file:///etc/passwd", "data:text/plain,hello", "//example.test/x",
            "relative/path", "https://", "https://bad host/a", "https://example.test\\@evil.test/",
            "https://name:password@example.test/", "https://name@example.test/",
            "https://example.test:65536/", "https://example.test:invalid/", "https://example.test:/",
            "https://[bad]/", "https://-invalid.test/", "https://a..test/", "https://a_test/",
            " https://example.test/", "https://example.test/\n", "https://example.test/%0aheader",
            "https://example.test/%GG", "https://example.test/" + "a" * 4096, 42, "",
        ]
        for field in ("cover_url", "play_url", "source_url"):
            for value in invalid:
                with self.subTest(field=field, value=value), self.assertRaises(transfer.TransferError):
                    self.import_items([dict(title="URL测试", **{field: value})])
        self.assertEqual(self.rows(), [])

    def test_unicode_ipv6_urls_unknown_and_zero_totals(self):
        result = self.import_items([
            dict(title="国际化", source_url="https://例子.测试/动漫?q=追番", watched_episodes=77),
            dict(title="IPv6", play_url="http://[::1]:8080/watch", total_episodes=0),
        ])
        self.assertEqual(result.created, 2)

    def test_datetime_microseconds_and_offsets(self):
        self.import_items([dict(
            title="时间", status="finished", created_at="2026-10-01T01:02:03.000004",
            updated_at="2026-10-15T12:34:56.123456+08:00",
            completed_at="2026-10-15T04:34:56.123456Z",
            last_reminded_at="2026-10-14T23:59:59.987654-02:00",
        )])
        anime = self.rows()[0]
        self.assertEqual(anime.created_at, datetime(2026, 10, 1, 1, 2, 3, 4))
        self.assertEqual(anime.updated_at, datetime(2026, 10, 15, 4, 34, 56, 123456))
        self.assertEqual(anime.completed_at, anime.updated_at)
        self.assertEqual(anime.last_reminded_at, datetime(2026, 10, 15, 1, 59, 59, 987654))
        destination = self.root / "roundtrip.json"
        transfer.save_export(self.db, destination)
        repeated = transfer.load_import(self.db, destination, "replace_existing", self.backups)
        self.assertEqual((repeated.updated, repeated.skipped), (0, 1))

    def test_bad_envelopes_versions_and_record_types(self):
        invalid = [
            [], None, "string", {}, self.document(version=2), self.document(version=True),
            self.document(version="1"), self.document(format="another-app"), self.document(items={}),
            self.document(exported_at="yesterday"), self.document(exported_at=None),
            self.document(items=[None]), self.document(items=[[]]), self.document(items=[{}]),
            self.document(settings=dict(api_key="secret")),
        ]
        missing = self.document()
        del missing["version"]
        invalid.append(missing)
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(transfer.TransferError):
                self.write_document(document)
                transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(self.rows(), [])

    def test_corrupt_json_duplicate_keys_encoding_nonfinite_and_nesting(self):
        base = json.dumps(self.document())
        invalid = [
            b"", b"{truncated", b"\xff\xfe", b"[" * 2000 + b"]" * 2000,
            base.replace('"version": 1', '"version": 1, "version": 1').encode(),
            base.replace('"title":', '"title": "duplicate", "title":').encode(),
            json.dumps(self.document([dict(title="\\ud800")])).replace("\\\\ud800", "\\ud800").encode(),
        ]
        for value in (float("nan"), float("inf"), float("-inf")):
            invalid.append(json.dumps(self.document([dict(title="rating", user_rating=value)])).encode())
        invalid.append(json.dumps(self.document([dict(title="rating", score=0)]))
                       .replace('"score": 0', '"score": 1e999').encode())
        for content in invalid:
            with self.subTest(content=content[:80]), self.assertRaises(transfer.TransferError):
                self.input.write_bytes(content)
                transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(self.rows(), [])

    def test_utf8_bom_is_accepted(self):
        self.input.write_bytes(b"\xef\xbb\xbf" + json.dumps(self.document()).encode())
        self.assertEqual(transfer.load_import(self.db, self.input).created, 1)

    def test_import_size_and_item_limits(self):
        self.input.write_bytes(b" " * 257)
        with patch.object(transfer, "MAX_IMPORT_BYTES", 256), self.assertRaises(transfer.TransferError):
            transfer.load_import(self.db, self.input)
        self.write_document(self.document([dict(title="one"), dict(title="two")]))
        with patch.object(transfer, "MAX_IMPORT_ITEMS", 1), self.assertRaises(transfer.TransferError):
            transfer.load_import(self.db, self.input)
        self.assertEqual(self.rows(), [])

    def test_export_limits_preserve_previous_output(self):
        self.seed()
        self.seed(source_id="43")
        destination = self.root / "previous.json"
        destination.write_bytes(b"previous output")
        for name, limit in (("MAX_IMPORT_ITEMS", 1), ("MAX_IMPORT_BYTES", 1)):
            with self.subTest(name=name), patch.object(transfer, name, limit), \
                    self.assertRaises(transfer.TransferError):
                transfer.save_export(self.db, destination)
            self.assertEqual(destination.read_bytes(), b"previous output")

    def test_atomic_replace_and_fsync_failures_preserve_previous_file(self):
        self.seed()
        destination = self.root / "previous.json"
        destination.write_bytes(b"previous output")
        for function in ("replace", "fsync"):
            with self.subTest(function=function), patch.object(
                transfer.os, function, side_effect=OSError("simulated IO failure")
            ), self.assertRaises(OSError):
                transfer.save_export(self.db, destination)
            self.assertEqual(destination.read_bytes(), b"previous output")
            self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_backup_failure_prevents_every_database_change(self):
        self.seed()
        before = self.snapshot()
        self.write_document(self.document([
            dict(title="匹配更新", source="bangumi", source_id="42"), dict(title="不得新增"),
        ]))
        with patch.object(transfer.os, "replace", side_effect=OSError("backup failure")), self.assertRaises(OSError):
            transfer.load_import(self.db, self.input, "replace_existing", self.backups)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_sqlite_failure_after_update_and_insert_rolls_back_everything(self):
        self.seed()
        before = self.snapshot()
        self.write_document(self.document([
            dict(title="不得保留更新", source="bangumi", source_id="42"),
            dict(title="首次写入"), dict(title="触发数据库错误"),
        ]))
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_test_insert BEFORE INSERT ON anime "
                "WHEN NEW.title = '触发数据库错误' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        with self.assertRaises(SQLAlchemyError):
            transfer.load_import(self.db, self.input, "replace_existing", self.backups)
        self.assertEqual(self.snapshot(), before)
        backups = list(self.backups.glob("*.json"))
        self.assertEqual(len(backups), 1)
        original = json.loads(backups[0].read_text(encoding="utf-8"))["items"][0]
        self.assertEqual((original["title"], original["watched_episodes"]), ("本机番剧", 8))
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER reject_test_insert")
        result = transfer.load_import(self.db, self.input, "replace_existing", self.backups)
        self.assertEqual((result.created, result.updated), (2, 1))

    def test_commit_failure_rolls_back(self):
        self.seed()
        before = self.snapshot()
        self.write_document(self.document([dict(title="新条目")]))
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit refused")), self.assertRaises(RuntimeError):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(self.snapshot(), before)

    def test_database_changes_commit_exactly_once(self):
        self.seed()
        commits = []
        event.listen(self.db, "after_commit", lambda session: commits.append(True))
        self.import_items([
            dict(title="更新", source="bangumi", source_id="42"),
            dict(title="新增一"), dict(title="新增二"),
        ], conflict="replace_existing")
        self.assertEqual(commits, [True])

    def test_nonempty_memory_database_requires_explicit_backup_directory(self):
        self.seed()
        before = self.snapshot()
        self.write_document(self.document([dict(title="新增")]))
        with patch.object(transfer, "create_backup", side_effect=AssertionError("unsafe fallback")):
            with self.assertRaisesRegex(transfer.TransferError, "backup_dir"):
                transfer.load_import(self.db, self.input)
        self.assertEqual(self.snapshot(), before)

    def test_default_backup_path_handles_sqlite_filename_spaces_and_unicode(self):
        folder = self.root / "电脑 A with spaces 中文"
        folder.mkdir()
        database = folder / "追番 data.db"
        engine = create_engine(URL.create("sqlite", database=str(database)))
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.write_document(self.document([dict(title="迁入")]))
        with sessionmaker(bind=engine)() as db:
            db.add(Anime(title="原有", watched_episodes=4))
            db.commit()
            summary = transfer.load_import(db, self.input)
            self.assertEqual(summary.backup_path.parent, folder.resolve() / "backups")
            self.assertTrue(summary.backup_path.is_file())
            items = json.loads(summary.backup_path.read_text(encoding="utf-8"))["items"]
            self.assertEqual([item["title"] for item in items], ["原有"])
            self.assertEqual(items[0]["watched_episodes"], 4)

    def test_export_rejects_database_and_journal_destinations(self):
        database = self.root / "data with spaces.db"
        engine = create_engine(URL.create("sqlite", database=str(database)))
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            db.add(Anime(title="保护数据库"))
            db.commit()
            for suffix in ("", "-wal", "-shm", "-journal"):
                with self.subTest(suffix=suffix), self.assertRaises(transfer.TransferError):
                    transfer.save_export(db, Path(str(database) + suffix))
            self.assertEqual(db.scalar(select(Anime.title)), "保护数据库")

    def test_unique_backups_can_be_reimported(self):
        self.seed()
        first = transfer.create_backup(self.db, self.backups)
        second = transfer.create_backup(self.db, self.backups)
        self.assertNotEqual(first, second)
        self.db.execute(text("DELETE FROM anime"))
        self.db.commit()
        result = transfer.load_import(self.db, first)
        self.assertEqual(result.created, 1)
        self.assertEqual(self.rows()[0].watched_episodes, 8)

    def test_pending_changes_are_never_flushed_exported_or_committed(self):
        self.write_document(self.document())
        pending = Anime(title="尚未提交")
        self.db.add(pending)
        operations = (
            lambda: transfer.save_export(self.db, self.root / "export.json"),
            lambda: transfer.create_backup(self.db, self.backups),
            lambda: transfer.load_import(self.db, self.input, backup_dir=self.backups),
        )
        for operation in operations:
            with self.assertRaises(transfer.TransferError):
                operation()
        self.assertIsNone(pending.id)
        self.assertIn(pending, self.db.new)
        self.assertFalse(self.backups.exists())
        self.db.rollback()
        self.assertEqual(self.rows(), [])

    def test_explicit_caller_transaction_is_left_intact(self):
        self.write_document(self.document())
        with self.db.begin():
            with self.assertRaisesRegex(transfer.TransferError, "own transaction"):
                transfer.load_import(self.db, self.input)
            self.assertTrue(self.db.in_transaction())
        self.assertEqual(self.rows(), [])

    def test_unknown_conflict_policy_rejects_before_changes_or_backup(self):
        self.seed()
        before = self.snapshot()
        self.write_document(self.document())
        for conflict in ("overwrite", "replace", "", None, []):
            with self.subTest(conflict=conflict), self.assertRaises(transfer.TransferError):
                transfer.load_import(self.db, self.input, conflict, self.backups)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.backups.exists())

    def test_missing_file_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertFalse(self.input.exists())

    def test_empty_import_still_backs_up_a_nonempty_library(self):
        self.seed()
        before = self.snapshot()
        summary = self.import_items([])
        self.assertEqual((summary.created, summary.updated, summary.skipped), (0, 0, 0))
        self.assertTrue(summary.backup_path.is_file())
        self.assertEqual(self.snapshot(), before)

    def test_flushed_caller_writes_are_not_committed_or_rolled_back(self):
        self.write_document(self.document())
        pending = Anime(title="已 flush 但未提交")
        self.db.add(pending)
        self.db.flush()
        self.assertFalse(self.db.new)
        with self.assertRaisesRegex(transfer.TransferError, "pre-existing SQLite transaction"):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertTrue(self.db.in_transaction())
        self.assertIsNotNone(self.db.get(Anime, pending.id))
        self.assertFalse(self.backups.exists())
        self.db.rollback()
        self.assertEqual(self.rows(), [])

    def test_uncommitted_direct_sql_is_not_committed_by_import(self):
        self.write_document(self.document())
        self.db.execute(Anime.__table__.insert().values(title="pending SQL"))
        with self.assertRaisesRegex(transfer.TransferError, "pre-existing SQLite transaction"):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(self.db.scalar(text("SELECT count(*) FROM anime")), 1)
        self.db.rollback()
        self.assertEqual(self.rows(), [])

    def test_dirty_or_deleted_caller_objects_are_rejected_untouched(self):
        anime = self.seed()
        self.write_document(self.document())
        anime.title = "本地尚未保存"
        with self.assertRaises(transfer.TransferError):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertEqual(anime.title, "本地尚未保存")
        self.db.rollback()
        self.db.delete(anime)
        with self.assertRaises(transfer.TransferError):
            transfer.load_import(self.db, self.input, backup_dir=self.backups)
        self.assertIn(anime, self.db.deleted)
        self.db.rollback()
        self.assertEqual(len(self.rows()), 1)

    def test_stale_cache_is_refreshed_and_concurrent_writes_are_locked_during_backup(self):
        database = self.root / "concurrent test.db"
        engine = create_engine(URL.create("sqlite", database=str(database)), connect_args={"timeout": 0})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.write_document(self.document([dict(title="新增")]))
        with sessionmaker(bind=engine, expire_on_commit=False)() as db:
            anime = Anime(title="原有", source="bangumi", source_id="42", watched_episodes=2)
            db.add(anime)
            db.commit()
            with engine.begin() as connection:
                connection.execute(text("UPDATE anime SET watched_episodes = 9 WHERE source_id = '42'"))
            self.assertEqual(anime.watched_episodes, 2)
            create_backup = transfer.create_backup
            attempts = []

            def checked_backup(session, directory):
                with self.assertRaises(SQLAlchemyError):
                    with engine.begin() as connection:
                        connection.execute(text("UPDATE anime SET watched_episodes = 0"))
                attempts.append(True)
                return create_backup(session, directory)

            with patch.object(transfer, "create_backup", side_effect=checked_backup):
                summary = transfer.load_import(db, self.input, backup_dir=self.backups)
            self.assertEqual(attempts, [True])
            backup = json.loads(summary.backup_path.read_text(encoding="utf-8"))
            self.assertEqual(backup["items"][0]["watched_episodes"], 9)
            self.assertEqual(db.get(Anime, anime.id).watched_episodes, 9)

    def test_malformed_ipv6_authority_is_rejected(self):
        with self.assertRaises(transfer.TransferError):
            self.import_items([dict(title="bad IPv6", play_url="https://[::1]extra.test/")])

    def test_invalid_local_data_blocks_export_without_overwriting_previous_file(self):
        self.seed(watched_episodes=13, total_episodes=12)
        destination = self.root / "previous.json"
        destination.write_bytes(b"previous output")
        with self.assertRaises(transfer.TransferError):
            transfer.save_export(self.db, destination)
        self.assertEqual(destination.read_bytes(), b"previous output")


if __name__ == "__main__":
    unittest.main()
