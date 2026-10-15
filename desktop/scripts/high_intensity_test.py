import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run high-intensity Playwright E2E tests.")
    parser.add_argument("--headed", action="store_true", help="Show browser during tests.")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    screenshot_dir = report_dir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    test_db = PROJECT_ROOT / "data" / "test_e2e.db"
    if test_db.exists():
        test_db.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{test_db.as_posix()}"

    import uvicorn

    from backend.app.main import app

    port = args.port or find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    server_thread = threading.Thread(target=server.run, daemon=True)

    results: list[dict] = []
    started_at = datetime.now()

    try:
        server_thread.start()
        wait_for_health(f"{base_url}/api/health")
        record(results, "server health", True, f"{base_url}/api/health")

        with sync_playwright() as p:
            from backend.app.crawlers.xifan_playwright import _resolve_browser_path

            launch_options = dict(
                headless=not args.headed,
                slow_mo=250 if args.headed else 0,
            )
            executable_path = _resolve_browser_path(None)
            if executable_path:
                launch_options["executable_path"] = executable_path
            browser = p.chromium.launch(**launch_options)
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            page = context.new_page()

            fake_search = build_fake_search_payload()
            page.route("**/api/crawlers/xifan/search?**", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(fake_search, ensure_ascii=False),
            ))

            run_ui_tests(page, base_url, screenshot_dir, results)
            run_responsive_check(page, base_url, screenshot_dir, results)
            browser.close()

        verify_api_state(base_url, results)
    except Exception as exc:
        record(results, "unexpected failure", False, repr(exc))
        raise
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)

    ended_at = datetime.now()
    report = build_report(results, started_at, ended_at, base_url, test_db)
    report_path = PROJECT_ROOT / "docs" / "TEST_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    json_path = report_dir / "high_intensity_test.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)


def run_ui_tests(page, base_url: str, screenshot_dir: Path, results: list[dict]) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="追番助手")).to_be_visible()
    record(results, "front page renders", True, "主标题和中文工作台可见。")

    page.screenshot(path=screenshot_dir / "01_home.png", full_page=True)
    record(results, "home screenshot", True, "reports/screenshots/01_home.png")

    page.get_by_placeholder("例如：无职转生").fill("E2E Anime")
    page.get_by_role("button", name="搜索番剧").click()
    expect(page.get_by_text("找到 2 条结果。")).to_be_visible(timeout=10000)
    expect(page.get_by_text("E2E Playwright Anime")).to_be_visible()
    record(results, "mocked xifan search", True, "搜索结果由固定测试数据稳定渲染。")

    page.screenshot(path=screenshot_dir / "02_search_results.png", full_page=True)

    page.locator("#resultList").get_by_role("button", name="加入追番").first.click()
    expect(page.get_by_text("已加入追番：E2E Playwright Anime")).to_be_visible(timeout=10000)
    expect(page.locator("#animeList").get_by_text("E2E Playwright Anime")).to_be_visible()
    expect(page.locator("#resultList").get_by_role("button", name="已在列表").first).to_be_disabled()
    record(results, "import to watchlist", True, "导入成功且重复导入按钮被禁用。")

    page.locator("#animeList").get_by_role("button", name="+1 集").first.click()
    expect(page.get_by_text("进度已更新：E2E Playwright Anime")).to_be_visible(timeout=10000)
    expect(page.locator("#animeList .progress-label strong").first).to_have_text("1 / 12")
    record(results, "progress update", True, "进度加一并正确显示 1 / 12。")

    page.locator("#animeList").get_by_role("button", name="提醒设置").first.click()
    page.locator("#broadcastDayInput").select_option("0")
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_text("提醒设置已保存。")).to_be_visible(timeout=10000)
    expect(page.locator("#animeList").get_by_text("周日 20:00 提醒")).to_be_visible()
    record(results, "reminder settings", True, "提醒日、时间和开关可保存。")

    page.locator("#animeList").get_by_role("button", name="标记看完").first.click()
    expect(page.get_by_text("E2E Playwright Anime：已看完")).to_be_visible(timeout=10000)
    expect(page.locator("#finishedStat")).to_have_text("1")
    page.get_by_role("button", name="已看完", exact=True).click()
    expect(page.locator("#animeList").get_by_text("E2E Playwright Anime")).to_be_visible()
    record(results, "status and filter", True, "完结状态和筛选统计同步更新。")

    page.screenshot(path=screenshot_dir / "03_watchlist_progress.png", full_page=True)

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#animeList").get_by_role("button", name="移除").first.click()
    expect(page.get_by_text("已移除：E2E Playwright Anime")).to_be_visible(timeout=10000)
    expect(page.get_by_text("这里还没有番剧，试试搜索或手动添加。")).to_be_visible()
    record(results, "delete watchlist item", True, "确认后可从列表移除番剧。")

    page.get_by_role("button", name="手动添加").click()
    page.locator("#manualTitleInput").fill("手动测试番剧")
    page.locator("#manualTotalInput").fill("2")
    page.locator("#manualWatchedInput").fill("1")
    page.get_by_role("button", name="添加到追番").click()
    expect(page.get_by_text("番剧已手动添加。")).to_be_visible(timeout=10000)
    page.get_by_role("button", name="全部", exact=True).click()
    expect(page.locator("#animeList").get_by_text("手动测试番剧")).to_be_visible()
    record(results, "manual entry", True, "无需外部数据源也可手动添加番剧。")

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#animeList").get_by_role("button", name="移除").first.click()
    expect(page.get_by_text("已移除：手动测试番剧")).to_be_visible(timeout=10000)


