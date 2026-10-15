/**
 * 通用 TTL 内存缓存（无框架依赖，单实例本地用）。
 * 上公网多实例时替换为 Redis 实现，接口签名不变——调用方无需改动。
 */

type CacheEntry = { expiresAt: number; value: unknown };

const store = new Map<string, CacheEntry>();

export async function withCache<T>(
  key: string,
  ttlMs: number,
  loader: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const hit = store.get(key);
  if (hit && hit.expiresAt > now) {
    return hit.value as T;
  }
  const value = await loader();
  store.set(key, { expiresAt: now + ttlMs, value });
  return value;
}

/** 仅测试用：清空缓存，避免用例间相互污染 */
export function resetCache(): void {
  store.clear();
}
