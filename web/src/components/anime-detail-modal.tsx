"use client";

/**
 * 番剧详情弹窗：点卡片弹出，展示封面/简介/标签/评分/链接，
 * 懒人不用跳外站就能决定"看不看"。
 */
interface AnimeDetailModalProps {
  title: string;
  titleCn?: string | null;
  coverUrl?: string | null;
  score?: number | null;
  date?: string | null;
  tags?: string[];
  summary?: string | null;
  status?: string | null;
  bangumiId?: number | null;
  watchTitle?: string | null;
  onClose: () => void;
}

export default function AnimeDetailModal({
  title,
  titleCn,
  coverUrl,
  score,
  date,
  tags,
  summary,
  bangumiId,
  watchTitle,
  onClose,
}: AnimeDetailModalProps) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        style={{
          maxWidth: 520,
          width: "100%",
          maxHeight: "80vh",
          overflowY: "auto",
          background: "#FFFFFF",
          borderRadius: 16,
          padding: 20,
          display: "flex",
          gap: 16,
        }}
      >
        {coverUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={coverUrl}
            alt={titleCn || title}
            style={{
              width: 120,
              height: 160,
              objectFit: "cover",
              borderRadius: 10,
              flexShrink: 0,
            }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4, lineHeight: 1.4 }}>
            {titleCn || title}
          </h2>
          {titleCn && titleCn !== title && (
            <p style={{ fontSize: 12, color: "#6B7280", marginBottom: 6 }}>{title}</p>
          )}
          <div style={{ fontSize: 12, color: "#6B7280", marginBottom: 8 }}>
            {score ? `评分 ${Number(score).toFixed(1)}` : "暂无评分"}
            {date ? ` · ${date}` : ""}
          </div>
          {(tags ?? []).length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
              {(tags ?? []).slice(0, 8).map((tag) => (
                <span
                  key={tag}
                  style={{
                    fontSize: 11,
                    padding: "1px 8px",
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
          {summary ? (
            <p
              style={{
                fontSize: 13,
                color: "#374151",
                lineHeight: 1.7,
                maxHeight: 180,
                overflowY: "auto",
                marginBottom: 12,
              }}
            >
              {summary}
            </p>
          ) : (
            <p style={{ fontSize: 13, color: "#9CA3AF", marginBottom: 12 }}>
              暂无简介（可在 Bangumi 条目页查看）
            </p>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {bangumiId && (
              <a
                href={`https://bgm.tv/subject/${bangumiId}`}
                target="_blank"
                rel="noreferrer"
                style={{
                  padding: "6px 12px",
                  borderRadius: 8,
                  border: "1px solid #E4E3DD",
                  background: "#FFFFFF",
                  fontSize: 13,
                  color: "#1A1B1C",
                  textDecoration: "none",
                }}
              >
                Bangumi 条目 ↗
              </a>
            )}
            {watchTitle && (
              <a
                href={`https://search.bilibili.com/bangumi?keyword=${encodeURIComponent(watchTitle)}`}
                target="_blank"
                rel="noreferrer"
                style={{
                  padding: "6px 12px",
                  borderRadius: 8,
                  background: "#F0FDF4",
                  border: "1px solid #BBF7D0",
                  color: "#15803D",
                  fontSize: 13,
                  textDecoration: "none",
                }}
              >
                ▶ 去观看
              </a>
            )}
            <button
              onClick={onClose}
              style={{
                padding: "6px 12px",
                borderRadius: 8,
                border: "1px solid #E4E3DD",
                background: "#FFFFFF",
                fontSize: 13,
                cursor: "pointer",
                marginLeft: "auto",
              }}
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
