import { describe, expect, it, vi } from "vitest";
import { resetCache, withCache } from "@/lib/cache";

describe("withCache", () => {
  it("首次调用执行 loader，TTL 内再次调用直接命中", async () => {
    resetCache();
    const loader = vi.fn().mockResolvedValue("value");
    const first = await withCache("k1", 60_000, loader);
    const second = await withCache("k1", 60_000, loader);
    expect(first).toBe("value");
    expect(second).toBe("value");
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("过期后重新执行 loader", async () => {
    resetCache();
    vi.useFakeTimers();
    try {
      const loader = vi.fn().mockResolvedValue("v");
      await withCache("k2", 1_000, loader);
      vi.advanceTimersByTime(1_001);
      await withCache("k2", 1_000, loader);
      expect(loader).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("不同 key 互不影响", async () => {
    resetCache();
    const loaderA = vi.fn().mockResolvedValue("a");
    const loaderB = vi.fn().mockResolvedValue("b");
    await withCache("ka", 60_000, loaderA);
    await withCache("kb", 60_000, loaderB);
    await withCache("ka", 60_000, loaderA);
    expect(loaderA).toHaveBeenCalledTimes(1);
    expect(loaderB).toHaveBeenCalledTimes(1);
  });
});
