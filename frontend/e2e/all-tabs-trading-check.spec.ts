/**
 * 盘中全 Tab 功能验证
 * 覆盖 9 个 Tab,每个抓: 截图 + console error + 网络失败 + 内容长度 + 空数据/异常文字
 */
import { test, Page } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const MONITOR_URL = 'http://localhost:5174/monitor';
const OUT_DIR = '/tmp/tabs-trading-check';

if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

test.setTimeout(180000);

interface TabReport {
  name: string;
  contentLen: number;
  hasNaN: boolean;
  hasUndefined: boolean;
  hasError: boolean;
  hasLoading: boolean;
  hasEmpty: boolean;
  consoleErrors: string[];
  networkFails: string[];
  screenshot: string;
  bodyTextSnippet: string;
}

test('所有Tab盘中实盘验证', async ({ page }) => {
  const reports: TabReport[] = [];
  const consoleErrors: string[] = [];
  const networkFails: string[] = [];

  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text().slice(0, 200));
    }
  });
  page.on('requestfailed', req => {
    networkFails.push(`${req.method()} ${req.url()} - ${req.failure()?.errorText}`);
  });
  page.on('response', async resp => {
    if (resp.status() >= 400) {
      networkFails.push(`${resp.status()} ${resp.url()}`);
    }
  });

  console.log('🚀 打开监控页...');
  await page.goto(MONITOR_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);

  // 列出所有 Tab (按显示文本)
  const tabs = [
    '行情', '盘前', '实盘', '信号', '复盘', '情绪', '分析', '账户', '运维', '扫描追踪', '历史',
    'Guide', 'Premarket', 'Trading', 'Signal', 'Review', 'Sentiment', 'Analysis', 'Account', 'Ops', 'ScanTrace', 'History',
  ];

  for (const tabName of tabs) {
    const localErrs = consoleErrors.length;
    const localFails = networkFails.length;
    
    const tabBtn = page.locator(`text=${tabName}`).first();
    const count = await tabBtn.count();
    if (count === 0) {
      continue; // Tab 不存在
    }
    const visible = await tabBtn.isVisible().catch(() => false);
    if (!visible) continue;

    console.log(`\n📂 切到 [${tabName}]...`);
    try {
      await tabBtn.click({ timeout: 5000 });
    } catch (e) {
      console.warn(`  ⚠️ 点击失败: ${e}`);
      continue;
    }
    await page.waitForTimeout(3000);

    const body = page.locator('.mm-body, .mm-content, .mm-main, .mm').first();
    let html = '';
    let bodyText = '';
    try {
      html = await body.innerHTML().catch(() => '');
      bodyText = await body.innerText().catch(() => '');
    } catch {}

    const screenshotPath = path.join(OUT_DIR, `${tabName.replace(/[^\w]/g,'_')}.png`);
    try {
      await page.screenshot({ path: screenshotPath, fullPage: false });
    } catch {}

    const report: TabReport = {
      name: tabName,
      contentLen: html.length,
      hasNaN: bodyText.includes('NaN'),
      hasUndefined: bodyText.includes('undefined') || bodyText.includes('null'),
      hasError: /错误|Error|失败|exception|崩溃|red-text/i.test(bodyText),
      hasLoading: /加载中|Loading|loading\.\.\./i.test(bodyText) && bodyText.length < 200,
      hasEmpty: /暂无数据|无数据|没有数据|empty|no.?data/i.test(bodyText),
      consoleErrors: consoleErrors.slice(localErrs),
      networkFails: networkFails.slice(localFails),
      screenshot: screenshotPath,
      bodyTextSnippet: bodyText.slice(0, 300).replace(/\s+/g, ' '),
    };
    reports.push(report);

    // 找错误关键字上下文
    const errorContexts: string[] = [];
    for (const kw of ['错误', '失败', '崩溃', 'Error']) {
      let idx = 0;
      while ((idx = bodyText.indexOf(kw, idx)) !== -1 && errorContexts.length < 8) {
        const ctx = bodyText.slice(Math.max(0, idx - 30), Math.min(bodyText.length, idx + 60)).replace(/\s+/g, ' ');
        errorContexts.push(`[${kw}@${idx}] ${ctx}`);
        idx += kw.length;
      }
    }
    (report as any).errorContexts = errorContexts;
    (report as any).bodyText = bodyText.slice(0, 4000).replace(/\s+/g, ' ');

    console.log(`  内容长度: ${report.contentLen}`);
    console.log(`  NaN/undef/error/loading/empty: ${[report.hasNaN, report.hasUndefined, report.hasError, report.hasLoading, report.hasEmpty]}`);
    if (report.consoleErrors.length) console.log(`  ❌ console: ${report.consoleErrors.length}个`);
    if (report.networkFails.length) console.log(`  ❌ network: ${report.networkFails.length}个`);
    console.log(`  片段: ${report.bodyTextSnippet.slice(0, 100)}`);
  }

  // 输出报告
  fs.writeFileSync(path.join(OUT_DIR, 'report.json'), JSON.stringify(reports, null, 2));
  console.log(`\n\n📊 总结: 检查了 ${reports.length} 个 Tab`);
  console.log(`报告保存到: ${OUT_DIR}/report.json`);
});
