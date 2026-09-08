/**
 * 番剧搜索：POST /v0/search/subjects（仅动画 type=[2]）。
 */
import { BangumiClient } from "./client";
import type { PagedSubjects } from "./types";

export type { PagedSubjects };

export interface SearchParams {
  /** 关键词 */
  keyword: string;
  limit?: number;
  offset?: number;
}

export async function searchSubjects(
  params: SearchParams,
  client: BangumiClient = new BangumiClient(),
): Promise<PagedSubjects> {
  return client.postJson<PagedSubjects>("/v0/search/subjects", {
    keyword: params.keyword,
    sort: "match",
    filter: { type: [2] },
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  });
}
