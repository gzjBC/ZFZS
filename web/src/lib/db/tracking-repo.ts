/**
 * tracking 仓储：追番清单的增删改查。
 * 所有函数接收 Pool 参数（依赖注入），便于测试使用独立测试库。
 * pg 对 numeric 返回字符串、DATE 返回字符串，统一在此层转换为业务类型。
 */
import type { Pool } from "pg";

export type TrackingStatus = "wish" | "watching" | "completed" | "hold";

export interface TrackingRecord {
  id: number;
  bangumi_subject_id: number;
  title: string;
  title_cn: string | null;
  cover_url: string | null;
  summary: string | null;
  status: TrackingStatus;
  episode_progress: number;
  total_episodes: number | null;
  rating: number | null;
  air_date: string | null;
  tags: string[];
  /** 看完时间：status 变更为 completed 时自动记录，改出 completed 时清空 */
  completed_at: Date | null;
  created_at: Date;
  updated_at: Date;
}

export interface TrackingInput {
  bangumi_subject_id: number;
  title: string;
  title_cn?: string | null;
  cover_url?: string | null;
  summary?: string | null;
  status?: TrackingStatus;
  episode_progress?: number;
  total_episodes?: number | null;
  rating?: number | null;
  air_date?: string | null;
  tags?: string[];
}

/** 可更新字段白名单：key 为调用方字段，value 为数据库列名（防注入） */
const UPDATEABLE_COLUMNS: Record<string, string> = {
  title: "title",
  titleCn: "title_cn",
  coverUrl: "cover_url",
  summary: "summary",
  status: "status",
  episodeProgress: "episode_progress",
  totalEpisodes: "total_episodes",
  rating: "rating",
  airDate: "air_date",
  tags: "tags",
};

/** 更新补丁：camelCase 字段（与 UPDATEABLE_COLUMNS 的 key 一致，供接口层使用） */
export interface UpdatePatch {
  title?: string;
  titleCn?: string | null;
  coverUrl?: string | null;
  summary?: string | null;
  status?: TrackingStatus;
  episodeProgress?: number;
  totalEpisodes?: number | null;
  rating?: number | null;
  airDate?: string | null;
  tags?: string[];
}

/** pg 的 DATE 列返回 Date 对象，统一格式化为 YYYY-MM-DD（本地时区，避免跨日偏移） */
function formatDate(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) {
    const y = value.getFullYear();
    const m = String(value.getMonth() + 1).padStart(2, "0");
    const d = String(value.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }
  return String(value);
}

function mapRow(row: Record<string, unknown>): TrackingRecord {
  return {
    id: row.id as number,
    bangumi_subject_id: row.bangumi_subject_id as number,
    title: row.title as string,
    title_cn: (row.title_cn as string | null) ?? null,
    cover_url: (row.cover_url as string | null) ?? null,
    summary: (row.summary as string | null) ?? null,
    status: row.status as TrackingStatus,
    episode_progress: row.episode_progress as number,
    total_episodes: (row.total_episodes as number | null) ?? null,
    rating: row.rating === null || row.rating === undefined ? null : Number(row.rating),
    air_date: formatDate(row.air_date),
    tags: (row.tags as string[]) ?? [],
    completed_at: (row.completed_at as Date | null) ?? null,
    created_at: row.created_at as Date,
    updated_at: row.updated_at as Date,
  };
}

export async function listTracking(
  pool: Pool,
  opts: { status?: TrackingStatus } = {},
): Promise<TrackingRecord[]> {
  if (opts.status) {
    const { rows } = await pool.query(
      "SELECT * FROM tracking WHERE status = $1 ORDER BY updated_at DESC",
      [opts.status],
    );
    return rows.map(mapRow);
  }
  const { rows } = await pool.query("SELECT * FROM tracking ORDER BY updated_at DESC");
  return rows.map(mapRow);
}

export async function getTracking(pool: Pool, id: number): Promise<TrackingRecord | null> {
  const { rows } = await pool.query("SELECT * FROM tracking WHERE id = $1", [id]);
  return rows[0] ? mapRow(rows[0]) : null;
}

export async function addTracking(pool: Pool, input: TrackingInput): Promise<TrackingRecord> {
  const { rows } = await pool.query(
    `INSERT INTO tracking
       (bangumi_subject_id, title, title_cn, cover_url, summary, status,
        episode_progress, total_episodes, rating, air_date, tags)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
     RETURNING *`,
    [
      input.bangumi_subject_id,
      input.title,
      input.title_cn ?? null,
      input.cover_url ?? null,
      input.summary ?? null,
      input.status ?? "wish",
      input.episode_progress ?? 0,
      input.total_episodes ?? null,
      input.rating ?? null,
      input.air_date ?? null,
      input.tags ?? [],
    ],
  );
  return mapRow(rows[0]);
}

export async function updateTracking(
  pool: Pool,
  id: number,
  patch: UpdatePatch,
): Promise<TrackingRecord | null> {
  const sets: string[] = [];
  const values: unknown[] = [];
  let paramIndex = 1;
  let statusParamIndex: number | undefined;
  for (const [key, column] of Object.entries(UPDATEABLE_COLUMNS)) {
    const value = (patch as Record<string, unknown>)[key];
    if (value !== undefined) {
      const idx = paramIndex++;
      sets.push(`${column} = $${idx}`);
      values.push(value);
      if (key === "status") statusParamIndex = idx;
    }
  }
  if (sets.length === 0) {
    return getTracking(pool, id);
  }
  // 状态变为 completed → 记录完成时间（首次）；改出 completed → 清空完成时间
  if (statusParamIndex !== undefined) {
    sets.push(
      `completed_at = CASE WHEN $${statusParamIndex} = 'completed' ` +
        `THEN COALESCE(completed_at, now()) ELSE NULL END`,
    );
  }
  sets.push("updated_at = now()");
  values.push(id);
  const { rows } = await pool.query(
    `UPDATE tracking SET ${sets.join(", ")} WHERE id = $${paramIndex} RETURNING *`,
    values,
  );
  return rows[0] ? mapRow(rows[0]) : null;
}

export async function removeTracking(pool: Pool, id: number): Promise<boolean> {
  const { rows } = await pool.query("DELETE FROM tracking WHERE id = $1 RETURNING id", [id]);
  return rows.length > 0;
}

/** AI 推荐依据：已看完且评分的番剧，按评分降序 */
export async function getCompletedHistory(pool: Pool): Promise<TrackingRecord[]> {
  const { rows } = await pool.query(
    `SELECT * FROM tracking
     WHERE status = 'completed'
     ORDER BY rating DESC NULLS LAST, updated_at DESC`,
  );
  return rows.map(mapRow);
}
