import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/tracking/route";

vi.mock("@/lib/db/tracking-repo", () => ({
  addTracking: vi.fn(),
  listTracking: vi.fn(),
}));
vi.mock("@/lib/db/pool", () => ({
  getPool: vi.fn(() => ({})),
}));

import { addTracking, listTracking } from "@/lib/db/tracking-repo";

const mockedAdd = vi.mocked(addTracking);
const mockedList = vi.mocked(listTracking);

const record = {
  id: 1,
  bangumi_subject_id: 456080,
  title: "示例番",
  status: "wish",
  episode_progress: 0,
  rating: null,
};

beforeEach(() => {
  mockedAdd.mockReset();
  mockedList.mockReset();
});

describe("GET /api/tracking", () => {
  it("成功返回清单", async () => {
    mockedList.mockResolvedValue([record] as never);
    const res = await GET(new Request("http://localhost/api/tracking"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.items).toHaveLength(1);
  });

  it("支持 status 过滤并透传", async () => {
    mockedList.mockResolvedValue([] as never);
    await GET(new Request("http://localhost/api/tracking?status=completed"));
    expect(mockedList).toHaveBeenCalledWith(expect.anything(), { status: "completed" });
  });

  it("非法 status 返回 400", async () => {
    const res = await GET(new Request("http://localhost/api/tracking?status=done"));
    expect(res.status).toBe(400);
  });

  it("仓库异常返回 500", async () => {
    mockedList.mockRejectedValue(new Error("db down"));
    const res = await GET(new Request("http://localhost/api/tracking"));
    expect(res.status).toBe(500);
  });
});

describe("POST /api/tracking", () => {
  it("合法输入返回 201", async () => {
    mockedAdd.mockResolvedValue(record as never);
    const res = await POST(
      new Request("http://localhost/api/tracking", {
        method: "POST",
        body: JSON.stringify({ bangumi_subject_id: 456080, title: "示例番" }),
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.item.title).toBe("示例番");
  });

  it("缺必填字段返回 400", async () => {
    const res = await POST(
      new Request("http://localhost/api/tracking", {
        method: "POST",
        body: JSON.stringify({ bangumi_subject_id: 1 }),
      }),
    );
    expect(res.status).toBe(400);
    expect(mockedAdd).not.toHaveBeenCalled();
  });

  it("重复条目返回 409", async () => {
    const err = new Error("dup") as Error & { code: string };
    err.code = "23505";
    mockedAdd.mockRejectedValue(err);
    const res = await POST(
      new Request("http://localhost/api/tracking", {
        method: "POST",
        body: JSON.stringify({ bangumi_subject_id: 1, title: "x" }),
      }),
    );
    expect(res.status).toBe(409);
  });

  it("非法 JSON 返回 400", async () => {
    const res = await POST(
      new Request("http://localhost/api/tracking", {
        method: "POST",
        body: "not-json",
      }),
    );
    expect(res.status).toBe(400);
  });
});
