"use client";

import { useState } from "react";
import { getStatusBadge, isStatusKey } from "@/lib/ui/status";

/**
 * 番剧卡片：纯展示组件，供日历/季度/清单页面复用。
 * 只接收 props，不发起任何请求；图片加载失败时降级为占位块。
 */
interface AnimeCardProps {
  title: string;
  titleCn?: string | null;
  coverUrl?: string | null;
  score?: number | null;
  date?: string | null;
  /** 类型标签（最多展示前 3 个） */
  tags?: string[];
  /** 追番状态（wish/watching/completed/hold），传入则显示徽章 */
  status?: string | null;
  /** Bangumi 条目 id，传入后标题可点击跳转条目页（bgm.tv/subject/{id}，新标签打开） */
  bangumiId?: number | null;
  /** 观看搜索标题：传入后显示「去观看」链接（B站番剧搜索，新标签打开） */
  watchTitle?: string | null;
  /** 点击卡片主体（非链接/按钮）时触发，用于打开详情弹窗 */
  onDetail?: () => void;
  extra?: React.ReactNode;
}

export default function AnimeCard({
  title,
  titleCn,
  coverUrl,
  score,
  date,
  tags,
  status,
  bangumiId,
  watchTitle,
  onDetail,
  extra,
}: AnimeCardProps) {
  const [imgError, setImgError] = useState(false);
  const badge = isStatusKey(status) ? getStatusBadge(status) : null;
  const showCover = Boolean(coverUrl) && !imgError;
  const showTags = (tags ?? []).slice(0, 3);

  return (
    <div
      onClick={onDetail}
      onKeyDown={(e) => e.key === "Enter" && onDetail?.()}
      role={onDetail ? "button" : undefined}
      tabIndex={onDetail ? 0 : undefined}
      style={{
        border: "1px solid #E4E3DD",
        borderRadius: 12,
        overflow: "hidden",
        background: "#FFFFFF",
        display: "flex",
        flexDirection: "column",
        cursor: onDetail ? "pointer" : "default",
      }}
    >
      {showCover ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={coverUrl as string}
          alt={titleCn || title}
          onError={() => setImgError(true)}
          style={{
            width: "100%",
            aspectRatio: "3/4",
            objectFit: "cover",
            display: "block",
            background: "#F3F4F6",
          }}
        />
      ) : (
        <div
          style={{
            width: "100%",
            aspectRatio: "3/4",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "linear-gradient(135deg, #F3F4F6, #E5E7EB)",
            color: "#9CA3AF",
            fontSize: 28,
            fontWeight: 600,
          }}
        >
          {(titleCn || title || "?").charAt(0)}
        </div>
      )}
      <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {bangumiId ? (
            <a
              href={`https://bgm.tv/subject/${bangumiId}`}
              target="_blank"
              rel="noreferrer"
              title="在 Bangumi 查看条目与放送链接"
              style={{
                fontSize: 13,
                fontWeight: 600,
                lineHeight: 1.4,
                color: "#1A1B1C",
                textDecoration: "none",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "#2563EB")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "#1A1B1C")}
              onClick={(e) => e.stopPropagation()}
            >
              {titleCn || title}
              <span style={{ fontSize: 11, color: "#6B7280", marginLeft: 2 }}>↗</span>
            </a>
          ) : (
            <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4 }}>
              {titleCn || title}
            </span>
          )}
          {badge && (
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
          )}
        </div>
        {titleCn && titleCn !== title && (
          <div style={{ fontSize: 12, color: "#6B7280" }}>{title}</div>
        )}
        {showTags.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {showTags.map((tag) => (
              <span
                key={tag}
                style={{
                  fontSize: 11,
                  padding: "0 6px",
                  borderRadius: 6,
                  background: "#F3F4F6",
                  color: "#4B5563",
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}
        <div style={{ fontSize: 12, color: "#6B7280", marginTop: "auto" }}>
          {score ? `评分 ${Number(score).toFixed(1)}` : "暂无评分"}
          {date ? ` · ${date}` : ""}
        </div>
        {watchTitle && (
          <a
            href={`https://search.bilibili.com/bangumi?keyword=${encodeURIComponent(watchTitle)}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{
              marginTop: 4,
              padding: "4px 10px",
              borderRadius: 8,
              background: "#F0FDF4",
              border: "1px solid #BBF7D0",
              color: "#15803D",
              fontSize: 12,
              textAlign: "center",
              textDecoration: "none",
              display: "block",
            }}
          >
            ▶ 去观看
          </a>
        )}
        {extra}
      </div>
    </div>
  );
}
