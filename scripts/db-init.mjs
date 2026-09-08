#!/usr/bin/env node
/**
 * 数据库初始化（幂等，可反复运行）：
 *  1. 确保主库表结构存在（执行 src/lib/db/schema.sql，CREATE IF NOT EXISTS）
 *  2. 确保测试库 anime_tracker_test 存在并建好同样的表结构（供 npm run test）
 *
 * 用法：
 *  npm run db:init            # 用 .env.local 的 DATABASE_URL（默认本地 anime_tracker）
 *  DATABASE_URL=xxx npm run db:init
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCHEMA_FILE = path.resolve(__dirname, "../src/lib/db/schema.sql");
const DEFAULT_DATABASE_URL = "postgres://anime:anime@localhost:5432/anime_tracker";
const TEST_DB_NAME = "anime_tracker_test";

async function applySchema(client, label) {
  const schema = readFileSync(SCHEMA_FILE, "utf-8");
  await client.query(schema);
  console.log(`✓ ${label}表结构已就绪（tracking 等）`);
}

async function main() {
  const url = process.env.DATABASE_URL || DEFAULT_DATABASE_URL;
  const mainClient = new pg.Client({ connectionString: url });
  await mainClient.connect();
  const mainDb = new URL(url).pathname.slice(1) || "anime_tracker";
  console.log(`连接主库 ${mainDb} …`);
  await applySchema(mainClient, `主库 ${mainDb} `);

  // 确保测试库存在（跑 npm run test 需要）
  const testUrl = new URL(url);
  testUrl.pathname = `/${TEST_DB_NAME}`;
  const { rowCount } = await mainClient.query(
    "SELECT 1 FROM pg_database WHERE datname = $1",
    [TEST_DB_NAME],
  );
  if (rowCount === 0) {
    await mainClient.query(`CREATE DATABASE ${TEST_DB_NAME}`);
    console.log(`✓ 已创建测试库 ${TEST_DB_NAME}`);
  } else {
    console.log(`✓ 测试库 ${TEST_DB_NAME} 已存在`);
  }
  await mainClient.end();

  const testClient = new pg.Client({ connectionString: testUrl.href });
  await testClient.connect();
  await applySchema(testClient, `测试库 ${TEST_DB_NAME} `);
  await testClient.end();

  console.log("\n完成。可以启动开发服务器：npm run dev");
}

main().catch((err) => {
  console.error(`✗ 数据库初始化失败：${err.message}`);
  console.error("  请确认：1) Docker Desktop 已启动  2) 已执行 docker compose up -d  3) 端口/密码与连接串一致");
  process.exit(1);
});
