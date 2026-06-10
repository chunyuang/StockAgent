/**
 * Playwright 配置 — 生产构建产物冒烟测试
 *
 * 【v2.9.90 新增】专门用于验证 `vite build` 产物在浏览器中能正常运行
 * 起因：v2.9.89 element-plus 拆 chunk 后子模块间 ESM 循环依赖 → 浏览器白屏
 *      dev server (端口 5174) 不做 chunk 拆分,完全没暴露问题
 *      普通 E2E 没拦住 → 必须用 vite preview 跑构建产物
 *
 * 运行：
 *   npm run build           # 先必须 build
 *   npx playwright test --config=playwright.preview.config.ts
 */
import { defineConfig } from '@playwright/test';

const PREVIEW_PORT = 4173;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/build-smoke.spec.ts', // 只跑构建产物冒烟
  timeout: 60000,
  expect: { timeout: 10000 },
  fullyParallel: false,
  retries: 0, // 白屏是确定性问题,失败就是失败,不要 retry 掩盖
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PREVIEW_PORT}`,
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: {
    // vite preview 服务的是 dist/ 真实构建产物,等价于用户访问 nginx 的体验
    command: `npx vite preview --port ${PREVIEW_PORT} --strictPort`,
    port: PREVIEW_PORT,
    reuseExistingServer: false, // 必须用 fresh server,避免老 dist 残留
    timeout: 30000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
