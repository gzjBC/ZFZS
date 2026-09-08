"use client";

import { useState } from "react";
import type { RecommendationResult } from "@/lib/ai/recommend";

const PROVIDER_LABELS: Record<string, string> = {
  qwen: "千问（Qwen）",
  deepseek: "DeepSeek",
};

export default function RecommendPage() {
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
            由 {PROVIDER_LABELS[result.provider] ?? result.provider}（{result.model}）生成
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {result.items.map((item, i) => (
              <div
                key={i}
                style={{
                  border: "1px solid #E4E3DD",
                  borderRadius: 12,
                  padding: "12px 14px",
                  background: "#FFFFFF",
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 15, fontWeight: 600 }}>
                    {i + 1}. {item.titleCn || item.title}
                  </span>
                  {item.titleCn && item.titleCn !== item.title && (
                    <span style={{ fontSize: 12, color: "#6B7280" }}>{item.title}</span>
                  )}
                  {item.season && (
                    <span
                      style={{
                        fontSize: 12,
                        color: "#6B7280",
                        border: "1px solid #E4E3DD",
                        borderRadius: 6,
                        padding: "1px 6px",
                      }}
                    >
                      {item.season}
                    </span>
                  )}
                </div>
                {item.reason && (
                  <p style={{ fontSize: 13, color: "#374151", marginTop: 6, lineHeight: 1.6 }}>
                    {item.reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
