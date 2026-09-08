/**
 * UI 展示辅助：追番状态标签与星期工具。
 * 纯函数、无框架依赖，供页面与组件复用（可单测）。
 */
export type StatusKey = "wish" | "watching" | "completed" | "hold";

export const STATUS_LABELS: Record<StatusKey, string> = {
  wish: "想看",
  watching: "在看",
  completed: "看完",
  hold: "搁置",
};

export function isStatusKey(value: unknown): value is StatusKey {
  return typeof value === "string" && value in STATUS_LABELS;
}

export interface StatusBadgeStyle {
  label: string;
  bg: string;
  border: string;
  color: string;
}

const BADGE_STYLES: Record<StatusKey, Omit<StatusBadgeStyle, "label">> = {
  wish: { bg: "#EFF6FF", border: "#BFDBFE", color: "#1D4ED8" },
  watching: { bg: "#F0FDF4", border: "#BBF7D0", color: "#15803D" },
  completed: { bg: "#FAF5FF", border: "#E9D5FF", color: "#7E22CE" },
  hold: { bg: "#F3F4F6", border: "#E5E7EB", color: "#4B5563" },
};

export function getStatusBadge(status: StatusKey): StatusBadgeStyle {
  return { label: STATUS_LABELS[status], ...BADGE_STYLES[status] };
}

/**
 * 将 JS Date 转换为 Bangumi 星期编号（1=周一 … 7=周日）。
 * Bangumi /calendar 的 weekday.id 即此编号。
 */
export function toBangumiWeekday(date: Date = new Date()): number {
  const day = date.getDay();
  return day === 0 ? 7 : day;
}

/** Bangumi 星期编号 → 中文（"周一"…"周日"） */
export function weekdayLabel(id: number): string {
  return `周${"一二三四五六日"[id - 1] ?? ""}`;
}

/** 完成时间 → 中文日期（兼容 Date 与 ISO 字符串；无效值返回空串） */
export function formatCompletedDate(value: Date | string | null | undefined): string {
  if (value == null || value === "") return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** 按看完时间每 3 个月分组的组标题，如 2026-04 → "2026年4-6月" */
export function quarterGroupLabel(month: number, year: number): string {
  const start = Math.floor((month - 1) / 3) * 3 + 1;
  return `${year}年${start}-${start + 2}月`;
}

export interface QuarterGroup<T> {
  /** 组所在季度起始月（1/4/7/10） */
  year: number;
  month: number;
  label: string;
  items: T[];
}

/**
 * 将「已看完」记录按完成时间每 3 个月（季度）分组，组内按完成时间降序。
 * 兼容 Date 与 ISO 字符串两种形态（API JSON 序列化后是字符串）。
 * 无完成时间的记录归入「完成时间未知」组（year/month 为 0）。
 */
export function groupByQuarter<T extends { completedAt: Date | string | null }>(
  records: T[],
): QuarterGroup<T>[] {
  const groups = new Map<string, QuarterGroup<T>>();
  for (const record of records) {
    const raw = record.completedAt;
    const date = raw == null || raw === "" ? null : new Date(raw);
    const valid = date && !Number.isNaN(date.getTime());
    const year = valid ? date.getFullYear() : 0;
    const month = valid ? Math.floor(date.getMonth() / 3) * 3 + 1 : 0; // 季度起始月
    const key = valid ? `${year}-${month}` : "unknown";
    if (!groups.has(key)) {
      groups.set(key, {
        year,
        month,
        label: valid ? quarterGroupLabel(month, year) : "完成时间未知",
        items: [],
      });
    }
    groups.get(key)!.items.push(record);
  }
  const list = Array.from(groups.values());
  // 有时间的组按时间降序排前，未知时间组放最后
  list.sort((a, b) => {
    if (a.year !== b.year) return b.year - a.year;
    return b.month - a.month;
  });
  for (const group of list) {
    group.items.sort((a, b) => {
      const ta = toTime(a.completedAt);
      const tb = toTime(b.completedAt);
      return tb - ta;
    });
  }
  return list;
}

function toTime(value: Date | string | null | undefined): number {
  if (value == null || value === "") return 0;
  const time = value instanceof Date ? value.getTime() : new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}
