import { describe, expect, it } from "vitest";
import {
  formatCompletedDate,
  getStatusBadge,
  groupByQuarter,
  isStatusKey,
  quarterGroupLabel,
  STATUS_LABELS,
  toBangumiWeekday,
  weekdayLabel,
} from "@/lib/ui/status";

describe("STATUS_LABELS", () => {
  it("覆盖四种状态", () => {
    expect(Object.keys(STATUS_LABELS)).toEqual([
      "wish",
      "watching",
      "completed",
      "hold",
    ]);
  });

  it("isStatusKey 校验", () => {
    expect(isStatusKey("watching")).toBe(true);
    expect(isStatusKey("done")).toBe(false);
    expect(isStatusKey(null)).toBe(false);
  });
});

describe("getStatusBadge", () => {
  it("返回标签与配色", () => {
    const badge = getStatusBadge("watching");
    expect(badge.label).toBe("在看");
    expect(badge.bg).toBeTruthy();
    expect(badge.color).toBeTruthy();
    expect(badge.border).toBeTruthy();
  });

  it("四种状态标签映射正确", () => {
    expect(getStatusBadge("wish").label).toBe("想看");
    expect(getStatusBadge("completed").label).toBe("看完");
    expect(getStatusBadge("hold").label).toBe("搁置");
  });
});

describe("toBangumiWeekday", () => {
  it("周一 → 1，周日 → 7", () => {
    expect(toBangumiWeekday(new Date(2026, 8, 7))).toBe(1); // 2026-09-07 周一
    expect(toBangumiWeekday(new Date(2026, 8, 13))).toBe(7); // 2026-09-13 周日
    expect(toBangumiWeekday(new Date(2026, 8, 12))).toBe(6); // 2026-09-12 周六
  });
});

describe("formatCompletedDate", () => {
  it("Date 与 ISO 字符串均输出中文日期", () => {
    expect(formatCompletedDate(new Date(2026, 8, 8))).toBe("2026年9月8日");
    expect(formatCompletedDate("2026-01-10T00:00:00.000Z")).not.toBe("");
    expect(formatCompletedDate("2026-01-10T00:00:00.000Z")).toContain("2026年");
  });

  it("空值/无效值返回空串", () => {
    expect(formatCompletedDate(null)).toBe("");
    expect(formatCompletedDate(undefined)).toBe("");
    expect(formatCompletedDate("")).toBe("");
    expect(formatCompletedDate("not-a-date")).toBe("");
  });
});

describe("weekdayLabel", () => {
  it("1-7 → 周一至周日", () => {
    expect(weekdayLabel(1)).toBe("周一");
    expect(weekdayLabel(7)).toBe("周日");
    expect(weekdayLabel(3)).toBe("周三");
  });
});

describe("quarterGroupLabel", () => {
  it("季度起始月映射", () => {
    expect(quarterGroupLabel(1, 2026)).toBe("2026年1-3月");
    expect(quarterGroupLabel(4, 2026)).toBe("2026年4-6月");
    expect(quarterGroupLabel(7, 2026)).toBe("2026年7-9月");
    expect(quarterGroupLabel(12, 2026)).toBe("2026年10-12月");
  });
});

describe("groupByQuarter", () => {
  const rec = (id: number, completedAt: Date | string | null) => ({ id, completedAt });

  it("按完成时间每 3 个月分组，组间降序", () => {
    const groups = groupByQuarter([
      rec(1, new Date(2026, 6, 5)), // 2026-07
      rec(2, new Date(2026, 1, 10)), // 2026-02
      rec(3, new Date(2026, 10, 1)), // 2026-11
      rec(4, new Date(2026, 8, 20)), // 2026-09
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      "2026年10-12月",
      "2026年7-9月",
      "2026年1-3月",
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual([3]);
    expect(groups[1].items.map((i) => i.id)).toEqual([4, 1]); // 9月 在 7月 前
  });

  it("组内按完成时间降序", () => {
    const groups = groupByQuarter([
      rec(1, new Date(2026, 7, 1)),
      rec(2, new Date(2026, 8, 30)),
      rec(3, new Date(2026, 8, 2)),
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual([2, 3, 1]);
  });

  it("无完成时间的记录归入「完成时间未知」且放最后", () => {
    const groups = groupByQuarter([
      rec(1, null),
      rec(2, new Date(2026, 0, 1)),
      rec(3, null),
    ]);
    expect(groups[groups.length - 1].label).toBe("完成时间未知");
    expect(groups[groups.length - 1].items).toHaveLength(2);
  });

  it("兼容 ISO 字符串形态（API JSON 序列化后为字符串）", () => {
    const groups = groupByQuarter([
      rec(1, "2026-08-05T00:00:00.000Z"),
      rec(2, "2026-01-10T00:00:00.000Z"),
      rec(3, ""),
    ]);
    expect(groups[0].label).toBe("2026年7-9月");
    expect(groups[0].items.map((i) => i.id)).toEqual([1]);
    expect(groups[groups.length - 1].label).toBe("完成时间未知");
  });
});
