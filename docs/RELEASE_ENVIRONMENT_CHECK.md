# 发布环境独立核验

日期：2026-10-15；时区：Asia/Shanghai（UTC+08:00）。核心现场探测时间为 11:31–11:37。

范围：`F:\science yjs\work\ZFJB`，目标仓库为 `https://github.com/gzjBC/ZFZS`，不是 game。主产品是 `desktop/`（Python 3.13 + Tkinter + SQLite），`web/` 是可选参考实现。本次只新增本报告；产品代码、配置、数据库、容器及 Git 引用均未修改，未 commit / push / fetch。

## 1. 结论

| 对象 | 状态 | 本次证据与限制 |
|---|---|---|
| GitHub 仓库 HTTPS 只读访问 | **可达** | 11:33:24，升级权限后的 `git ls-remote` 退出 0，约 2.49 秒，返回 `main=b314c0edc71bf16bcb4f8cc5e8b40bb1effef8e5`。未使用凭证助手或关闭 TLS 验证。 |
| GitHub 写权限、推送、Actions 结果 | **未知** | 没有推送、认证测试或远程工作流查询；只读成功不能证明可写。 |
| Docker Engine | **可达** | 11:33:23，升级权限后的 `docker version` 退出 0，约 0.44 秒；Client / Server 均为 `29.5.3`。此前“Engine 超时”的结论不代表本次状态。 |
| ZFZS 预期 PostgreSQL 16 实例 | **未知／未就绪** | 当前 Docker 上按项目固定容器名及镜像过滤均无匹配；`postgres:16-alpine` 镜像未找到。不能据此断言其他 Docker context 或主机上也没有。 |
| 本机 TCP 5432 | **可达** | IPv4 / IPv6 回环连接均成功；Docker 端口过滤显示实际发布该端口的是 `pgvector/pgvector:pg17`。这不是 Compose 声明的项目 PostgreSQL 16 镜像。 |
| 测试库的既有测试连接 | **不可达（认证失败）** | 仅针对 `localhost:5432/anime_tracker_test` 发起连接，PostgreSQL 返回 `28P01`。不是 TCP 故障，也不是沙箱权限错误。 |
| `anime_tracker_test` 是否存在、是否仅用于测试 | **未知** | 认证失败，未执行任何 SQL；未确认隔离前提，因此没有运行 13 项 PostgreSQL 测试。 |
| 本机 Web 默认入口 3000 | **不可达（未监听）** | `127.0.0.1:3000` 与 `[::1]:3000` 均 `ECONNREFUSED`；不表示项目代码损坏，也不排除使用其他端口。 |
| Web 本地依赖与测试入口 | **可用（检查范围内）** | Node `v24.14.1`、Vitest `5.0.0`；当前平台所需包的元数据与锁文件版本匹配，关键原生模块可加载。没有重跑历史 92 项非 DB 测试。 |

发布判断：GitHub 只读访问和 Docker Engine 本次均已恢复可用；本机 Web 数据库集成验收仍被测试连接认证及隔离状态未知阻塞。Docker / PostgreSQL 不是原生桌面客户端的运行依赖，不应因此把桌面交付改成容器或 Web 交付。

## 2. 精简证据与安全边界

### Git

- 开始核验时分支为 `main`，HEAD 为 `eb8c9916aa09`。
- 本地缓存 `refs/remotes/origin/main` 与本次实时 `ls-remote` 返回值相同，均为 `b314c0edc71bf16bcb4f8cc5e8b40bb1effef8e5`。
- `git rev-list --left-right --count refs/remotes/origin/main...HEAD` 返回 `0 2`。
- 对本次实时远端 SHA 执行 `git merge-base --is-ancestor <SHA> HEAD`，退出 0；两条本地提交为 `8b5835b` 与 `eb8c991`。这只是核验时刻的关系，集成后须重新核对。
- 初始工作树已有 `docs/AGENT_TASKS.md`；后续出现其他 agent 的桌面脚本、UI 和发现模块改动，均保留且未编辑。
- 沙箱内 Git 状态检查遇到全局 ignore 读取拒绝；升级只读检查后成功。沙箱内 HTTPS 探测报 `SEC_E_NO_CREDENTIALS`，升级后同一仓库只读请求成功，不能将首次结果写成 GitHub 故障。

远端查询使用显式 ZFZS HTTPS URL，而非可能变化的 remote 名称。仅通过单次命令的 `-c` 参数禁用凭证助手、交互及额外请求头，设置 `http.sslVerify=true`；子进程禁用凭证提示及 Git 调试跟踪。不访问本机凭证存储，不修改仓库或全局 Git 配置。本次没有重现既往的证书吊销服务错误，也没有绕过证书或吊销检查。

### Docker 与端口

