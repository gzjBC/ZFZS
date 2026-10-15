/**
 * Bangumi HTTP 客户端：统一处理 baseUrl、User-Agent、错误与超时。
 * 支持通过 HTTPS_PROXY / HTTP_PROXY 环境变量走代理（梯子/公司代理）。
 * 使用 undici 自带 fetch（Node 全局 fetch 无法透传代理 dispatcher）。
 * 本模块无框架依赖；测试通过注入 fetchImpl 模拟网络，不打真实请求。
 */
import { fetch as undiciFetch, ProxyAgent } from "undici";
import type { Dispatcher } from "undici";

export const BANGUMI_BASE_URL = "https://api.bgm.tv";

export class BangumiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "BangumiError";
  }
}

export interface BangumiClientOptions {
  baseUrl?: string;
  userAgent?: string;
  /** 请求超时（毫秒），默认 10s */
  timeoutMs?: number;
  /** 代理地址，如 http://127.0.0.1:7892；不传则读 HTTPS_PROXY/HTTP_PROXY 环境变量 */
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

export class BangumiClient {
  private readonly baseUrl: string;
  private readonly userAgent: string;
  private readonly timeoutMs: number;
  private readonly dispatcher: Dispatcher | undefined;
  private readonly fetchImpl: FetchLike;

  constructor(opts: BangumiClientOptions = {}) {
    this.baseUrl = opts.baseUrl ?? BANGUMI_BASE_URL;
    this.userAgent = opts.userAgent ?? process.env.BANGUMI_USER_AGENT ?? "anime-tracker/0.1 (local)";
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    const proxy =
      opts.proxy ??
      process.env.HTTPS_PROXY ??
      process.env.https_proxy ??
      process.env.HTTP_PROXY ??
      process.env.http_proxy;
    this.dispatcher = proxy ? resolveProxyAgent(proxy) : undefined;
    this.fetchImpl = opts.fetchImpl ?? (undiciFetch as unknown as FetchLike);
  }

  async getJson<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  async postJson<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const init: RequestInit & { dispatcher?: Dispatcher } = {
        method,
        headers: {
          "User-Agent": this.userAgent,
          Accept: "application/json",
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        signal: controller.signal,
      };
      if (body !== undefined) {
        init.body = JSON.stringify(body);
      }
      if (this.dispatcher) {
        init.dispatcher = this.dispatcher;
      }
      const res = await this.fetchImpl(`${this.baseUrl}${path}`, init);
      if (!res.ok) {
        throw new BangumiError(`Bangumi API 请求失败 ${res.status}: ${path}`, res.status);
      }
      return (await res.json()) as T;
    } catch (err) {
      if (err instanceof BangumiError) throw err;
      const msg =
        err instanceof Error && err.name === "AbortError"
          ? "Bangumi API 请求超时"
          : `Bangumi API 请求异常: ${(err as Error).message}`;
      throw new BangumiError(msg);
    } finally {
      clearTimeout(timer);
    }
  }
}
