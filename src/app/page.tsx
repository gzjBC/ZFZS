"use client";

import { useEffect, useMemo, useState } from "react";
import AnimeCard from "@/components/anime-card";
import AnimeDetailModal from "@/components/anime-detail-modal";
import { toBangumiWeekday, weekdayLabel } from "@/lib/ui/status";
import { buildTodayFeed } from "@/lib/ui/feed";
import type { CalendarDay, Subject } from "@/lib/bangumi/types";
import type { TrackingRecord } from "@/lib/db/tracking-repo";

type CalendarResponse = { days: CalendarDay[] } | { error: string };
type TrackingResponse = { items: TrackingRecord[] } | { error: string };

interface DetailState {
  subject: Subject;
  status?: string;
}

export default function HomePage() {
  const [days, setDays] = useState<CalendarDay[] | null>(null);
  const [tracking, setTracking] = useState<TrackingRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const today = toBangumiWeekday();

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/calendar").then((res) => res.json() as Promise<CalendarResponse>),
      fetch("/api/tracking").then((res) => res.json() as Promise<TrackingResponse>),
    ])
      .then(([calBody, trackBody]) => {
        if (cancelled) return;
        if ("error" in calBody) setError(calBody.error);
        else setDays(calBody.days);
        if (!("error" in trackBody)) setTracking(trackBody.items);
      })
      .catch(() => {
        if (!cancelled) setError("网络异常，请稍后重试");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const feed = useMemo(
    () => (days ? buildTodayFeed(days, tracking, today) : null),
    [days, tracking, today],
  );

  const statusOf = (subjectId: number): string | undefined =>
    tracking.find((t) => t.bangumi_subject_id === subjectId)?.status;

  const renderGrid = (items: Subject[], withStatus: boolean) => (
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
          date={s.air_date}
          status={withStatus ? statusOf(s.id) : undefined}
          bangumiId={s.id}
          watchTitle={s.name_cn || s.name}
          onDetail={() => setDetail({ subject: s, status: statusOf(s.id) })}
        />
      ))}
      {items.length === 0 && <p style={{ fontSize: 13, color: "#9CA3AF" }}>当日暂无放送</p>}
    </div>
  );

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
        追番助手
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

      {/* 今日更新：我追的番今天播 */}
      {feed && feed.today.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h2
            style={{
              fontSize: 17,
              fontWeight: 700,
              marginBottom: 8,
              display: "flex",
              gap: 8,
              alignItems: "center",
            }}
          >
            今日更新
            <span
              style={{
                fontSize: 11,
                padding: "1px 8px",
                borderRadius: 999,
                background: "#1A1B1C",
                color: "#FFFFFF",
              }}
            >
              {feed.today.length} 部在追
            </span>
          </h2>
          {renderGrid(feed.today.map((i) => i.subject), true)}
        </section>
      )}

      {/* 本周你追的番（其他天） */}
      {feed && feed.week.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            本周你还在追 · 共 {feed.week.length} 部
          </h2>
          {renderGrid(feed.week.map((i) => i.subject), true)}
        </section>
      )}

      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
        本周放送日历
      </h2>
      {days &&
        days.map((day) => {
          const isToday = day.weekday.id === today;
          return (
            <section key={day.weekday.en} style={{ marginBottom: 20 }}>
              <h3
                style={{
                  fontSize: 15,
                  fontWeight: 600,
                  marginBottom: 8,
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                }}
              >
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
              </h3>
              {renderGrid(day.items, true)}
            </section>
          );
        })}

      {detail && (
        <AnimeDetailModal
          title={detail.subject.name}
          titleCn={detail.subject.name_cn}
          coverUrl={detail.subject.images?.medium}
          score={detail.subject.rating?.score}
          date={detail.subject.air_date}
          summary={detail.subject.summary}
          status={detail.status}
          bangumiId={detail.subject.id}
          watchTitle={detail.subject.name_cn || detail.subject.name}
          onClose={() => setDetail(null)}
        />
      )}
    </main>
  );
}