执行的只读命令（输出限于版本、镜像、状态和端口等必要字段）：

```text
docker version --format 'Client={{.Client.Version}};Server={{if .Server}}{{.Server.Version}}{{else}}unavailable{{end}}'
docker ps -a --filter ancestor=postgres:16-alpine --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
docker ps -a --filter name=^/anime-tracker-db$ --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
docker images postgres:16-alpine --format '{{.Repository}}:{{.Tag}} | {{.ID}} | {{.Size}}'
docker images postgres --format '{{.Repository}}:{{.Tag}} | {{.ID}} | {{.Size}}'
docker ps --filter publish=5432 --format '{{.Image}} | {{.Status}} | {{.Ports}}'
```

- 初次沙箱内 `docker version` 被配置文件和命名管道权限拒绝；升级后成功，不将沙箱限制归因于 Engine。
- 项目名 / `postgres:16-alpine` 过滤结果为空；`docker images postgres` 仅返回 `postgres:17-alpine`（约 424 MB）。这不是项目已准备好 PostgreSQL 16 的证据。
- 5432 发布端口对应的运行镜像为 `pgvector/pgvector:pg17`，状态为 Up；未访问该容器的环境变量、数据库内容或日志，也未启停、更改或清理它。
- 端口归属查询首次遭 CIM 权限拒绝；升级后显示 `com.docker.backend` 与 `wslrelay` 监听 5432，与 Docker 转发相符。未读取进程命令行或环境。
- 每次 Git 网络 / Docker 子进程探测均设置 18 秒硬上限，超时会结束该探测进程树；没有超过 20 秒的探测。权限升级后的必要重试各一次，未反复轮询。回环 TCP 探测限时 2 秒，测试库连接探测总上限 15 秒。

### Web 依赖、测试及数据库保护

- 已读取适用的 `web/AGENTS.md`；本次不改 Next.js 代码。未读取 `.env`、`.env.local` 或本机密钥文件。
- 15 个直接依赖 / 开发依赖的已装版本与 `package-lock.json` 一致；关键版本为 Next `16.3.4`、React / React DOM `19.2.8`、pg `8.23.0`、Undici `8.10.2`、TypeScript `5.9.3`、Vitest `5.0.0`。
- 锁文件包含 507 个包条目；排除其他平台及其嵌套分支的 99 项后，Windows x64 适用的 408 项均存在，版本无不一致、无必需或适用可选包缺失。此为包元数据检查，不是逐文件哈希或供应链安全审计。
- SWC、Rolldown、unrs resolver、Tailwind Oxide、Lightning CSS 的 Windows x64 原生绑定加载成功。曾额外探测 Rollup 绑定返回 `MODULE_NOT_FOUND`，复核确认该包根本不在锁文件中：实际 Vite `8.2.2` 使用 Rolldown `1.2.7`，对应绑定加载成功，因此不判作缺依赖。
- `node node_modules/vitest/vitest.mjs --version` 正常返回 `vitest/5.0.0 win32-x64 node-v24.14.1`；测试 CLI 文件和 Next / TypeScript / ESLint 入口均存在。
- 现有依赖引擎要求中，Next 要求 Node `>=20.9.0`，Undici 要求 `>=22.19.0`，Vitest 要求 `^22.12.0 || ^24.0.0 || >=26.0.0`；当前 Node 24 满足。`web/README.md` 中“Node >=18”不再足以覆盖当前依赖，建议主 agent 后续修正文档，本次未改该文件。
- `web/tests/lib/db/tracking-repo.test.ts` 中有 13 项数据库测试，连接被硬编码到 `localhost:5432/anime_tracker_test`，会在钩子中 `DROP TABLE` / `TRUNCATE tracking`。设置普通 `DATABASE_URL` 并不会重定向这组测试。
- 本次连接探测沿用测试文件中的既有测试夹具参数，不输出连接串或密码；连接前严格校验主机、端口、库名，并设置只读会话选项及连接 / 查询超时。认证阶段返回 `28P01`，故数据库身份、表、会话和行数查询均未执行。没有换用生产库或猜测其他凭证。
- `npm run test` 默认包含数据库测试；`npm run check` 最终会调用全部测试。`npm run dev` 的 `predev` 会调用 `db:init`；该初始化脚本会修改主库表结构并创建 / 初始化测试库。以上命令均不适合在当前未确认隔离的现场直接运行，本次未执行。

