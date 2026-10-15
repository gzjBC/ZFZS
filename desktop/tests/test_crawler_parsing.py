import tempfile
import unittest
from pathlib import Path

from backend.app.crawlers.xifan_playwright import (
    XifanCrawlerError,
    _extract_source_id,
    _parse_card_text,
    _parse_episode_status,
    _pick_detail_title,
    _resolve_browser_path,
)


class XifanParserTests(unittest.TestCase):
    def test_card_metadata_is_parsed(self):
        card = _parse_card_text(
            "7.9\n更新至 10 / 12\n无职转生 第三季\n连载新番 · 2026"
        )

        self.assertEqual(card.title, "无职转生 第三季")
        self.assertEqual(card.score, 7.9)
        self.assertEqual(card.status_text, "更新至 10 / 12")
        self.assertEqual(card.total_episodes, 12)
        self.assertEqual(card.year, 2026)

    def test_finished_episode_status_is_parsed(self):
        status, current, total = _parse_episode_status("日本 · 全 13 集 · 完结")

        self.assertEqual(status, "全 13 集")
        self.assertEqual(current, 13)
        self.assertEqual(total, 13)

    def test_detail_title_prefers_heading_and_removes_duplicate_season(self):
        title = _pick_detail_title(
            "无职转生 第三季 ～到了异世界就拿出真本事～第三季",
            "无职转生 第三季 ～到了异世界就拿出真本事～ (2026) · 稀饭动漫 Next",
        )

        self.assertEqual(title, "无职转生 第三季 ～到了异世界就拿出真本事～")

    def test_source_id_is_extracted_from_detail_and_play_urls(self):
        self.assertEqual(_extract_source_id("https://next.xifanacg.com/anime/3403"), "3403")
        self.assertEqual(_extract_source_id("https://next.xifanacg.com/anime/3403/play/1"), "3403")

    def test_invalid_explicit_browser_path_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-browser.exe"
            with self.assertRaisesRegex(XifanCrawlerError, "浏览器路径不存在"):
                _resolve_browser_path(str(missing))


if __name__ == "__main__":
    unittest.main()
