"""Public Bangumi discovery, without reading collections or user progress.

API schemas: https://github.com/bangumi/api/tree/master/open-api
The legacy calendar uses air_date/eps_count; v0 uses date/total_episodes.
GET /v0/subjects accepts year/month (one month), not an air_date range.
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

import requests

from backend.app.core.config import get_settings
from backend.app.crawlers.bangumi import BANGUMI_API_BASE, BANGUMI_SITE_BASE, BangumiError
from backend.app.schema.crawler import XifanAnimeResult


_MAX_RESULTS = 50
_MAX_PAGES_PER_MONTH = 20
_BAD_DATA = "Bangumi 条目数据格式异常，请稍后重试。"
_BAD_PAGE = "Bangumi 返回了无法识别的分页结果，请稍后重试。"
_WEEKDAYS = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")


class BangumiDiscoveryClient:
    def __init__(
        self,
        base_url: str = BANGUMI_API_BASE,
        user_agent: str | None = None,
        timeout_seconds: float = 12.0,
        session: requests.Session | None = None,
    ):
        if (
            type(timeout_seconds) not in (int, float)
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds 必须是正的有限数值。")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or get_settings().bangumi_user_agent
        self.timeout_seconds = timeout_seconds
        # Preserve requests' default trust_env and any injected proxy settings.
        self.session = session if session is not None else requests.Session()

    def calendar(self, weekday: int | None = None, limit: int = 50) -> list[XifanAnimeResult]:
        """Return unique anime; weekday is 0=Sunday through 6=Saturday.

        None selects the whole week. Filtering precedes the global result cap.
        Invalid arguments raise ValueError; API failures raise BangumiError.
        """
        if weekday is not None and (type(weekday) is not int or not 0 <= weekday <= 6):
            raise ValueError("weekday 必须为 0 至 6 的整数或 None。")
        safe_limit = _result_limit(limit)
        payload = self._get_json("/calendar", "放送日历")
        if not isinstance(payload, list):
            raise BangumiError("Bangumi 返回了无法识别的放送日历，请稍后重试。")

        results: list[XifanAnimeResult] = []
        seen: set[str] = set()
        for day in payload:
            if not isinstance(day, dict) or not isinstance(day.get("weekday"), dict):
                raise BangumiError(_BAD_DATA)
            day_id = day["weekday"].get("id")
            if type(day_id) is not int or not 0 <= day_id <= 7:
                raise BangumiError(_BAD_DATA)
            day_id %= 7  # The legacy endpoint represents Sunday as 7.
            if not isinstance(day.get("items"), list):
                raise BangumiError(_BAD_DATA)
            if weekday is not None and day_id != weekday:
                continue
            for item in day["items"]:
                if not _is_anime(item):
                    continue
                result = _subject_to_result(item, weekday=day_id)
                if result.source_id in seen:
                    continue
                seen.add(result.source_id)
                results.append(result)
                if len(results) >= safe_limit:
                    return results
        return results

    def season(self, year: int, month: int, limit: int = 50) -> list[XifanAnimeResult]:
        """Return up to min(limit, 50) unique anime from a three-month quarter.

        year must be 1..9999 and month must be 1, 4, 7 or 10. Months are
        visited in calendar order, retaining the API's date sort within each.
        A missing date is accepted on the strength of the API's month filter.
        """
        if type(year) is not int or not 1 <= year <= 9999:
            raise ValueError("year 必须为 1 至 9999 的整数。")
        if type(month) is not int or month not in (1, 4, 7, 10):
            raise ValueError("month 必须为季度起始月 1、4、7 或 10。")
        safe_limit = _result_limit(limit)
        results: list[XifanAnimeResult] = []
        seen: set[str] = set()

        # Iterating exactly three calendar months also avoids year+1 overflow
        # for 9999-Q4, and never requests January as part of the previous Q4.
        for current_month in range(month, month + 3):
            offset = 0
            page_signatures: set[tuple[str, ...]] = set()
            for _ in range(_MAX_PAGES_PER_MONTH):
                page_limit = safe_limit - len(results)
                payload = self._get_json(
                    "/v0/subjects",
                    "季度新番",
                    params={
                        "type": 2,
                        "year": year,
                        "month": current_month,
                        "sort": "date",
                        "limit": page_limit,
                        "offset": offset,
                    },
                )
                items, total, returned_limit = _page(payload, offset, page_limit)
                if not items:
                    break
                signature = tuple(_subject_id(item) for item in items)
                if signature in page_signatures:
                    raise BangumiError("Bangumi 返回了重复的分页结果，请稍后重试。")
                page_signatures.add(signature)
                for item in items:
                    if not _is_anime(item):
                        continue
                    air_date = _air_date(item)
                    parsed_date = _parse_date(air_date)
                    if parsed_date and (parsed_date.year, parsed_date.month) != (year, current_month):
                        continue
                    result = _subject_to_result(item)
                    if result.source_id in seen:
                        continue
                    seen.add(result.source_id)
                    results.append(result)
                    if len(results) >= safe_limit:
                        return results
                # Offset counts API rows, including duplicates/filtered rows.
                offset += len(items)
                if total is not None:
                    if offset >= total:
                        break
                elif len(items) < returned_limit:
                    break
            else:
                raise BangumiError("Bangumi 分页次数超出安全上限，请稍后重试。")
        return results

    def _get_json(self, path: str, label: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout:
            raise BangumiError(f"Bangumi {label}请求超时，请检查网络后重试。") from None
        except (requests.RequestException, ValueError):
            # Do not expose request URLs, proxy credentials, or exception chains.
            raise BangumiError(f"Bangumi {label}请求失败，请检查网络后重试。") from None
        try:
            return response.json()
        except (requests.RequestException, ValueError):
            raise BangumiError(f"Bangumi 返回了无法识别的{label}响应，请稍后重试。") from None


def _result_limit(limit: int) -> int:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit 必须为正整数（结果最多 50 条）。")
    return min(limit, _MAX_RESULTS)


def _page(payload: Any, offset: int, requested_limit: int) -> tuple[list, int | None, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise BangumiError(_BAD_PAGE)
    total = payload.get("total")
    page_offset = payload.get("offset", offset)
    page_limit = payload.get("limit", requested_limit)
    if (
        (total is not None and (type(total) is not int or total < 0))
        or type(page_offset) is not int
        or page_offset != offset
        or type(page_limit) is not int
        or not 1 <= page_limit <= _MAX_RESULTS
    ):
        raise BangumiError(_BAD_PAGE)
    return payload["data"], total, page_limit


def _is_anime(item: Any) -> bool:
    if not isinstance(item, dict):
        raise BangumiError(_BAD_DATA)
    return item.get("type") in (None, 2, "2")


def _subject_id(item: Any) -> str:
    if not isinstance(item, dict):
        raise BangumiError(_BAD_DATA)
    value = _positive_int(item.get("id"))
    if value is None:
        raise BangumiError(_BAD_DATA)
    return str(value)


def _positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            value = int(value)
        except ValueError:
            raise BangumiError(_BAD_DATA) from None
    if type(value) is not int or value < 0:
        raise BangumiError(_BAD_DATA)
    return value or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BangumiError(_BAD_DATA)
    return value.strip() or None


def _optional_object(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BangumiError(_BAD_DATA)
    return value


def _air_date(item: dict) -> str | None:
    return _text(item.get("date")) or _text(item.get("air_date"))


def _parse_date(value: str | None) -> date | None:
    if value is not None and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass  # Legacy records can have unknown dates such as 0000-00-00.
    return None


def _subject_to_result(item: dict, weekday: int | None = None) -> XifanAnimeResult:
    subject_id = _subject_id(item)
    title = _text(item.get("name_cn")) or _text(item.get("name")) or f"Bangumi #{subject_id}"
    air_date = _air_date(item)
    parsed_date = _parse_date(air_date)
    total_episodes = None
    for field in ("total_episodes", "eps", "eps_count"):
        total_episodes = _positive_int(item.get(field))
        if total_episodes is not None:
            break
    rating = _optional_object(item.get("rating"))
    raw_score = rating.get("score") or item.get("score")
    score = None
    if raw_score is not None and raw_score != "":
        try:
            score = float(raw_score)
        except (TypeError, ValueError, OverflowError):
            raise BangumiError(_BAD_DATA) from None
        if isinstance(raw_score, bool) or not isfinite(score) or not 0 <= score <= 10:
            raise BangumiError(_BAD_DATA)
        score = score or None
    images = _optional_object(item.get("images"))
    cover_url = next((url for key in ("large", "common", "medium", "small", "grid")
                      if (url := _text(images.get(key)))), None)
    raw_tags = item.get("tags")
    if raw_tags is None:
        raw_tags = []
    if not isinstance(raw_tags, list):
        raise BangumiError(_BAD_DATA)
    tags = []
    for tag in raw_tags:
        name = _text(_optional_object(tag).get("name"))
        if name and name not in tags:
            tags.append(name)
        if len(tags) == 8:
            break
    status_parts = []
    if weekday is not None:
        status_parts.append(f"{_WEEKDAYS[weekday]}放送")
    if air_date:
        prefix = "预计 " if parsed_date and parsed_date > date.today() else ""
        status_parts.append(f"{prefix}{air_date} 开播")
    if total_episodes:
        status_parts.append(f"共 {total_episodes} 集")
    source_url = f"{BANGUMI_SITE_BASE}/{subject_id}"
    return XifanAnimeResult(
        title=title,
        source="bangumi",
        source_id=subject_id,
        source_url=source_url,
        cover_url=cover_url,
        summary=_text(item.get("summary")),
        score=score,
        status_text=" · ".join(status_parts) or None,
        year=parsed_date.year if parsed_date else None,
        watched_episodes=0,
        total_episodes=total_episodes,
        tags=tags,
        play_url=source_url,
    )
