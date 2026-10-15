# 可选后台系统提醒

后台提醒只应由用户在桌面 UI 明确点击“启动后台提醒”后开启。查询状态、导入
模块、打开应用以及关闭主窗口都不应启动 worker。开启后，独立进程可以在主窗口
关闭后继续轮询本次登录会话的提醒；用户可重新打开应用查询或停止它。

本功能不注册系统服务、计划任务、LaunchAgent、开机自启或新的权限配置，不需要
管理员权限，也不会修改系统通知设置。退出登录、重启后不会自动重新启动；不保证
休眠、系统冻结或退出登录时仍能发送通知。非 Windows 系统对注销后进程的清理取决于
桌面会话管理器，因此这不是一个保证在注销瞬间结束的系统服务。

## UI 集成契约

所有函数位于 `desktop/backend/app/service/notification_service.py`。

| 函数 | 行为及返回值 |
| --- | --- |
| `background_status(data_dir: Path) -> bool` | 只探测已存在的 OS 文件锁；不创建目录/文件，不启动进程。`True` 表示 worker 持锁，包括短暂的启动/停止阶段。 |
| `start_background_worker(data_dir: Path) -> bool` | 仅在显式用户操作中调用。`True` 表示该目录已有 worker 就绪，或新 worker 已完成数据库/表结构检查并写入本次启动的就绪标识。重复启动不会生成第二个 worker。 |
| `stop_background_worker(data_dir: Path) -> bool` | `True` 表示本 worker 的合作停止请求已写入，或 worker 已停止；不是强制退出确认。UI 应显示“正在停止”并再次查询状态。 |
| `run_worker(data_dir: Path, poll_seconds: int = 30) -> None` | 在当前进程内运行后台循环；不创建窗口。轮询间隔须为正整数。 |
| `send_system_notification(title: str, message: str) -> bool` | `True` 表示系统 API/通知命令调用成功，不表示用户实际看到了通知。失败返回 `False` 并记录不含正文的错误分类。 |
| `run_once(data_dir: Path, *, now=None, notifier=None, stop_requested=None) -> int` | 单次轮询，返回通知成功且提醒时间已写入数据库的数量。可用于临时数据库测试。 |

启动最多等待 8 秒就绪握手。若超时，会按该次启动的随机标识写入取消请求，即使
子进程仍在导入模块，稍后开始运行也会读取取消请求。另有可撤销的启动标识文件，
防止后续启停覆盖旧取消请求后，旧的慢启动子进程意外开始运行。读写失败等极端条件仍需 UI
提示用户查询状态与日志，不能把启动失败当作已经启用。

停止是合作式的：空闲轮询一般每 250 毫秒检查一次；正在发送的 Windows 通知会
保留临时隐藏窗口约 10 秒，macOS/Linux 通知命令超时为 15 秒。停止请求不会撤回
已提交的通知；当前调用返回后不再发送该批次的剩余条目。

### 启动入口

源码模式使用参数列表启动（无 shell）：

```text
<sys.executable> <desktop>/scripts/reminder_worker.py --data-dir <data_dir>
```

打包模式使用：

```text
<sys.executable> --reminder-worker --data-dir <data_dir>
```

打包主入口必须在建立 Tk、桌面单实例互斥或正常用户存储初始化之前识别此 flag，
设置明确的 `data_dir`，调用 `run_worker` 后返回，不能落入主窗口启动路径。不要在
UI 退出时自动停止已由用户开启的 worker，也不要在下一次登录自动恢复启动。

子进程的 stdin/stdout/stderr 均不连接 UI；向 stdout 打印“成功”不会让用户界面
收到启动/停止确认，也不能替代系统通知。UI 使用返回值和状态查询，后台故障查看
`data_dir/reminder-worker.log`。日志轮转为单文件至多 128 KiB、两份备份，记录错误
类别/退出码而不记录番剧标题、完整观看数据、数据库 URL、通知正文或 API Key。

### 数据库边界

worker 固定使用传入目录下**已经存在**的 `zfzs.db`，以 SQLite `mode=rw` 打开，
不创建空数据库，不调用绑定到全局引擎的迁移或 `SessionLocal`。先通过正常 UI 完成
数据库建表及轻量迁移，再启用后台提醒。

启动函数会检查 UI 的实际 SQLAlchemy `engine.url`，而不只检查可能已变化的环境变量。
只有普通 SQLite URL 解析到同一个 `data_dir/zfzs.db` 才允许启动。内存数据库、其他
路径、带 URI/query 的 SQLite 配置和非 SQLite 后端返回 `False`，不会偷偷换用另一
数据库。worker 的独立连接不继承正式或其他 `DATABASE_URL`；子进程也显式覆盖路径，
并移除名称以 `API_KEY` 结尾的环境变量。

