import { describe, expect, it } from "vitest";
import { buildTodayFeed } from "@/lib/ui/feed";
import type { CalendarDay, Subject } from "@/lib/bangumi/types";
import type { TrackingRecord } from "@/lib/db/tracking-repo";

const subject = (id: number, score = 0): Subject =>
  ({
    id,
    url: `https://bgm.tv/subject/${id}`,
    type: 2,
    name: `Title ${id}`,
    name_cn: `标题 ${id}`,
    summary: "",
    air_date: "2026-09-08",
    air_weekday: 2,
    images: {} as Subject["images"],
    eps: 0,
    eps_count: 0,
    rank: 0,
    rating: { total: 0, count: {}, score },
  }) as Subject;

const day = (weekdayId: number, items: Subject[]): CalendarDay => ({
  weekday: { en: String(weekdayId), cn: String(weekdayId), ja: String(weekdayId), id: weekdayId },
  items,
});

const tracking = (bangumi_subject_id: number, status: string): TrackingRecord =>
  ({
    id: bangumi_subject_id,
    bangumi_subject_id,
    title: `Title ${bangumi_subject_id}`,
    title_cn: `标题 ${bangumi_subject_id}`,
    cover_url: null,
    summary: null,
    status: status as TrackingRecord["status"],
    episode_progress: 0,
    total_episodes: 12,
    rating: null,
    air_date: null,
    tags: [],
    completed_at: null,
    created_at: new Date(),
    updated_at: new Date(),
  }) as TrackingRecord;

describe("buildTodayFeed", () => {
  const days = [
    day(2, [subject(1, 8.0), subject(2, 7.0)]), // 今天（周二）
    day(3, [subject(3, 9.0)]), // 明天
    day(6, [subject(4, 6.0)]), // 周六
  ];

  it("今天播的「在看/想看」进 today，其他天「在看」进 week", () => {
    const feed = buildTodayFeed(
      days,
      [
        tracking(1, "watching"),
        tracking(2, "wish"),
        tracking(3, "watching"), // 明天播
        tracking(4, "hold"), // 周六播但搁置，不出现
      ],
      2,
    );
    expect(feed.today.map((i) => i.subject.id)).toEqual([1, 2]);
    expect(feed.week.map((i) => i.subject.id)).toEqual([3]);
  });

  it("today 按评分降序", () => {
    const feed = buildTodayFeed(
      [day(2, [subject(1, 6.0), subject(2, 9.0)])],
      [tracking(1, "watching"), tracking(2, "watching")],
      2,
    );
    expect(feed.today.map((i) => i.subject.id)).toEqual([2, 1]);
  });

  it("completed / 不在清单的番不出现", () => {
    const feed = buildTodayFeed(
      days,
      [tracking(1, "completed"), tracking(3, "completed")],
      2,
    );
    expect(feed.today).toHaveLength(0);
    expect(feed.week).toHaveLength(0);
  });

  it("空清单返回空结果", () => {
    const feed = buildTodayFeed(days, [], 2);
    expect(feed.today).toHaveLength(0);
    expect(feed.week).toHaveLength(0);
  });
});
