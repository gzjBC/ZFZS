"use client";

import { useEffect, useState } from "react";
import AnimeCard from "@/components/anime-card";
import { toBangumiWeekday, weekdayLabel } from "@/lib/ui/status";
import type { CalendarDay } from "@/lib/bangumi/types";

type CalendarResponse = { days: CalendarDay[] } | { error: string };

export default function HomePage() {
  const [days, setDays] = useState<CalendarDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const today = toBangumiWeekday();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/calendar")
      .then((res) => res.json() as Promise<CalendarResponse>)
      .then((body) => {
        if (cancelled) return;
        if ("error" in body) {
          setError(body.error);
        } else {
          setDays(body.days);
        }
      })
      .catch(() => {
        if (!cancelled) setError("网络异常，请稍后重试");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
        本周放送日历
      </h1>
      <p style={{ fontSize: 13, color: "#6B7280", marginBottom: 16 }}>
        今天是{weekdayLabel(today)} · 数据来自 Bangumi
      </p>

      {error && (
        <p style={{ color: "#B91C1C", background: "#FEE2E2", borderRadius: 8, padding: "10px 14px" }}>
          {error}
        </p>
      )}

      {!days && !error && <p style={{ color: "#6B7280" }}>加载中…</p>}

      {days &&
        days.map((day) => {
          const isToday = day.weekday.id === today;
          return (
            <section key={day.weekday.en} style={{ marginBottom: 20 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
                {weekdayLabel(day.weekday.id)}
                {isToday && (
                  <span
                    style={{
                      fontSize: 11,
                      padding: "1px 8px",
                      borderRadius: 999,
                      background: "#1A1B1C",
                      color: "#FFFFFF",
                    }}
                  >
                    今天
                  </span>
                )}
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
                  gap: 12,
                }}
              >
                {day.items.map((s) => (
                  <AnimeCard
                    key={s.id}
                    title={s.name}
                    titleCn={s.name_cn}
                    coverUrl={s.images?.medium}
                    score={s.rating?.score}
                    date={s.air_date}
                    bangumiId={s.id}
                    watchTitle={s.name_cn || s.name}
                  />
                ))}
                {day.items.length === 0 && (
                  <p style={{ fontSize: 13, color: "#9CA3AF" }}>当日暂无放送</p>
                )}
              </div>
            </section>
          );
        })}
    </main>
  );
}
