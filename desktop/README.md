# ZFZS 原生桌面端

这是 ZFZS 的主产品：一个直接打开原生窗口的本地追番客户端，不依赖 Web 页面或 Docker。

## 功能

- 默认通过 Bangumi 官方 API 搜索番剧，也可切换稀饭动漫数据源；
- “发现番剧”提供本周放送日历、季度新番和加入追番，加载失败后可重试并保留原结果；
- 加入追番、进度增减、暂停/继续、标记看完和手动添加；
- 每周更新时间与提前提醒设置；
- 重复导入更新元数据但保留观看进度；
- SQLite 本地存储，Windows 与 macOS 使用各自的标准应用数据目录。

## Windows

双击 `start.bat`，或运行：

```powershell
.\scripts\run_desktop.ps1
```

首次启动会创建 `.venv` 并安装依赖。双击 `install-desktop-shortcut.bat` 可以创建“ZFZS 追番助手”桌面快捷方式。

构建独立程序：

```powershell
.\scripts\build_desktop.ps1
```

产物位于 `dist/ZFZS-Anime-Tracker/`。请保留整个目录，直接打开其中的 `ZFZS-Anime-Tracker.exe`。打包后重新安装快捷方式，会优先指向这个独立程序。

## macOS

先安装含 Tkinter 的 Python 3.13，运行 `python3 -m tkinter` 检查。然后克隆仓库并进入 `desktop/`。Windows 的 `.venv` 和 `.exe` 不要复制到 Mac 使用：

```bash
chmod +x scripts/run_desktop.sh scripts/build_desktop.sh
./scripts/run_desktop.sh
```

构建 `.app`：

```bash
./scripts/build_desktop.sh
```

PyInstaller 不是交叉编译器，macOS 应用必须在 Mac 上构建。

仓库 Actions 中还提供手动运行的 `Build native desktop apps` 工作流，分别生成 Windows 与 macOS 产物。它们尚未做发行签名或 macOS notarization。本次只在 Windows 实测。

## 测试

Windows：

```powershell
.\scripts\test.ps1
```

脚本会选用与启动/打包相同的可用解释器；默认只运行单元测试。原生窗口验收执行 `scripts/test.ps1 -NoInstall -NativeSmoke`，旧版浏览器 E2E 使用 `-BrowserE2E`，真实稀饭网络检查使用 `-Live`。

只运行单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 数据位置

原生 UI 烟测可运行 `python tests/smoke_desktop.py`，它使用临时数据库，不接触你的追番记录。

- Windows：`%LOCALAPPDATA%\ZFZS\zfzs.db`
- macOS：`~/Library/Application Support/ZFZS/zfzs.db`
- Linux：`$XDG_DATA_HOME/zfzs/zfzs.db`

稀饭动漫搜索需要本机 Chrome、Edge 或 Playwright Chromium；Bangumi 搜索不需要浏览器。可用 `XIFAN_BROWSER_PATH` 指定自定义浏览器路径，用 `BANGUMI_USER_AGENT` 配置 API 应用标识。

首次源码启动会将旧 `data/zfzs.db` 复制到尚不存在的标准数据目录，并保留原文件。已有目标数据库不会被覆盖。迁移电脑时，在两端退出应用后复制 `zfzs.db` 到对应位置；Git 只同步源码，不同步个人数据库。可用环境变量 `ZFZS_DATA_DIR` 指定其他数据目录，或用 `DATABASE_URL` 指定数据库。默认数据目录不读 `.env` 中的 `DATABASE_URL`，这是旧版 API 调试服务的配置。

Bangumi 网络不通时可配置系统 `HTTPS_PROXY` 环境变量，或切换稀饭动漫/手动添加。日历按所选日期的星期查询当前放送表，不提供历史排期；季度由所选起始月的三个月组成，每次最多返回 50 条。提醒目前为应用内列表；系统通知和 AI 推荐仍待迁移。

Mac 环境准备、架构和打包验收详见 [Mac 开发说明](../docs/MACOS_DEVELOPMENT.md)。
