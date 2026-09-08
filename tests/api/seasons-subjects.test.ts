import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as GET_SEASONS } from "@/app/api/seasons/route";
import { GET as GET_SUBJECTS } from "@/app/api/subjects/route";
import { resetCache } from "@/lib/cache";

vi.mock("@/lib/bangumi/seasons", () => ({
  getCurrentSeasonMonth: vi.fn(() => 10),
  getSeasonAnime: vi.fn(),
}));
vi.mock("@/lib/bangumi/search", () => ({
  searchSubjects: vi.fn(),
}));

import { getSeasonAnime } from "@/lib/bangumi/seasons";
import { searchSubjects } from "@/lib/bangumi/search";

const mockedSeason = vi.mocked(getSeasonAnime);
const mockedSearch = vi.mocked(searchSubjects);

const seasonPayload = { data: [{ id: 1, name: "x" }], total: 1, limit: 30, offset: 0 };

beforeEach(() => {
  resetCache();
  mockedSeason.mockReset();
  mockedSearch.mockReset();
});

describe("GET /api/seasons", () => {
  it("不传参数时使用默认当前季度（2026-10）", async () => {
    mockedSeason.mockResolvedValue(seasonPayload as never);
    const res = await GET_SEASONS(new Request("http://localhost/api/seasons"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toHaveLength(1);
    expect(body.total).toBe(1);
    expect(mockedSeason).toHaveBeenCalledWith({ year: 2026, month: 10 });
  });

  it("显式传 year/month 透传", async () => {
    mockedSeason.mockResolvedValue(seasonPayload as never);
    const res = await GET_SEASONS(new Request("http://localhost/api/seasons?year=2026&month=7"));
    expect(res.status).toBe(200);
    expect(mockedSeason).toHaveBeenCalledWith({ year: 2026, month: 7 });
  });

  it("非法 month 返回 400", async () => {
    const res = await GET_SEASONS(new Request("http://localhost/api/seasons?month=3"));
    expect(res.status).toBe(400);
  });

  it("异常返回 502", async () => {
    mockedSeason.mockRejectedValue(new Error("down"));
    const res = await GET_SEASONS(new Request("http://localhost/api/seasons"));
    expect(res.status).toBe(502);
  });
});

describe("GET /api/subjects", () => {
  it("缺少 q 返回 400", async () => {
    const res = await GET_SUBJECTS(new Request("http://localhost/api/subjects"));
    expect(res.status).toBe(400);
  });

  it("搜索关键词透传并返回结果", async () => {
    mockedSearch.mockResolvedValue(seasonPayload as never);
    const res = await GET_SUBJECTS(
      new Request("http://localhost/api/subjects?q=%E8%BF%9B%E5%87%BB"),
    );
    expect(res.status).toBe(200);
    expect(mockedSearch).toHaveBeenCalledWith({ keyword: "进击" });
    const body = await res.json();
    expect(body.total).toBe(1);
  });

  it("异常返回 502", async () => {
    mockedSearch.mockRejectedValue(new Error("down"));
    const res = await GET_SUBJECTS(new Request("http://localhost/api/subjects?q=x"));
    expect(res.status).toBe(502);
  });
});
