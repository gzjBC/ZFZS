# High Intensity Test Report

- Status: PASS
- Started: 2026-09-04T16:48:53
- Ended: 2026-09-04T16:48:59
- Duration seconds: 6.0
- Base URL: http://127.0.0.1:61233
- Test database: `F:\science yjs\work\ZFJB\data\test_e2e.db`
- Checks: 13/13 passed

## Checks

- PASS: server health - http://127.0.0.1:61233/api/health
- PASS: front page renders - 主标题和中文工作台可见。
- PASS: home screenshot - reports/screenshots/01_home.png
- PASS: mocked xifan search - 搜索结果由固定测试数据稳定渲染。
- PASS: import to watchlist - 导入成功且重复导入按钮被禁用。
- PASS: progress update - 进度加一并正确显示 1 / 12。
- PASS: reminder settings - 提醒日、时间和开关可保存。
- PASS: status and filter - 完结状态和筛选统计同步更新。
- PASS: delete watchlist item - 确认后可从列表移除番剧。
- PASS: manual entry - 无需外部数据源也可手动添加番剧。
- PASS: mobile viewport render - reports/screenshots/04_mobile.png
- PASS: anime API returns list - count=0
- PASS: reminders API returns list - count=0

## Scope

- Starts the FastAPI app with an isolated SQLite database.
- Opens the real frontend with Playwright.
- Intercepts the xifan search endpoint with deterministic fixture data for stress testing UI flows.
- Exercises search rendering, import deduplication, progress, reminders, status filters, manual entry, deletion, mobile layout, and core APIs.

## Screenshots

- `reports/screenshots/01_home.png`
- `reports/screenshots/02_search_results.png`
- `reports/screenshots/03_watchlist_progress.png`
- `reports/screenshots/04_mobile.png`
