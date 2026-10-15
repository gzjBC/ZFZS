#!/usr/bin/env node
/** Read-only Web PostgreSQL -> versioned native desktop JSON export. */
import { writeFile, link, unlink, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import pg from "pg";

const MAX_ITEMS = 10_000;
const MAX_BYTES = 20 * 1024 * 1024;
const STATUS = { wish: "paused", hold: "paused", watching: "watching", completed: "finished" };

function integer(value, field, nullable = false) {
  if (value == null && nullable) return null;
  if (!Number.isSafeInteger(value) || value < 0 || value > 1_000_000) throw new Error(`Invalid ${field}`);
  return value;
}

function text(value, field, maximum, required = false) {
  if (value == null && !required) return null;
  if (typeof value !== "string" || value.length > maximum || (required && !value.trim())) throw new Error(`Invalid ${field}`);
  return value;
}

function timestamp(value, field, nullable = false) {
  if (value == null && nullable) return null;
  if (value == null) throw new Error(`Missing ${field}`);
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error(`Invalid ${field}`);
  return date.toISOString();
}

function coverUrl(value) {
  if (value == null || value === "") return null;
  const url = new URL(text(value, "cover_url", 4096));
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Invalid cover URL");
  return url.href;
}

/** Convert only the source library fields, never configuration or credentials. */
export function toDesktopExport(rows, now = new Date()) {
  if (!Array.isArray(rows) || rows.length > MAX_ITEMS) throw new Error("Too many records");
  const seen = new Set();
  const items = rows.map((row) => {
    if (!row || typeof row !== "object" || !Number.isSafeInteger(row.bangumi_subject_id) || row.bangumi_subject_id <= 0) throw new Error("Invalid subject ID");
    const sourceId = String(row.bangumi_subject_id);
    if (seen.has(sourceId)) throw new Error("Duplicate subject ID");
    seen.add(sourceId);
    if (!Object.hasOwn(STATUS, row.status)) throw new Error("Invalid watching status");
    const watched = integer(row.episode_progress, "episode_progress");
    const total = integer(row.total_episodes, "total_episodes", true);
    const rating = row.rating == null ? null : Number(row.rating);
    if (row.rating === "" || typeof row.rating === "boolean" || (rating != null && (!Number.isFinite(rating) || rating < 0 || rating > 10))) throw new Error("Invalid personal rating");
    const title = text(row.title, "title", 255, true);
    const titleCn = text(row.title_cn, "title_cn", 255);
    const tags = row.tags ?? [];
    if (!Array.isArray(tags) || tags.some((tag) => typeof tag !== "string")) throw new Error("Invalid tags");
    const joinedTags = tags.length ? text(tags.join(","), "tags", 10_000) : null;
    let year = null;
    if (row.air_date != null) {
      const candidate = row.air_date instanceof Date ? row.air_date.getFullYear() : Number(String(row.air_date).slice(0, 4));
      if (Number.isInteger(candidate) && candidate >= 1900 && candidate <= 2200) year = candidate;
    }
    const sourceUrl = `https://bgm.tv/subject/${sourceId}`;
    return {
      title: titleCn?.trim() || title,
      title_cn: titleCn,
      cover_url: coverUrl(row.cover_url),
      summary: text(row.summary, "summary", 100_000),
      status: STATUS[row.status],
      broadcast_day: null,
      broadcast_time: "20:00",
      reminder_enabled: false,
      reminder_minutes: 15,
      watched_episodes: watched,
      // Preserve real watched progress when legacy totals are stale.
      total_episodes: total != null && total < watched ? null : total,
      play_url: sourceUrl,
      source: "bangumi",
      source_id: sourceId,
      source_url: sourceUrl,
      source_status: row.status === "wish" ? "从 Web 想看清单迁入" : "从 Web 追番清单迁入",
      year,
      score: null,
      user_rating: rating,
      tags: joinedTags,
      last_reminded_at: null,
      completed_at: timestamp(row.completed_at, "completed_at", true),
      created_at: timestamp(row.created_at, "created_at"),
      updated_at: timestamp(row.updated_at, "updated_at"),
    };
  });
  const document = { format: "zfzs-library", version: 1, exported_at: timestamp(now, "exported_at"), items };
  if (Buffer.byteLength(JSON.stringify(document)) > MAX_BYTES) throw new Error("Export too large");
  return document;
}

async function main() {
  if (process.argv.length !== 3 || path.extname(process.argv[2]).toLowerCase() !== ".json") throw new Error("Usage: node scripts/export-desktop.mjs /path/to/new-export.json");
  const output = path.resolve(process.argv[2]);
  const pool = new pg.Pool({
    connectionString: process.env.DATABASE_URL || "postgres://anime:anime@localhost:5432/anime_tracker",
    connectionTimeoutMillis: 5000,
    options: "-c default_transaction_read_only=on -c statement_timeout=15000",
  });
  let document;
  try {
    const result = await pool.query(
      "SELECT bangumi_subject_id, title, title_cn, cover_url, summary, status, episode_progress, total_episodes, rating, air_date, tags, completed_at, created_at, updated_at FROM tracking ORDER BY id LIMIT 10001",
    );
    document = toDesktopExport(result.rows);
  } finally {
    await pool.end();
  }
  await mkdir(path.dirname(output), { recursive: true });
  const content = JSON.stringify(document, null, 2) + "\n";
  if (Buffer.byteLength(content) > MAX_BYTES) throw new Error("Export too large");
  const temporary = path.join(path.dirname(output), `.zfzs-export-${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, content, { flag: "wx", mode: 0o600 });
    // Atomic and no overwrite: an existing destination is never replaced.
    await link(temporary, output);
  } finally {
    await unlink(temporary).catch(() => {});
  }
  console.log(`Exported ${document.items.length} records. Import this JSON from the desktop data menu.`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const code = typeof error.code === "string" && /^[A-Z0-9_]{1,20}$/.test(error.code) ? error.code : "VALIDATION_OR_CONNECTION";
    console.error(`Export failed (${code}). Check the database connection, data validity and new .json destination.`);
    process.exitCode = 1;
  });
}
