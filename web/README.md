# 追番助手 (Anime Tracker)

本地优先的追番管理 Web 应用：**放送日历 · 季度新番 · 追番清单 · AI 推荐** 四大板块。
数据来自 [Bangumi API](https://bangumi.github.io/api/)，AI 推荐走千问（默认）/ DeepSeek（兜底），全部数据存在本地 PostgreSQL。

> ⚠️ 本项目**不需要登录**、数据全在本地；接口层已为后续公网部署预留。

---

## 功能一览

| 板块 | 路由 | 说明 |
|---|---|---|
| 📅 放送日历 | `/` | 本周每天放送的番，今天高亮，空档提示 |
| 🍂 季度新番 | `/seasons` | 按年份 + 季度（1/4/7/10 月）浏览新番，加入清单 |
| 📋 我的追番 | `/tracking` | 搜索添加、状态（想看/在看/看完/搁置）、进度 +1、一键看完、评分；自动分「正在追 / 已追完（按每 3 个月归档）」 |
| 🤖 AI 推荐 | `/recommend` | 基于「看完并评分」的番，AI 生成 5 部推荐（千问优先，失败自动切 DeepSeek） |

**看番跳转**：卡片标题 ↗ 打开 Bangumi 条目页；「▶ 去观看」一键直达 B 站番剧搜索。

---

## 技术栈

- **前端**：Next.js 16 (App Router) + TypeScript + Tailwind CSS 4（页面样式为内联 style，无复杂 UI 库）
- **后端**：Next.js API Routes（Route Handlers）
- **数据库**：PostgreSQL 16（Docker Compose 起容器）
- **AI**：OpenAI 兼容协议 HTTP 客户端（千问 `qwen-flash` 最便宜档 → DeepSeek `deepseek-v4-flash` 兜底）
- **测试**：Vitest（验收门 `npm run check`：lint → typecheck → 101 个测试）
- **网络**：undici + ProxyAgent（Node 内置 fetch 无法透传代理，已踩坑验证）

```
src/
├── app/                # 页面与 API 路由
│   ├── page.tsx        # 放送日历（首页）
│   ├── seasons/        # 季度新番
│   ├── tracking/       # 我的追番
│   ├── recommend/      # AI 推荐
│   └── api/            # calendar / seasons / subjects / tracking / recommend
├── components/         # AnimeCard 等复用组件（纯展示，props 驱动）
├── lib/
│   ├── bangumi/        # Bangumi 客户端（calendar / seasons / search，代理注入）
│   ├── db/             # 连接池、schema.sql、tracking-repo（参数化防注入）
│   ├── ai/             # AI 客户端 / 双供应商配置 / 推荐编排
│   ├── api/            # 接口纯校验函数
│   ├── cache.ts        # 内存缓存
│   └── ui/             # 纯 UI 逻辑（状态徽章、季度分组、日期格式化，全单测）
scripts/
├── check.mjs           # 验收门：lint + typecheck + vitest
└── db-init.mjs         # 数据库初始化（幂等，npm run dev 前自动执行）
tests/                  # 按模块组织，DB 层连真实测试库
```

---

## 快速开始（别人下载后照做）

### 前置要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Node.js | ≥ 18（开发用 24） | `node -v` 查看 |
| Docker Desktop | 任意较新版本 | 跑 PostgreSQL 容器 |
| 梯子（可选） | — | 访问 Bangumi 数据与条目页需要；AI 推荐不需要 |
| AI API Key（可选） | — | 不用 AI 推荐可跳过 |

### 步骤

```bash
# 1. 安装依赖
npm install

# 2. 复制环境变量模板（可先全留空，AI 推荐功能会提示引导）
cp .env.example .env.local

# 3. 启动数据库容器（首次会自动建库）
docker compose up -d

# 4. 启动开发服务器（自动执行数据库初始化，无需手动建表）
npm run dev
```

浏览器打开 **http://localhost:3000**。

> 提示：`npm run dev` 前会自动跑 `db:init`（幂等建表 + 确保测试库）。也可以单独执行 `npm run db:init`。

### 环境变量（.env.local）

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | 否 | PostgreSQL 连接串，默认 `postgres://anime:anime@localhost:5432/anime_tracker`（与 docker-compose 一致） |
| `BANGUMI_USER_AGENT` | 否 | 调用 Bangumi API 的应用标识 |
| `HTTPS_PROXY` | 否 | 梯子本地代理地址（如 `http://127.0.0.1:7892`），不填则直连 |
| `DASHSCOPE_API_KEY` | 否* | 千问 API Key（阿里云百炼申请），AI 推荐首选 |
| `QWEN_MODEL` | 否 | 千问模型，默认 `qwen-flash`（最便宜档） |
| `DEEPSEEK_API_KEY` | 否* | DeepSeek API Key，千问不可用时兜底 |
| `DEEPSEEK_MODEL` | 否 | DeepSeek 模型，默认 `deepseek-v4-flash`（最便宜档） |

\* 两个 AI Key 至少配一个才能用 AI 推荐；都不配则推荐页给引导提示，其余功能不受影响。

---

## 常用命令

```bash
npm run dev        # 开发服务器（自动先初始化数据库）
npm run check      # 验收门：lint + typecheck + 全部测试
npm run test       # 只跑测试（DB 测试连本地 anime_tracker_test 库）
npm run db:init    # 手动初始化数据库（幂等）
npm run build      # 生产构建
```

---

## 测试

- 覆盖：缓存、参数校验、Bangumi 解析、DB 仓库（真实 PostgreSQL 测试库）、AI 客户端与推荐编排、推荐 API、UI 纯逻辑
- 运行测试需要本地数据库（`docker compose up -d` 后 `npm run db:init` 会顺带建好测试库）

---

## 常见问题

**Q：打开页面正常，但日历/季度是空的或报错？**
A：Bangumi 数据需要梯子。检查 `.env.local` 的 `HTTPS_PROXY` 是否为当前代理地址，且梯子已开启。

**Q：点标题打开 bgm.tv 加载失败？**
A：同上，需要梯子。B 站「▶ 去观看」不需要。

**Q：AI 推荐提示"还没可推荐的历史"？**
A：需要先在追番清单里把至少一部番标记为「看完」并评分。

**Q：AI 推荐里有不认识的番？**
A：LLM 可能产生幻觉，推荐仅供参考，建议在季度新番/搜索里核实条目。

**Q：`npm run dev` 报数据库连接失败？**
A：确认 Docker Desktop 已启动、已执行 `docker compose up -d`、端口 5432 未被占用。

---

## 开发约定（维护者）

- **按模块开发**：每个模块（bangumi / db / ai / ui / api）高内聚低耦合，页面只调接口不碰数据层
- **每模块必测试**：纯逻辑进 `tests/`，DB 层连真实测试库
- **重复工作脚本化**：验收门 `scripts/check.mjs`、建表 `scripts/db-init.mjs`
- **接口层为公网部署预留**：API 全在 `/api/*`，无登录态，后续可平移至托管环境

## License

MIT
