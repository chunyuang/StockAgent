/**
 * 扫所有 Tab 的"需手动刷新"提示
 * 重用 all-tabs-trading-check 的稳定模式
 */
import { test } from '@playwright/test';
import fs from 'fs';

const MONITOR_URL = 'http://localhost:5174/monitor';

test.setTimeout(180000);

const NEED_REFRESH_PATTERNS = [
  /点击刷新加载数据/,
  /请点击.*?刷新/,
  /请.*?手动.*?加载/,
  /点击.*?按钮.*?加载/,
];

interface TabResult {
  name: string;
  contentLen: number;
  needRefreshHits: string[];
  bodyTextSnippet: string;
}

test('扫所有Tab是否有需手动刷新的提示', async ({ page }) => {
  const reports: TabResult[] = [];

  await page.goto(MONITOR_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);

  const tabs = ['行情', '盘前', '实盘', '复盘', '情绪', '分析', '账户', '运维', '扫描追踪', '历史'];

  for (const tabName of tabs) {
    const tabBtn = page.locator(`text=${tabName}`).first();
    if ((await tabBtn.count()) === 0) continue;
    if (!await tabBtn.isVisible().catch(() => false)) continue;

    console.log(`\n📂 切到 [${tabName}]...`);
    try {
      await tabBtn.click({ timeout: 5000 });
    } catch (e) {
      console.warn(`  ⚠️ 点击失败: ${e}`);
      continue;
    }
    await page.waitForTimeout(3000);

    const body = page.locator('.mm-body, .mm-content, .mm-main, .mm').first();
    const bodyText = await body.innerText().catch(() => '');

    const hits: string[] = [];
    for (const pat of NEED_REFRESH_PATTERNS) {
      const m = bodyText.match(pat);
      if (m) hits.push(m[0]);
    }

    reports.push({
      name: tabName,
      contentLen: bodyText.length,
      needRefreshHits: hits,
      bodyTextSnippet: bodyText.slice(0, 200).replace(/\s+/g, ' '),
    });

    console.log(`   len=${bodyText.length} needRefreshHits=${JSON.stringify(hits)}`);
  }

  fs.writeFileSync('/tmp/tab-empty-state-scan.json', JSON.stringify(reports, null, 2));
  console.log(`\n📊 报告写入: /tmp/tab-empty-state-scan.json`);

  const bad = reports.filter(r => r.needRefreshHits.length > 0);
  if (bad.length) {
    console.log(`\n🚨 ${bad.length} 个 Tab 有"需手动刷新"提示:`);
    bad.forEach(b => console.log(`   - ${b.name}: ${JSON.stringify(b.needRefreshHits)}`));
  } else {
    console.log(`\n✅ 所有 Tab 默认自动加载,无需手动刷新`);
  }
});
