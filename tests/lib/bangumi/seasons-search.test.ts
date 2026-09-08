import { describe, expect, it, vi } from "vitest";
import { getSeasonAnime, getCurrentSeasonMonth } from "@/lib/bangumi/seasons";
import { searchSubjects } from "@/lib/bangumi/search";
import { BangumiClient } from "@/lib/bangumi/client";
import type { FetchLike } from "@/lib/bangumi/client";

function okFetch(body: unknown): FetchLike {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  }) as unknown as FetchLike;
}

describe("getSeasonAnime", () => {
  it("按 year+month 请求并解析分页结构", async () => {
    const payload = { data: [{ id: 1, name: "x" }], total: 1, limit: 30, offset: 0 };
    const days = await getSeasonAnime(
      { year: 2026, month: 7 },
      new BangumiClient({ fetchImpl: okFetch(payload) }),
    );
    expect(days.data).toHaveLength(1);
    expect(days.total).toBe(1);
  });

  it("请求参数正确：air_date、sort、limit", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [], total: 0, limit: 30, offset: 0 }),
    }) as unknown as FetchLike;
    await getSeasonAnime(
      { year: 2026, month: 10, limit: 50, sort: "date", order: "asc" },
      new BangumiClient({ fetchImpl }),
    );
    const [url] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("/v0/subjects?");
    expect(url).toContain("type=2");
    expect(url).toContain("year=2026");
    expect(url).toContain("month=10");
    expect(url).toContain("sort=date");
    expect(url).toContain("order=asc");
    expect(url).toContain("limit=50");
  });

  it("year/month 直接传数字参数", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [], total: 0 }),
    }) as unknown as FetchLike;
    await getSeasonAnime({ year: 2026, month: 1 }, new BangumiClient({ fetchImpl }));
    const [url] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("year=2026");
    expect(url).toContain("month=1");
  });
});

describe("getCurrentSeasonMonth", () => {
  it.each([
    [new Date("2026-01-15"), 1],
    [new Date("2026-04-01"), 4],
    [new Date("2026-09-30"), 7],
    [new Date("2026-10-01"), 10],
    [new Date("2026-12-31"), 10],
  ])("%s → %s", (d, expected) => {
    expect(getCurrentSeasonMonth(d as Date)).toBe(expected);
  });
});

describe("searchSubjects", () => {
  it("POST 到搜索接口，body 限定动画类型", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [], total: 0 }),
    }) as unknown as FetchLike;
    await searchSubjects({ keyword: "进击的巨人" }, new BangumiClient({ fetchImpl }));
    const [url, init] = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("https://api.bgm.tv/v0/search/subjects");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.keyword).toBe("进击的巨人");
    expect(body.filter.type).toEqual([2]);
    expect(body.limit).toBe(20);
  });
});
