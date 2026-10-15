# Scripts

桌面客户端启动、打包和维护脚本。以下命令均在 `desktop/` 目录执行。

当前脚本：

- `run_desktop.ps1` / `run_desktop.sh`：启动原生桌面窗口。
- `install_desktop_shortcut.ps1`：Windows 桌面快捷方式；存在打包版时优先使用打包版。
- `build_desktop.ps1` / `build_desktop.sh`：在当前系统打包原生应用。
- `test.ps1`：单元测试与旧版 FastAPI 前端 E2E。
- `dev.ps1` / `start.ps1`：可选的旧版 FastAPI Web 调试服务。
- `init_db.py`：创建 SQLite 数据库表。

运行：

```powershell
.\scripts\run_desktop.ps1
```
