# 原生桌面 AI 推荐服务

本次只增加推荐服务、离线单元测试和本文档；不改共享模型/迁移/配置，不操作正式用户数据库，不接 UI/路由，不提交或推送。沿用 Web 的「看完 + 个人评分 → JSON 推荐 → 千问优先 / DeepSeek 回退」，不执行模型返回的内容。

## 主 agent / UI 契约

模块：`backend.app.service.recommendation_service`

```python
def generate_recommendations(
    db: Session,
    preference: str = "",
    provider: str = "auto",
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> list[Recommendation]: ...

@dataclass(frozen=True, slots=True)
class Recommendation:
    title: str
    reason: str
    search_keyword: str

class RecommendationError(RuntimeError): ...
```

- 成功返回 1–5 条。无历史、无 Key、读取数据库失败、网络/供应商/格式错误、无可用结果均抛可读中文 `RecommendationError`，不暴露原始异常、响应体、Key 或模型链接。
- 调用前展示模块常量 `PRIVACY_NOTICE`、`COST_NOTICE`、`VERIFICATION_NOTICE`，由用户主动确认/点击后调用。服务没有后台调用、遥测、日志或落盘逻辑。
- 同步服务应在工作线程执行；该线程创建并使用自己的 SQLAlchemy Session，不阻塞 UI，也不要跨线程复用 Session。
- 返回字段按纯文本渲染，不解析 HTML/Markdown，不自动打开链接。
- `search_keyword` 只是作品名称搜索词。用户之后主动搜索并核对 Bangumi 的真实结果，才能使用其真实 subject ID / 导入；模型没有可信番剧 ID。此服务不会自行搜索 Bangumi 或导入作品。
- `preference` 必须是至多 2000 字符的文本；可为空。

## 历史与隐私边界

只选择 `status == 'finished'` 且 `user_rating` 非空、有限、在 0–10 内的作品，0 分有效。按 `coalesce(completed_at, updated_at, created_at)` 降序、`id` 降序取最近 50 条。个人评分只来自 `user_rating`，**不使用网站 `score`**。

请求消息的数据部分严格白名单：

```json
{
  "history": [
    {"title": "原名", "title_cn": "中文名", "user_rating": 9.5, "tags": "治愈,冒险"}
  ],
  "preference": "用户本次主动输入的偏好"
}
```

标题/中文名各最多 255 字符，标签最多 512 字符；另加固定系统指令和协议所需的模型名/输出格式/Token 上限。绝不序列化整个 ORM 实体或 Settings，不发送数据库路径、站点评分、播放/封面/来源 URL、简介、播出时间、提醒、日期或其他用户配置。Key 仅放在 Authorization Header，不放入提示词。

所有已看完作品（包括未评分、未发送的旧历史），以及 `watched_episodes > 0` 的作品，其标题和中文名仅在本地用于排除推荐，**不会因此扩大外发历史集**。只做 SELECT，使用 `no_autoflush`，不 flush/commit 或修改调用方未保存对象。

## Provider 与临时 Key

| 模式 | 临时 `api_key` 归属 | 失败行为 |
| --- | --- | --- |
| `auto` | 仅覆盖本次千问 Key | 千问失败后，只在 DeepSeek 有配置 Key 时尝试一次 DeepSeek |
| `qwen` | 仅覆盖本次千问 Key | 失败不切换 |
| `deepseek` | 仅覆盖本次 DeepSeek Key | 失败不切换 |

通过 `get_settings()` 读取 `dashscope_api_key` / `deepseek_api_key` 的 `SecretStr.get_secret_value()`；模型读取 `qwen_model` / `deepseek_model`。临时 Key 为 `None` 才使用配置 Key；显式传空/纯空白 Key 表示本次不使用该 provider，不悄悄恢复配置 Key。无 Key 的 provider 不请求。临时 Key 不写回 Settings、数据库、文件或模块缓存；Python 不保证对临时字符串做密码学级内存擦除。

只访问固定官方 HTTPS endpoint：

- 千问：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- DeepSeek：`https://api.deepseek.com/chat/completions`

禁用 HTTP 重定向，不接受任意 base URL，不请求模型产生的 URL。默认自建 `requests.Session` 关闭环境代理/`.netrc` 继承，维持默认 TLS 验证，调用结束即关闭。注入 Session 由调用方所有，不关闭或修改；生产调用方不能为它配置隐式重试、不安全 TLS、重定向钩子或非预期代理。

