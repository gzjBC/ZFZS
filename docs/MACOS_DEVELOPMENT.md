# macOS 继续开发与桌面打包

本项目仓库是 `https://github.com/gzjBC/ZFZS`。主产品在 `desktop/`，使用 Python **3.13.x**、Tkinter、SQLite、PyInstaller；`web/` 是独立的参考实现。桌面开发不要求 Node、Docker 或 PostgreSQL。

## 从 Windows 转到 Mac

1. 在 Mac 安装带 Tcl/Tk 的 Python 3.13。不要复制 Windows 的 `.venv`、`build/` 或 `dist/`；虚拟环境及打包产物不能跨系统复用。
2. 克隆仓库，或同步主 agent 已集成的源码。以下示例故意保留路径中的空格：

   ```bash
   mkdir -p "$HOME/Projects/Anime Work"
   cd "$HOME/Projects/Anime Work"
   git clone https://github.com/gzjBC/ZFZS.git
   cd ZFZS/desktop
   python3.13 -c 'import sys, tkinter; assert sys.version_info[:2] == (3, 13); print(sys.version); print(tkinter.Tcl().eval("info patchlevel"))'
   bash scripts/run_desktop.sh --prepare-only
   ```

   该检查不创建窗口。如果 `_tkinter` 导入或 Tcl 初始化失败，需要修复基础 Python 的 Tcl/Tk 安装；`pip install tkinter` 不能解决。终端检查成功仍不能替代图形会话中的真实 Tk 窗口验证。
3. 运行源码：

   ```bash
   bash scripts/run_desktop.sh --mode source
   ```

   默认也是 `source`；即使 `dist/` 有旧包，开发启动仍使用当前源码。终端保留异常输出。普通源码启动会使用实际用户数据；首次验证优先使用下文的隔离烟测。

脚本按自身位置确定项目目录，不依赖调用目录。统一选取顺序是：显式 `--python /完整路径/python` → 完整可用的 `desktop/.venv` → 完整可用的根 `.venv`（迁移回退）→ 创建或修复 `desktop/.venv`。显式路径无效时直接报错，不悄悄换解释器。

可用检查包括 Python 3.13、Tkinter 导入、无窗口 Tcl 初始化、依赖导入和 requirements 中的固定版本；构建另外检查 PyInstaller。仅有 `bin/python` 不表示虚拟环境已准备好。

## 半安装环境和迁移

- Python/Tk 正常、依赖或 pip 缺失：再次执行 `--prepare-only`，脚本用 `ensurepip` 与对应 requirements 修复，并在安装后重新验证。
- `desktop/.venv` 不完整而根 `.venv` 完整：直接使用根环境，不先重复安装。准备、测试和构建使用相同的选择规则。
- 基础 Python 不可执行、版本不符或 Tk 损坏，且没有可用回退：找到正常的系统 Python 3.13 后，将旧目录保留为 `desktop/.venv.backup-*`，再创建规范环境。备份不会自动删除，也不要提交到 Git。
- 想从根环境迁回规范位置：先确认基础 Python/Tk，再运行 `python3.13 -m venv .venv`，然后 `bash scripts/run_desktop.sh --prepare-only --python "$PWD/.venv/bin/python"`。显式路径可强制修复这一环境，避免继续回退；依赖完整后默认启动就会优先选它。若 `.venv` 已经损坏或来自 Windows，先自行重命名保留，不要覆盖原环境。
- `--no-install` 是只检查模式：不创建、移动环境，不安装依赖；不可用时非零退出。环境准备和单元测试不要求 Playwright 浏览器下载，旧稀饭浏览器功能另有浏览器要求。

## 可重复、不打开 UI 的验证

在 `desktop/` 执行：

```bash
bash -n scripts/run_desktop.sh scripts/build_desktop.sh
python_path="$(bash scripts/run_desktop.sh --print-python --no-install)"
printf 'Selected Python: %s\n' "$python_path"
"$python_path" -B -c 'import sys, tkinter; print(sys.executable); print(sys.version); print(tkinter.Tcl().eval("info patchlevel"))'
DATABASE_URL='sqlite:///:memory:' "$python_path" -B -m unittest discover -s tests -v
```

