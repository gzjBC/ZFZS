import unittest
from unittest.mock import Mock

import requests

from backend.app.crawlers.bangumi import BangumiClient, BangumiError, _subject_to_result


class BangumiTests(unittest.TestCase):
    def test_subject_maps_to_common_search_result(self):
        result = _subject_to_result({
            "id": 123,
            "name": "Original",
            "name_cn": "中文标题",
            "date": "2026-04-01",
            "total_episodes": 12,
            "summary": "简介",
            "rating": {"score": 8.4},
            "images": {"large": "https://example.test/cover.jpg"},
            "tags": [{"name": "科幻"}, {"name": "原创"}],
        })

        self.assertEqual(result.source, "bangumi")
        self.assertEqual(result.source_id, "123")
        self.assertEqual(result.title, "中文标题")
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.total_episodes, 12)
        self.assertEqual(result.score, 8.4)
        self.assertEqual(result.tags, ["科幻", "原创"])

    def test_search_sends_anime_filter_and_user_agent(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": []}
        session = Mock()
        session.post.return_value = response

        client = BangumiClient(session=session, user_agent="ZFZS-Test/1.0")
        self.assertEqual(client.search("测试", limit=5), [])

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["params"]["limit"], 5)
        self.assertEqual(kwargs["json"]["filter"], {"type": [2]})
        self.assertEqual(kwargs["headers"]["User-Agent"], "ZFZS-Test/1.0")

    def test_timeout_has_user_facing_message(self):
        session = Mock()
        session.post.side_effect = requests.Timeout("timeout")
        with self.assertRaisesRegex(BangumiError, "搜索超时"):
            BangumiClient(session=session).search("测试")

    def test_invalid_response_has_user_facing_error(self):
        session = Mock()
        session.post.return_value.json.return_value = {"data": None}
        with self.assertRaisesRegex(BangumiError, "无法识别"):
            BangumiClient(session=session).search("测试")


if __name__ == "__main__":
    unittest.main()
