# ZFZS 多 Agent 任务分工

分派日期：2026-10-15。起始提交：`eb8c991`。

## 当前并行任务

| Agent | 责任 | 分派状态 | Agent ID |
|---|---|---|---|
| Newton | 桌面界面 | 已交付；原生 UI 17 项复验通过 | `01a13d99-65e7-7f40-a3fc-d890b7c4a37e` |
| Carver | Bangumi数据层 | 已交付；29 项新增测试及真实查询通过 | `01a13d99-69d1-7071-83ee-2c0bb164f07c` |
| Zeno | 跨平台打包 | 已交付；Windows 验证通过，Mac 实机待验收 | `01a13d99-6ee4-71b1-a394-0b2edf7b4efc` |
| Banach | 发布环境核验 | 已交付；GitHub/Docker 可达，测试库认证失败 | `01a13d99-7422-7a42-a5b1-a49562430c5c` |

### Newton：原生桌面界面

- 将放送日历与季度新番接入 Tkinter，并支持从发现列表加入追番。
- 沿用后台任务队列，处理加载状态、网络失败与恢复。
- 修改范围：桌面入口和原生 UI 烟测。
- 验收：不启动 Web 服务即可使用新界面；加入列表保留来源去重和观看进度；隔离数据库烟测通过。

### Carver：Bangumi 数据层

- 新增独立的日历/季度客户端，对齐官方旧版和 v0 数据格式。
- 处理周日编号、季度跨年、分页限额、超时与异常响应。
- 修改范围：`bangumi_discovery.py` 与对应单元测试。
- 验收：可注入模拟网络；日期和参数边界有测试；返回现有通用条目结构。

### Zeno：Windows/macOS 启动与打包

- 检查含空格路径、虚拟环境恢复、Tkinter 依赖、失败退出和打包产物。
- 对齐启动与测试脚本选用的 Python，完善 GitHub Actions。
- 修改范围：启动/打包/快捷方式脚本、CI、新增 Mac 开发说明。
- 验收：本机可验证的脚本通过检查；明确列出需要 Mac 执行的验收，不能将静态检查写成 Mac 实测。

### Banach：发布环境核验

- 有界检查 GitHub 远程可达状态、Docker Engine 和 PostgreSQL 测试前提。
- 修改范围：新增 `RELEASE_ENVIRONMENT_CHECK.md`；项目代码和 Git 状态只读。
- 验收：区分网络、权限和服务问题；保留简洁证据；仅在确认隔离测试库后运行破坏性数据库测试。

## 并行接口约定

界面与数据层共同采用：

```python
from backend.app.crawlers.bangumi_discovery import BangumiDiscoveryClient

client.calendar(weekday=None, limit=50)
client.season(year=2026, month=10, limit=50)
```

- 两方法返回 `list[XifanAnimeResult]`；`source="bangumi"`，观看进度为 0。
- `weekday` 为 0=周日、1=周一至 6=周六；`None` 表示整周。
- 季度起始月份只能是 1、4、7、10。
- 外部访问失败抛出已有 `BangumiError`，UI 负责显示可读提示。

## 主 Agent 的集成职责

1. 维护任务边界和接口，避免多个 Agent 编辑相同文件。
2. 审阅改动，完成数据层与 UI 联调、单元测试和隔离原生窗口验证。
3. 更新 README、进度书和真实验收状态。
4. 统一 Git 提交与推送；任何远程更新必须以实际返回结果为准。

所有子 Agent 均不自行提交或推送，不改全局网络设置，不操作用户正式数据库。

## 后续阶段（尚未分派实现）

- 桌面 AI 推荐与用户评分闭环。
- 应用关闭后的系统通知、后台调度。
- Web PostgreSQL 向桌面 SQLite 的导入工具。
- macOS 实机验证、签名与发行包。

本轮四个子任务均已交付。主 Agent 已复验整合后的 57 项单元测试、17 项原生 UI 检查及真实 Bangumi 日历/季度查询。后续 AI、后台通知及 Mac 实机验收属于下一阶段，不包含在本轮完成范围内。最终提交、打包和远程同步以主任务交付说明为准。
