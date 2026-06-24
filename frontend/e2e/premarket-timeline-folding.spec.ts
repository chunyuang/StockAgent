/**
 * 验证: 竞价时间线 1) 默认折叠 2) 数据未就绪有标识 3) 阶段着色
 */
import { test, expect } from '@playwright/test';

test.setTimeout(60000);

test('竞价时间线-折叠+阶段着色', async ({ page }) => {
  await page.goto('http://localhost:5174/monitor', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  // 切到 盘前
  await page.locator('text=盘前').first().click();
  await page.waitForTimeout(4000);

  await page.screenshot({ path: '/tmp/premarket-timeline-folded.png', fullPage: true });

  // 检查默认折叠 — 所有 .pm-tl-detail 应该都 hidden
  const rows = await page.locator('.pm-tl-row').count();
  const expandedDetails = await page.locator('.pm-tl-detail:visible').count();
  console.log(`rows=${rows}, expandedDetails=${expandedDetails}`);

  // 检查阶段标签
  const phaseTagSamples = await page.locator('.pm-phase-tag').allInnerTexts();
  console.log(`phase tags (head): ${phaseTagSamples.slice(0, 5).join(' | ')}`);

  // 检查"数据未就绪"标签
  const invalidCount = await page.locator('.pm-invalid-tag').count();
  console.log(`数据未就绪标签数: ${invalidCount}`);

  // 检查阶段着色 (border-left)
  const phaseClassCounts: Record<string, number> = {};
  for (const cls of ['pm-phase-free', 'pm-phase-collect', 'pm-phase-final', 'pm-phase-open', 'pm-phase-invalid', 'pm-phase-pre']) {
    phaseClassCounts[cls] = await page.locator(`.${cls}`).count();
  }
  console.log(`阶段分布:`, JSON.stringify(phaseClassCounts));

  // 测试点击展开
  if (rows > 0) {
    await page.locator('.pm-tl-summary').first().click();
    await page.waitForTimeout(500);
    const expandedNow = await page.locator('.pm-tl-detail:visible').count();
    console.log(`点击后展开数: ${expandedNow}`);
    expect(expandedNow).toBeGreaterThan(0);
  }

  expect(rows).toBeGreaterThan(0);
  expect(expandedDetails).toBe(0);  // 默认全折叠
});
