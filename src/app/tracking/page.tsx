"use client";

import { useEffect, useState } from "react";
import AnimeCard from "@/components/anime-card";
import { formatCompletedDate, getStatusBadge, groupByQuarter } from "@/lib/ui/status";
import type { TrackingRecord } from "@/lib/db/tracking-repo";
import type { SubjectV0 } from "@/lib/bangumi/types";

const STATUS_LABELS: Record<string, string> = {
  wish: "想看",
  watching: "在看",
  completed: "看完",
  hold: "搁置",
};

export default function TrackingPage() {
  const [items, setItems] = useState<TrackingRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SubjectV0[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingIds, setAddingIds] = useState<Set<number>>(new Set());
  const [addedIds, setAddedIds] = useState<Set<number>>(new Set());

  const loadItems = () => {
    fetch("/api/tracking")
      .then((res) => res.json())
      .then((body) => {
        if (body.error) setError(body.error);
        else setItems(body.items);
      })
      .catch(() => setError("加载清单失败"));
  };

  useEffect(loadItems, []);

  const doSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setError(null);
    try {
      const res = await fetch(`/api/subjects?q=${encodeURIComponent(q)}`);
      const body = await res.json();
      if (body.error) setError(body.error);
      else setResults(body.data ?? []);
    } catch {
      setError("搜索失败");
    } finally {
      setSearching(false);
    }
  };

  const addSubject = async (s: SubjectV0) => {
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
      if (res.status === 409) {
        setError("该番剧已在清单中");
        setAddedIds((prev) => new Set(prev).add(s.id));
      } else if (!res.ok) {
        setError("添加失败");
      } else {
        setAddedIds((prev) => new Set(prev).add(s.id));
        loadItems();
      }
    } catch {
      setError("添加失败");
    } finally {
      setAddingIds((prev) => {
        const next = new Set(prev);
        next.delete(s.id);
        return next;
      });
    }
  };

  const patchItem = async (id: number, patch: Record<string, unknown>) => {
    try {
      const res = await fetch(`/api/tracking/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (res.ok) loadItems();
      else setError("更新失败");
    } catch {
      setError("更新失败");
    }
  };

  const removeItem = async (id: number) => {
    try {
      const res = await fetch(`/api/tracking/${id}`, { method: "DELETE" });
      if (res.ok) loadItems();
      else setError("删除失败");
    } catch {
      setError("删除失败");
    }
  };

  /** 一键看完：进度拉满并标记 completed */
  const finishItem = (item: TrackingRecord) => {
    const target = item.total_episodes ?? item.episode_progress + 1;
    patchItem(item.id, { episode_progress: target, status: "completed" });
  };

  const active = items.filter((i) => i.status !== "completed");
  const done = items.filter((i) => i.status === "completed");
  const doneGroups = groupByQuarter(
    done.map((i) => ({ ...i, completedAt: i.completed_at })),
  );

  const renderRow = (item: TrackingRecord) => {
    const badge = getStatusBadge(item.status);
    return (
      <div
        key={item.id}
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          border: "1px solid #E4E3DD",
          borderRadius: 12,
          padding: 10,
          background: "#FFFFFF",
          flexWrap: "wrap",
        }}
      >
        {item.cover_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.cover_url}
            alt={item.title_cn || item.title}
            style={{ width: 56, height: 74, objectFit: "cover", borderRadius: 8 }}
          />
        )}
        <div style={{ flex: "1 1 200px", minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <a
              href={`https://bgm.tv/subject/${item.bangumi_subject_id}`}
              target="_blank"
              rel="noreferrer"
              title="在 Bangumi 查看条目与放送链接"
              style={{ fontSize: 14, fontWeight: 600, color: "#1A1B1C", textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "#2563EB")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "#1A1B1C")}
            >
              {item.title_cn || item.title}
              <span style={{ fontSize: 11, color: "#6B7280", marginLeft: 2 }}>↗</span>
            </a>
            <a
              href={`https://search.bilibili.com/bangumi?keyword=${encodeURIComponent(item.title_cn || item.title)}`}
              target="_blank"
              rel="noreferrer"
              title="去 B站搜索播放源"
              style={{
                fontSize: 12,
                padding: "1px 8px",
                borderRadius: 6,
                background: "#F0FDF4",
                border: "1px solid #BBF7D0",
                color: "#15803D",
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              ▶ 去观看
            </a>
            <span
              style={{
                fontSize: 11,
                padding: "1px 6px",
                borderRadius: 6,
                background: badge.bg,
                border: `1px solid ${badge.border}`,
                color: badge.color,
                whiteSpace: "nowrap",
              }}
            >
              {badge.label}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>
            {item.air_date ? `${item.air_date} · ` : ""}
            进度 {item.episode_progress}/{item.total_episodes ?? "?"}
            {item.rating != null ? ` · 评分 ${Number(item.rating).toFixed(1)}` : ""}
            {item.completed_at
              ? ` · 看完于 ${formatCompletedDate(item.completed_at)}`
              : ""}
          </div>
        </div>

        <select
          value={item.status}
          onChange={(e) => patchItem(item.id, { status: e.target.value })}
          style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid #E4E3DD", fontSize: 13 }}
        >
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>

        <button
          onClick={() => patchItem(item.id, { episode_progress: item.episode_progress + 1 })}
          style={{
            padding: "6px 10px",
            borderRadius: 8,
            border: "1px solid #E4E3DD",
            background: "#FFFFFF",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          +1 集
        </button>

        <button
          onClick={() => finishItem(item)}
          disabled={item.status === "completed"}
          style={{
            padding: "6px 10px",
            borderRadius: 8,
            border: "1px solid #BBF7D0",
            background: item.status === "completed" ? "#F3F4F6" : "#F0FDF4",
            color: item.status === "completed" ? "#9CA3AF" : "#15803D",
            fontSize: 13,
            cursor: item.status === "completed" ? "default" : "pointer",
          }}
        >
          {item.status === "completed" ? "已看完" : "看完"}
        </button>

        <input
          type="number"
          min={0}
          max={10}
          step={0.5}
          placeholder="评分"
          defaultValue={item.rating ?? ""}
          onBlur={(e) => {
            const v = e.target.value;
            if (v !== "") patchItem(item.id, { rating: Number(v) });
          }}
          style={{ width: 70, padding: "6px 8px", borderRadius: 8, border: "1px solid #E4E3DD", fontSize: 13 }}
        />

        <button
          onClick={() => removeItem(item.id)}
          style={{
            padding: "6px 10px",
            borderRadius: 8,
            border: "1px solid #FECACA",
            background: "#FEF2F2",
            color: "#B91C1C",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          移除
        </button>
      </div>
    );
  };

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>我的追番</h1>

      {error && (
        <p style={{ color: "#B91C1C", background: "#FEE2E2", borderRadius: 8, padding: "10px 14px" }}>
          {error}
        </p>
      )}

      {/* 搜索添加 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          placeholder="搜索番剧加入清单"
          style={{
            flex: "1 1 240px",
            padding: "8px 12px",
            borderRadius: 8,
            border: "1px solid #E4E3DD",
            fontSize: 14,
          }}
        />
        <button
          onClick={doSearch}
          disabled={searching}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: "#1A1B1C",
            color: "#FFFFFF",
            fontSize: 14,
            cursor: "pointer",
          }}
        >
          {searching ? "搜索中…" : "搜索"}
        </button>
      </div>

      {results.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>搜索结果</h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
              gap: 12,
            }}
          >
            {results.slice(0, 12).map((s) => (
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
                      onClick={() => addSubject(s)}
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
        </div>
      )}

      {/* 正在追 */}
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
        正在追（{active.length}）
      </h2>
      {active.length === 0 && !error && (
        <p style={{ color: "#6B7280", fontSize: 14, marginBottom: 20 }}>
          还没有在追的番，用上面的搜索添加吧。
        </p>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 24 }}>
        {active.map(renderRow)}
      </div>

      {/* 已追完（按每 3 个月分组） */}
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
        已追完（{done.length}）
      </h2>
      {done.length === 0 && !error && (
        <p style={{ color: "#6B7280", fontSize: 14 }}>把追的番标记为「看完」后会按时间归档到这里。</p>
      )}
      {doneGroups.map((group) => (
        <section key={`${group.year}-${group.month}`} style={{ marginBottom: 16 }}>
          <h3
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "#6B7280",
              marginBottom: 8,
              display: "flex",
              gap: 6,
              alignItems: "center",
            }}
          >
            {group.label}
            <span
              style={{
                fontSize: 11,
                background: "#F3F4F6",
                color: "#6B7280",
                borderRadius: 999,
                padding: "0 8px",
              }}
            >
              {group.items.length} 部
            </span>
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {group.items.map(renderRow)}
          </div>
        </section>
      ))}
    </main>
  );
}
