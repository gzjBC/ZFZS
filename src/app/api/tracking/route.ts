import { addTracking, listTracking } from "@/lib/db/tracking-repo";
import { getPool } from "@/lib/db/pool";
import {
  parseTrackingInput,
  parseTrackingStatus,
  TRACKING_STATUSES,
} from "@/lib/api/params";

export async function GET(req: Request): Promise<Response> {
  const status = parseTrackingStatus(new URL(req.url).searchParams.get("status"));
  if (new URL(req.url).searchParams.get("status") !== null && !status) {
    return Response.json(
      { error: `status 必须是 ${TRACKING_STATUSES.join("/")} 之一` },
      { status: 400 },
    );
  }
  try {
    const items = await listTracking(getPool(), status ? { status } : {});
    return Response.json({ items });
  } catch (err) {
    console.error("[tracking] GET 失败:", err);
    return Response.json({ error: "查询追番清单失败" }, { status: 500 });
  }
}

export async function POST(req: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "请求体不是合法 JSON" }, { status: 400 });
  }
  const parsed = parseTrackingInput(body);
  if (!parsed.ok) {
    return Response.json({ error: parsed.error }, { status: 400 });
  }
  try {
    const item = await addTracking(getPool(), parsed.value);
    return Response.json({ item }, { status: 201 });
  } catch (err) {
    if ((err as { code?: string }).code === "23505") {
      return Response.json({ error: "该番剧已在清单中" }, { status: 409 });
    }
    console.error("[tracking] POST 失败:", err);
    return Response.json({ error: "添加追番失败" }, { status: 500 });
  }
}
