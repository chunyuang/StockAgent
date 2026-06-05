/**
 * 市场监听页面冒烟测试
 * 
 * 验证所有Tab能渲染、数据不为空、关键交互正常。
 * 每次后端改代码后跑 npx playwright test e2e/ 即可验证前端功能。
 * 
 * 运行方式:
 *   npx playwright test e2e/ --reporter=list
 *   npx playwright test e2e/ --headed  # 可视化调试
 *   npx playwright test e2e/ --update-snapshots  # 更新截图基准
 */

import { test, expect, Page } from '@playwright/test';

const MONITOR_URL = 'http://localhost:5174/monitor';
const API_BASE = 'http://localhost:50051';

// 超时设置：页面加载可能较慢
test.setTimeout(60000);

// 辅助：检查API是否可用
async function apiAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// 辅助：等待页面加载完成
async function waitForPageReady(page: Page) {
  await page.goto(MONITOR_URL, { waitUntil: 'networkidle', timeout: 30000 });
  // 等待主容器出现
  await page.waitForSelector('.mm', { timeout: 15000 }).catch(() => {});
  // 额外等2秒让API请求完成
  await page.waitForTimeout(2000);
}

test.beforeAll(async () => {
  if (!await apiAvailable()) {
    console.warn('⚠️ 后端API不可用，部分测试可能失败');
  }
});

test.describe('市场监听 - 冒烟测试', () => {

  test('页面能正常加载', async ({ page }) => {
    await waitForPageReady(page);
    // 页面标题不为空
    const title = await page.title();
    expect(title).toBeTruthy();
    // 没有Vue渲染错误（检查是否有白屏）
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(100);
  });

  test('页面无console错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    
    await waitForPageReady(page);
    await page.waitForTimeout(3000); // 等3秒让所有API请求完成
    
    // 过滤掉已知的无害错误
    const realErrors = errors.filter(e => 
      !e.includes('favicon') && 
      !e.includes('net::ERR_CONNECTION_REFUSED') && // scanner未运行时的WS错误
      !e.includes('WebSocket') // WS连接失败是正常的(非开盘时间)
    );
    
    if (realErrors.length > 0) {
      console.error('❌ 页面Console错误:', realErrors);
    }
    expect(realErrors.length).toBe(0);
  });

  test('指南Tab默认显示', async ({ page }) => {
    await waitForPageReady(page);
    // 指南Tab应该默认展示，有架构图或说明文字
    const guideContent = page.locator('.guide-section, .guide-tab, [class*="guide"]').first();
    // 或检查页面是否有"启动"按钮
    const startBtn = page.locator('button:has-text("启动"), button:has-text("开始")');
    const hasGuide = await guideContent.isVisible().catch(() => false);
    const hasStartBtn = await startBtn.isVisible().catch(() => false);
    expect(hasGuide || hasStartBtn).toBeTruthy();
  });

  test('Tab切换正常 - 实盘Tab', async ({ page }) => {
    await waitForPageReady(page);
    // 点击实盘Tab
    const tab = page.locator('text=实盘, [class*="tab"]:has-text("实盘")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1000);
      // 实盘Tab应该有信号/持仓区域（即使为空也应该有空状态提示）
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('信号') || content.includes('持仓') || content.includes('暂无');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 盘前竞价Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=盘前, [class*="tab"]:has-text("盘前")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1500);
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('涨停') || content.includes('跌停') || content.includes('暂无') || content.includes('非交易');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 扫描追踪Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=扫描追踪, [class*="tab"]:has-text("扫描")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1500);
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('漏斗') || content.includes('日期') || content.includes('暂无') || content.includes('扫描');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 复盘Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=复盘, [class*="tab"]:has-text("复盘")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(2000);
      const content = await page.locator('.mm').innerText().catch(() => '');
      // 复盘Tab应该有日/周/月切换，或有Hero结论
      const hasContent = content.includes('日复盘') || content.includes('周复盘') || content.includes('月复盘') || 
                         content.includes('胜率') || content.includes('收益') || content.includes('暂无');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 情绪Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=情绪, [class*="tab"]:has-text("情绪")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1500);
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('情绪') || content.includes('冰点') || content.includes('高潮') || content.includes('震荡');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 风控Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=风控, [class*="tab"]:has-text("风控")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1500);
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('风控') || content.includes('止损') || content.includes('风险') || content.includes('仪表');
      expect(hasContent).toBeTruthy();
    }
  });

  test('Tab切换正常 - 历史Tab', async ({ page }) => {
    await waitForPageReady(page);
    const tab = page.locator('text=历史, [class*="tab"]:has-text("历史")').first();
    if (await tab.isVisible().catch(() => false)) {
      await tab.click();
      await page.waitForTimeout(1500);
      const content = await page.locator('.mm').innerText().catch(() => '');
      const hasContent = content.includes('历史') || content.includes('订单') || content.includes('平仓') || content.includes('暂无');
      expect(hasContent).toBeTruthy();
    }
  });

  test('页面无NaN或undefined显示', async ({ page }) => {
    await waitForPageReady(page);
    
    // 逐个点击所有Tab，检查是否有NaN/undefined渲染
    const tabs = ['实盘', '盘前', '扫描', '复盘', '情绪', '风控', '历史'];
    const badTexts: string[] = [];
    
    for (const tabName of tabs) {
      const tab = page.locator(`[class*="tab"]:has-text("${tabName}")`).first();
      if (await tab.isVisible().catch(() => false)) {
        await tab.click();
        await page.waitForTimeout(1000);
        
        const content = await page.locator('.mm').innerText().catch(() => '');
        // 检查NaN
        if (content.includes('NaN')) badTexts.push(`${tabName}: NaN`);
        // 检查undefined (不是"暂无数据"这种正常文案)
        if (content.match(/\bundefined\b/)) badTexts.push(`${tabName}: undefined`);
      }
    }
    
    if (badTexts.length > 0) {
      console.error('❌ 发现NaN/undefined:', badTexts);
    }
    expect(badTexts.length).toBe(0);
  });

  test('页面无白屏区域', async ({ page }) => {
    await waitForPageReady(page);
    
    const tabs = ['实盘', '盘前', '扫描', '复盘', '情绪', '风控', '历史'];
    const blankTabs: string[] = [];
    
    for (const tabName of tabs) {
      const tab = page.locator(`[class*="tab"]:has-text("${tabName}")`).first();
      if (await tab.isVisible().catch(() => false)) {
        await tab.click();
        await page.waitForTimeout(1500);
        
        // 检查Tab内容区域是否有实际内容（不只是空div）
        const content = await page.locator('.mm').innerText().catch(() => '');
        if (content.length < 20) {
          blankTabs.push(tabName);
        }
      }
    }
    
    if (blankTabs.length > 0) {
      console.error('❌ 白屏Tab:', blankTabs);
    }
    // 不要求所有Tab都有数据（scanner可能未运行），但不应完全空白
    expect(blankTabs.length).toBe(0);
  });
});