备份/迁移后应停止旧数据目录的 worker，再在新目录重新开启；备份系统不应复制或
恢复 `.reminder-*.lock`、`.reminder-worker.json`、`.reminder-stop.json`、
`.reminder-launch.json` 及日志。

## 提醒周期与失败策略

保留 `list_today_due_anime(db, now=None)`、`mark_reminded(db, anime, now=None)` 和
`_is_due(anime, now)` 原签名。星期继续使用周日为 0。放送周期的有效窗口为“放送
时间减提前分钟数”至“放送日次日零点”；提前量最多 1440 分钟，因此检查今天和
明天的放送即可涵盖跨午夜、周六到周日、周日到周一的边界。

只提醒 `watching` 且启用提醒的条目；暂停、已看完、已知总集数且进度已完成的条目
不会发送。只有通知返回成功才调用 `mark_reminded`。同一周期内的
`last_reminded_at` 会阻止午夜后的重复发送；下周恢复提醒。原有导入功能保留此字段，
重复导入、暂停后恢复、缩短提前分钟数不会导致本周期重发。超过有效窗口的历史周期不会补发。

worker 生命周期锁与单次派发锁分离。Windows 使用 `msvcrt` 字节锁，macOS/Linux
使用 `fcntl.flock`；进程退出后 OS 自动释放。锁文件保持原 inode，不删除/替换。
启动/停止操作另有控制锁；停止文件携带随机运行标识，不使用旧 PID，也不调用
`kill`/`taskkill`/强制 terminate。因此过期控制文件不会杀死或停止无关的新进程。

**可靠性边界：** 这里不是跨 OS 通知系统与 SQLite 的分布式事务。若通知已提交，
但进程恰在写回提醒时间之前崩溃或数据库提交失败，下次轮询可能重发；不声称
crash-safe exactly-once。手动修改提醒计划、系统时间/时区回拨或通过外部工具清除
`last_reminded_at` 也可能改变周期归属。时间按本机墙钟处理，不提供独立番剧时区。

## 各平台实现与已核对文档

- Windows：标准库 `ctypes` 直接调用 Unicode `Shell_NotifyIconW`，不需要 PowerShell
  模块、第三方 toast 库、AppUserModelID 注册或快捷方式。标题和正文写入固定大小的
  UTF-16 结构字段，不会成为脚本代码；保留 Unicode 边界，检查添加/版本/提交 API
  返回值，最终清理临时通知区域图标及隐藏窗口。遵循系统 quiet-time 设置。
  原生 API 成功不保证横幅可见；勿扰模式、用户偏好或其他通知排队仍可能抑制显示。
  依据：[Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw)、
  [NOTIFYICONDATAW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw)、
  [通知区域](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area)。
- macOS：调用已安装的 `osascript` 执行固定的 AppleScript `display notification`。
  标题与正文通过子进程环境属性传入，绝不拼接进脚本。缺命令、非零退出及超时会
  返回失败和可读错误类别，不自动请求/更改系统权限。显示方式和实际可见性受用户
  的通知设置影响。依据：[Apple 官方通知脚本文档](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/DisplayNotifications.html)。
  **本次仅完成文档核对和模拟命令契约测试，未在 Mac 实机验证。**
- Linux：可用时调用 `notify-send`，以参数列表及 `--` 分隔用户文本，转义正文 markup；
  无工具时明确返回未支持，不自动安装软件。还需要可用的图形桌面通知服务/会话总线，
  无图形会话或服务失败时返回失败。依据：[libnotify 命令手册](https://manpages.debian.org/unstable/libnotify-bin/notify-send.1.en.html)、
  [freedesktop 通知规范](https://specifications.freedesktop.org/notification/latest-single/)。
  本次未进行 Linux 实机通知测试。

## 离线测试

在 `desktop` 目录使用根虚拟环境（PowerShell）：

```powershell
$env:DATABASE_URL = 'sqlite:///:memory:'
& ..\.venv\Scripts\python.exe -B -m unittest tests.test_notifications tests.test_services -v
```

`run_once` 可注入 `now` 与 `notifier`；`run_worker` 额外可注入 `clock` 与 `wait`。
测试只使用临时路径、临时 SQLite、替身子进程、替身系统 DLL/通知命令及合作停止
请求，不启动真实常驻进程、不发送真实系统通知、不读取正式用户数据库，不调用
付费 AI。Windows ABI wrapper 的模拟测试仅在 Windows 执行；macOS/Linux 分支为
命令契约模拟，不能据此声称跨平台实机验收通过。
