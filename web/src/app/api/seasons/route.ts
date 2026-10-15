import { getCurrentSeasonMonth, getSeasonAnime } from "@/lib/bangumi/seasons";
import { withCache } from "@/lib/cache";

const SEASON_CACHE_TTL_MS = 6 * 60 * 60 * 1000;

const SEASON_MONTHS = [1, 4, 7, 10];

export async function GET(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const now = new Date();
  const year = Number(url.searchParams.get("year") ?? now.getFullYear());
  const month = Number(url.searchParams.get("month") ?? getCurrentSeasonMonth(now));

  if (!Number.isInteger(year) || year < 2000 || year > 2100) {
    return Response.json({ error: "year 必须是 2000-2100 的整数" }, { status: 400 });
  }
  if (!SEASON_MONTHS.includes(month)) {
    return Response.json({ error: "month 必须是 1/4/7/10 之一" }, { status: 400 });
  }

  try {
    const data = await withCache(
      `season:${year}-${month}`,
      SEASON_CACHE_TTL_MS,
      () => getSeasonAnime({ year, month }),
    );
    return Response.json({ items: data.data, total: data.total });
  } catch {
    return Response.json({ error: "季度新番获取失败，请稍后重试" }, { status: 502 });
  }
}
