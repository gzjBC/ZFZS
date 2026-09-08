import { getCalendar } from "@/lib/bangumi/calendar";
import { withCache } from "@/lib/cache";

/** 放送日历缓存 6 小时，避免频繁请求触发 Bangumi 限流 */
const CALENDAR_CACHE_TTL_MS = 6 * 60 * 60 * 1000;

export async function GET(): Promise<Response> {
  try {
    const days = await withCache("calendar", CALENDAR_CACHE_TTL_MS, getCalendar);
    return Response.json({ days });
  } catch {
    return Response.json({ error: "放送日历获取失败，请稍后重试" }, { status: 502 });
  }
}
