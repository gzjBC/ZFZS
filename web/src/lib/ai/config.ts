/**
 * AI Provider 配置与选择：
 * - 千问优先（阿里云百炼 OpenAI 兼容），DeepSeek 兜底；
 * - resolveAiConfigs() 返回「可用且有序」的候选列表（千问在前）；
 * - 全部未配置时抛 AiConfigError（由 route 层转为可读错误）。
 */
export interface AiProviderConfig {
  name: "qwen" | "deepseek";
  baseUrl: string;
  model: string;
  apiKeyEnv: string;
}

export class AiConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AiConfigError";
  }
}

const QWEN: AiProviderConfig = {
  name: "qwen",
  baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  model: process.env.QWEN_MODEL ?? "qwen-flash", // 千问最便宜档
  apiKeyEnv: "DASHSCOPE_API_KEY",
};

const DEEPSEEK: AiProviderConfig = {
  name: "deepseek",
  baseUrl: "https://api.deepseek.com",
  model: process.env.DEEPSEEK_MODEL ?? "deepseek-v4-flash", // DeepSeek 最便宜档
  apiKeyEnv: "DEEPSEEK_API_KEY",
};

/** 按「千问优先、DeepSeek 兜底」返回已配置 Key 的候选列表 */
export function resolveAiConfigs(): AiProviderConfig[] {
  const available: AiProviderConfig[] = [];
  if (process.env[QWEN.apiKeyEnv]) available.push(QWEN);
  if (process.env[DEEPSEEK.apiKeyEnv]) available.push(DEEPSEEK);
  return available;
}

/** 兼容入口：返回第一个可用 provider（等价于 resolveAiConfigs()[0]） */
export function resolveAiConfig(): AiProviderConfig {
  const list = resolveAiConfigs();
  if (list.length === 0) {
    throw new AiConfigError(
      "未配置 AI API Key：请在 .env.local 中填写 DASHSCOPE_API_KEY（千问）或 DEEPSEEK_API_KEY（DeepSeek）",
    );
  }
  return list[0];
}
