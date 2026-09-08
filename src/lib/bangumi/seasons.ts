/**
 * 季度新番：GET /v0/subjects?type=2&year=YYYY&month=M
 * 官方参数为 year + month（air_date 仅存在于搜索接口 filter）。
 */
import { BangumiClient } from "./client";
import type { PagedSubjects } from "./types";

export type { PagedSubjects };

export interface SeasonParams {
  year: number;
  /** 季度起始月：1 | 4 | 7 | 10 */
  month: number;
  limit?: number;
  /** 排序：date（按开播日期，默认）| rank（实测 rank+asc 组合可能返回空，谨慎使用） */
  sort?: "date" | "rank";
  order?: "asc" | "desc";
}

/** 季度起始月：1-3月→1，4-6月→4，7-9月→7，10-12月→10 */
export function getCurrentSeasonMonth(now: Date = new Date()): number {
  const m = now.getMonth() + 1;
  if (m <= 3) return 1;
  if (m <= 6) return 4;
  if (m <= 9) return 7;
  return 10;
}

export async function getSeasonAnime(
  params: SeasonParams,
  client: BangumiClient = new BangumiClient(),
): Promise<PagedSubjects> {
  const qs = new URLSearchParams({
    type: "2",
    year: String(params.year),
    month: String(params.month),
    sort: params.sort ?? "date",
    order: params.order ?? "asc",
    limit: String(params.limit ?? 30),
    offset: "0",
  });
  return client.getJson<PagedSubjects>(`/v0/subjects?${qs.toString()}`);
}
