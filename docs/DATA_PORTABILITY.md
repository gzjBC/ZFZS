# 桌面数据备份与跨电脑迁移

## 服务契约

实现位于 `desktop/backend/app/service/transfer_service.py`，无需新增依赖。

```python
save_export(db: Session, path: Path) -> int
create_backup(db: Session, backup_dir: Path) -> Path
load_import(db: Session, path: Path, conflict: str = "keep_local",
            backup_dir: Path | None = None) -> ImportSummary
```

`ImportSummary` 是不可变 dataclass，字段为 `created: int`、`updated: int`、
`skipped: int`、`backup_path: Path | None`。计数以输入条目为单位；显式替换时，
字段完全相同的条目计入 `skipped`，不改写时间戳。

导入应使用独立、干净的 Session，不得包含未提交/已 flush 的调用者写入或显式
`begin()` / SAVEPOINT。普通 SQLite legacy 模式中，由查询自动开启的逻辑事务可接受；
已有物理 SQLite 事务会被拒绝且保持原样。导入负责一次 commit，发生异常则 rollback。
导出和手动备份不 commit、不修改数据库，也不调用配置读取函数或读写设置文件。

```python
with SessionLocal() as db:
    count = save_export(db, Path("D:/migration/library.json"))

with SessionLocal() as db:
    result = load_import(db, Path("D:/migration/library.json"))
# 只有用户明确选择“替换已有条目”时，才传 conflict="replace_existing"。
```

## JSON v1

UTF-8（导入也接受 UTF-8 BOM），固定顶层结构：

```json
{
  "format": "zfzs-library",
  "version": 1,
  "exported_at": "2026-10-15T08:30:00.123456+00:00",
  "items": [{"title": "示例番剧"}]
}
```

正式导出包含每条记录的完整白名单字段：

- 基本信息：`title`、`title_cn`、`cover_url`、`summary`、`tags`。
- 观看信息：`status`、`watched_episodes`、`total_episodes`、`play_url`。
- 提醒信息：`broadcast_day`、`broadcast_time`、`reminder_enabled`、
  `reminder_minutes`、`last_reminded_at`。
- 来源信息：`source`、`source_id`、`source_url`、`source_status`、`year`。
- 评分和时间：网站评分 `score`、个人评分 `user_rating`、`completed_at`、
  `created_at`、`updated_at`。

不导出数据库行 `id`、API Key、环境变量、配置或电脑路径。
白名单字段内的用户文本和链接仍属于个人数据；JSON 未加密，应由用户妥善保管。

手工构造 v1 文件时只要求 `title`；省略字段使用 ORM 对应默认值（状态 watching、
20:00、开启提醒、提前 15 分钟、已看 0，其余可空），创建/更新时间默认使用文件
`exported_at`，保证同一文件重复导入稳定。显式替换是整条白名单字段替换，
省略字段也会恢复为这些默认值，不是局部 patch。未知字段、重复 JSON 键和未知版本拒绝。

## 身份及冲突规则

- 有 `source_id` 时必须同时有非空 `source`。身份是
  `("source", source.strip().casefold(), source_id.strip())`；ID 区分大小写，
  不同来源相同 ID 不冲突，标题变化不影响匹配。
- 无 `source_id` 时视为手动条目。身份是 `("manual", 规范化标题, 主链接或空串)`。
  标题采用 Unicode NFKC、合并空白、casefold；主链接优先 `source_url`，否则 `play_url`。
  URL 的协议/域名规范化为小写、域名 IDNA 化、去默认端口/片段、空路径变 `/`；
  路径和 query 保留原值及顺序。手动条目改名或更换主链接后视为不同条目；
  只有同名同链接（或都无链接）才合并，不做模糊匹配。
- 导入文件内出现重复身份，或某输入身份对应多个本地条目，整批拒绝；
  不任选一条、不静默丢弃。已有重复数据仍可导出以保全原始记录，
  但该文件重新导入前必须由用户消歧。
- 默认 `keep_local`：匹配条目完整保留，包括进度、个人评分和提醒设置。
  `replace_existing`：只更新匹配项并新增缺失项；绝不删除其他本地条目。

