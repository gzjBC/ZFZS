# ZFZS 原生桌面端

这是 ZFZS 的主产品：一个直接打开原生窗口的本地追番客户端，不依赖 Web 页面或 Docker。

当前界面标识为 `v0.3.0 · 封面版`。2026-10-25 已修复下载结束时误报失败、共享封面重试不刷新其他列表的问题，并为打包后的 HTTPS 加入便携证书。修复后的 Windows 包已生成；实际桌面窗口的最终图片验收尚未完成，详见下方验收记录。

## 功能

- 默认通过 Bangumi 官方 API 搜索番剧，也可切换稀饭动漫数据源；
- “发现番剧”提供本周放送日历、季度新番和加入追番，加载失败后可重试并保留原结果；
- 我的追番、搜索结果和发现番剧列表均提供封面缩略图及选中条目的侧边预览，支持后台加载、本机缓存和失败重试；
- 加入追番、进度增减、暂停/继续、标记看完和手动添加；
- 每周更新时间与提前提醒设置；
- 个人评分与网站评分分开保存；基于已看完且有个人评分的作品请求可选 AI 推荐；
- JSON 导出、备份、跨电脑合并导入，默认保留本地记录；
- 可主动启停后台系统提醒，关闭主窗口后可继续本次会话的提醒；
- 重复导入更新元数据但保留观看进度；
- SQLite 本地存储，Windows 与 macOS 使用各自的标准应用数据目录。

## 封面加载、缓存与重试

列表先显示占位图，封面下载与规范化解码在后台进行，Tk 图片对象和控件只在主线程更新。缩略图为 54×76，选中预览最大为 180×254，等比缩放并留边、不裁切；预览随可用空间缩小。刷新追番列表时尽量保留当前选择，旧列表的迟到下载结果不会覆盖新条目。

缺少封面地址时显示“该条目未提供封面”；下载或解码失败时保留占位图，可选中该条目点击“重试封面”。失败不会自动无限重试，也不阻止搜索、加入追番或进度操作。“重试封面”用于重试失败项，不会强制刷新已有有效缓存。

同一地址的并发请求会合并，内存复用近期图片；磁盘缓存位于桌面数据目录下的 `cache/covers/`，随 `ZFZS_DATA_DIR` 使用相应目录。缓存按完整地址的 SHA-256 命名，只保存规范化 PNG，不保存原始图片元数据；有效缓存命中不需要 DNS 或网络。缓存清理目标为最多 256 个条目、总计 32 MiB，单条最多 256 KiB，只清理本服务的哈希命名文件。缓存不可写时仍可显示已加载图片，损坏缓存会尝试重新获取，不改动追番数据库。

支持 JPEG、PNG、WebP 和 GIF（动画只取首帧）。单次下载上限 5 MiB，解码上限 1200 万像素，并设连接、读取和下载时限。封面缓存不属于 JSON 追番备份内容，无需随数据库迁移。

### 封面网络与本机代理边界

以下限制针对封面下载器，不等同于 Bangumi API 或其他服务的网络策略：

- 仅接受公网域名的 HTTP/HTTPS 图片地址；拒绝带认证信息、IP 字面量、本地域名及解析到非公网地址的目标，混合公网/非公网 DNS 结果也拒绝；不跟随重定向。
- 只读取已有系统/环境代理配置，不修改全局设置、不启动代理。可用代理仅限无认证的 HTTP 端点：`http://127.0.0.1:端口`、`http://localhost:端口` 或 `http://[::1]:端口`；`localhost` 固定连接到 `127.0.0.1`。不接受用户名/密码、路径（包括末尾 `/`）、查询或片段，也不接受远程/LAN 代理、其他回环地址、HTTPS 或 SOCKS 代理协议。
- HTTPS 目标依次检查已有 `https`、`http`、`all` 代理项；HTTP 目标先检查 `http`。无合规配置时使用公网直连；已选代理连接失败则显示加载失败，不关闭安全检查。下载请求不继承 API Key、Cookie、`.netrc` 或代理认证。
- 默认将直连及代理目标固定到已验证的公网 IP：HTTPS 代理通过 CONNECT 隧道，HTTP 代理使用带数字 IP 的绝对请求地址。唯一例外是 **HTTPS 的精确主机 `lain.bgm.tv`**：为兼容按域名路由的本机代理，允许 CONNECT 使用该主机名；不扩展到子域名、相似后缀或 HTTP。此前仍须通过本地公网 DNS 校验，但最终目的地址由受信任的本机代理解析，不再固定为本地校验的 IP。HTTPS 始终保留原始主机的证书验证与 SNI。

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

