# 项目进度文档

> 以下为早期开发历史，包含当时的 Web/小程序设想。当前目标已调整为 Windows/macOS 原生桌面客户端；最新状态见 [项目整合与跨平台进度书](../../docs/项目整合与跨平台进度书.md)。

## 项目目标

构建一个追番辅助助手，第一阶段先完成后端基础能力：

- 使用 SQLite 存储追番数据。
- 使用 FastAPI 提供 JSON API。
- 使用 SQLAlchemy 管理数据库模型和查询。
- 采用工程化分层结构：`router / service / model / schema`。

后续扩展：

- 微信小程序前端。
- Playwright 自动搜索网站获取番剧信息。
- Bangumi / RSS 数据源。
- DeepSeek AI 推荐接口。
- 微信订阅消息提醒。

## 当前技术栈

- Python 3.13
- FastAPI
- SQLAlchemy
- SQLite
- Uvicorn
- Pydantic

## 当前项目结构

```text
ZFJB/
  backend/
    __init__.py
    app/
      __init__.py
      main.py
      core/
        __init__.py
        config.py
      db/
        __init__.py
        base.py
        session.py
      router/
        __init__.py
        anime.py
        health.py
        reminders.py
      service/
        __init__.py
        anime_service.py
        reminder_service.py
      model/
        __init__.py
        anime.py
      schema/
        __init__.py
        anime.py
      crawlers/
        __init__.py
  data/
    .gitkeep
  docs/
    PROGRESS.md
  scripts/
    README.md
    dev.ps1
    init_db.py
  .env.example
  .gitignore
  README.md
  requirements.txt
```

## 分层说明

### `backend/app/main.py`

FastAPI 应用入口。

职责：

- 创建 FastAPI app。
- 注册所有 router。
- 启动时创建数据库表。

### `backend/app/core/`

核心配置层。

职责：

- 读取环境变量。
- 管理应用名称、环境、数据库连接地址。

当前文件：

- `config.py`：使用 `pydantic-settings` 读取 `.env`。

### `backend/app/db/`

数据库基础设施层。

职责：

- 创建 SQLAlchemy engine。
- 创建 SessionLocal。
- 提供 FastAPI 依赖 `get_db()`。
- 汇总所有 model，确保建表时能发现模型。

当前文件：

- `session.py`：数据库连接和 session 管理。
- `base.py`：导入所有模型。

### `backend/app/model/`

数据库模型层。

职责：

- 定义数据库表结构。
- 不写 HTTP 逻辑。
- 不写复杂业务逻辑。

当前模型：

- `Anime`：番剧、追番进度、更新时间、提醒设置、播放链接。

### `backend/app/schema/`

接口数据结构层。

职责：

- 定义请求体。
- 定义响应体。
- 做基础字段校验。

当前 schema：

- `AnimeCreate`
- `AnimeUpdate`
- `AnimeProgressUpdate`
- `AnimeRead`

### `backend/app/service/`

业务逻辑层。

职责：

- 操作数据库。
- 处理追番业务规则。
- 处理提醒计算。
- 不直接处理 HTTP 请求。

当前 service：

- `anime_service.py`：番剧 CRUD、进度更新。
- `reminder_service.py`：今日提醒计算、标记已提醒。

### `backend/app/router/`

HTTP 路由层。

职责：

- 定义 API 路径。
- 接收请求参数。
- 调用 service。
- 返回 schema。

当前 router：

- `health.py`：健康检查。
- `anime.py`：番剧 CRUD 和进度。
- `reminders.py`：今日提醒。

### `backend/app/crawlers/`

爬取/搜索层预留目录。

后续放：

- Bangumi API 搜索。
- Playwright 网页搜索。
- RSS 更新检查。

## 当前 API

```text
GET    /api/health
GET    /api/anime
POST   /api/anime
GET    /api/anime/{anime_id}
PATCH  /api/anime/{anime_id}
DELETE /api/anime/{anime_id}
POST   /api/anime/{anime_id}/progress
POST   /api/anime/{anime_id}/reminded
GET    /api/reminders/today
```

## 当前已完成