测试和启动都通过 `--print-python` 使用同一解释器，不要在根回退生效时硬编码 `desktop/.venv/bin/python`。单元测试采用内存／临时 SQLite，不导入桌面入口来探测环境；不要用实际用户数据库做验证。

失败分支可以无安装验证：

```bash
if bash scripts/run_desktop.sh --prepare-only --no-install --python /nonexistent/python; then
  echo 'ERROR: invalid interpreter was accepted'; exit 1
fi
if bash scripts/build_desktop.sh --unsupported-option; then
  echo 'ERROR: invalid build option was accepted'; exit 1
fi
```

在独立的临时源码副本中验证干净机器／半安装恢复：不复制两个 `.venv`，先确认 `--prepare-only --no-install` 失败，再执行普通 `--prepare-only`；另一个副本只执行 `python3.13 -m venv .venv`，再执行准备脚本。两种情形最终都应选中 `desktop/.venv`。如果安装中断，重跑应恢复；离线或安装失败必须非零退出，不能显示“ready”。此过程会安装依赖，未在本轮 Windows 核验中执行。

## macOS 原生包

必须在 Mac 上构建；Windows 产物不能转换为 `.app`。脚本拒绝在非 macOS 上构建 `.app`。

```bash
bash scripts/run_desktop.sh --prepare-only --build-dependencies
bash scripts/build_desktop.sh --no-install
```

脚本检查 `Contents/Info.plist`、bundle identifier、可执行文件的执行权限、`_tkinter` 扩展、Tcl/Tk 资源以及失效符号链接。资源列表取自当前 PyInstaller 的收集结果，不假定所有 Tk 安装都有独立 `.tcl` 文件（系统 framework／内嵌资源可能采用不同布局）。成功才通过 `ditto` 生成 `desktop/dist/ZFZS-macOS.zip`，保留 `.app` 的符号链接和可执行位。不要直接把裸 `.app` 上传为普通 CI artifact，也不要只复制 `Contents/MacOS` 内的可执行文件。

```bash
unpack="$(mktemp -d "${TMPDIR:-/tmp}/ZFZS archive.XXXXXX")"
ditto -x -k dist/ZFZS-macOS.zip "$unpack"
test -x "$unpack/ZFZS Anime Tracker.app/Contents/MacOS/ZFZS Anime Tracker"
"$python_path" -I -B - "$unpack/ZFZS Anime Tracker.app" <<'PY'
from pathlib import Path
import sys
from PyInstaller.utils.hooks.tcl_tk import tcltk_info
root = Path(sys.argv[1])
assert any(p.is_file() for p in root.rglob('_tkinter*.so'))
assert all((root / 'Contents/Resources' / name).is_file() for name, _, _ in tcltk_info.data_files)
assert not any(p.is_symlink() and not p.exists() for p in root.rglob('*'))
PY
```

`bash scripts/run_desktop.sh --mode packaged` 打开已构建的应用，不要求源码 Python 环境；`--mode auto` 在包存在时优先打开包，否则运行源码。开发时建议保持默认 `source`，避免误看旧包。

包未配置发行签名／公证，不能保证在别人的 Mac 上直接打开；本流程不修改系统安全设置、不移除 quarantine、不申请证书，也不做公网发布。构建架构取决于当前 Mac/Python；CI artifact 标注 runner 架构，不代表 universal2 或已覆盖所有 Intel/Apple Silicon 机器。

## Windows 对应操作

从仓库根执行（所有脚本兼容 Windows PowerShell 5.1）：

```powershell
.\desktop\scripts\run_desktop.ps1 -PrepareOnly -NoInstall
.\desktop\scripts\test.ps1 -NoInstall
.\desktop\start.bat -Mode Source
.\desktop\start.bat -Mode Packaged
.\desktop\scripts\run_desktop.ps1 -Console -NoInstall
.\desktop\scripts\build_desktop.ps1 -NoInstall
.\desktop\install-desktop-shortcut.bat -Mode Source
```

