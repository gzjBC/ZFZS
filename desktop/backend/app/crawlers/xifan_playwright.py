import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from backend.app.schema.crawler import XifanAnimeResult
from backend.app.core.config import get_settings


XIFAN_SEARCH = "https://next.xifanacg.com/search?q={keyword}"
SYSTEM_BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)


class XifanCrawlerError(RuntimeError):
    """A user-facing error raised when the external source cannot be read."""


@dataclass
class XifanCrawlerOptions:
    headed: bool = False
    slow_mo_ms: int = 350
    chrome_path: str | None = None
    timeout_ms: int = 60000


class XifanPlaywrightCrawler:
    def __init__(self, options: XifanCrawlerOptions | None = None):
        self.options = options or XifanCrawlerOptions()

    def search(self, keyword: str, limit: int = 8) -> list[XifanAnimeResult]:
        keyword = keyword.strip()
        if not keyword:
            return []

        with sync_playwright() as p:
            browser = self._launch_browser(p)
            page = browser.new_page(
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            try:
                self._show_flow(page, f"搜索番剧：{keyword}")
                search_url = XIFAN_SEARCH.format(keyword=quote(keyword))
                self._goto(page, search_url)
                self._wait_for_search(page)

                results = self._parse_search_results(page, limit=limit)
                detailed_results = []
                for item in results:
                    if item.source_url:
                        self._show_flow(page, f"读取详情：{item.title}")
                        try:
                            detail = self.detail(item.source_url, page=page)
                            detailed_results.append(_merge_result(item, detail))
                        except XifanCrawlerError as exc:
                            print(f"[xifan] 详情读取失败，保留搜索结果：{exc}")
                            detailed_results.append(item)
                    else:
                        detailed_results.append(item)
                return detailed_results
            finally:
                if self.options.headed:
                    time.sleep(1.0)
                browser.close()

    def detail(self, source_url: str, page: Page | None = None) -> XifanAnimeResult:
        owns_browser = page is None
        if owns_browser:
            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            page = browser.new_page(
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
        else:
            playwright = None
            browser = None

        try:
            assert page is not None
            self._goto(page, source_url)
            return self._parse_detail(page)
        finally:
            if owns_browser:
                assert browser is not None and playwright is not None
                browser.close()
                playwright.stop()

    def _launch_browser(self, playwright: Playwright) -> Browser:
        executable_path = _resolve_browser_path(self.options.chrome_path)
        launch_options = {
            "headless": not self.options.headed,
            "slow_mo": self.options.slow_mo_ms if self.options.headed else 0,
        }
        if executable_path:
            launch_options["executable_path"] = executable_path
        try:
            return playwright.chromium.launch(**launch_options)
        except PlaywrightError as exc:
            hint = "请安装 Chrome/Edge，或执行 playwright install chromium"
            raise XifanCrawlerError(f"无法启动浏览器；{hint}") from exc

    def _goto(self, page: Page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.options.timeout_ms)
        except PlaywrightError as exc:
            raise XifanCrawlerError(f"无法访问 {url}") from exc
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PlaywrightTimeoutError:
            pass

    def _wait_for_search(self, page: Page) -> None:
        try:
            page.wait_for_function(
                r"""() => {
                    const main = document.querySelector('main');
                    if (!main) return false;
                    if (main.querySelector('a[href^="/anime/"], a[href*="/anime/"]')) return true;
                    return /共\s*0\s*条结果|暂无结果|没有找到/.test(main.innerText || '');
                }""",
                timeout=min(self.options.timeout_ms, 20000),
            )
        except PlaywrightTimeoutError as exc:
            raise XifanCrawlerError("搜索结果加载超时，请稍后重试") from exc

    def _show_flow(self, page: Page, message: str) -> None:
        print(f"[xifan] {message}")
        if not self.options.headed:
            return
        try:
            page.evaluate(
                """message => {
                    let box = document.getElementById('__zfzs_flow_box');
                    if (!box) {
                        box = document.createElement('div');
                        box.id = '__zfzs_flow_box';
                        box.style.cssText = [
                            'position:fixed',
                            'z-index:2147483647',
                            'left:16px',
                            'top:16px',
                            'max-width:520px',
                            'padding:12px 14px',
                            'border-radius:8px',
                            'background:#101820',
                            'color:white',
                            'font:14px/1.5 system-ui, sans-serif',
                            'box-shadow:0 12px 32px rgba(0,0,0,.28)'
                        ].join(';');
                        document.documentElement.appendChild(box);
                    }
                    box.textContent = 'ZFZS Playwright 流程：' + message;
                }""",
                message,
            )
        except Exception:
            pass

    def _parse_search_results(self, page: Page, limit: int) -> list[XifanAnimeResult]:
        links = page.evaluate(
            """() => Array.from(document.querySelectorAll(
                    'main a[href^="/anime/"], main a[href*="/anime/"]'
                ))
                .map(a => ({
                    text: (a.innerText || a.textContent || '').trim(),
                    href: a.href,
                    title: (a.querySelector('p')?.innerText || a.querySelector('img')?.alt || '').trim(),
                    cover: a.querySelector('img')?.currentSrc || a.querySelector('img')?.src || ''
                }))
                .filter(item => item.text && item.href)
            """
        )
        results: list[XifanAnimeResult] = []
        seen = set()
        for link in links:
            source_id = _extract_source_id(link["href"])
            if not source_id or source_id in seen:
                continue
            parsed = _parse_card_text(link["text"])
            title = _clean_title(link.get("title") or parsed.title)
            if not title:
                continue
            seen.add(source_id)
            results.append(
                XifanAnimeResult(
                    title=title,
                    source_id=source_id,
                    source_url=link["href"],
                    cover_url=link.get("cover") or None,
                    score=parsed.score,
                    status_text=parsed.status_text,
                    year=parsed.year,
                    total_episodes=parsed.total_episodes,
                    tags=[],
                    play_url=link["href"],
                )
            )
            if len(results) >= limit:
                break
        return results

    def _parse_detail(self, page: Page) -> XifanAnimeResult:
        data = page.evaluate(
            """() => {
                const main = document.querySelector('main') || document.body;
                return {
                    url: location.href,
                    title: document.title,
                    heading: (main.querySelector('h1')?.innerText || '').trim(),
                    text: main.innerText || '',
                    images: Array.from(main.querySelectorAll('img')).map(img => ({
                        alt: img.alt || '',
                        src: img.currentSrc || img.src || ''
                    })),
                    tags: Array.from(main.querySelectorAll('a[href*="/browse/tag/"]'))
                        .map(a => (a.innerText || a.textContent || '').trim()).filter(Boolean),
                    year: (Array.from(main.querySelectorAll('a[href*="/browse/year/"]'))
                        .map(a => (a.innerText || '').trim()).find(value => /^\\d{4}$/.test(value)) || null),
                    watchLink: (Array.from(main.querySelectorAll('a'))
                        .find(a => (a.innerText || a.textContent || '').trim().includes('立即观看')) || {}).href || location.href
                };
            }"""
        )
        text = _normalize_lines(data["text"])
        title = _pick_detail_title(data.get("heading"), data["title"])
        score = _first_float_after_title(text, title)
        status_text, _, total_ep = _parse_episode_status("\n".join(text))
        year = int(data["year"]) if data.get("year") else _first_year(text)
        tags = list(dict.fromkeys(data.get("tags") or _parse_tags(text)))
        summary = _parse_summary(text)
        cover_url = _pick_cover(data["images"], title)
        return XifanAnimeResult(
            title=title,
            source_id=_extract_source_id(data["url"]),
            source_url=data["url"],
            cover_url=cover_url,
            summary=summary,
            score=score,
            status_text=status_text,
            year=year,
            watched_episodes=0,
            total_episodes=total_ep,
            tags=tags,
            play_url=data.get("watchLink") or data["url"],
        )


@dataclass
class ParsedCard:
    title: str
    score: float | None = None
    status_text: str | None = None
    year: int | None = None
    total_episodes: int | None = None


def _parse_card_text(text: str) -> ParsedCard:
    lines = _normalize_lines(text)
    score = _safe_float(lines[0]) if lines else None
    status_line = next((line for line in lines if "更新至" in line or "全 " in line), None)
    title_candidates = [
        line for line in lines
        if not _safe_float(line)
        and not re.fullmatch(r"\d{4}", line)
        and "更新至" not in line
        and "全 " not in line
        and "连载新番" not in line
        and "完结旧番" not in line
    ]
    title = title_candidates[0] if title_candidates else ""
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    _, _, total_ep = _parse_episode_status(text)
    return ParsedCard(title=title, score=score, status_text=status_line, year=year, total_episodes=total_ep)


def _normalize_lines(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", text or "") if line.strip()]


def _extract_source_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/anime/(\d+)", url)
    return match.group(1) if match else None


def _safe_float(value: str | None) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except ValueError:
        return None


def _parse_episode_status(text: str) -> tuple[str | None, int | None, int | None]:
    match = re.search(r"更新至\s*(?:EP\s*)?(\d+)\s*/\s*(\d+)", text)
    if match:
        current, total = int(match.group(1)), int(match.group(2))
        return f"更新至 {current} / {total}", current, total
    match = re.search(r"全\s*(\d+)\s*集", text)
    if match:
        total = int(match.group(1))
        return f"全 {total} 集", total, total
    return None, None, None


def _pick_detail_title(heading: str | None, document_title: str) -> str:
    if heading:
        return _clean_title(heading)
    title = re.sub(r"\s*\(\d{4}\)\s*[·|-]\s*稀饭动漫 Next\s*$", "", document_title)
    title = title.replace(" - 稀饭动漫 Next", "")
    return _clean_title(title)


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    for suffix in ("第一季", "第二季", "第三季", "第四季", "第五季", "第六季"):
        if title.endswith(suffix) and suffix in title[:-len(suffix)]:
            return title[:-len(suffix)].strip()
    return title


def _first_float_after_title(lines: list[str], title: str) -> float | None:
    try:
        start = lines.index(title)
    except ValueError:
        start = 0
    for line in lines[start:start + 10]:
        value = _safe_float(line)
        if value is not None:
            return value
    return None


def _first_year(lines: list[str]) -> int | None:
    for line in lines:
        if re.fullmatch(r"\d{4}", line):
            return int(line)
    return None


def _parse_tags(lines: list[str]) -> list[str]:
    known = {
        "奇幻", "冒险", "小说改", "漫画改", "原创", "校园", "恋爱", "喜剧", "日常",
        "战斗", "科幻", "悬疑", "治愈", "运动", "音乐", "热血", "异世界",
    }
    tags = [line for line in lines if line in known]
    return list(dict.fromkeys(tags))


def _parse_summary(lines: list[str]) -> str | None:
    stop_words = {"展开", "剧集列表", "相关推荐根据题材标签匹配", "系列作品共 5 部"}
    candidates = [
        line for line in lines
        if len(line) >= 40
        and line not in stop_words
        and not line.startswith("稀饭动漫")
    ]
    return candidates[0] if candidates else None


def _pick_cover(images: list[dict], title: str) -> str | None:
    for image in images:
        alt = image.get("alt") or ""
        src = image.get("src") or ""
        if src and (title in alt or alt in title):
            return src
    for image in images:
        src = image.get("src") or ""
        if src and not src.endswith(("logow.png", "logob.png")):
            return src
    return None


def _merge_result(base: XifanAnimeResult, detail: XifanAnimeResult) -> XifanAnimeResult:
    data = base.model_dump()
    for key, value in detail.model_dump().items():
        if value not in (None, "", [], 0):
            data[key] = value
    data["source_id"] = base.source_id or detail.source_id
    data["source_url"] = base.source_url or detail.source_url
    return XifanAnimeResult(**data)


def _resolve_browser_path(configured_path: str | None) -> str | None:
    explicit_path = configured_path or os.environ.get("XIFAN_BROWSER_PATH") or get_settings().xifan_browser_path
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if not candidate.is_file():
            raise XifanCrawlerError(f"浏览器路径不存在：{candidate}")
        return str(candidate)

    for candidate in SYSTEM_BROWSER_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None