def run_responsive_check(page, base_url: str, screenshot_dir: Path, results: list[dict]) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url, wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="追番助手")).to_be_visible()
    page.screenshot(path=screenshot_dir / "04_mobile.png", full_page=True)
    record(results, "mobile viewport render", True, "reports/screenshots/04_mobile.png")


def verify_api_state(base_url: str, results: list[dict]) -> None:
    anime = request_json(f"{base_url}/api/anime")
    reminders = request_json(f"{base_url}/api/reminders/today")
    record(results, "anime API returns list", isinstance(anime, list), f"count={len(anime)}")
    record(results, "reminders API returns list", isinstance(reminders, list), f"count={len(reminders)}")


def build_fake_search_payload() -> dict:
    return {
        "keyword": "E2E Anime",
        "source_url": "https://next.xifanacg.com/search?q=E2E%20Anime",
        "results": [
            {
                "title": "E2E Playwright Anime",
                "source": "xifan",
                "source_id": "900001",
                "source_url": "https://next.xifanacg.com/anime/900001",
                "cover_url": "https://example.com/e2e-cover.jpg",
                "summary": "A deterministic test anime used to verify search, import, progress and delete flows.",
                "score": 8.8,
                "status_text": "更新至 3 / 12",
                "year": 2026,
                "watched_episodes": 0,
                "total_episodes": 12,
                "tags": ["Test", "Playwright"],
                "play_url": "https://next.xifanacg.com/anime/900001/play/1"
            },
            {
                "title": "E2E Finished Anime",
                "source": "xifan",
                "source_id": "900002",
                "source_url": "https://next.xifanacg.com/anime/900002",
                "cover_url": "",
                "summary": "A secondary card to exercise grid rendering.",
                "score": 7.4,
                "status_text": "全 12 集",
                "year": 2025,
                "watched_episodes": 0,
                "total_episodes": 12,
                "tags": ["Test"],
                "play_url": "https://next.xifanacg.com/anime/900002/play/1"
            }
        ]
    }


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_health(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            payload = request_json(url)
            if payload.get("ok"):
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.3)
    raise RuntimeError(f"server did not become healthy: {last_error}")


def request_json(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def record(results: list[dict], name: str, passed: bool, detail: str) -> None:
    results.append({
        "name": name,
        "passed": bool(passed),
        "detail": detail,
    })


def build_report(results: list[dict], started_at: datetime, ended_at: datetime, base_url: str, test_db: Path) -> str:
    passed = sum(1 for item in results if item["passed"])
    failed = len(results) - passed
    status = "PASS" if failed == 0 else "FAIL"
    lines = [
        "# High Intensity Test Report",
        "",
        f"- Status: {status}",
        f"- Started: {started_at.isoformat(timespec='seconds')}",
        f"- Ended: {ended_at.isoformat(timespec='seconds')}",
        f"- Duration seconds: {(ended_at - started_at).total_seconds():.1f}",
        f"- Base URL: {base_url}",
        f"- Test database: `{test_db}`",
        f"- Checks: {passed}/{len(results)} passed",
        "",
        "## Checks",
        "",
    ]
    for item in results:
        marker = "PASS" if item["passed"] else "FAIL"
        lines.append(f"- {marker}: {item['name']} - {item['detail']}")
    lines.extend([
        "",
        "## Scope",
        "",
        "- Starts the FastAPI app with an isolated SQLite database.",
        "- Opens the real frontend with Playwright.",
        "- Intercepts the xifan search endpoint with deterministic fixture data for stress testing UI flows.",
        "- Exercises search rendering, import deduplication, progress, reminders, status filters, manual entry, deletion, mobile layout, and core APIs.",
        "",
        "## Screenshots",
        "",
        "- `reports/screenshots/01_home.png`",
        "- `reports/screenshots/02_search_results.png`",
        "- `reports/screenshots/03_watchlist_progress.png`",
        "- `reports/screenshots/04_mobile.png`",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
