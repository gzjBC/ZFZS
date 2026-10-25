# 项目进度文档

> 当前目标为 Windows/macOS 原生桌面客户端。本页先记录本轮封面版状态，再完整保留早期 Web/小程序开发历史；此前整合与跨平台验收见 [项目整合与跨平台进度书](../../docs/项目整合与跨平台进度书.md)，其中旧 CI/构建结果不覆盖本轮尚未推送的改动。

## 2026-10-25 更新：v0.3.0 封面版，待最终集成与交付验收

### 当前源码能力

- `scripts/desktop_app.py` 显示 `v0.3.0 · 封面版`；我的追番、搜索结果、发现番剧（日历/季度）均接入列表缩略图和选中侧边预览。追番刷新保留仍存在的选择，空列表或缺少封面时显示明确状态。
- `scripts/cover_view.py` 将下载任务交给后台工作线程，以主线程轮询创建 Tk 图片和更新控件；同 URL 请求合并，保留图片引用，按列表代次丢弃过期结果。失败显示占位图并可手动“重试封面”，不触发应用级阻塞任务或无限自动重试；有效缓存不因重试而强制刷新。
- `backend/app/service/cover_service.py` 负责有界下载、解码、等比留边及缓存，输出 54×76 缩略图和 180×254 预览。JPEG/PNG/WebP/GIF 支持仅限规范化静态首帧；下载上限 5 MiB，解码上限 1200 万像素。
- 磁盘缓存位于桌面数据目录的 `cache/covers/`，只保存按完整 URL 的 SHA-256 命名的规范化 PNG；有效命中不访问 DNS/网络。按最多 256 条、32 MiB 总量和 256 KiB 单条限制清理本服务文件；写入失败不妨碍显示，损坏条目可重新获取，不修改用户追番数据库。
- Pillow 与 certifi 已加入依赖；Windows/macOS 打包检查覆盖图像解码器、便携证书和 Tcl/Tk。Windows 拒绝覆盖正在运行的目标程序，可通过 `-DistPath` 在项目内另一个目录构建。
- 修复 HTTP 最后一个数据块关闭连接后仍设置超时、导致完整封面被丢弃的问题；增加真实 socket/HTTPResponse 回归。共享 URL 的一次成功重试会刷新全部当前列表及预览。

### 当前严格限定的代理行为

封面下载仅使用既有、无认证的 HTTP 回环代理，主机只允许 `127.0.0.1`、`::1`、`localhost`（固定连接 `127.0.0.1`），不接受路径、认证、查询、片段、其他回环地址、远程/LAN 或 SOCKS/HTTPS 代理端点。不改全局代理设置，不继承 API Key、Cookie、`.netrc` 或代理凭据；没有合规代理配置时直连。

公网域名与全部 DNS 地址的校验在联网前执行，拒绝非公网目标、IP 字面量及重定向。默认将目的地址固定到已验证的公网 IP；仅对 HTTPS 精确主机 `lain.bgm.tv` 允许本机代理使用主机名 CONNECT，最终解析委托给受信任的本机代理，不能视为普通 IP 固定路径。此例外不扩展至子域名或 HTTP，仍须通过本地公网 DNS 校验，并保持原始主机 TLS 证书验证与 SNI。完整使用边界见 [桌面 README](../README.md#封面网络与本机代理边界)。

### 验收证据与待办

下表按来源与日期区分，不能把旧结果、离线检查或脚本内断言当作新包/真实网络/云端已经通过。

| 范围 | 已知证据 | 尚未覆盖 / 下一步 |
|---|---|---|
| 2026-10-16 历史本地运行 | 此前记录为 254 项单测、1 项跳过，46 项 Tk 烟测检查通过 | 仅为历史基线，不充作今日新跑 |
| 2026-10-25 最终修复单测 | 258 项，`OK (skipped=1)` | 跳过项为 Windows 符号链接权限；含真实连接关闭生命周期、便携 CA 和共享 URL 重试回归 |
| 2026-10-25 原生 Tk 烟测 | 主 Agent 今日反馈 46 项检查全部为 `true`；隔离数据库、离线生成图片与模拟网络 | 不证明真实图片下载或代理可用，也不是新可执行程序验收 |
| 修复后真实网络 | 当季前三张真实封面并发下载成功，尺寸为 54×76/180×254，禁止联网的缓存复读通过 | 证明加载器链路；实际 EXE 图片仍待验收 |
| 修复后 Windows 构建 | 独立目录 `dist/cover-update-0.3.0` 构建通过，Pillow/certifi/TclTk 资源检查通过，分发 ZIP 校验通过 | 原程序仍运行，未覆盖其文件 |
| 本轮实际 EXE 界面 | 首次包显示封面列但图片失败，由此定位并修复上述连接生命周期缺陷 | 用户停止桌面控制后未继续操作；修复包实际窗口和原快捷方式最终切换待验收 |
| 本轮集成 / 远程 / Mac | 封面实现及配套文档处于本地工作区，尚未推送 | 最终集成、主 Agent 授权范围内的提交/同步、新 CI、两平台构建及目标 Mac 验收待完成 |
| 2026-10-15 历史云端 | 既有记录：`efd7b5e` 的 Windows/macOS/Web CI 与 Windows x64/macOS ARM64 打包均通过 | 仅证明旧提交；不包含本轮未推送封面改动，不等于全架构或目标机图形验证 |

源代码、构建、网络下载和窗口显示分别验收。剩余实际 EXE 图片验收及远程状态见主进度书，不提前标记完整交付。

## 早期开发历史（原记录保留）

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