重建前请关闭目标目录中的独立程序并停止其后台提醒进程；Windows 构建脚本会拒绝覆盖正在使用的目标。可用 `-DistPath dist/cover-update-0.3.0` 在项目内的独立目录构建，随后退出旧程序再替换整个应用目录。构建检查覆盖 Pillow 原生解码器、certifi 证书文件和 Tcl/Tk 资源。

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

仓库 Actions 中还提供手动运行的 `Build native desktop apps` 工作流，分别生成 Windows 与 macOS 产物。它们尚未做发行签名或 macOS notarization。Mac 构建也检查 Pillow 原生解码器；本轮封面版尚无新的 Mac 构建或目标机验收结果。

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

### 验收记录与未完成项（2026-10-25）

- 最终修复后单测：258 项，`OK (skipped=1)`。新增真实 socket/HTTPResponse 关闭生命周期、各类响应结尾、便携 TLS 信任和跨列表重试回归。此前同日 46 项原生 Tk 烟测通过，使用隔离数据库与模拟网络。
- 首次 EXE 联网验收发现图片下载到最后一块后，关闭的连接仍被设置超时而误报失败；已修复，并重新构建独立更新包。Pillow 解码器、certifi 证书和 Tcl/Tk 检查通过。旧程序仍运行时不覆盖其文件。
- 修复后，当前季度前三部作品的真实封面并发下载全部成功：万圣街特别篇、永远的大和号第七章、罗小黑战记学前篇；54×76 缩略图、180×254 预览及禁止再次联网的缓存读取均通过。
- 桌面控制被用户停止后未继续操作窗口；修复包的实际 EXE 图片显示、原快捷方式最终切换仍待验收。远程 CI/构建状态另见项目进度书。
- 已有历史绿色结果为 2026-10-15 的提交 `efd7b5e`：Windows/macOS/Web CI 和 Windows x64/macOS ARM64 云端构建通过；不包含本轮未推送的封面改动，也不替代目标 Mac 的图形界面、Gatekeeper 或通知验收。

历史验证与本轮更新记录见[进度文档](docs/PROGRESS.md)。

## 数据位置

原生 UI 烟测可运行 `python tests/smoke_desktop.py`，它使用临时数据库，不接触你的追番记录。

- Windows：`%LOCALAPPDATA%\ZFZS\zfzs.db`
- macOS：`~/Library/Application Support/ZFZS/zfzs.db`
- Linux：`$XDG_DATA_HOME/zfzs/zfzs.db`

稀饭动漫搜索需要本机 Chrome、Edge 或 Playwright Chromium；Bangumi 搜索不需要浏览器。可用 `XIFAN_BROWSER_PATH` 指定自定义浏览器路径，用 `BANGUMI_USER_AGENT` 配置 API 应用标识。

首次源码启动会将旧 `data/zfzs.db` 复制到尚不存在的标准数据目录，并保留原文件。已有目标数据库不会被覆盖。迁移电脑时，在两端退出应用后复制 `zfzs.db` 到对应位置；Git 只同步源码，不同步个人数据库。可用环境变量 `ZFZS_DATA_DIR` 指定其他数据目录，或用 `DATABASE_URL` 指定数据库。默认数据目录不读 `.env` 中的 `DATABASE_URL`，这是旧版 API 调试服务的配置。

Bangumi 网络不通时可配置系统 `HTTPS_PROXY` 环境变量，或切换稀饭动漫/手动添加。日历按所选日期的星期查询当前放送表，不提供历史排期；季度由所选起始月的三个月组成，每次最多返回 50 条。

## 评分、备份与后台提醒

“我的评分”独立于网站评分，可清除。先把作品标记看完并填写个人评分，再到“AI 推荐”页主动生成。支持千问/DeepSeek，可在当前会话输入遮罩 Key，或通过环境变量配置；生成可能产生供应商费用。模型结果须先转到 Bangumi 搜索确认，再加入追番。自动化验收不执行真实付费调用。

“数据管理”提供导出、导入和手动备份。导入先自动备份现有记录；默认保留本地冲突项，覆盖匹配记录需要勾选并二次确认，不删除其他记录。换到 Mac 时可把导出 JSON 导入新客户端；Web 旧数据也可通过桥接导出工具迁入。

“今日提醒”中可主动启动或停止后台。默认关闭，不注册开机自启；退出登录、重启或睡眠期间不保证通知。系统 API 接受通知不等于一定显示横幅，Mac/Linux 分支尚未实机验收。使用自定义数据库时，只有匹配当前数据目录的普通 SQLite 配置才支持后台。

详见 [数据迁移](../docs/DATA_PORTABILITY.md)、[AI 推荐](../docs/AI_RECOMMENDATIONS.md) 和 [后台提醒](../docs/BACKGROUND_REMINDERS.md)。

Mac 环境准备、架构和打包验收详见 [Mac 开发说明](../docs/MACOS_DEVELOPMENT.md)。
