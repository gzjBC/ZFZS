"use client";

import { useState } from "react";
import AnimeCard from "@/components/anime-card";
import type { RecommendationResult } from "@/lib/ai/recommend";

const PROVIDER_LABELS: Record<string, string> = {
  qwen: "千问（Qwen）",
  deepseek: "DeepSeek",
};

export default function RecommendPage() {
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const [addedKeys, setAddedKeys] = useState<Set<string>>(new Set());

  const generate = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/recommend");
      const body = await res.json();
      if (!res.ok) setError(body.error ?? "推荐生成失败");
      else setResult(body);
    } catch {
      setError("推荐生成失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  /** 懒人一键：按标题搜 Bangumi 拿 id 并加入清单 */
  const searchAndAdd = async (title: string) => {
    setAddingKey(title);
    setError(null);
    try {
      const searchRes = await fetch(`/api/subjects?q=${encodeURIComponent(title)}`);
      const searchBody = await searchRes.json();
      const hit = (searchBody.data ?? [])[0];
      if (!hit) {
        setError(`没搜到「${title}」，可去季度新番里手动搜`);
        return;
      }
      const addRes = await fetch("/api/tracking", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bangumi_subject_id: hit.id,
          title: hit.name,
          title_cn: hit.name_cn,
          cover_url: hit.images?.medium ?? null,
          summary: hit.summary,
          air_date: hit.date,
          total_episodes: hit.total_episodes,
        }),
      });
      if (addRes.status === 409) setError("「" + (hit.name_cn || hit.name) + "」已在清单中");
      else if (!addRes.ok) setError("加入清单失败");
      else setAddedKeys((prev) => new Set(prev).add(title));
    } catch {
      setError("加入清单失败，请检查网络");
    } finally {
      setAddingKey(null);
    }
  };

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>AI 推荐</h1>
      <p style={{ fontSize: 13, color: "#6B7280", marginBottom: 16 }}>
        基于追番清单中「看完并评分」的番剧，用 AI 生成 5 部你可能喜欢的动画
      </p>

      <button
        onClick={generate}
        disabled={loading}
        style={{
          padding: "10px 20px",
          borderRadius: 8,
          border: "none",
          background: "#1A1B1C",
          color: "#FFFFFF",
          fontSize: 14,
          cursor: "pointer",
          marginBottom: 20,
        }}
      >
        {loading ? "生成中…" : "生成推荐"}
      </button>

      {error && (
        <p
          style={{
            color: "#B45309",
            background: "#FEF3C7",
            borderRadius: 8,
            padding: "10px 14px",
            marginBottom: 12,
          }}
        >
          {error}
        </p>
      )}

      {result && (
        <>
          <p style={{ fontSize: 13, color: "#6B7280", marginBottom: 12 }}>
            由 {PROVIDER_LABELS[result.provider] ?? result.provider}（{result.model}）生成 ·{" "}
            <span style={{ color: "#B45309" }}>AI 可能有幻觉，参考后请在季度新番核实</span>
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              gap: 12,
            }}
          >
            {result.items.map((item, i) => {
              const key = item.titleCn || item.title;
              return (
                <AnimeCard
                  key={`${i}-${key}`}
                  title={`${i + 1}. ${item.title}`}
                  titleCn={`${i + 1}. ${item.titleCn || item.title}`}
                  score={null}
                  date={item.season ?? undefined}
                  watchTitle={key}
                  extra={
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {item.reason && (
                        <p style={{ fontSize: 12, color: "#374151", lineHeight: 1.5 }}>
                          {item.reason}
                        </p>
                      )}
                      {addedKeys.has(key) ? (
                        <div
                          style={{
                            padding: "5px 10px",
                            borderRadius: 8,
                            background: "#F0FDF4",
                            color: "#166534",
                            fontSize: 12,
                            textAlign: "center",
                          }}
                        >
                          已加入
                        </div>
                      ) : (
                        <button
                          onClick={() => searchAndAdd(key)}
                          disabled={addingKey === key}
                          style={{
                            padding: "5px 10px",
                            borderRadius: 8,
                            border: "1px solid #E4E3DD",
                            background: "#FFFFFF",
                            fontSize: 12,
                            cursor: "pointer",
                            width: "100%",
                          }}
                        >
                          {addingKey === key ? "搜加中…" : "加入清单"}
                        </button>
                      )}
                    </div>
                  }
                />
              );
            })}
          </div>
        </>
      )}
    </main>
  );
}
