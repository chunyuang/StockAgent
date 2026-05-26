# V63 前端 UI/UX 审计报告

**日期**: 2026-05-27  
**版本**: V63  
**审计范围**: StockAgent 前端全部页面与组件  
**构建状态**: ✅ 通过 (9.80s)

---

## 修复清单

### P0 级（数据显示错误或功能故障）

| # | 问题 | 文件 | 修复 | 状态 |
|---|------|------|------|------|
| P0-1 | todayPnl fallback 分支数学错误 | CockpitView.vue | 删除 `costAmt = shares * price / (1 + profit_pct / 100)` 反推公式，仅使用 `profit_amount` 字段 | ✅ |
| P0-2 | StrategyEditView 使用全局注册组件名 | StrategyEditView.vue | 显式 import ElButton/ElForm/ElFormItem/ElInput/ElSlider/ElSwitch/ElTag/ElSkeleton | ✅ |
| P0-4 | 卖出确认弹窗缺成本价 | MarketMonitorView.vue | 确认弹窗增加 `成本 ¥${pos.cost_price.toFixed(2)} →` | ✅ |
| P0-5 | 实盘模式切换无二次确认 | CockpitView.vue | 切换到 gm 模式时增加 ElMessageBox.prompt，必须输入 "LIVE" 确认码 | ✅ |

### P1 级（体验问题）

| # | 问题 | 文件 | 修复 | 状态 |
|---|------|------|------|------|
| P1-1 | 交易参数小数 vs 百分比显示 | StrategyConfigPanel.vue | max_position_per_stock / max_total_position 的 unit 从 `%` 改为 `= XX%` 动态转换 | ✅ |
| P1-5 | 日志无 ANSI 颜色渲染 | AnsiLogPanel.vue | 引入 `ansiToHtml` 工具，检测到 ANSI 码时自动渲染为彩色 HTML | ✅ |
| P1-8 | 紧急平仓按钮不够醒目 | CockpitView.vue | 新增 `.emergency-btn-v2` 样式：14px/800字重/红底白字/2px边框/emergency-flash 闪烁动画 | ✅ |
| P1-9 | 交易记录表格无分页 | BacktestResultPanel.vue | 新增 `tradeCurrentPage/tradePageSize/pagedTrades`，添加 ElPagination 组件(10/20/50/100) | ✅ |
| P1-10 | 移动端适配缺失 | StrategyConfigPanel.vue | 添加 @media (max-width: 768px) 响应式样式（缩小 label/input/collapse） | ✅ |
| P1-11 | 回测历史对比缺净值曲线 | BacktestHistoryPanel.vue | 新增 ECharts 柱状图对比(收益率/胜率/夏普)，VChart 渲染 | ✅ |
| P1-12 | 风控参数格式不统一 | SystemStatusView.vue | 删除 `slVal < 1 ? slVal : slVal / 100` heuristics，与后端约定统一小数格式 | ✅ |
| P1-13 | 管道可视化缺数值标注 | CockpitView.vue | 管道层新增 `.pipe-io` 标注 `N→M`（输入→输出），从 pipe-status 分离 | ✅ |
| P1-15 | WebSocket 重连不提示 | CockpitView.vue | 新增 `wsConnected` ref + 顶部 `📡 断开/📡` 状态指示器 + blink 动画 | ✅ |

### P2 级（UI细节优化）

| # | 问题 | 文件 | 修复 | 状态 |
|---|------|------|------|------|
| P2-1 | KPI strip 换行不美观 | BacktestResultPanel.vue | `.kpi-strip` 从 flex 改为 CSS Grid `repeat(auto-fill, minmax(90px, 1fr))` | ✅ |
| P2-2 | 折叠面板标题过长 | StrategyConfigPanel.vue | 3个 collapse title 从长参数摘要缩短为 `📅 基础配置` / `💹 交易参数` / `🔍 全局筛选` | ✅ |
| P2-14 | 缺少键盘快捷键 | UltraShortBacktestViewV2.vue | 新增 `onGlobalKeydown`，Ctrl+Enter 提交回测 | ✅ |

---

## UI 增强优化

| 增强 | 文件 | 描述 | 状态 |
|------|------|------|------|
| 管道数据流动画 | CockpitView.vue | `.pipe-node::after` 添加渐变扫光动画 `data-flow 3s`，pass 层绿色/ filter 层红色 | ✅ |
| KPI 趋势小图标 | BacktestResultPanel.vue | 累计收益/年化收益/最大回撤/胜率 KPI 添加 `↑`/`↓` 趋势箭头 | ✅ |
| 交易记录涨跌色 | BacktestResultPanel.vue | 表格行添加 `trade-profit`/`trade-loss` class，浅绿/浅红背景 | ✅ |

---

## 未修复项（需后续处理）

| # | 问题 | 原因 |
|---|------|------|
| P1-11 完整版 | 回测历史对比缺少净值曲线叠加图 | 需要额外 API 获取历史回测的 net_value_series，当前对比面板仅用 KPI 柱状图替代 |
| 月度收益热力图 | BacktestResultPanel 月度归因 tab | 需 ECharts heatmap 组件，当前用柱状图+累计线替代 |
| 大 chunk 拆分 | element-plus 921KB / echarts 585KB | 需 dynamic import + manualChunks 配置 |
| 深色模式优化 | 全局 CSS 变量 | 部分硬编码颜色需改为 CSS 变量 |

---

## 修改文件清单

1. `src/views/monitor/CockpitView.vue` — P0-1/P0-5/P1-8/P1-13/P1-15/UI增强(6处)
2. `src/views/strategy/StrategyEditView.vue` — P0-2
3. `src/views/monitor/MarketMonitorView.vue` — P0-4
4. `src/components/ultrashort/StrategyConfigPanel.vue` — P1-1/P1-10/P2-2
5. `src/components/backtest/AnsiLogPanel.vue` — P1-5
6. `src/components/ultrashort/BacktestResultPanel.vue` — P1-9/P2-1/UI增强(3处)
7. `src/components/backtest/BacktestHistoryPanel.vue` — P1-11
8. `src/views/system/SystemStatusView.vue` — P1-12
9. `src/views/backtest/UltraShortBacktestViewV2.vue` — P2-14

---

## 构建验证

```
✓ built in 9.80s
所有 492 模块转换成功
无 TypeScript 错误
无 Vue 模板编译错误
```
