import { afterEach, describe, expect, it, vi } from "vitest";
import { getCalendar } from "@/lib/bangumi/calendar";
import { BangumiClient, BangumiError } from "@/lib/bangumi/client";
import type { FetchLike } from "@/lib/bangumi/client";

const calendarPayload = [
  {
    weekday: { en: "Mon", cn: "一", ja: "月", id: 1 },
    items: [
      {
        id: 12,
        url: "https://bgm.tv/subject/12",
        type: 2,
        name: "サンプル",
        name_cn: "示例番",
        summary: "简介",
        air_date: "2026-07-01",
        air_weekday: 1,
        images: { large: "", common: "", medium: "", small: "", grid: "" },
        eps: 12,
        eps_count: 12,
        rank: 123,
        rating: { total: 456, count: { "1": 1 }, score: 7.8 },
      },
    ],
  },
];

function mockFetchOnce(status: number, body: unknown): FetchLike {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as FetchLike;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("getCalendar", () => {
  it("正常：请求 /calendar 并解析为按星期分组的列表", async () => {
    const days = await getCalendar(new BangumiClient({ fetchImpl: mockFetchOnce(200, calendarPayload) }));
    expect(days).toHaveLength(1);
    expect(days[0].weekday.cn).toBe("一");
    expect(days[0].items[0].name_cn).toBe("示例番");
    expect(days[0].items[0].rating.score).toBe(7.8);
  });

  it("正常：请求携带 User-Agent 与 baseUrl 正确", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    }) as unknown as FetchLike;

    await getCalendar(new BangumiClient({ userAgent: "anime-tracker/0.1 (test)", fetchImpl }));
    const [url, init] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.bgm.tv/calendar");
    expect(init.headers).toMatchObject({ "User-Agent": "anime-tracker/0.1 (test)" });
  });

  it("边界：非 2xx 抛出 BangumiError 并带状态码", async () => {
    await expect(getCalendar(new BangumiClient({ fetchImpl: mockFetchOnce(429, {}) }))).rejects.toMatchObject({
      name: "BangumiError",
      status: 429,
    });
  });

  it("异常：网络失败包装为 BangumiError", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("ENOTFOUND")) as unknown as FetchLike;
    await expect(getCalendar(new BangumiClient({ fetchImpl }))).rejects.toBeInstanceOf(BangumiError);
  });

  it("异常：请求超时触发 abort 并报超时", async () => {
    const fetchImpl = ((
      _url: string,
      init?: RequestInit,
    ) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const e = new Error("The operation was aborted.");
          e.name = "AbortError";
          reject(e);
        });
      })) as unknown as FetchLike;
    const client = new BangumiClient({ timeoutMs: 1, fetchImpl });
    await expect(getCalendar(client)).rejects.toMatchObject({
      name: "BangumiError",
      message: "Bangumi API 请求超时",
    });
  });
});
