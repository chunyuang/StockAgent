/**
 * 验证: 数据分析 Tab 打开后自动加载,不再显示"点击刷新加载数据"
 */
import { test, expect } from '@playwright/test';

test('分析Tab打开自动加载,无ana-empty', async ({ page }) => {
  await page.goto('http://localhost:5174/monitor', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // 切到 数据分析
  await page.locator('text=数据分析').first().click();
  await page.waitForTimeout(4000);  // 等 fetchAnalysis 完成

  // 截图
  await page.screenshot({ path: '/tmp/analysis-tab-after-fix.png' });

  // 不应有 ana-empty 提示
  const emptyHint = await page.locator('text=点击刷新加载数据').count();
  console.log(`'点击刷新加载数据' 出现次数: ${emptyHint}`);

  // 不应有"加载中..."卡住 (4s 后应该已加载完)
  const loadingHint = await page.locator('.ana-loading').count();
  console.log(`'.ana-loading' 元素数: ${loadingHint}`);

  // 应该有 KPI 卡片或'暂无数据'
  const kpiStrip = await page.locator('.kpi-strip').count();
  const emptyData = await page.locator('text=暂无,text=无数据').count();
  console.log(`.kpi-strip 数: ${kpiStrip}, 暂无数据元素: ${emptyData}`);

  expect(emptyHint).toBe(0);  // 关键: 不能再出现"点击刷新加载数据"
  expect(loadingHint).toBe(0);  // 不应卡在加载中
});
