import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildRecommendationMessages,
  getRecommendations,
  parseRecommendations,
} from "@/lib/ai/recommend";
import { AiConfigError } from "@/lib/ai/config";
import { OpenAICompatibleClient } from "@/lib/ai/client";
import type { TrackingRecord } from "@/lib/db/tracking-repo";

/** fallback 测试用的可编程假客户端：按队列逐个消费 chat 调用 */
const aiMockState = vi.hoisted(() => ({
  queue: [] as ((model: string) => Promise<string>)[],
}));

vi.mock("@/lib/ai/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/ai/client")>();
  return {
    ...actual,
    OpenAICompatibleClient: class {
      private model: string;
      constructor(opts: { model: string }) {
        this.model = opts.model;
      }
      chat(): Promise<string> {
        const handler = aiMockState.queue.shift();
        if (!handler) throw new Error("测试队列为空");
        return handler(this.model);
      }
    },
  };
});

const history: TrackingRecord[] = [
  {
    id: 1,
    bangumi_subject_id: 1,
    title: "Bocchi the Rock!",
    title_cn: "孤独摇滚！",
    cover_url: null,
    summary: null,
    status: "completed",
    episode_progress: 12,
    total_episodes: 12,
    rating: 9.5,
    air_date: "2022-10-08",
    tags: [],
    completed_at: null,
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 2,
    bangumi_subject_id: 2,
    title: "Shirobako",
    title_cn: "白箱",
    cover_url: null,
    summary: null,
    status: "completed",
    episode_progress: 24,
    total_episodes: 24,
    rating: null,
    air_date: "2014-10-09",
    tags: [],
    completed_at: null,
    created_at: new Date(),
    updated_at: new Date(),
  },
];

describe("buildRecommendationMessages", () => {
  it("包含系统角色与看过历史的标题+评分", () => {
    const messages = buildRecommendationMessages(history);
    expect(messages[0].role).toBe("system");
    const user = messages[1].content;
    expect(user).toContain("孤独摇滚！");
    expect(user).toContain("9.5");
    expect(user).toContain("白箱");
    expect(user).toContain("5 部");
  });

  it("空历史时给出提示占位", () => {
    const messages = buildRecommendationMessages([]);
    expect(messages[1].content).toContain("暂无看过记录");
  });
});

describe("parseRecommendations", () => {
  const valid =
    '{"recommendations":[{"title":"K-On!","titleCn":"轻音少女","reason":"喜欢日常音乐番必看","season":"2009年4月"}]}';

  it("解析合法 JSON", () => {
    const items = parseRecommendations(valid);
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("K-On!");
    expect(items[0].titleCn).toBe("轻音少女");
    expect(items[0].reason).toContain("日常音乐");
    expect(items[0].season).toBe("2009年4月");
  });

  it("容忍 markdown 代码块包裹", () => {
    const items = parseRecommendations("```json\n" + valid + "\n```");
    expect(items).toHaveLength(1);
  });

  it("title 缺失时抛错", () => {
    expect(() =>
      parseRecommendations('{"recommendations":[{"reason":"x"}]}'),
    ).toThrow("缺少 title");
  });

  it("缺少 recommendations 数组时抛错", () => {
    expect(() => parseRecommendations('{"foo":1}')).toThrow("recommendations");
  });

  it("非 JSON 输出抛错", () => {
    expect(() => parseRecommendations("我推荐以下几部：")).toThrow("JSON");
  });
});

describe("getRecommendations", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  function mockClient(content: string): OpenAICompatibleClient {
    return {
      chat: vi.fn().mockResolvedValue(content),
    } as unknown as OpenAICompatibleClient;
  }

  it("配置千问 Key 时优先使用千问 provider", async () => {
    process.env.DASHSCOPE_API_KEY = "sk-qwen";
    delete process.env.DEEPSEEK_API_KEY;
    const client = mockClient(
      '{"recommendations":[{"title":"A","reason":"r","season":null}]}',
    );
    const result = await getRecommendations(history, client);
    expect(result.provider).toBe("qwen");
    expect(result.model).toContain("qwen");
    expect(result.items).toHaveLength(1);
  });

  it("无千问 Key 时回退 DeepSeek", async () => {
    delete process.env.DASHSCOPE_API_KEY;
    process.env.DEEPSEEK_API_KEY = "sk-ds";
    const client = mockClient('{"recommendations":[{"title":"B","reason":"r"}]}');
    const result = await getRecommendations(history, client);
    expect(result.provider).toBe("deepseek");
  });

  it("两个 Key 都没有时抛 AiConfigError", async () => {
    delete process.env.DASHSCOPE_API_KEY;
    delete process.env.DEEPSEEK_API_KEY;
    await expect(getRecommendations(history)).rejects.toThrow(AiConfigError);
  });

  it("AI 输出解析失败时抛出错误（不静默返回空）", async () => {
    process.env.DASHSCOPE_API_KEY = "sk-qwen";
    const client = mockClient("我不是 JSON");
    await expect(getRecommendations(history, client)).rejects.toThrow("JSON");
  });

  it("千问失败时自动回退 DeepSeek（真实双 Key 场景）", async () => {
    process.env.DASHSCOPE_API_KEY = "sk-qwen";
    process.env.DEEPSEEK_API_KEY = "sk-ds";
    aiMockState.queue = [
      (model) => {
        expect(model).toContain("qwen");
        return Promise.reject(new Error("余额不足"));
      },
      (model) => {
        expect(model).toContain("deepseek");
        return Promise.resolve(
          '{"recommendations":[{"title":"C","reason":"r"}]}',
        );
      },
    ];
    const result = await getRecommendations(history);
    expect(result.provider).toBe("deepseek");
    expect(result.items).toHaveLength(1);
  });

  it("所有 provider 都失败时抛出最后一个错误", async () => {
    process.env.DASHSCOPE_API_KEY = "sk-qwen";
    process.env.DEEPSEEK_API_KEY = "sk-ds";
    aiMockState.queue = [
      () => Promise.reject(new Error("千问超时")),
      () => Promise.reject(new Error("DeepSeek 限流")),
    ];
    await expect(getRecommendations(history)).rejects.toThrow("DeepSeek 限流");
  });
});
