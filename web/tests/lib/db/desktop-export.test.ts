import { describe, expect, it } from "vitest";
import { toDesktopExport } from "../../../scripts/export-desktop.mjs";

const row = {
  bangumi_subject_id: 42, title: "Original", title_cn: "中文作品",
  cover_url: null, summary: "Summary", status: "completed",
  episode_progress: 12, total_episodes: 12, rating: "9.5", air_date: "2026-01-01",
  tags: ["治愈", "日常"], completed_at: new Date("2026-10-01T10:00:00Z"),
  created_at: new Date("2026-01-01T00:00:00Z"), updated_at: new Date("2026-10-01T10:00:00Z"),
};

describe("desktop data export", () => {
  it("maps personal ratings, progress and identity into the native format", () => {
    const exported = toDesktopExport([{ ...row, api_key: "never-export-this" }]);
    expect(exported.format).toBe("zfzs-library");
    expect(exported.version).toBe(1);
    expect(exported.items[0]).toMatchObject({
      title: "中文作品", source: "bangumi", source_id: "42", status: "finished",
      watched_episodes: 12, total_episodes: 12, user_rating: 9.5, score: null,
      reminder_enabled: false, tags: "治愈,日常",
    });
    expect(JSON.stringify(exported)).not.toContain("never-export-this");
  });

  it("keeps wish/hold inactive and preserves progress exceeding stale totals", () => {
    const exported = toDesktopExport([
      { ...row, status: "wish", episode_progress: 13 },
      { ...row, bangumi_subject_id: 43, status: "hold" },
    ]);
    expect(exported.items[0].status).toBe("paused");
    expect(exported.items[0].total_episodes).toBeNull();
    expect(exported.items[0].watched_episodes).toBe(13);
    expect(exported.items[1].status).toBe("paused");
  });

  it("refuses invalid identity, ratings and credentials in cover URLs", () => {
    for (const invalid of [
      { ...row, rating: "NaN" }, { ...row, bangumi_subject_id: 0 },
      { ...row, cover_url: "https://user:secret@example.com/image.png" },
      { ...row, status: "unknown" },
    ]) expect(() => toDesktopExport([invalid])).toThrow();
    expect(() => toDesktopExport([row, row])).toThrow();
  });
});