## 校验、备份及事务

导入上限为 20 MiB、10,000 条；导出同样限制，以保证生成文件可再次导入。
全部记录在任何数据库访问前完成类型和内容校验，禁止字符串到数字/布尔的隐式转换。
进度为 0–1,000,000 的整数，总集数可为 null；已看不得超过已知总集数，
未知总集数请用 null，不使用 0。评分必须为 0–10 的有限数字或 null。
状态限 watching/paused/finished；播出星期 0–6，时间为 24 小时 HH:MM，
提前提醒 0–1440 分钟，年份 1900–2200。标题/来源等遵循模型长度，
URL 最大 4096 字符、摘要 100,000、标签 10,000；非法控制字符拒绝。

三个 URL 字段仅接受无账号密码的绝对 HTTP(S) URL，校验主机/端口、转义字符，
不访问网络。时间必须含日期、时分秒，可含 1–6 位微秒及 Z/时区偏移。
当前 ORM 使用无时区 DateTime：原无时区时间原样保留；有偏移时间按相同瞬间转成
UTC 无时区时间，偏移文本本身不保留。不自行推断无时区时间所属时区，
跨时区迁移不会自动重排播出提醒的本地钟点。

应用默认的 SQLite legacy 模式在读取本地快照前通过 `BEGIN IMMEDIATE` 获取写锁，
刷新已缓存的 ORM 对象，避免备份/合并期间其他连接插入写入。非 legacy 模式只允许
新 Session 的驱动自建事务；若锁升级失败则整批回滚，不重试部分记录。若非空本地库，
即使最终全部 skipped 或输入为空，也必须先成功备份：

- 明确传入 `backup_dir` 时，仅在该目录生成备份。
- 否则通过 SQLite `PRAGMA database_list` 取得实际文件，在其旁 `backups/` 目录保存，
  支持文件名中的空格、中文；不读取配置猜测路径。
- 内存/临时 SQLite 和非文件数据库必须显式传目录，不回退用户数据路径。
- 空本地库无需自动备份，`backup_path=None`。手动 `create_backup` 仍可备份空库。

备份名包含 UTC 时间与 UUID；文件先写同目录临时文件、flush/fsync，再原子替换。
旧导出文件在失败时保留，临时文件正常清理。禁止导出覆盖数据库及其
`-wal`、`-shm`、`-journal` 文件。备份失败不允许修改数据库；写入失败整批回滚，
已完成的导入前备份保留供恢复。无自动清理/轮换，用户自行管理磁盘空间。

内容/策略/会话错误抛 `TransferError`（`ValueError` 子类）；磁盘错误保留 `OSError`，
数据库错误保留 SQLAlchemy 异常。UI 应捕获异常显示失败，不能在错误后继续导入。
此服务不迁移设置，不调用 AI，不配置后台任务，不执行数据库 schema 迁移。
本地已有非法字段（如已看集数大于已知总集数）也会阻止导出/导入，须先由用户修正；
不会截断、纠正或绕过校验静默丢失数据。
测试仅使用临时目录/内存库；当前不包含 UI 接线、非 SQLite 的并发验证、
跨操作系统实机或断电级文件系统耐久性保证。

## 从 Web PostgreSQL 迁入

在 `web/` 执行 `node --env-file=.env.local scripts/export-desktop.mjs <新的.json路径>`，或通过系统 `DATABASE_URL` 提供连接后省略 `--env-file`。该脚本只读查询追番表，不修改数据库、不导出连接串或 API Key，目标文件存在时拒绝覆盖。

Web 的 `rating` 映射为 `user_rating`，Bangumi 身份和观看进度保留；`completed` 映射为 `finished`，`wish/hold` 映射为 `paused`，提醒关闭。旧总集数小于已看进度时转为未知总集数而保留真实进度。导出的文件可直接通过桌面“数据管理”导入；默认保留本地冲突项。

主 Agent 已用实际 Node 转换器输出和 Python 导入器执行跨项目回环及重复导入验收。源码与打包版的备份/导入仅包含追番字段，不包含后台进程锁、日志或 AI Key。
