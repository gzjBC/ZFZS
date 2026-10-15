/**
 * PostgreSQL 连接池：业务代码用 getPool() 单例，测试注入独立连接。
 * DATABASE_URL 未配置时默认连本地 docker-compose 的 anime_tracker 库，
 * 保证 clone 下来零配置即可启动（AI Key 等仍需 .env.local）。
 */
import { Pool } from "pg";

const DEFAULT_DATABASE_URL = "postgres://anime:anime@localhost:5432/anime_tracker";

export function createPool(
  connectionString: string = process.env.DATABASE_URL || DEFAULT_DATABASE_URL,
): Pool {
  return new Pool({ connectionString });
}

let sharedPool: Pool | undefined;

/** 应用级单例连接池 */
export function getPool(): Pool {
  if (!sharedPool) {
    sharedPool = createPool();
  }
  return sharedPool;
}
