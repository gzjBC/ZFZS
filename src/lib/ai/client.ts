/**
 * OpenAI 兼容 HTTP 客户端：供千问/DeepSeek 等兼容服务共用。
 * - 统一处理 baseUrl、apiKey、超时与错误；
 * - 支持通过 HTTPS_PROXY / HTTP_PROXY 环境变量走代理（与 BangumiClient 同模式）；
 * - 使用 undici 自带 fetch（Node 全局 fetch 无法透传代理 dispatcher）；
 * - fetch 依赖注入，测试不打真实网络。
 */
import { fetch as undiciFetch, ProxyAgent } from "undici";
import type { Dispatcher } from "undici";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export class AiClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "AiClientError";
  }
}

export interface OpenAICompatibleClientOptions {
  baseUrl: string;
  apiKey: string;
  model: string;
  /** 请求超时（毫秒），默认 30s（大模型生成较慢） */
  timeoutMs?: number;
  /** 代理地址；不传则读 HTTPS_PROXY/HTTP_PROXY 环境变量 */
  proxy?: string;
  /** 测试注入：模拟网络层，默认 undici fetch */
  fetchImpl?: FetchLike;
}

type FetchLike = (
  url: string,
  init: RequestInit & { dispatcher?: Dispatcher },
) => Promise<Response>;

export type { FetchLike };

/** 模块级代理单例，避免每个请求重复建连接池 */
let sharedProxyAgent: ProxyAgent | undefined;

function resolveProxyAgent(proxy: string): Dispatcher {
  if (!sharedProxyAgent) {
    sharedProxyAgent = new ProxyAgent(proxy);
  }
  return sharedProxyAgent;
}

export class OpenAICompatibleClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly timeoutMs: number;
  private readonly dispatcher: Dispatcher | undefined;
  private readonly fetchImpl: FetchLike;

  constructor(opts: OpenAICompatibleClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey;
    this.model = opts.model;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    const proxy =
      opts.proxy ??
      process.env.HTTPS_PROXY ??
      process.env.https_proxy ??
      process.env.HTTP_PROXY ??
      process.env.http_proxy;
    this.dispatcher = proxy ? resolveProxyAgent(proxy) : undefined;
    this.fetchImpl = opts.fetchImpl ?? (undiciFetch as unknown as FetchLike);
  }

  /**
   * 发送一轮对话，返回 assistant 的文本回复。
   * @param messages 对话消息（system/user/assistant 角色）
   * @param opts.expectedJson 要求模型按 JSON 输出（OpenAI 兼容的 response_format）
   */
  async chat(
    messages: ChatMessage[],
    opts: { expectedJson?: boolean } = {},
  ): Promise<string> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const init: RequestInit & { dispatcher?: Dispatcher } = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        signal: controller.signal,
      };
      const body: Record<string, unknown> = {
        model: this.model,
        messages,
      };
      if (opts.expectedJson) {
        body.response_format = { type: "json_object" };
      }
      init.body = JSON.stringify(body);
      if (this.dispatcher) {
        init.dispatcher = this.dispatcher;
      }
      const res = await this.fetchImpl(
        `${this.baseUrl}/chat/completions`,
        init,
      );
      if (!res.ok) {
        throw new AiClientError(
          `AI 服务请求失败 ${res.status}（${this.model}）`,
          res.status,
        );
      }
      const data = (await res.json()) as {
        choices?: { message?: { content?: string } }[];
      };
      const content = data.choices?.[0]?.message?.content;
      if (!content) {
        throw new AiClientError("AI 服务返回空响应");
      }
      return content;
    } catch (err) {
      if (err instanceof AiClientError) throw err;
      const msg =
        err instanceof Error && err.name === "AbortError"
          ? "AI 服务请求超时"
          : `AI 服务请求异常: ${(err as Error).message}`;
      throw new AiClientError(msg);
    } finally {
      clearTimeout(timer);
    }
  }
}
