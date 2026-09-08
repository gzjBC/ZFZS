import { describe, expect, it } from "vitest";
import {
  parseId,
  parseTrackingInput,
  parseTrackingPatch,
  parseTrackingStatus,
} from "@/lib/api/params";

describe("parseId", () => {
  it("合法 id", () => {
    expect(parseId("12")).toBe(12);
  });
  it("非法/缺失返回 null", () => {
    expect(parseId("abc")).toBeNull();
    expect(parseId("1.5")).toBeNull();
    expect(parseId("0")).toBeNull();
    expect(parseId(undefined)).toBeNull();
  });
});

describe("parseTrackingStatus", () => {
  it("合法状态", () => {
    expect(parseTrackingStatus("watching")).toBe("watching");
  });
  it("非法状态返回 null", () => {
    expect(parseTrackingStatus("done")).toBeNull();
    expect(parseTrackingStatus(1)).toBeNull();
  });
});

describe("parseTrackingInput", () => {
  it("合法输入解析为仓储输入", () => {
    const r = parseTrackingInput({
      bangumi_subject_id: 456080,
      title: " 示例番 ",
      status: "watching",
      episode_progress: 3,
      rating: 8.5,
      tags: ["校园"],
    });
    expect(r).toMatchObject({
      ok: true,
      value: {
        bangumi_subject_id: 456080,
        title: "示例番",
        status: "watching",
        episode_progress: 3,
        rating: 8.5,
        tags: ["校园"],
      },
    });
  });

  it("缺必填字段报错", () => {
    expect(parseTrackingInput({ bangumi_subject_id: 1 })).toMatchObject({
      ok: false,
      error: "title 必填",
    });
    expect(parseTrackingInput({ title: "x" })).toMatchObject({
      ok: false,
      error: "bangumi_subject_id 必须是正整数",
    });
  });

  it("非法 status / rating / progress 报错", () => {
    expect(parseTrackingInput({ bangumi_subject_id: 1, title: "x", status: "done" })).toMatchObject({
      ok: false,
    });
    expect(
      parseTrackingInput({ bangumi_subject_id: 1, title: "x", rating: 11 }),
    ).toMatchObject({ ok: false });
    expect(
      parseTrackingInput({ bangumi_subject_id: 1, title: "x", episode_progress: -1 }),
    ).toMatchObject({ ok: false });
  });

  it("非对象请求体报错", () => {
    expect(parseTrackingInput(null)).toMatchObject({ ok: false });
    expect(parseTrackingInput([1, 2])).toMatchObject({ ok: false });
    expect(parseTrackingInput("x")).toMatchObject({ ok: false });
  });
});

describe("parseTrackingPatch", () => {
  it("合法 patch 映射到仓储字段名", () => {
    const r = parseTrackingPatch({ status: "completed", episode_progress: 10, rating: 9 });
    expect(r).toMatchObject({
      ok: true,
      value: { status: "completed", episodeProgress: 10, rating: 9 },
    });
  });

  it("禁止修改 bangumi_subject_id", () => {
    expect(parseTrackingPatch({ bangumi_subject_id: 2 })).toMatchObject({ ok: false });
  });

  it("rating 为 null 表示清空评分", () => {
    const r = parseTrackingPatch({ rating: null });
    expect(r).toMatchObject({ ok: true, value: { rating: null } });
  });

  it("tags 必须是字符串数组", () => {
    expect(parseTrackingPatch({ tags: [1, 2] })).toMatchObject({ ok: false });
    expect(parseTrackingPatch({ tags: ["a"] })).toMatchObject({ ok: true });
  });
});