每个 provider 最多一个 POST，连接/读超时为 5/30 秒；这是 requests 的连接/读取超时，不是整次操作的绝对时限。自动回退可能产生第二笔请求/费用，失败请求也可能计费，不保证免费。不做隐藏重试或额外的「修复 JSON」付费调用。

## 官方协议核对与模型限制

已阅读 Web 参考 `web/src/lib/ai/{recommend,config,client}.ts`，并在 2026-10-15 核对供应商官方文档：

- [阿里云 Chat Completions 主文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)：`model`、`messages`、`stream`、`max_tokens`、`response_format` 和 HTTP 顶层 `enable_thinking`。文档说明原 `dashscope.aliyuncs.com` 域名仍可正常使用，业务空间新域名迁移不在本次写集。
- [阿里云结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)：提示词包含 JSON，指定 `response_format={"type":"json_object"}`；`qwen-flash` 非思考模式示例使用 `enable_thinking=false`。默认 qwen-flash 使用当前仍支持的 `max_tokens=2048`，不照搬仅适用于较新型号的 `max_completion_tokens`。
- [DeepSeek Chat Completions 主文档](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)：固定 endpoint、Bearer 认证、非流式 JSON 模式、`max_tokens`。供应商的 `thinking` 默认 enabled，本服务明确发送 `thinking={"type":"disabled"}`，让 2048 Token 输出预算用于结构化推荐；仅解析 `choices[0].message.content`，不使用 reasoning/tool calls。

**当前选择：**主 agent 已核对官方模型 `deepseek-flash` / `deepseek-v4-pro`，并将共享配置和 `.env.example` 默认值更新为 `deepseek-flash`；本服务原样尊重配置，不暗中更换模型。推荐请求默认非思考：显式选择 DeepSeek、自动模式仅有 DeepSeek Key、千问失败回退到 DeepSeek，均设置 `thinking={"type":"disabled"}` 并保留 `max_tokens=2048`。已用离线模拟验证默认模型和自定义 `deepseek-v4-pro`，**仍需用户使用真实 Key 验收服务可用性与推荐效果**；本任务没有执行真实 AI 调用，也不会为探测模型发额外请求。

## 输出与错误处理

- `json.loads` 拒绝 Python dict repr、JSONP、拼接说明、重复键、NaN/Infinity、错误结构；可兼容单个完整 JSON 代码围栏，不从任意正文抽取 JSON。
- 校验非空标题、理由、文本搜索词，拒绝数字 ID 搜索词；搜索词缺省时使用标题。旧 Web `titleCn` / `title_cn` 仅帮助本地去重，不作为新返回字段。
- NFKC、大小写、空白/标点正规化后，按标题、搜索词和已知别名去重/排除已看；最多 5 条。文字含 URL、协议链接、域名或所用 Key 回显的条目不返回。额外 `url` / `play_url` / `id` 字段忽略，不请求、不输出。
- 认证/权限、余额不足、限流、超时、网络失败、重定向、响应截断/过滤/工具调用、无效 JSON、空结果、去重后无结果，在 `auto` 中均可触发下一有 Key 的 provider；显式 provider 绝不切换。
- 不同译名和作品真实身份不能仅靠文字正规化完全确认，仍须用户之后用 Bangumi 查证。

## 离线测试

从仓库根目录使用已有解释器；只给当前测试进程设置路径和内存数据库，不修改系统配置：

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath desktop).Path
$env:DATABASE_URL = 'sqlite:///:memory:'
& '.venv/Scripts/python.exe' -W error -m unittest discover -s desktop/tests -p test_recommendations.py -v
```

39 项推荐测试通过（含多个参数化子场景），新增 DeepSeek 两种官方模型在显式/自动直达/自动回退路径下关闭思考、保留 2048 Token 和 JSON 模式的离线断言。测试使用 SQLite 内存数据库、虚构 Key、模拟 Session/Response，并额外封锁真实 `requests.sessions.Session.request`。不读取正式用户数据，不调用真实 AI，不发生付费网络请求。覆盖历史白名单/50 条上限/0 分/站点评分隔离、Key 隔离、回退/显式模式、脱敏错误、JSON/URL/ID 防护、去重、数据库只读和会话生命周期。

同一环境下执行 `-m unittest discover -s desktop/tests -p 'test_*.py'`，当前工作区全量 201 项通过。回归包含其他 agent 的在途集成改动，仅代表本次运行时的工作区状态；本任务没有重跑打包、真实原生窗口检查或跨平台实机验证。
