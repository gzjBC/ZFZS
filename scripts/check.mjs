#!/usr/bin/env node
/**
 * 一键验收门：lint + typecheck + test，全绿才算模块完成。
 * 任一环节失败立即以非 0 退出，并给出失败环节。
 */
import { execSync } from "node:child_process";

const steps = [
  { name: "ESLint", cmd: "npm run lint" },
  { name: "TypeScript 类型检查", cmd: "npm run typecheck" },
  { name: "Vitest 测试", cmd: "npm run test" },
];

for (const step of steps) {
  process.stdout.write(`\n▶ ${step.name} ...\n`);
  try {
    execSync(step.cmd, { stdio: "inherit" });
  } catch {
    console.error(`\n✘ ${step.name} 未通过，验收门拦截。`);
    process.exit(1);
  }
}

console.log("\n✔ 验收门全部通过：lint + typecheck + test 全绿");
