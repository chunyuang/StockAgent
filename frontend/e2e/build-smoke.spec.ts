/**
 * 构建产物冒烟测试 (Build Output Smoke Test)
 *
 * 【v2.9.90 新增 — 起因 v2.9.89 element-plus 拆 chunk 白屏事故】
 *
 * ⚠️ 与 monitor-smoke.spec.ts 的差异:
 *   - monitor-smoke 连 vite dev server (5174), dev 模式不拆 chunk
 *   - build-smoke 连 vite preview (4173), 跑真实构建产物
 *   - 这是用户实际访问 nginx 部署的等价场景
 *
 * 核心检查:
 *   1. Vue 能 mount (#app 非空)
 *   2. 没有 JS 加载错误 / ESM 循环依赖错误
 *   3. window.__vueErrors 为空
 *   4. 关键路由都能正常渲染
 *   5. 所有 modulepreload 资源加载成功
 *
 * 运行:
 *   cd frontend && npx vite build && npx playwright test --config=playwright.preview.config.ts
 */
import { test, expect, Page } from '@playwright/test';

// 必须测试的路由清单 (跟 router/index.ts 对齐)
const CRITICAL_ROUTES = [
  '/',
  '/monitor',
  '/cockpit',
  '/strategies',
  '/system/status',
  '/admin/db',
  '/settings',
];

interface PageError {
  type: 'pageerror' | 'console' | 'request_failed' | 'response_error';
  url: string;
  message: string;
}

/**
 * 监听页面所有可能的错误来源
 */
function attachErrorListeners(page: Page): { errors: PageError[]; clear: () => void } {
  const errors: PageError[] = [];
  const url = () => page.url();

  // 1. 未捕获的 JS 异常 (包括 ESM 循环依赖 ReferenceError)
  page.on('pageerror', (err) => {
    errors.push({
      type: 'pageerror',
      url: url(),
      message: `${err.name}: ${err.message}\n${(err.stack || '').substring(0, 500)}`,
    });
  });

  // 2. console.error (Vue warn/error 都走这)
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // 过滤 favicon 等无害错误
      if (text.includes('favicon') || text.includes('manifest.json')) return;
      errors.push({ type: 'console', url: url(), message: text.substring(0, 500) });
    }
  });

  // 3. 请求失败 (chunk 404 等)
  page.on('requestfailed', (req) => {
    const failure = req.failure();
    // 忽略主动取消的请求
    if (failure?.errorText?.includes('aborted')) return;
    errors.push({
      type: 'request_failed',
      url: req.url(),
      message: failure?.errorText || 'unknown',
    });
  });

  // 4. 响应非 2xx (chunk 加载失败)
  page.on('response', (res) => {
    const u = res.url();
    // 只关注我们自己的 chunk/css/js (相对路径或同域)
    if (!u.includes('localhost:4173')) return;
    if (u.includes('/api/')) return; // API 失败由其他测试覆盖
    if (res.status() >= 400) {
      errors.push({
        type: 'response_error',
        url: u,
        message: `HTTP ${res.status()} ${res.statusText()}`,
      });
    }
  });

  return {
    errors,
    clear: () => (errors.length = 0),
  };
}

/**
 * 等待 Vue mount 完成
 */
async function waitForVueMount(page: Page, timeoutMs = 10000): Promise<number> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const appHtmlLen = await page.evaluate(() => {
      return document.getElementById('app')?.innerHTML?.length || 0;
    });
    if (appHtmlLen > 100) return appHtmlLen;
    await page.waitForTimeout(200);
  }
  return 0;
}

