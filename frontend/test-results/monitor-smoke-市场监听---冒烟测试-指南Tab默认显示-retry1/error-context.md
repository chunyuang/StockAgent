# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: monitor-smoke.spec.ts >> 市场监听 - 冒烟测试 >> 指南Tab默认显示
- Location: e2e/monitor-smoke.spec.ts:82:3

# Error details

```
Error: expect(received).toBeTruthy()

Received: false
```

# Test source

```ts
  1   | /**
  2   |  * 市场监听页面冒烟测试
  3   |  * 
  4   |  * 验证所有Tab能渲染、数据不为空、关键交互正常。
  5   |  * 每次后端改代码后跑 npx playwright test e2e/ 即可验证前端功能。
  6   |  * 
  7   |  * 运行方式:
  8   |  *   npx playwright test e2e/ --reporter=list
  9   |  *   npx playwright test e2e/ --headed  # 可视化调试
  10  |  *   npx playwright test e2e/ --update-snapshots  # 更新截图基准
  11  |  */
  12  | 
  13  | import { test, expect, Page } from '@playwright/test';
  14  | 
  15  | const MONITOR_URL = 'http://localhost:5174/monitor';
  16  | const API_BASE = 'http://localhost:50051';
  17  | 
  18  | // 超时设置：页面加载可能较慢
  19  | test.setTimeout(60000);
  20  | 
  21  | // 辅助：检查API是否可用
  22  | async function apiAvailable(): Promise<boolean> {
  23  |   try {
  24  |     const res = await fetch(`${API_BASE}/health`);
  25  |     return res.ok;
  26  |   } catch {
  27  |     return false;
  28  |   }
  29  | }
  30  | 
  31  | // 辅助：等待页面加载完成
  32  | async function waitForPageReady(page: Page) {
  33  |   await page.goto(MONITOR_URL, { waitUntil: 'networkidle', timeout: 30000 });
  34  |   // 等待主容器出现
  35  |   await page.waitForSelector('.mm', { timeout: 15000 }).catch(() => {});
  36  |   // 额外等2秒让API请求完成
  37  |   await page.waitForTimeout(2000);
  38  | }
  39  | 
  40  | test.beforeAll(async () => {
  41  |   if (!await apiAvailable()) {
  42  |     console.warn('⚠️ 后端API不可用，部分测试可能失败');
  43  |   }
  44  | });
  45  | 
  46  | test.describe('市场监听 - 冒烟测试', () => {
  47  | 
  48  |   test('页面能正常加载', async ({ page }) => {
  49  |     await waitForPageReady(page);
  50  |     // 页面标题不为空
  51  |     const title = await page.title();
  52  |     expect(title).toBeTruthy();
  53  |     // 没有Vue渲染错误（检查是否有白屏）
  54  |     const bodyText = await page.locator('body').innerText();
  55  |     expect(bodyText.length).toBeGreaterThan(100);
  56  |   });
  57  | 
  58  |   test('页面无console错误', async ({ page }) => {
  59  |     const errors: string[] = [];
  60  |     page.on('console', msg => {
  61  |       if (msg.type() === 'error') {
  62  |         errors.push(msg.text());
  63  |       }
  64  |     });
  65  |     
  66  |     await waitForPageReady(page);
  67  |     await page.waitForTimeout(3000); // 等3秒让所有API请求完成
  68  |     
  69  |     // 过滤掉已知的无害错误
  70  |     const realErrors = errors.filter(e => 
  71  |       !e.includes('favicon') && 
  72  |       !e.includes('net::ERR_CONNECTION_REFUSED') && // scanner未运行时的WS错误
  73  |       !e.includes('WebSocket') // WS连接失败是正常的(非开盘时间)
  74  |     );
  75  |     
  76  |     if (realErrors.length > 0) {
  77  |       console.error('❌ 页面Console错误:', realErrors);
  78  |     }
  79  |     expect(realErrors.length).toBe(0);
  80  |   });
  81  | 
  82  |   test('指南Tab默认显示', async ({ page }) => {
  83  |     await waitForPageReady(page);
  84  |     // 指南Tab应该默认展示，有架构图或说明文字
  85  |     const guideContent = page.locator('.guide-section, .guide-tab, [class*="guide"]').first();
  86  |     // 或检查页面是否有"启动"按钮
  87  |     const startBtn = page.locator('button:has-text("启动"), button:has-text("开始")');
  88  |     const hasGuide = await guideContent.isVisible().catch(() => false);
  89  |     const hasStartBtn = await startBtn.isVisible().catch(() => false);
> 90  |     expect(hasGuide || hasStartBtn).toBeTruthy();
      |                                     ^ Error: expect(received).toBeTruthy()
  91  |   });
  92  | 
  93  |   test('Tab切换正常 - 实盘Tab', async ({ page }) => {
  94  |     await waitForPageReady(page);
  95  |     // 点击实盘Tab
  96  |     const tab = page.locator('text=实盘, [class*="tab"]:has-text("实盘")').first();
  97  |     if (await tab.isVisible().catch(() => false)) {
  98  |       await tab.click();
  99  |       await page.waitForTimeout(1000);
  100 |       // 实盘Tab应该有信号/持仓区域（即使为空也应该有空状态提示）
  101 |       const content = await page.locator('.mm').innerText().catch(() => '');
  102 |       const hasContent = content.includes('信号') || content.includes('持仓') || content.includes('暂无');
  103 |       expect(hasContent).toBeTruthy();
  104 |     }
  105 |   });
  106 | 
  107 |   test('Tab切换正常 - 盘前竞价Tab', async ({ page }) => {
  108 |     await waitForPageReady(page);
  109 |     const tab = page.locator('text=盘前, [class*="tab"]:has-text("盘前")').first();
  110 |     if (await tab.isVisible().catch(() => false)) {
  111 |       await tab.click();
  112 |       await page.waitForTimeout(1500);
  113 |       const content = await page.locator('.mm').innerText().catch(() => '');
  114 |       const hasContent = content.includes('涨停') || content.includes('跌停') || content.includes('暂无') || content.includes('非交易');
  115 |       expect(hasContent).toBeTruthy();
  116 |     }
  117 |   });
  118 | 
  119 |   test('Tab切换正常 - 扫描追踪Tab', async ({ page }) => {
  120 |     await waitForPageReady(page);
  121 |     const tab = page.locator('text=扫描追踪, [class*="tab"]:has-text("扫描")').first();
  122 |     if (await tab.isVisible().catch(() => false)) {
  123 |       await tab.click();
  124 |       await page.waitForTimeout(1500);
  125 |       const content = await page.locator('.mm').innerText().catch(() => '');
  126 |       const hasContent = content.includes('漏斗') || content.includes('日期') || content.includes('暂无') || content.includes('扫描');
  127 |       expect(hasContent).toBeTruthy();
  128 |     }
  129 |   });
  130 | 
  131 |   test('Tab切换正常 - 复盘Tab', async ({ page }) => {
  132 |     await waitForPageReady(page);
  133 |     const tab = page.locator('text=复盘, [class*="tab"]:has-text("复盘")').first();
  134 |     if (await tab.isVisible().catch(() => false)) {
  135 |       await tab.click();
  136 |       await page.waitForTimeout(2000);
  137 |       const content = await page.locator('.mm').innerText().catch(() => '');
  138 |       // 复盘Tab应该有日/周/月切换，或有Hero结论
  139 |       const hasContent = content.includes('日复盘') || content.includes('周复盘') || content.includes('月复盘') || 
  140 |                          content.includes('胜率') || content.includes('收益') || content.includes('暂无');
  141 |       expect(hasContent).toBeTruthy();
  142 |     }
  143 |   });
  144 | 
  145 |   test('Tab切换正常 - 情绪Tab', async ({ page }) => {
  146 |     await waitForPageReady(page);
  147 |     const tab = page.locator('text=情绪, [class*="tab"]:has-text("情绪")').first();
  148 |     if (await tab.isVisible().catch(() => false)) {
  149 |       await tab.click();
  150 |       await page.waitForTimeout(1500);
  151 |       const content = await page.locator('.mm').innerText().catch(() => '');
  152 |       const hasContent = content.includes('情绪') || content.includes('冰点') || content.includes('高潮') || content.includes('震荡');
  153 |       expect(hasContent).toBeTruthy();
  154 |     }
  155 |   });
  156 | 
  157 |   test('Tab切换正常 - 风控Tab', async ({ page }) => {
  158 |     await waitForPageReady(page);
  159 |     const tab = page.locator('text=风控, [class*="tab"]:has-text("风控")').first();
  160 |     if (await tab.isVisible().catch(() => false)) {
  161 |       await tab.click();
  162 |       await page.waitForTimeout(1500);
  163 |       const content = await page.locator('.mm').innerText().catch(() => '');
  164 |       const hasContent = content.includes('风控') || content.includes('止损') || content.includes('风险') || content.includes('仪表');
  165 |       expect(hasContent).toBeTruthy();
  166 |     }
  167 |   });
  168 | 
  169 |   test('Tab切换正常 - 历史Tab', async ({ page }) => {
  170 |     await waitForPageReady(page);
  171 |     const tab = page.locator('text=历史, [class*="tab"]:has-text("历史")').first();
  172 |     if (await tab.isVisible().catch(() => false)) {
  173 |       await tab.click();
  174 |       await page.waitForTimeout(1500);
  175 |       const content = await page.locator('.mm').innerText().catch(() => '');
  176 |       const hasContent = content.includes('历史') || content.includes('订单') || content.includes('平仓') || content.includes('暂无');
  177 |       expect(hasContent).toBeTruthy();
  178 |     }
  179 |   });
  180 | 
  181 |   test('页面无NaN或undefined显示', async ({ page }) => {
  182 |     await waitForPageReady(page);
  183 |     
  184 |     // 逐个点击所有Tab，检查是否有NaN/undefined渲染
  185 |     const tabs = ['实盘', '盘前', '扫描', '复盘', '情绪', '风控', '历史'];
  186 |     const badTexts: string[] = [];
  187 |     
  188 |     for (const tabName of tabs) {
  189 |       const tab = page.locator(`[class*="tab"]:has-text("${tabName}")`).first();
  190 |       if (await tab.isVisible().catch(() => false)) {
```