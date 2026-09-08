"use client";

import { useCallback, useEffect, useState } from "react";
import AnimeCard from "@/components/anime-card";
import type { SubjectV0 } from "@/lib/bangumi/types";

const QUARTER_MONTHS = [1, 4, 7, 10];
const YEAR_RANGE = [2024, 2025, 2026, 2027];

function currentQuarter(): { year: number; month: number } {
  const now = new Date();
  const m = now.getMonth() + 1;
  const month = m <= 3 ? 1 : m <= 6 ? 4 : m <= 9 ? 7 : 10;
  return { year: now.getFullYear(), month };
}

export default function SeasonsPage() {
  const init = currentQuarter();
  const [year, setYear] = useState(init.year);
  const [month, setMonth] = useState(init.month);
  const [items, setItems] = useState<SubjectV0[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set());
  const [addingIds, setAddingIds] = useState<Set<number>>(new Set());

  const load = useCallback(() => {
    setError(null);
    fetch(`/api/seasons?year=${year}&month=${month}`)
      .then((res) => res.json())
      .then((body) => {
        if (body.error) setError(body.error);
        else {
          setItems(body.items ?? []);
          setTotal(body.total ?? 0);
        }
      })
      .catch(() => setError("季度新番加载失败"))
      .finally(() => setLoading(false));
  }, [year, month]);

  useEffect(() => {
    fetch(`/api/seasons?year=${year}&month=${month}`)
      .then((res) => res.json())
      .then((body) => {
        if (body.error) setError(body.error);
        else {
          setItems(body.items ?? []);
          setTotal(body.total ?? 0);
        }
      })
      .catch(() => setError("季度新番加载失败"))
      .finally(() => setLoading(false));
  }, [year, month]);

  const addToTracking = async (s: SubjectV0) => {
    setAddingIds((prev) => new Set(prev).add(s.id));
    try {
      const res = await fetch("/api/tracking", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bangumi_subject_id: s.id,
          title: s.name,
          title_cn: s.name_cn,
          cover_url: s.images?.medium ?? null,
          summary: s.summary,
          air_date: s.date,
          total_episodes: s.total_episodes,
        }),
      });
      if (res.ok || res.status === 409) {
        setAddedIds((prev) => new Set(prev).add(s.id));
        if (res.status === 409) setError("该番剧已在清单中");
      } else setError("加入清单失败");
    } catch {
      setError("加入清单失败");
    } finally {
      setAddingIds((prev) => {
        const next = new Set(prev);
        next.delete(s.id);
        return next;
      });
    }
  };

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>季度新番</h1>
      <p style={{ fontSize: 13, color: "#6B7280", marginBottom: 16 }}>
        数据来自 Bangumi 条目浏览接口，按季度筛选动画
      </p>

      {/* 季度切换 */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 20 }}>
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #E4E3DD", fontSize: 14 }}
        >
          {YEAR_RANGE.map((y) => (
            <option key={y} value={y}>
              {y} 年
            </option>
          ))}
        </select>
        <div style={{ display: "flex", gap: 6 }}>
          {QUARTER_MONTHS.map((m) => (
            <button
              key={m}
              onClick={() => setMonth(m)}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: month === m ? "1px solid #1A1B1C" : "1px solid #E4E3DD",
                background: month === m ? "#1A1B1C" : "#FFFFFF",
                color: month === m ? "#FFFFFF" : "#1A1B1C",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              {m}月番
            </button>
          ))}
        </div>
        {loading && <span style={{ fontSize: 13, color: "#6B7280" }}>加载中…</span>}
      </div>

      {error && (
        <p style={{ color: "#B91C1C", background: "#FEE2E2", borderRadius: 8, padding: "10px 14px", marginBottom: 12 }}>
          {error}
        </p>
      )}

      <p style={{ fontSize: 13, color: "#6B7280", marginBottom: 12 }}>
        {year} 年 {month} 月开播 · 本季共 {total} 条
      </p>

      {items.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
            gap: 12,
          }}
        >
          {items.map((s) => (
            <AnimeCard
              key={s.id}
              title={s.name}
              titleCn={s.name_cn}
              coverUrl={s.images?.medium}
              score={s.rating?.score}
              date={s.date}
              bangumiId={s.id}
              watchTitle={s.name_cn || s.name}
              extra={
                addedIds.has(s.id) ? (
                  <div
                    style={{
                      marginTop: 6,
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
                    onClick={() => addToTracking(s)}
                    disabled={addingIds.has(s.id)}
                    style={{
                      marginTop: 6,
                      padding: "5px 10px",
                      borderRadius: 8,
                      border: "1px solid #E4E3DD",
                      background: "#FFFFFF",
                      fontSize: 12,
                      cursor: "pointer",
                      width: "100%",
                    }}
                  >
                    {addingIds.has(s.id) ? "添加中…" : "加入清单"}
                  </button>
                )
              }
            />
          ))}
        </div>
      )}
    </main>
  );
}
