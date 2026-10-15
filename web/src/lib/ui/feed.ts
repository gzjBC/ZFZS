/**
 * 首页「今日更新」联动逻辑：把追番清单与本周放送日历合并，
 * 找出"我追的番里今天播什么、本周播什么"，懒人打开首页就知道该看啥。
 * 纯函数：日历/清单/today 均为入参，可单测。
 */
import type { CalendarDay, Subject } from "@/lib/bangumi/types";
import type { TrackingRecord } from "@/lib/db/tracking-repo";

export type FeedStatus = "watching" | "wish" | "hold" | "completed";

export interface FeedItem {
  subject: Subject;
  /** 该番在清单中的状态（仅 watching/wish 会进今日，watching 会进本周） */
  status: FeedStatus;
}

export interface TodayFeed {
  /** 今天放送、且在我的清单里（在看或想看）的番 */
  today: FeedItem[];
  /** 本周其他天放送、我在看的番（不含今天） */
  week: FeedItem[];
}

const DAY_PRIORITY: Record<FeedStatus, number> = {
  watching: 0,
  wish: 1,
  hold: 2,
  completed: 3,
};

export function buildTodayFeed(
  days: CalendarDay[],
  tracking: TrackingRecord[],
  todayWeekday: number,
): TodayFeed {
  const statusBySubjectId = new Map<number, FeedStatus>();
  for (const record of tracking) {
    statusBySubjectId.set(record.bangumi_subject_id, record.status as FeedStatus);
  }

  const today: FeedItem[] = [];
  const week: FeedItem[] = [];

  for (const day of days) {
    for (const subject of day.items) {
      const status = statusBySubjectId.get(subject.id);
      if (!status) continue; // 不在我的清单里
      if (day.weekday.id === todayWeekday) {
        if (status === "watching" || status === "wish") {
          today.push({ subject, status });
        }
      } else if (status === "watching") {
        week.push({ subject, status });
      }
    }
  }

  const byScore = (a: FeedItem, b: FeedItem) => {
    const diff = (b.subject.rating?.score ?? 0) - (a.subject.rating?.score ?? 0);
    return diff !== 0 ? diff : DAY_PRIORITY[a.status] - DAY_PRIORITY[b.status];
  };

  return {
    today: today.sort(byScore),
    week: week.sort(byScore),
  };
}