- 初始化 Python 项目结构。
- 创建 `.venv` 虚拟环境。
- 添加 FastAPI + SQLite + SQLAlchemy 基础代码。
- 按 `router / service / model / schema` 分层。
- 创建番剧模型。
- 创建追番 CRUD API。
- 创建今日提醒 API。
- 创建启动脚本和数据库初始化脚本。

## 下一步建议

1. 安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 初始化数据库：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

3. 启动服务：

```powershell
.\scripts\dev.ps1
```

4. 打开接口文档：

```text
http://127.0.0.1:8000/docs
```

5. 下一阶段开发：

- 添加 `crawler` 模块，用 Playwright 搜索番剧信息。
- 添加 `ai` 模块，接 DeepSeek 推荐 JSON。
- 添加微信小程序前端。

## 2026-07-18 更新：稀饭 Playwright 抓取第一版

新增文件：

- `backend/app/crawlers/xifan_playwright.py`
- `backend/app/schema/crawler.py`
- `backend/app/router/crawlers.py`
- `scripts/xifan_search.py`
- `frontend/index.html`
- `frontend/app.css`
- `frontend/app.js`

新增能力：

- 使用 Playwright 打开 `https://xifan.moe/`。
- 跳转到新版站点 `https://next.xifanacg.com/`。
- 通过 `/search?q=关键词` 获取搜索结果。
- 进入番剧详情页读取标题、评分、集数、标签、简介、封面、播放链接。
- 支持 headed 模式，让用户看到浏览器执行流程。
- 新增 Web 工作台，可搜索稀饭、导入追番、查看追番列表和今日提醒。

命令行验证：

```powershell
.\.venv\Scripts\python.exe scripts\xifan_search.py "无职转生" --limit 3
```

可见浏览器流程：

```powershell
.\.venv\Scripts\python.exe scripts\xifan_search.py "无职转生" --limit 3 --headed
```

新增 API：

```text
GET  /api/crawlers/xifan/search?q=无职转生&limit=3&headed=false
POST /api/crawlers/xifan/import
```

Web 工作台：

```text
http://127.0.0.1:8000/
```

## 2026-07-18 更新：可用前端与一键启动

新增/更新：

- `frontend/index.html`：追番助手 Web 页面。
- `frontend/app.css`：前端布局和卡片样式。
- `frontend/app.js`：搜索稀饭、导入追番、刷新列表、+1 集、删除追番。
- `scripts/start.ps1`：一键启动脚本，自动检查依赖、初始化数据库、选择端口并启动服务。
- `start.bat`：Windows 双击启动入口。

使用方式：

```powershell
.\scripts\start.ps1
```

或双击：

```text
start.bat
```

启动后打开：

```text
http://127.0.0.1:8000/
```

如果 8000 被占用，脚本会自动尝试后续端口。

注意：

- `headed=true` 会在服务端打开浏览器窗口，适合本机调试；部署到服务器时应使用默认 `headed=false`。
- 站点页面结构变化时，`xifan_playwright.py` 的解析规则需要同步调整。

## 2026-09-04 更新：稳定性与可用性完善

本轮将项目从功能原型完善为可日常使用的本地工作台：

- 修复稀饭详情页顶栏广告被误识别为番剧标题的问题。
- 搜索时等待动态结果出现，并在超时、站点不可达或浏览器缺失时返回可读错误。
- 自动检测 Chrome / Edge，支持通过 `XIFAN_BROWSER_PATH` 自定义路径。
- 重复导入仅刷新来源资料，不再清零观看进度或覆盖用户状态。
- 新增 `source_status` 和 `year` 字段，并为现有 SQLite 数据库提供轻量迁移。
- 区分来源更新状态与用户观看状态；完结旧番导入后仍进入“正在追”。
- 修复提醒计算使用系统当天而非传入时间日期的问题。
- 增加状态、时间格式和进度上限校验。
- Web 工作台全面中文化，新增统计、筛选、进度减一、暂停/看完、提醒设置和手动添加。
- 新增 9 个单元测试和 13 项 Playwright E2E 检查。
- 新增统一测试入口 `scripts/test.ps1`，`-Live` 可执行真实站点烟测。
