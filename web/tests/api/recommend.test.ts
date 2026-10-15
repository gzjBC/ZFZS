import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/recommend/route";

vi.mock("@/lib/ai/recommend", () => ({
  getRecommendations: vi.fn(),
}));
vi.mock("@/lib/ai/config", () => ({
  AiConfigError: class AiConfigError extends Error {
    constructor(message: string) {
      super(message);
      this.name = "AiConfigError";
    }
  },
}));
vi.mock("@/lib/db/tracking-repo", () => ({
  getCompletedHistory: vi.fn(),
}));
vi.mock("@/lib/db/pool", () => ({
  getPool: vi.fn(() => ({})),
}));

import { getCompletedHistory } from "@/lib/db/tracking-repo";
import { getRecommendations } from "@/lib/ai/recommend";

const mockedHistory = vi.mocked(getCompletedHistory);
const mockedRecommend = vi.mocked(getRecommendations);

const record = { id: 1, title: "示例", status: "completed" as const };

beforeEach(() => {
  mockedHistory.mockReset();
  mockedRecommend.mockReset();
});

describe("GET /api/recommend", () => {
  it("无看过历史时返回 422 与提示", async () => {
    mockedHistory.mockResolvedValue([] as never);
    const res = await GET();
    expect(res.status).toBe(422);
    const body = await res.json();
    expect(body.error).toContain("看完");
  });

  it("成功返回推荐与 provider", async () => {
    mockedHistory.mockResolvedValue([record] as never);
    mockedRecommend.mockResolvedValue({
      provider: "qwen",
      model: "qwen-flash",
      items: [{ title: "K-On!", titleCn: "轻音少女", reason: "r", season: null }],
    });
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.provider).toBe("qwen");
    expect(body.items).toHaveLength(1);
  });

  it("未配置 API Key 时返回 503", async () => {
    mockedHistory.mockResolvedValue([record] as never);
    mockedRecommend.mockRejectedValue(
      new (await import("@/lib/ai/config")).AiConfigError("未配置 AI API Key"),
    );
    const res = await GET();
    expect(res.status).toBe(503);
  });

  it("AI 服务异常时返回 502", async () => {
    mockedHistory.mockResolvedValue([record] as never);
    mockedRecommend.mockRejectedValue(new Error("AI 服务请求超时"));
    const res = await GET();
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.error).toContain("AI 推荐生成失败");
  });

  it("读取历史失败时返回 500", async () => {
    mockedHistory.mockRejectedValue(new Error("db down"));
    const res = await GET();
    expect(res.status).toBe(500);
  });
});