| 验证项 | 本次真实结果 |
|---|---|
| Web 依赖 / 锁文件 / 原生绑定 / Vitest CLI | 上述限定范围内通过 |
| 13 项 PostgreSQL 集成测试 | **未执行，0/13 运行**；不是测试断言失败 |
| 92 项非 DB 测试 | **本次未重跑**；此前通过为用户交接信息及已有项目文档记录 |
| Web lint / typecheck / production build | **本次未重跑**；未把现有构建产物当成新验收结果 |
| Python 17 项、Windows 独立程序启动 | **本次未重跑**；由主 agent 负责集成后重新验收 |
| macOS 运行、打包、签名 | **未验证**；没有 Mac 实机测试结论 |

## 3. 给主 agent 的可执行发布建议

### 安全同步 GitHub

1. 等并行 agent 完成，由主 agent 审阅实际 diff、整合测试并统一提交。仅暂存明确属于本轮的源码 / 文档，不带入数据库、密钥、虚拟环境、依赖目录或构建目录；本报告不代表其他 agent 的变更已验收。
2. 推送前确认 `origin` 的目标确为 `https://github.com/gzjBC/ZFZS.git`（不是 game），不要输出任何带认证信息的 URL。重新用最长 20 秒的只读 `git ls-remote` 取得实时 `main` SHA，不依赖本报告或旧的 `origin/main` 缓存。
3. 对实时 SHA 检查 `git merge-base --is-ancestor <实时SHA> HEAD`。仅退出 0 才按快进流程继续；若对象不在本地、远端更新或关系不符，停止并由主 agent 审阅同步方案，不 force push、不 reset。此子任务没有 fetch。
4. 在主 agent 的推送授权范围内，先做 `git push --dry-run origin HEAD:main`，成功后再由主 agent 执行 `git push -u origin HEAD:main`。这两个命令**本次均未执行**；只读可达不保证写权限或推送链路可用。网络操作继续使用有界超时，失败时保存简洁脱敏证据，不关闭 TLS / 吊销验证、不借用未配置代理、不改全局网络设置。
5. 推送后重新 `ls-remote`，确认远端 SHA 等于本地 `git rev-parse HEAD`，再检查该提交的 Actions 真实结果。超时不等于“肯定没推上”，先读回远端再决定是否重试。

### 桌面交付优先，Web 数据库验收隔离

- 桌面交付继续以 Python 3.13 + Tkinter + SQLite 为主；根 `.venv\Scripts\python.exe` 是交接指定的现成解释器。由主 agent 在隔离用户数据目录复验最终源码与 Windows 包，不触碰真实用户 SQLite。本次未重装依赖或执行打包。
- Web 的 13 项数据库测试优先交给**临时、专用 CI PostgreSQL 16 服务**。核验时 `.github/workflows/ci.yml` 已声明该服务、Node 24、`npm ci`、`db:init`、`npm run check` 和构建；这些是配置证据，不是 Actions 运行通过证据。并行 agent 正在维护 CI，集成后须重新审阅最终配置。
- 若要补本机数据库验收，先由主 agent / 用户确认现有 5432 服务的归属、有效测试连接及 `anime_tracker_test` 专用性。不要为了套用 Compose 而删除现有 pg17 容器、清卷、重置数据库密码或抢占端口。
- 只有确认目标为可销毁的 `anime_tracker_test` 且无用户数据 / 业务用途后，才可从 `web/` 运行单文件测试：`node node_modules/vitest/vitest.mjs run tests/lib/db/tracking-repo.test.ts`。若隔离测试服务使用其他端口，现有测试的硬编码连接必须先经主 agent 审阅修改；不能只改 `DATABASE_URL` 就开跑。
- 无须为本次环境报告无条件重跑 92 项非 DB 测试；最终集成若修改 Web 逻辑，由主 agent 决定相应回归范围。未确认测试库前不要运行全量 `npm test` / `npm run check`。
- Windows 可准备内部预发布；正式交付仍需最终集成版本的独立程序和人工使用验收。macOS 必须在 Mac 上验证 Python/Tk、启动、打包后 `.app`、路径与数据持久化；CI 编译或静态脚本检查不能替代实机验收。签名 / notarization 状态另行确认，不宣称已通过。

## 4. 未验证事项与剩余阻塞

- GitHub 推送权限、保护分支要求、最终提交是否已同步、CI 与打包工作流实际结果：未知。
- 测试库是否存在及专用、测试夹具为何与当前 5432 服务认证不匹配：未知；没有访问本机凭证或其他数据库追查。
- 13 项 PostgreSQL 集成测试：受上述安全前提阻塞，未执行。
- 当前 3000 默认 Web 服务未监听；没有启动服务器，也未测真实 API / AI / Bangumi 链路。
- 并行改动的最终集成、Windows 最终发行包验收、macOS 实机 / 架构兼容与签名：由主 agent 后续验收。

本报告记录一次现场快照；网络、Docker 和远端引用都可能变化。已排除的沙箱权限问题与仍存在的数据库认证 / 隔离问题须分别跟踪。
