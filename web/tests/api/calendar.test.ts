import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/calendar/route";
import { resetCache } from "@/lib/cache";

// 接口层测试：mock 底层 lib，聚焦 route 自身的成功/失败/缓存行为
vi.mock("@/lib/bangumi/calendar", () => ({
  getCalendar: vi.fn(),
}));

import { getCalendar } from "@/lib/bangumi/calendar";

const mockedGetCalendar = vi.mocked(getCalendar);

const daysPayload = [{ weekday: { en: "Mon", cn: "一", ja: "月" }, items: [] }];

beforeEach(() => {
  resetCache();
  mockedGetCalendar.mockReset();
});

describe("GET /api/calendar", () => {
  it("成功：返回 200 与按星期分组的放送列表", async () => {
    mockedGetCalendar.mockResolvedValue(daysPayload as never);
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.days).toHaveLength(1);
    expect(body.days[0].items).toHaveLength(0);
  });

  it("异常：Bangumi 不可用时返回 502 与错误信息", async () => {
    mockedGetCalendar.mockRejectedValue(new Error("bangumi down"));
    const res = await GET();
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(body.error).toBeTruthy();
  });

  it("缓存：6h 内重复调用只向底层请求一次", async () => {
    mockedGetCalendar.mockResolvedValue(daysPayload as never);
    await GET();
    await GET();
    expect(mockedGetCalendar).toHaveBeenCalledTimes(1);
  });
});
