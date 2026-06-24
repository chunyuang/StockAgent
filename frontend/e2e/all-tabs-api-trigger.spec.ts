/**
 * 扫所有 Tab: 切到 Tab 后是否触发了 API 请求
 * 真正的"自动加载"判定 = 看 fetch 调用,不看 DOM
 */
import { test } from '@playwright/test';
import fs from 'fs';

test.setTimeout(180000);

test('扫所有Tab自动触发API请求', async ({ page }) => {
  const requestsByTab: Record<string, string[]> = {};
  let currentTab = 'init';

  page.on('request', req => {
    const url = req.url();
    // 只关心 /api 业务请求
    if (!url.includes('/api/')) return;
    // 过滤掉公共请求
    if (url.includes('/api/v1/scanner/status') ||
        url.includes('/api/v1/scanner/account') ||
        url.includes('/api/v1/scanner/state')) return;
    if (!requestsByTab[currentTab]) requestsByTab[currentTab] = [];
    requestsByTab[currentTab].push(url.replace(/^https?:\/\/[^/]+/, ''));
  });

  await page.goto('http://localhost:5174/monitor', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  // 切到一个明显不需要 fetch 的初始 Tab,再切到目标 Tab,这样 currentTab 切换准
  const tabs = ['行情', '盘前', '实盘', '复盘', '情绪', '分析', '账户', '运维', '扫描追踪', '历史'];

  for (const tabName of tabs) {
    const tabBtn = page.locator(`text=${tabName}`).first();
    if ((await tabBtn.count()) === 0) continue;
    if (!await tabBtn.isVisible().catch(() => false)) continue;

    currentTab = tabName;
    requestsByTab[tabName] = [];
    
    try {
      await tabBtn.click({ timeout: 5000 });
    } catch (e) {
      console.warn(`[${tabName}] 点击失败`);
      continue;
    }
    await page.waitForTimeout(2500);

    const calls = requestsByTab[tabName] || [];
    console.log(`\n📂 [${tabName}] 触发了 ${calls.length} 个业务 API:`);
    const uniq = Array.from(new Set(calls)).slice(0, 6);
    uniq.forEach(c => console.log(`   - ${c}`));
  }

  fs.writeFileSync('/tmp/tab-api-trigger-scan.json', JSON.stringify(requestsByTab, null, 2));
  console.log(`\n📊 报告: /tmp/tab-api-trigger-scan.json`);
});
