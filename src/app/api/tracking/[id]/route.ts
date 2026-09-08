import { getPool } from "@/lib/db/pool";
import { removeTracking, updateTracking } from "@/lib/db/tracking-repo";
import { parseId, parseTrackingPatch } from "@/lib/api/params";

type RouteContext = { params: Promise<{ id: string }> };

export async function PATCH(req: Request, ctx: RouteContext): Promise<Response> {
  const id = parseId((await ctx.params).id);
  if (id === null) {
    return Response.json({ error: "无效的 id" }, { status: 400 });
  }
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "请求体不是合法 JSON" }, { status: 400 });
  }
  const parsed = parseTrackingPatch(body);
  if (!parsed.ok) {
    return Response.json({ error: parsed.error }, { status: 400 });
  }
  try {
    const item = await updateTracking(getPool(), id, parsed.value);
    if (!item) {
      return Response.json({ error: "清单中不存在该条目" }, { status: 404 });
    }
    return Response.json({ item });
  } catch {
    return Response.json({ error: "更新追番失败" }, { status: 500 });
  }
}

export async function DELETE(_req: Request, ctx: RouteContext): Promise<Response> {
  const id = parseId((await ctx.params).id);
  if (id === null) {
    return Response.json({ error: "无效的 id" }, { status: 400 });
  }
  try {
    const removed = await removeTracking(getPool(), id);
    if (!removed) {
      return Response.json({ error: "清单中不存在该条目" }, { status: 404 });
    }
    return new Response(null, { status: 204 });
  } catch {
    return Response.json({ error: "删除追番失败" }, { status: 500 });
  }
}