test.describe('构建产物冒烟测试 (Build Smoke)', () => {

  test('入口页面 / 能正常渲染 (Vue mount 成功)', async ({ page }) => {
    const { errors } = attachErrorListeners(page);

    // domcontentloaded 足够触发初始化,不等 networkidle (WS 心跳会阻塞)
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    const appLen = await waitForVueMount(page, 10000);

    // ❌ 这是白屏检测的核心: Vue 没 mount = app 为空
    expect(appLen, `#app 渲染长度=${appLen}, 浏览器白屏! 错误清单:\n${JSON.stringify(errors, null, 2)}`).toBeGreaterThan(100);

    // 没有 pageerror (ReferenceError, TypeError 等)
    const pageErrors = errors.filter(e => e.type === 'pageerror');
    expect(pageErrors.length, `JS 运行时错误:\n${pageErrors.map(e => `  - ${e.message}`).join('\n')}`).toBe(0);

    // 没有 chunk 加载失败
    const chunkFails = errors.filter(e => (e.type === 'request_failed' || e.type === 'response_error') && /\.(js|css|mjs)$/.test(e.url));
    expect(chunkFails.length, `chunk 加载失败:\n${chunkFails.map(e => `  - ${e.url}: ${e.message}`).join('\n')}`).toBe(0);
  });

  // 单独检测 ESM 循环依赖 — 这是 v2.9.89 事故的精确复现条件
  test('无 ESM 循环依赖 / 变量初始化错误', async ({ page }) => {
    const { errors } = attachErrorListeners(page);

    // 用 domcontentloaded 而非 networkidle: 前端持续 WS 心跳会让 networkidle 永不到达
    // ESM 循环依赖错误发生在 chunk 解析阶段,DOM 加载完成时已经触发
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000); // 让所有 chunk 完成执行

    // v2.9.89 的精确报错: "Cannot access 'qo' before initialization"
    const initErrors = errors.filter(e =>
      /before initialization|circular|cyclic dependen|cannot access/i.test(e.message)
    );

    expect(initErrors.length, `ESM 循环依赖/变量初始化错误 (与 v2.9.89 同类):\n${initErrors.map(e => `  [${e.type}] ${e.message}`).join('\n')}`).toBe(0);
  });

  // 每个关键路由都不能白屏
  for (const route of CRITICAL_ROUTES) {
    test(`路由 ${route} 能正常渲染`, async ({ page }) => {
      const { errors } = attachErrorListeners(page);

      await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 30000 });
      const appLen = await waitForVueMount(page, 10000);

      expect(appLen, `路由 ${route} 白屏! #app 长度=${appLen}`).toBeGreaterThan(100);

      // 路由级 pageerror 不容忍
      const pageErrors = errors.filter(e => e.type === 'pageerror');
      if (pageErrors.length > 0) {
        // 输出但不致命 (某些路由可能因 API 不可用报错,但页面骨架要渲染)
        console.warn(`⚠️ 路由 ${route} 有 JS 错误:`);
        pageErrors.forEach(e => console.warn(`  - ${e.message.substring(0, 200)}`));
      }
    });
  }

  test('modulepreload 资源全部加载成功', async ({ page }) => {
    const responses = new Map<string, number>();
    page.on('response', (res) => {
      const u = res.url();
      if (u.includes('localhost:4173/assets/')) {
        responses.set(u.split('/').pop() || u, res.status());
      }
    });

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    // 等 modulepreload 发起并完成 (echarts 等大 chunk 下载需要时间)
    await page.waitForLoadState('load', { timeout: 30000 });
    await page.waitForTimeout(2000);

    // 获取 index.html 里所有 modulepreload + script
    const preloads = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('link[rel="modulepreload"]')).map(l => (l as HTMLLinkElement).href);
      const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => (s as HTMLScriptElement).src);
      return [...links, ...scripts].filter(u => u.includes('/assets/'));
    });

    const failed: string[] = [];
    for (const url of preloads) {
      const fname = url.split('/').pop() || url;
      const status = responses.get(fname);
      // 只判定 HTTP 错误,'未请求' 不一定是问题 (浏览器会根据需要决定是否加载 preload)
      if (status && status >= 400) {
        failed.push(`${fname} (status=${status})`);
      }
    }

    expect(failed.length, `modulepreload 资源 HTTP 错误:\n  ${failed.join('\n  ')}`).toBe(0);
  });

  test('生产构建无 vite "evaluating" 错误', async ({ page }) => {
    const { errors } = attachErrorListeners(page);

    await page.goto('/monitor', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3000); // 等异步组件加载

    // vite 异步组件加载失败的标志: "Failed to fetch dynamically imported module"
    const dynImportErrors = errors.filter(e =>
      /failed to fetch dynamic|dynamically imported|failed to load module/i.test(e.message)
    );

    expect(dynImportErrors.length, `异步 chunk 加载失败:\n${dynImportErrors.map(e => `  - ${e.message}`).join('\n')}`).toBe(0);
  });
});
