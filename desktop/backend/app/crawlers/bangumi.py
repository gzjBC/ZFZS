from __future__ import annotations

from datetime import date
from typing import Any

import requests

from backend.app.schema.crawler import XifanAnimeResult
from backend.app.core.config import get_settings


BANGUMI_API_BASE = "https://api.bgm.tv"
BANGUMI_SITE_BASE = "https://bgm.tv/subject"


class BangumiError(RuntimeError):
    """A user-facing error raised when the Bangumi API cannot be read."""


class BangumiClient:
    def __init__(
        self,
        base_url: str = BANGUMI_API_BASE,
        user_agent: str | None = None,
        timeout_seconds: float = 12.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or get_settings().bangumi_user_agent
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def search(self, keyword: str, limit: int = 12) -> list[XifanAnimeResult]:
        keyword = keyword.strip()
        if not keyword:
            return []

        safe_limit = min(max(limit, 1), 50)
        try:
            response = self.session.post(
                f"{self.base_url}/v0/search/subjects",
                params={"limit": safe_limit, "offset": 0},
                json={
                    "keyword": keyword,
                    "sort": "match",
                    "filter": {"type": [2]},
                },
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise BangumiError("Bangumi 搜索超时，请检查网络后重试。") from exc
        except (requests.RequestException, ValueError) as exc:
            raise BangumiError(f"Bangumi 搜索失败：{exc}") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise BangumiError("Bangumi 返回了无法识别的搜索结果，请稍后重试。")
        try:
            return [_subject_to_result(item) for item in payload["data"]]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise BangumiError("Bangumi 条目数据格式异常，请稍后重试。") from exc


def _subject_to_result(item: dict[str, Any]) -> XifanAnimeResult:
    subject_id = str(item["id"])
    title = item.get("name_cn") or item.get("name") or f"Bangumi #{subject_id}"
    air_date = item.get("date") or ""
    year = int(air_date[:4]) if len(air_date) >= 4 and air_date[:4].isdigit() else None
    total_episodes = item.get("total_episodes") or item.get("eps") or None
    rating = item.get("rating") or {}
    score = rating.get("score") or item.get("score") or None
    images = item.get("images") or {}
    tags = [tag.get("name") for tag in item.get("tags", []) if tag.get("name")][:8]

    status_text = None
    if air_date:
        status_text = f"{air_date} 开播"
        try:
            if date.fromisoformat(air_date) > date.today():
                status_text = f"预计 {air_date} 开播"
        except ValueError:
            pass
    if total_episodes:
        status_text = f"{status_text} · {total_episodes} 集" if status_text else f"共 {total_episodes} 集"

    source_url = f"{BANGUMI_SITE_BASE}/{subject_id}"
    return XifanAnimeResult(
        title=title,
        source="bangumi",
        source_id=subject_id,
        source_url=source_url,
        cover_url=images.get("large") or images.get("common") or images.get("medium"),
        summary=item.get("summary") or None,
        score=float(score) if score else None,
        status_text=status_text,
        year=year,
        total_episodes=int(total_episodes) if total_episodes else None,
        tags=tags,
        play_url=source_url,
    )
