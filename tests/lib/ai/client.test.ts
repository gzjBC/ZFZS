import { describe, expect, it, vi } from "vitest";
import { OpenAICompatibleClient, AiClientError } from "@/lib/ai/client";
import type { FetchLike } from "@/lib/ai/client";

function okFetch(payload: unknown): FetchLike {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  }) as unknown as FetchLike;
}

function errFetch(status: number): FetchLike {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: async () => ({}),
  }) as unknown as FetchLike;
}

describe("OpenAICompatibleClient", () => {
  it("POST 到 {baseUrl}/chat/completions，带 Bearer 与 model/messages", async () => {
    const fetchImpl = okFetch({ choices: [{ message: { content: "你好" } }] });
    const client = new OpenAICompatibleClient({
      baseUrl: "https://api.example.com/v1/",
      apiKey: "sk-test",
      model: "m1",
      fetchImpl,
    });
    const text = await client.chat([
      { role: "system", content: "sys" },
      { role: "user", content: "hi" },
    ]);
    expect(text).toBe("你好");
    const [url, init] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { headers: Record<string, string>; body: string },
    ];
    expect(url).toBe("https://api.example.com/v1/chat/completions");
    expect(init.headers.Authorization).toBe("Bearer sk-test");
    const body = JSON.parse(init.body);
    expect(body.model).toBe("m1");
    expect(body.messages).toHaveLength(2);
  });

  it("expectedJson 时附带 response_format", async () => {
    const fetchImpl = okFetch({ choices: [{ message: { content: "{}" } }] });
    const client = new OpenAICompatibleClient({
      baseUrl: "https://api.example.com",
      apiKey: "sk-test",
      model: "m1",
      fetchImpl,
    });
    await client.chat([{ role: "user", content: "x" }], { expectedJson: true });
    const [, init] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { body: string },
    ];
    const body = JSON.parse(init.body);
    expect(body.response_format).toEqual({ type: "json_object" });
  });

  it("非 2xx 抛 AiClientError 且带状态码", async () => {
    const client = new OpenAICompatibleClient({
      baseUrl: "https://api.example.com",
      apiKey: "sk-test",
      model: "m1",
      fetchImpl: errFetch(401),
    });
    await expect(client.chat([{ role: "user", content: "x" }])).rejects.toThrow(AiClientError);
    await expect(client.chat([{ role: "user", content: "x" }])).rejects.toMatchObject({
      status: 401,
    });
  });

  it("choices 为空时抛 AiClientError", async () => {
    const client = new OpenAICompatibleClient({
      baseUrl: "https://api.example.com",
      apiKey: "sk-test",
      model: "m1",
      fetchImpl: okFetch({ choices: [] }),
    });
    await expect(client.chat([{ role: "user", content: "x" }])).rejects.toThrow(
      "AI 服务返回空响应",
    );
  });
});
