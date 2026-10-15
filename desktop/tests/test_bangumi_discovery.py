import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from backend.app.crawlers.bangumi import BangumiError
from backend.app.crawlers.bangumi_discovery import BangumiDiscoveryClient
from backend.app.schema.crawler import XifanAnimeResult


class FakeResponse:
    def __init__(self, payload=None, *, http_error=None, json_error=None):
        self.payload = payload
        self.http_error = http_error
        self.json_error = json_error

    def raise_for_status(self):
        if self.http_error is not None:
            raise self.http_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


def subject(subject_id=1, **fields):
    return {"id": subject_id, "name": f"Anime {subject_id}", "type": 2, **fields}


def day(weekday, *items):
    return {"weekday": {"id": weekday}, "items": list(items)}


def page(*items, total=None, offset=0, limit=50):
    return {
        "data": list(items),
        "total": len(items) if total is None else total,
        "offset": offset,
        "limit": limit,
    }


class BangumiDiscoveryTests(unittest.TestCase):
    def setUp(self):
        settings = patch(
            "backend.app.crawlers.bangumi_discovery.get_settings",
            return_value=SimpleNamespace(bangumi_user_agent="ZFZS-Settings-Test/1.0"),
        )
        self.get_settings = settings.start()
        self.addCleanup(settings.stop)

    def client(self, *payloads, **kwargs):
        session = Mock(spec=requests.Session)
        session.get.side_effect = [
            payload if isinstance(payload, (FakeResponse, Exception)) else FakeResponse(payload)
            for payload in payloads
        ]
        return BangumiDiscoveryClient(session=session, **kwargs), session

    def test_legacy_calendar_maps_metadata_and_ignores_remote_progress_and_url(self):
        item = subject(
            123,
            name_cn="中文标题",
            air_date="2024-10-06",
            air_weekday=7,
            eps=0,
            eps_count="12",
            images={"large": None, "common": "https://example.test/cover.jpg"},
            rating={"score": "8.4"},
            summary="简介",
            watched_episodes=9,
            url="https://untrusted.test/subject/123",
        )
        client, _ = self.client([day(7, item)])

        result, = client.calendar(weekday=0)

        self.assertIsInstance(result, XifanAnimeResult)
        self.assertEqual(result.title, "中文标题")
        self.assertEqual(result.source, "bangumi")
        self.assertEqual(result.source_id, "123")
        self.assertEqual(result.source_url, "https://bgm.tv/subject/123")
        self.assertEqual(result.play_url, result.source_url)
        self.assertEqual(result.cover_url, "https://example.test/cover.jpg")
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.total_episodes, 12)
        self.assertEqual(result.score, 8.4)
        self.assertEqual(result.summary, "简介")
        self.assertEqual(result.watched_episodes, 0)
        self.assertEqual(result.tags, [])
        self.assertIn("周日放送", result.status_text)
        self.assertIn("2024-10-06", result.status_text)

    def test_calendar_also_maps_v0_fields_and_tag_limit(self):
        item = subject(
            "456", name_cn="  ", date="2024-04-01", air_date="1999-01-01",
            total_episodes=24, eps=12, rating=None, score=7.5,
            images={"small": "https://example.test/small.jpg"},
            tags=[{"name": "科幻"}, {"name": "科幻"}, {}, None]
            + [{"name": f"tag{i}"} for i in range(10)],
        )
        client, _ = self.client([day(1, item)])

        result, = client.calendar()

        self.assertEqual(result.title, "Anime 456")
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.total_episodes, 24)
        self.assertEqual(result.score, 7.5)
        self.assertEqual(result.cover_url, "https://example.test/small.jpg")
        self.assertEqual(result.tags, ["科幻"] + [f"tag{i}" for i in range(7)])

    def test_calendar_handles_null_optional_values(self):
        item = subject(1, name=None, name_cn=None, date=None, air_date=None,
                       images=None, rating=None, tags=None, eps=None, summary=None)
        client, _ = self.client([day(0, item)])

        result, = client.calendar(0)

        self.assertEqual(result.title, "Bangumi #1")
        for field in ("year", "score", "cover_url", "total_episodes", "summary"):
            self.assertIsNone(getattr(result, field))
        self.assertEqual(result.tags, [])

    def test_calendar_filters_before_limiting_and_accepts_both_sunday_numbers(self):
        client, _ = self.client([
            day(1, subject(1), subject(2)),
            day(7, subject(3, type=1), subject(4)),
            day(0, subject(5)),
        ])
        self.assertEqual([r.source_id for r in client.calendar(0, limit=1)], ["4"])

    def test_calendar_all_week_deduplicates_and_filters_non_anime(self):
        client, _ = self.client([
            day(1, subject(1), subject(2, type=4)),
            day(2, subject(1), subject(3)),
            day(7, subject(4)),
        ])
        self.assertEqual([r.source_id for r in client.calendar()], ["1", "3", "4"])

    def test_calendar_all_week_has_global_cap_of_fifty(self):
        client, _ = self.client([day(1, *(subject(i) for i in range(1, 31))),
                                 day(2, *(subject(i) for i in range(31, 81)))])
        results = client.calendar(limit=999)
        self.assertEqual(len(results), 50)
        self.assertEqual(results[-1].source_id, "50")

    def test_calendar_empty_and_no_matching_day_are_empty_lists(self):
        for payload in ([], [day(1, subject())]):
            with self.subTest(payload=payload):
                client, _ = self.client(payload)
                self.assertEqual(client.calendar(6), [])

    def test_calendar_filters_each_weekday_without_off_by_one(self):
        payload = [day(i, subject(i)) for i in range(1, 8)]
        for weekday in range(7):
            with self.subTest(weekday=weekday):
                client, _ = self.client(payload)
                result, = client.calendar(weekday)
                self.assertEqual(result.source_id, str(weekday or 7))

    def test_requests_use_settings_user_agent_timeout_and_official_calendar_path(self):
        client, session = self.client([], base_url="https://api.bgm.tv/", timeout_seconds=3.5)
        client.calendar()
        session.get.assert_called_once_with(
            "https://api.bgm.tv/calendar", params=None,
            headers={"User-Agent": "ZFZS-Settings-Test/1.0", "Accept": "application/json"},
            timeout=3.5,
        )
        self.get_settings.assert_called_once_with()

    def test_custom_user_agent_and_injected_session_are_preserved(self):
        client, session = self.client([], user_agent="ZFZS-Override/2.0")
        session.trust_env = False
        session.proxies = {"https": "http://proxy.example.test:8080"}
        client.calendar()
        self.assertIs(client.session, session)
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies, {"https": "http://proxy.example.test:8080"})
        self.assertEqual(session.get.call_args.kwargs["headers"]["User-Agent"], "ZFZS-Override/2.0")
        self.assertNotIn("proxies", session.get.call_args.kwargs)
        self.get_settings.assert_not_called()

    def test_default_requests_session_keeps_system_proxy_support(self):
        client = BangumiDiscoveryClient()
        self.addCleanup(client.session.close)
        self.assertIsInstance(client.session, requests.Session)
        self.assertTrue(client.session.trust_env)

    def test_season_covers_all_three_months_with_official_get_parameters(self):
        client, session = self.client(
            page(subject(1, date="2026-10-01")),
            page(subject(2, date="2026-11-30")),
            page(subject(3, date="2026-12-31")),
        )
        results = client.season(2026, 10)
        self.assertEqual([r.source_id for r in results], ["1", "2", "3"])
        self.assertTrue(all(r.watched_episodes == 0 for r in results))
        for call, month, limit in zip(session.get.call_args_list, (10, 11, 12), (50, 49, 48)):
            self.assertEqual(call.args, ("https://api.bgm.tv/v0/subjects",))
            self.assertEqual(call.kwargs["params"], {
                "type": 2, "year": 2026, "month": month,
                "sort": "date", "limit": limit, "offset": 0,
            })
            self.assertEqual(call.kwargs["timeout"], 12.0)
        session.post.assert_not_called()

    def test_season_quarter_boundaries_exclude_previous_and_next_year(self):
        client, session = self.client(
            page(subject(1, date="2026-09-30"), subject(2, date="2026-10-01")),
            page(),
            page(subject(3, date="2026-12-31"), subject(4, date="2027-01-01")),
        )
        self.assertEqual([r.source_id for r in client.season(2026, 10)], ["2", "3"])
        self.assertEqual([c.kwargs["params"]["year"] for c in session.get.call_args_list], [2026] * 3)

    def test_season_january_includes_leap_day_and_excludes_april(self):
        client, _ = self.client(
            page(subject(1, date="2023-12-31"), subject(2, date="2024-01-01")),
            page(subject(3, date="2024-02-29")),
            page(subject(4, date="2024-03-31"), subject(5, date="2024-04-01")),
        )
        self.assertEqual([r.source_id for r in client.season(2024, 1)], ["2", "3", "4"])

    def test_season_handles_extreme_valid_years_without_overflow(self):
        for year, month, air_date in ((1, 1, "0001-01-01"), (9999, 10, "9999-12-31")):
            with self.subTest(year=year):
                pages = (page(subject(1, date=air_date)), page(), page()) if month == 1 else (
                    page(), page(), page(subject(1, date=air_date)))
                client, _ = self.client(*pages)
                result, = client.season(year, month)
                self.assertEqual(result.year, year)

    def test_season_pagination_uses_raw_row_count_not_deduplicated_count(self):
        client, session = self.client(
            page(subject(1), subject(1), total=5, limit=2),
            page(subject(1), subject(2), total=5, offset=2, limit=2),
            page(subject(3), total=5, offset=4, limit=1),
        )
        self.assertEqual([r.source_id for r in client.season(2026, 4, limit=3)], ["1", "2", "3"])
        self.assertEqual([c.kwargs["params"]["offset"] for c in session.get.call_args_list], [0, 2, 4])
        self.assertEqual([c.kwargs["params"]["limit"] for c in session.get.call_args_list], [3, 2, 1])

    def test_season_continues_short_page_when_total_indicates_more_rows(self):
        client, session = self.client(
            page(subject(1, type=4), total=3),
            page(subject(2), subject(3), total=3, offset=1),
        )
        self.assertEqual(len(client.season(2026, 7, limit=2)), 2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["offset"], 1)

    def test_season_without_paging_metadata_stops_on_short_page(self):
        client, session = self.client({"data": [subject(1)]}, {"data": []}, {"data": []})
        self.assertEqual(len(client.season(2026, 4)), 1)
        self.assertEqual(session.get.call_count, 3)

    def test_season_stops_on_empty_page_even_with_stale_total(self):
        client, session = self.client(page(total=100), page(total=100), page(total=100))
        self.assertEqual(client.season(2026, 4), [])
        self.assertEqual(session.get.call_count, 3)

    def test_season_late_failure_does_not_return_partial_success(self):
        client, _ = self.client(page(subject(1)), requests.Timeout("late page"))
        with self.assertRaisesRegex(BangumiError, "超时"):
            client.season(2026, 4)

    def test_season_deduplicates_across_months_and_accepts_missing_dates(self):
        client, _ = self.client(page(subject(1, date=None)),
                                 page(subject(1), subject(2)), page(subject(3)))
        self.assertEqual([r.source_id for r in client.season(2026, 4)], ["1", "2", "3"])

    def test_season_caps_request_and_result_even_if_server_over_returns(self):
        client, session = self.client(page(*(subject(i) for i in range(1, 70))))
        self.assertEqual(len(client.season(2026, 4, limit=1000)), 50)
        self.assertEqual(session.get.call_args.kwargs["params"]["limit"], 50)
        self.assertEqual(session.get.call_count, 1)

    def test_season_rejects_repeated_pages_instead_of_looping_forever(self):
        client, session = self.client(
            page(subject(1), total=100, limit=1),
            page(subject(1), total=100, offset=1, limit=1),
        )
        with self.assertRaisesRegex(BangumiError, "重复"):
            client.season(2026, 4)
        self.assertEqual(session.get.call_count, 2)

    def test_season_has_bounded_pagination_when_all_rows_are_filtered(self):
        client, session = self.client(*(
            page(subject(i + 1, type=4), total=10000, offset=i, limit=1)
            for i in range(20)
        ))
        with self.assertRaisesRegex(BangumiError, "安全上限"):
            client.season(2026, 4)
        self.assertEqual(session.get.call_count, 20)

    def test_invalid_arguments_fail_before_network_access(self):
        client, session = self.client()
        for weekday in (-1, 7, True, 1.0, "1", []):
            with self.subTest(weekday=weekday), self.assertRaises(ValueError):
                client.calendar(weekday)
        for year in (0, -1, 10000, True, 2026.0, "2026", None):
            with self.subTest(year=year), self.assertRaises(ValueError):
                client.season(year, 1)
        for month in (0, 2, 12, 13, True, 1.0, "1", None):
            with self.subTest(month=month), self.assertRaises(ValueError):
                client.season(2026, month)
        for limit in (0, -1, True, 1.5, "5", None):
            for method in (lambda: client.calendar(limit=limit),
                           lambda: client.season(2026, 4, limit=limit)):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    method()
        session.get.assert_not_called()

    def test_invalid_timeouts_are_rejected(self):
        for timeout in (0, -1, True, None, "10", float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                BangumiDiscoveryClient(timeout_seconds=timeout)

    def test_malformed_calendar_and_subject_payloads_raise_bangumi_error(self):
        payloads = (None, {}, {"error": "upstream failed"}, [None],
                    [{"weekday": None, "items": []}],
                    [day(8)], [{"weekday": {"id": 1}, "items": None}],
                    [day(1, None)], [day(1, {})], [day(1, subject(None))],
                    [day(1, subject(True))], [day(1, subject("../unsafe"))],
                    [day(1, subject(1, images="bad"))],
                    [day(1, subject(1, rating=[]))],
                    [day(1, subject(1, rating={"score": "NaN"}))],
                    [day(1, subject(1, total_episodes=-1))],
                    [day(1, subject(1, tags="bad"))])
        for payload in payloads:
            with self.subTest(payload=payload):
                client, _ = self.client(payload)
                with self.assertRaises(BangumiError):
                    client.calendar()

    def test_malformed_season_payloads_and_offsets_raise_bangumi_error(self):
        payloads = ([], None, {}, {"data": None}, {"data": [None]},
                    {"data": [{}]}, {"data": [], "total": "1"},
                    {"data": [], "total": -1}, {"data": [], "offset": 1},
                    {"data": [], "offset": True}, {"data": [], "limit": 0},
                    {"data": [], "limit": 51})
        for payload in payloads:
            with self.subTest(payload=payload):
                client, _ = self.client(payload)
                with self.assertRaises(BangumiError):
                    client.season(2026, 4)

    def test_network_http_and_json_errors_are_sanitized_for_both_methods(self):
        secret = "http://proxy-user:proxy-secret@proxy.example.test:8080"
        failures = (
            requests.Timeout(secret), requests.ConnectionError(secret),
            requests.exceptions.ProxyError(secret),
            ValueError(secret),
            FakeResponse(http_error=requests.HTTPError(secret)),
            FakeResponse(json_error=ValueError(secret)),
        )
        for failure in failures:
            for method in ("calendar", "season"):
                with self.subTest(failure=type(failure), method=method):
                    client, _ = self.client(failure)
                    try:
                        if method == "calendar":
                            client.calendar()
                        else:
                            client.season(2026, 4)
                    except BangumiError as error:
                        visible_trace = "".join(traceback.format_exception(error))
                        self.assertNotIn("proxy-secret", visible_trace)
                        self.assertNotIn("proxy-user", visible_trace)
                        self.assertIsNone(error.__cause__)
                        self.assertTrue(error.__suppress_context__)
                        if isinstance(failure, requests.Timeout):
                            self.assertIn("超时", str(error))
                    else:
                        self.fail("Expected BangumiError")


if __name__ == "__main__":
    unittest.main()
