import { beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, PATCH } from "@/app/api/tracking/[id]/route";

vi.mock("@/lib/db/tracking-repo", () => ({
  removeTracking: vi.fn(),
  updateTracking: vi.fn(),
}));
vi.mock("@/lib/db/pool", () => ({
  getPool: vi.fn(() => ({})),
}));

import { removeTracking, updateTracking } from "@/lib/db/tracking-repo";

const mockedRemove = vi.mocked(removeTracking);
const mockedUpdate = vi.mocked(updateTracking);

const record = { id: 1, bangumi_subject_id: 1, title: "示例番", status: "watching" };

beforeEach(() => {
  mockedRemove.mockReset();
  mockedUpdate.mockReset();
});

const ctx = async (id: string) => ({ params: Promise.resolve({ id }) });

describe("PATCH /api/tracking/:id", () => {
  it("更新成功返回 200", async () => {
    mockedUpdate.mockResolvedValue(record as never);
    const res = await PATCH(
      new Request("http://localhost/api/tracking/1", {
        method: "PATCH",
        body: JSON.stringify({ status: "watching" }),
      }),
      await ctx("1"),
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.item.status).toBe("watching");
  });

  it("无效 id 返回 400", async () => {
    const res = await PATCH(
      new Request("http://localhost/api/tracking/abc", { method: "PATCH", body: "{}" }),
      await ctx("abc"),
    );
    expect(res.status).toBe(400);
  });

  it("不存在的条目返回 404", async () => {
    mockedUpdate.mockResolvedValue(null);
    const res = await PATCH(
      new Request("http://localhost/api/tracking/99", {
        method: "PATCH",
        body: JSON.stringify({ status: "completed" }),
      }),
      await ctx("99"),
    );
    expect(res.status).toBe(404);
  });

  it("非法 status 返回 400", async () => {
    const res = await PATCH(
      new Request("http://localhost/api/tracking/1", {
        method: "PATCH",
        body: JSON.stringify({ status: "done" }),
      }),
      await ctx("1"),
    );
    expect(res.status).toBe(400);
    expect(mockedUpdate).not.toHaveBeenCalled();
  });
});

describe("DELETE /api/tracking/:id", () => {
  it("删除成功返回 204", async () => {
    mockedRemove.mockResolvedValue(true);
    const res = await DELETE(new Request("http://localhost/api/tracking/1"), await ctx("1"));
    expect(res.status).toBe(204);
  });

  it("不存在返回 404", async () => {
    mockedRemove.mockResolvedValue(false);
    const res = await DELETE(new Request("http://localhost/api/tracking/1"), await ctx("1"));
    expect(res.status).toBe(404);
  });
});
