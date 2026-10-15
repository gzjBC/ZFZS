# ZFZS 追番助手

ZFZS 是一个以**原生桌面客户端**为主的本地追番工具，同时保留一个功能更完整的 Next.js 实验端，用于 Bangumi 日历、季度新番和 AI 推荐能力的持续迁移。

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

桌面端已接入 Bangumi 搜索；放送日历、季度页和 AI 推荐目前仍在 `web/`，尚未迁入桌面 UI。提醒目前为应用内列表，尚未实现关闭应用后的系统通知。

验证状态（2026-10-15）：Python 单测 17/17、原生窗口加载/错误恢复、Windows 独立程序启动、Bangumi 实时搜索均通过；Web lint/typecheck、92 项非数据库测试及生产构建通过。Docker Engine 无响应，13 项 PostgreSQL 测试尚未在本机执行；macOS 实机运行与签名待验证。

详细说明见 [desktop/README.md](desktop/README.md)、[web/README.md](web/README.md) 和 [docs/项目整合与跨平台进度书.md](docs/项目整合与跨平台进度书.md)。
