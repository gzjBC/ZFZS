import { searchSubjects } from "@/lib/bangumi/search";
import { withCache } from "@/lib/cache";

const SEARCH_CACHE_TTL_MS = 60 * 60 * 1000;

export async function GET(req: Request): Promise<Response> {
  const q = new URL(req.url).searchParams.get("q")?.trim();
  if (!q) {
    return Response.json({ error: "缺少 q 参数" }, { status: 400 });
  }
  try {
    const data = await withCache(`search:${q}`, SEARCH_CACHE_TTL_MS, () =>
      searchSubjects({ keyword: q }),
    );
    return Response.json(data);
  } catch {
    return Response.json({ error: "搜索失败，请稍后重试" }, { status: 502 });
  }
}