`test.ps1` 默认仅运行单元测试；`-NativeSmoke` 才执行隔离原生窗口烟测；`-BrowserE2E` 才执行旧浏览器测试并写测试报告／测试库；`-Live` 需要外网和浏览器。可用 `-PythonPath` 显式指定解释器，用 `-PrintPython` 查看运行路径。Windows 打包前若缺少 PyInstaller，先执行 `run_desktop.ps1 -PrepareOnly -BuildDependencies`。

快捷方式默认 `Auto`：安装时存在包就指向包，否则指向源码启动器。它不是每次点击动态切换；用 `-Mode Source` 强制跟随源码，或用 `-Mode Packaged` 强制要求已构建包。源码快捷方式保留准备阶段控制台输出，便于看到安装错误。批处理转发参数、保留退出码，失败时暂停；设置 `CI` 环境变量可以避免无人值守检查被暂停。

Windows 分发必须包括完整 `ZFZS-Anime-Tracker/` 目录，不能只发 `.exe`。构建 CI 将整个目录归档为 `ZFZS-Windows.zip`。

## CI 与仍需 Mac 人工验收的边界

`ci.yml` 在 Windows/macOS 各自准备规范环境，然后复用同一环境跑单元测试和静态语法检查。`desktop-build.yml` 手动触发，在每个平台只准备一次开发依赖，随后以禁止安装模式测试／构建；macOS 另做解压回验后上传 ZIP。[2026-10-15 的 CI](https://github.com/gzjBC/ZFZS/actions/runs/38691850101) 已在 Windows/macOS/Web 全部通过；[macOS 云端打包任务](https://github.com/gzjBC/ZFZS/actions/runs/38691856632/job/116279348127) 也已完成 `.app` 构建、解压回验及产物上传。此结果不替代下面的目标 Mac 图形界面验收。

Mac 人工验收清单（本轮 Windows 工作区不能替代）：

- 记录 macOS 版本、CPU 架构、Python 3.13 补丁版本及 Tk/Tcl 版本；含空格、中文路径下执行上述命令。
- 在图形登录会话运行 `"$python_path" -B tests/smoke_desktop.py`，确认隔离数据库的 UI 烟测通过；此步骤会短暂创建窗口。
- 验证新装环境、缺依赖环境、根环境回退、错误 Python/Tk 的提示和非零退出；不要用正式数据库做这些实验。
- 实际构建 `.app`，核对归档解压后执行位／符号链接仍正常；在 Finder 中打开解压后的包，并验证无终端启动和源码启动均正常。
- 在临时 `ZFZS_DATA_DIR` 和临时 `DATABASE_URL` 下直接运行包内可执行文件，检查中文、后台加载、错误恢复、重启持久化。通过 Finder 运行时需另行确保不会使用正式数据，不能假定继承终端环境变量。
- 分别记录本机包与下载 artifact 的系统安全提示，不绕过 Gatekeeper；没有签名／公证不是已完成外部分发验收。
- 如需支持另一 CPU 架构或更旧 macOS，必须在目标组合单独构建／运行验证，不能从单台 CI runner 推断兼容。

当前已在 Windows 完成单元测试、真实 Tk 窗口烟测、独立程序构建启动，以及源码/打包后台进程启停验证；macOS 已通过真实云端单测和 `.app` 构建/归档回验。尚未验证目标 Mac 上的 Finder 启动、系统通知显示和 Gatekeeper 行为，也没有签名/公证或全架构兼容性承诺。

## 本轮新增功能的 Mac 验收

源码已接入个人评分、JSON 备份/合并导入、可选 AI 推荐和后台提醒。迁移个人数据优先在 Windows 的“数据管理”中导出 JSON，再在 Mac 导入；不要复制后台锁文件、worker 状态或日志。Web 旧库可先用 `web/scripts/export-desktop.mjs` 导出成同一格式。

在 Mac 上用临时数据目录验收后台时，先通过原生窗口创建数据库，再主动启用后台，关闭主窗口、重开并停止，确认实际通知与进程退出。后台不会自动配置 LaunchAgent 或开机自启，注销/睡眠期间不保证提醒。AI 真实请求只在配置自己的供应商 Key 并主动点击时发生，可能计费；自动化烟测使用模拟 AI 和通知，不代表实际供应商或 Mac 通知显示已通过。
