import { getRecommendations } from "@/lib/ai/recommend";
import { AiConfigError } from "@/lib/ai/config";
import { getCompletedHistory } from "@/lib/db/tracking-repo";
import { getPool } from "@/lib/db/pool";

export async function GET(): Promise<Response> {
  let history;
  try {
    history = await getCompletedHistory(getPool());
  } catch {
    return Response.json({ error: "读取追番历史失败" }, { status: 500 });
  }
  if (history.length === 0) {
    return Response.json(
      {
        error:
          "还没有可推荐的历史：请先在追番清单里把至少一部番标记为「看完」并打分，AI 才能基于你的口味推荐。",
      },
      { status: 422 },
    );
  }
  try {
    const result = await getRecommendations(history);
    return Response.json(result);
  } catch (err) {
    if (err instanceof AiConfigError) {
      return Response.json({ error: err.message }, { status: 503 });
    }
    return Response.json(
      { error: `AI 推荐生成失败：${(err as Error).message}` },
      { status: 502 },
    );
  }
}
