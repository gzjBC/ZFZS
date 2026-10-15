import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
from backend.app.model.anime import Anime
from backend.app.schema.crawler import XifanAnimeResult
from backend.app.service.anime_service import import_search_result, import_xifan_result, update_progress
from backend.app.service.reminder_service import _is_due, list_today_due_anime


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_reimport_updates_metadata_without_resetting_progress(self):
        original = XifanAnimeResult(
            title="测试番剧",
            source_id="100",
            source_url="https://example.test/anime/100",
            status_text="更新至 3 / 12",
            total_episodes=12,
            year=2026,
        )
        anime = import_xifan_result(self.session, original)
        update_progress(self.session, anime, 4)

        refreshed = original.model_copy(update={
            "title": "测试番剧（新标题）",
            "status_text": "更新至 5 / 12",
            "score": 8.6,
        })
        updated = import_xifan_result(self.session, refreshed)

        self.assertEqual(updated.id, anime.id)
        self.assertEqual(updated.title, "测试番剧（新标题）")
        self.assertEqual(updated.watched_episodes, 4)
        self.assertEqual(updated.status, "watching")
        self.assertEqual(updated.source_status, "更新至 5 / 12")
        self.assertEqual(updated.year, 2026)

    def test_imported_finished_show_is_still_a_user_watch_item(self):
        anime = import_xifan_result(self.session, XifanAnimeResult(
            title="旧番",
            source_id="101",
            status_text="全 12 集",
            total_episodes=12,
        ))

        self.assertEqual(anime.status, "watching")
        self.assertEqual(anime.watched_episodes, 0)

    def test_deduplication_is_scoped_to_source(self):
        xifan = import_search_result(self.session, XifanAnimeResult(
            title="稀饭条目", source="xifan", source_id="100"
        ))
        bangumi = import_search_result(self.session, XifanAnimeResult(
            title="Bangumi 条目", source="bangumi", source_id="100"
        ))

        self.assertNotEqual(xifan.id, bangumi.id)

    def test_due_check_uses_supplied_date_and_time(self):
        anime = Anime(
            title="提醒测试",
            status="watching",
            broadcast_day=1,
            broadcast_time="12:00",
            reminder_enabled=True,
            reminder_minutes=15,
        )

        self.assertFalse(_is_due(anime, datetime(2035, 1, 1, 11, 44)))
        self.assertTrue(_is_due(anime, datetime(2035, 1, 1, 11, 45)))

    def test_today_reminders_follow_zero_sunday_weekday_mapping(self):
        now = datetime(2035, 1, 1, 21, 0)
        expected_day = (now.weekday() + 1) % 7
        anime = Anime(
            title="今天更新",
            status="watching",
            broadcast_day=expected_day,
            broadcast_time="20:00",
            reminder_enabled=True,
            reminder_minutes=15,
        )
        self.session.add(anime)
        self.session.commit()

        due = list_today_due_anime(self.session, now=now)

        self.assertEqual([item.title for item in due], ["今天更新"])


if __name__ == "__main__":
    unittest.main()
