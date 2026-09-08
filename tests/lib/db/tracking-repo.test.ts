import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";
import {
  addTracking,
  getCompletedHistory,
  getTracking,
  listTracking,
  removeTracking,
  updateTracking,
} from "@/lib/db/tracking-repo";
import type { TrackingInput } from "@/lib/db/tracking-repo";

const TEST_DATABASE_URL = "postgres://anime:anime@localhost:5432/anime_tracker_test";

const sample: TrackingInput = {
  bangumi_subject_id: 456080,
  title: "転校先の清楚可憐な美少女が、昔男子と思って一緒に遊んだ幼馴染だった件",
  title_cn: "转学后班上的清纯可爱美少女，竟是小时候玩在一起的哥们儿",
  cover_url: "http://lain.bgm.tv/pic/cover/l/ce/e2/456080_C4q4C.jpg",
  summary: "示例简介",
  air_date: "2026-07-06",
  total_episodes: 12,
  tags: ["校园", "恋爱"],
};

let pool: Pool;

beforeAll(async () => {
  pool = new Pool({ connectionString: TEST_DATABASE_URL });
  const schema = readFileSync(path.resolve(process.cwd(), "src/lib/db/schema.sql"), "utf-8");
  await pool.query("DROP TABLE IF EXISTS tracking");
  await pool.query(schema);
});

afterAll(async () => {
  await pool.query("DROP TABLE IF EXISTS tracking");
  await pool.end();
});

beforeEach(async () => {
  await pool.query("TRUNCATE tracking RESTART IDENTITY");
});

describe("addTracking", () => {
  it("创建记录并应用默认值（wish / progress 0 / 空 tags）", async () => {
    const record = await addTracking(pool, sample);
    expect(record.id).toBeGreaterThan(0);
    expect(record.bangumi_subject_id).toBe(456080);
    expect(record.status).toBe("wish");
    expect(record.episode_progress).toBe(0);
    expect(record.tags).toEqual(["校园", "恋爱"]);
    expect(record.rating).toBeNull();
    expect(record.air_date).toBe("2026-07-06"); // DATE 归一化为 YYYY-MM-DD
    expect(record.created_at).toBeInstanceOf(Date);
  });

  it("重复 bangumi_subject_id 抛出唯一约束错误", async () => {
    await addTracking(pool, sample);
    await expect(addTracking(pool, sample)).rejects.toMatchObject({ code: "23505" });
  });
});

describe("getTracking / listTracking", () => {
  it("按 id 查询存在与不存在", async () => {
    const created = await addTracking(pool, sample);
    const found = await getTracking(pool, created.id);
    expect(found?.title_cn).toBe(sample.title_cn);
    expect(await getTracking(pool, 99999)).toBeNull();
  });

  it("listTracking 返回全部并按更新时间倒序", async () => {
    await addTracking(pool, { ...sample, bangumi_subject_id: 1, title: "A" });
    await addTracking(pool, { ...sample, bangumi_subject_id: 2, title: "B", status: "completed" });
    const all = await listTracking(pool);
    expect(all).toHaveLength(2);
    expect(all[0].title).toBe("B"); // 后插入的 updated_at 更晚
  });

  it("listTracking 支持按状态过滤", async () => {
    await addTracking(pool, { ...sample, bangumi_subject_id: 1 });
    await addTracking(pool, { ...sample, bangumi_subject_id: 2, status: "completed" });
    const completed = await listTracking(pool, { status: "completed" });
    expect(completed).toHaveLength(1);
    expect(completed[0].status).toBe("completed");
  });
});

describe("updateTracking", () => {
  it("更新状态/进度/评分并刷新 updated_at", async () => {
    const created = await addTracking(pool, sample);
    const updated = await updateTracking(pool, created.id, {
      status: "watching",
      episodeProgress: 3,
      rating: 7.5,
    });
    expect(updated?.status).toBe("watching");
    expect(updated?.episode_progress).toBe(3);
    expect(updated?.rating).toBe(7.5);
    expect(updated?.updated_at.getTime()).toBeGreaterThanOrEqual(created.updated_at.getTime());
  });

  it("空 patch 返回原记录不报错", async () => {
    const created = await addTracking(pool, sample);
    const updated = await updateTracking(pool, created.id, {});
    expect(updated?.title).toBe(sample.title);
  });

  it("改为 completed 时记录完成时间", async () => {
    const created = await addTracking(pool, sample);
    const updated = await updateTracking(pool, created.id, {
      status: "completed",
      episodeProgress: 12,
    });
    expect(updated?.status).toBe("completed");
    expect(updated?.completed_at).toBeInstanceOf(Date);
  });

  it("改出 completed 时清空完成时间", async () => {
    const created = await addTracking(pool, sample);
    const done = await updateTracking(pool, created.id, { status: "completed" });
    expect(done?.completed_at).toBeInstanceOf(Date);
    const back = await updateTracking(pool, created.id, { status: "watching" });
    expect(back?.completed_at).toBeNull();
  });

  it("只改进度不影响完成时间", async () => {
    const created = await addTracking(pool, sample);
    await updateTracking(pool, created.id, { status: "completed" });
    const progressed = await updateTracking(pool, created.id, { episodeProgress: 3 });
    expect(progressed?.completed_at).toBeInstanceOf(Date);
  });

  it("不存在的 id 返回 null", async () => {
    expect(await updateTracking(pool, 99999, { status: "completed" })).toBeNull();
  });
});

describe("removeTracking", () => {
  it("删除成功返回 true，重复删除返回 false", async () => {
    const created = await addTracking(pool, sample);
    expect(await removeTracking(pool, created.id)).toBe(true);
    expect(await removeTracking(pool, created.id)).toBe(false);
  });
});

describe("getCompletedHistory", () => {
  it("只返回已看完且有评分的番剧，按评分降序", async () => {
    await addTracking(pool, { ...sample, bangumi_subject_id: 1, status: "completed", rating: 8 });
    await addTracking(pool, { ...sample, bangumi_subject_id: 2, status: "completed", rating: 9.5 });
    await addTracking(pool, { ...sample, bangumi_subject_id: 3, status: "watching" });
    const history = await getCompletedHistory(pool);
    expect(history).toHaveLength(2);
    expect(history[0].rating).toBe(9.5);
    expect(history[1].rating).toBe(8);
  });
});
