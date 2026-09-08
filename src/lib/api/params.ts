/**
 * 接口层参数校验（纯函数，无框架依赖，可单测）。
 * 保持 route handler 薄：只做解析校验 + 转发。
 */
import type { TrackingInput, TrackingStatus, UpdatePatch } from "@/lib/db/tracking-repo";

export const TRACKING_STATUSES: readonly TrackingStatus[] = [
  "wish",
  "watching",
  "completed",
  "hold",
];

export function parseId(raw: string | undefined): number | null {
  if (!raw) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function parseTrackingStatus(raw: unknown): TrackingStatus | null {
  return typeof raw === "string" && (TRACKING_STATUSES as readonly string[]).includes(raw)
    ? (raw as TrackingStatus)
    : null;
}

type ParseResult<T> = { ok: true; value: T } | { ok: false; error: string };

function requireFields(body: Record<string, unknown>): string | null {
  const subjectId = Number(body.bangumi_subject_id);
  if (!Number.isInteger(subjectId) || subjectId <= 0) {
    return "bangumi_subject_id 必须是正整数";
  }
  if (typeof body.title !== "string" || body.title.trim() === "") {
    return "title 必填";
  }
  return null;
}

export function parseTrackingInput(body: unknown): ParseResult<TrackingInput> {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "请求体必须是 JSON 对象" };
  }
  const b = body as Record<string, unknown>;
  const fieldError = requireFields(b);
  if (fieldError) return { ok: false, error: fieldError };

  const status = b.status === undefined ? undefined : parseTrackingStatus(b.status);
  if (b.status !== undefined && !status) {
    return { ok: false, error: `status 必须是 ${TRACKING_STATUSES.join("/")} 之一` };
  }

  const rating = b.rating === undefined || b.rating === null ? null : Number(b.rating);
  if (rating !== null && (Number.isNaN(rating) || rating < 0 || rating > 10)) {
    return { ok: false, error: "rating 必须是 0-10 之间的数字" };
  }
  const progress = b.episode_progress === undefined ? 0 : Number(b.episode_progress);
  if (Number.isNaN(progress) || progress < 0) {
    return { ok: false, error: "episode_progress 必须是非负数字" };
  }

  return {
    ok: true,
    value: {
      bangumi_subject_id: Number(b.bangumi_subject_id),
      title: String(b.title).trim(),
      title_cn: optionalString(b.title_cn),
      cover_url: optionalString(b.cover_url),
      summary: optionalString(b.summary),
      status: status ?? undefined,
      episode_progress: progress,
      total_episodes:
        b.total_episodes === undefined || b.total_episodes === null
          ? undefined
          : Number(b.total_episodes),
      rating: rating ?? undefined,
      air_date: optionalString(b.air_date),
      tags: Array.isArray(b.tags) ? b.tags.filter((t): t is string => typeof t === "string") : undefined,
    },
  };
}

export function parseTrackingPatch(body: unknown): ParseResult<UpdatePatch> {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "请求体必须是 JSON 对象" };
  }
  const b = body as Record<string, unknown>;
  if (b.bangumi_subject_id !== undefined) {
    return { ok: false, error: "bangumi_subject_id 不可修改" };
  }
  const patch: UpdatePatch = {};
  for (const key of ["title", "title_cn", "cover_url", "summary", "air_date"] as const) {
    if (b[key] !== undefined) {
      (patch as Record<string, unknown>)[key] =
        b[key] === null ? null : String(b[key]).trim();
    }
  }
  if (b.status !== undefined) {
    const status = parseTrackingStatus(b.status);
    if (!status) return { ok: false, error: `status 必须是 ${TRACKING_STATUSES.join("/")} 之一` };
    patch.status = status;
  }
  if (b.episode_progress !== undefined) {
    const p = Number(b.episode_progress);
    if (Number.isNaN(p) || p < 0) return { ok: false, error: "episode_progress 必须是非负数字" };
    patch.episodeProgress = p;
  }
  if (b.rating !== undefined && b.rating !== null) {
    const r = Number(b.rating);
    if (Number.isNaN(r) || r < 0 || r > 10) return { ok: false, error: "rating 必须是 0-10 之间的数字" };
    patch.rating = r;
  } else if (b.rating === null) {
    patch.rating = null;
  }
  if (b.tags !== undefined) {
    if (!Array.isArray(b.tags) || b.tags.some((t) => typeof t !== "string")) {
      return { ok: false, error: "tags 必须是字符串数组" };
    }
    patch.tags = b.tags as string[];
  }
  return { ok: true, value: patch };
}

function optionalString(v: unknown): string | null | undefined {
  if (v === undefined) return undefined;
  return v === null ? null : String(v).trim();
}
