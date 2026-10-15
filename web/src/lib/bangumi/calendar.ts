/**
 * 放送日历：获取本周每天更新的番剧列表（GET /calendar）。
 */
import { BangumiClient } from "./client";
import type { CalendarDay } from "./types";

export async function getCalendar(
  client: BangumiClient = new BangumiClient(),
): Promise<CalendarDay[]> {
  return client.getJson<CalendarDay[]>("/calendar");
}
