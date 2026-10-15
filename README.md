# ZFZS 追番助手

ZFZS 是一个以**原生桌面客户端**为主的本地追番工具，支持搜索、放送日历、季度新番、个人评分、备份迁移、可选 AI 推荐与后台提醒；同时保留 Next.js 实验端。

## 仓库结构

```text
desktop/   Windows / macOS 原生客户端（Python + Tkinter + SQLite）
web/       Next.js + PostgreSQL 版本（可选，不是桌面端运行依赖）
docs/      整合进度、技术选型与后续路线
```

## 首选：原生桌面端

桌面端不需要 Docker，也不会在浏览器中运行。数据保存在本机 SQLite：

- Windows：`%LOCALAPPDATA%\ZFZS\zfzs.db`
- macOS：`~/Library/Application Support/ZFZS/zfzs.db`
- Linux：`$XDG_DATA_HOME/zfzs/zfzs.db`

Windows：

```powershell
cd desktop
.\scripts\run_desktop.ps1
```

也可以双击 `desktop/start.bat`。首次运行会自动创建虚拟环境并安装依赖。执行 `desktop/install-desktop-shortcut.bat` 可在 Windows 桌面创建快捷方式。

macOS（安装 Python 3.13，须包含 Tkinter；可先用 `python3 -m tkinter` 检查）：

```bash
cd desktop
chmod +x scripts/run_desktop.sh scripts/build_desktop.sh
./scripts/run_desktop.sh
```

打包独立应用：

```powershell
# Windows
cd desktop
.\scripts\build_desktop.ps1
```

```bash
# macOS（必须在 Mac 上构建 .app）
cd desktop
./scripts/build_desktop.sh
```

## 可选：Web 实验端

Web 端需要 Node.js 与 PostgreSQL。Docker 仅服务于这一子项目：

```bash
cd web
cp .env.example .env.local
docker compose up -d
npm ci
npm run dev
```

桌面端的“数据管理”可导出、导入和备份追番记录；“AI 推荐”仅在主动点击后向所选供应商发送已看完且有个人评分的标题/标签和偏好。后台系统提醒须主动启动，关闭窗口后可继续运行；没有注册开机自启。API Key 可仅在本次会话输入，不写入备份。

验证状态（2026-10-15）：Python 单测 201/201、原生窗口检查 42/42 通过；真实日历/季度查询、数据跨项目迁移、源码后台进程启停已验证。Web 在独立的临时 PostgreSQL 17 中通过 lint、类型检查和 108/108 项测试，未改动本机原有数据库。[GitHub CI](https://github.com/gzjBC/ZFZS/actions/runs/38691850101) 的 Windows、macOS、Web 三个任务均已通过，Mac `.app` 已在云端构建及归档回验。目标 Mac 的 Finder/Gatekeeper、真实付费 AI 请求及系统通知可见性尚未验收。

详细说明见 [desktop/README.md](desktop/README.md)、[web/README.md](web/README.md) 和 [docs/项目整合与跨平台进度书.md](docs/项目整合与跨平台进度书.md)。

Mac 继续开发见 [MACOS_DEVELOPMENT.md](docs/MACOS_DEVELOPMENT.md)，本机数据库与发布环境快照见 [RELEASE_ENVIRONMENT_CHECK.md](docs/RELEASE_ENVIRONMENT_CHECK.md)。
