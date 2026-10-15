/**
 * AI 推荐编排：读取"看完+评分"历史 → 组装 prompt → 调 AI → 解析并校验 JSON 输出。
 * 与 lib/db、lib/bangumi 相互独立：只依赖 client/config 与传入的历史数据。
 */
import { OpenAICompatibleClient } from "./client";
import { resolveAiConfigs, AiConfigError } from "./config";
import type { TrackingRecord } from "@/lib/db/tracking-repo";

export interface Recommendation {
  /** 推荐番剧名称（日文原名或通用名） */
  title: string;
  /** 中文名（如有） */
  titleCn: string | null;
  /** 推荐理由 */
  reason: string;
  /** 建议开播年份/季度（如有） */
  season: string | null;
}

export interface RecommendationResult {
  provider: "qwen" | "deepseek";
  model: string;
  items: Recommendation[];
}

/** 组装系统 + 用户消息：给定看过历史，要求输出 JSON 推荐列表 */
export function buildRecommendationMessages(
  history: TrackingRecord[],
): { role: "system" | "user"; content: string }[] {
  const lines = history.map(
    (r, i) =>
      `${i + 1}. 《${r.title_cn || r.title}》${r.rating != null ? `（评分 ${Number(r.rating).toFixed(1)}）` : ""}`,
  );

  const userContent = [
    "以下是我看过的动画（含我的评分）：",
    lines.join("\n") || "（暂无看过记录）",
    "",
    "请根据我的口味推荐 5 部我可能会喜欢的动画（优先近两三年的新作）。",
    "要求：",
    "1. 只输出 JSON，不要任何额外文字或代码块标记；",
    "2. JSON 格式为 {\"recommendations\": [{\"title\": \"日文原名或通用名\", \"titleCn\": \"中文名\", \"reason\": \"推荐理由（1-2句，结合我的口味）\", \"season\": \"年份季度，如 2026年1月，未知则 null\"}]}；",
    "3. 每条的 title 必填，reason 必填；",
    "4. 只推荐真实存在、你能确定的动画；不确定的标题不要编造，不确定的播出时间写 null。",
  ].join("\n");

  return [
    {
      role: "system",
      content:
        "你是一名了解日本动画（含中日欧美动画）的资深动画推荐人，擅长根据观众的历史评分推荐符合其口味的作品。你只输出严格的 JSON。",
    },
    { role: "user", content: userContent },
  ];
}

/** 从模型输出中提取 JSON 并校验（容忍 markdown 代码块包裹与前后杂音） */
export function parseRecommendations(text: string): Recommendation[] {
  const cleaned = text
    .replace(/```json/gi, "")
    .replace(/```/g, "")
    .trim();
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) {
    throw new Error("AI 输出不是合法 JSON");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(cleaned.slice(start, end + 1));
  } catch {
    throw new Error("AI 输出 JSON 解析失败");
  }
  const list = (parsed as { recommendations?: unknown }).recommendations;
  if (!Array.isArray(list)) {
    throw new Error("AI 输出缺少 recommendations 数组");
  }
  return list.map((item): Recommendation => {
    const raw = (item ?? {}) as Record<string, unknown>;
    const title = typeof raw.title === "string" ? raw.title.trim() : "";
    if (!title) throw new Error("AI 输出的某条推荐缺少 title");
    const reason = typeof raw.reason === "string" ? raw.reason.trim() : "";
    return {
      title,
      titleCn:
        typeof raw.titleCn === "string" && raw.titleCn.trim()
          ? raw.titleCn.trim()
          : null,
      reason,
      season:
        typeof raw.season === "string" && raw.season.trim()
          ? raw.season.trim()
          : null,
    };
  });
}

/**
 * 获取 AI 推荐：按「千问优先、DeepSeek 兜底」依次尝试 provider。
 * 前一 provider 失败（额度/网络/限流等）自动切换下一个；全部失败抛错。
 * @param history 看过+评分历史（通常来自 getCompletedHistory）
 * @param clientOverride 测试注入客户端（传入时跳过 provider 遍历，仅用第一个配置）
 */
export async function getRecommendations(
  history: TrackingRecord[],
  clientOverride?: OpenAICompatibleClient,
): Promise<RecommendationResult> {
  const messages = buildRecommendationMessages(history);
  const candidates = resolveAiConfigs();
  if (candidates.length === 0) {
    throw new AiConfigError(
      "未配置 AI API Key：请在 .env.local 中填写 DASHSCOPE_API_KEY（千问）或 DEEPSEEK_API_KEY（DeepSeek）",
    );
  }

  if (clientOverride) {
    const config = candidates[0];
    const content = await clientOverride.chat(messages, { expectedJson: true });
    return {
      provider: config.name,
      model: config.model,
      items: parseRecommendations(content),
    };
  }

  let lastError: Error | null = null;
  for (const config of candidates) {
    try {
      const client = new OpenAICompatibleClient({
        baseUrl: config.baseUrl,
        apiKey: process.env[config.apiKeyEnv] ?? "",
        model: config.model,
      });
      const content = await client.chat(messages, { expectedJson: true });
      const items = parseRecommendations(content);
      if (items.length === 0) throw new Error("AI 未返回任何推荐");
      return { provider: config.name, model: config.model, items };
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (candidates.length > 1) {
        console.warn(
          `[ai] ${config.name} 推荐失败，切换到下一 provider: ${(err as Error).message}`,
        );
      }
    }
  }
  throw lastError ?? new Error("AI 推荐失败");
}

export { AiConfigError };
