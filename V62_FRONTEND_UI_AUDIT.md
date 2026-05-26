# V62 前端 UI/UX 审查报告

**审查日期:** 2026-05-27  
**审查范围:** StockAgent 前端全部 22 个 Vue 组件/页面  
**审查人:** Frontend UI Audit Subagent

---

## P0: 数据显示错误或功能故障

### P0-1: CockpitView todayPnl 计算逻辑不可靠
- **文件:** `views/monitor/CockpitView.vue` L~175-195
- **问题:** `todayPnl` 计算中，从 `timeline` 的 sell 动作计算已实现盈亏时，使用 `profit_pct` 反推成本 `costAmt = shares * price / (1 + profit_pct / 100)`，这在卖出价≠买入价时逻辑有误。`shares * price` 是卖出金额而非成本。正确做法应直接使用 `profit_amount`（代码已有优先分支），但 fallback 分支的数学推导错误。
- **建议修复:** 删除 fallback 分支，或从持仓记录中查 cost_price 来计算。如果后端不返回 profit_amount，则从 positions 数据取 cost_price。
- **影响:** 驾驶舱"今日盈亏"数字偏差，影响交易决策。

### P0-2: StrategyEditView 使用 Element Plus 全局注册组件名（Options API 风格）
- **文件:** `views/strategy/StrategyEditView.vue` L~195+
- **问题:** 模板中使用 `<el-button>`, `<el-input>`, `<el-switch>`, `<el-slider>`, `<el-tag>`, `<el-form>`, `<el-form-item>`, `<el-skeleton>` 等全局注册名称，但其他组件都使用了显式 import（如 `ElButton`, `ElInput`）。项目可能未全局注册 Element Plus 组件，导致运行时渲染失败。
- **建议修复:** 在 `<script setup>` 中显式 import 所有使用的 Element Plus 组件，与其他页面保持一致。
- **影响:** 策略编辑页面可能完全无法渲染或部分组件丢失。

### P0-3: BacktestResultPanel 月度收益 key 格式不匹配
- **文件:** `components/ultrashort/BacktestResultPanel.vue` L~165-180
- **问题:** `monthlyData` 从 `net_value_series` 计算月度收益，`monthKey = date.substring(0, 6)` 得到 "202601"，显示格式 "2026-01"。但 `monthlyTrades` 从 `allTrades` 提取，`monthKey = date.substring(0, 7)` 得到 "2026-01"。两者用不同 key 格式，在 `monthlyMergedData` 中 `tradeMap.get(r.month)` 将无法匹配（r.month 是 "2026-01"，但 tradeMap 的 key 也是 "2026-01"——实际上这里可能能匹配，但需要确认 `monthlyData` 输出的 month 格式）。
  - **验证:** `monthlyData` 输出的 month = `month.substring(0,4) + '-' + month.substring(4)` → "2026-01" ✅ 与 monthlyTrades 的 "2026-01" 一致。**此项实际无bug，但代码可读性差。**
- **降级为 P2:** 建议统一 monthKey 格式到 ISO 格式。

### P0-4: MarketMonitorView 卖出确认弹窗显示 price 但无 cost 对比
- **文件:** `views/monitor/MarketMonitorView.vue` L~quickSell
- **问题:** `quickSell` 的确认文案只显示当前价和盈亏百分比，但缺少成本价对比。用户无法在确认弹窗中看到成本价，容易误操作。
- **建议修复:** 确认弹窗增加 `成本 ¥${pos.cost_price.toFixed(2)}` 信息。
- **影响:** 中等——可能导致误卖出操作。

### P0-5: CockpitView 模式切换无二次确认（实盘→模拟）
- **文件:** `views/monitor/CockpitView.vue` L~模式切换区域
- **问题:** 驾驶舱的模式切换（simulated/paper/live）如果切换到 live 模式，应该有严格的安全确认流程。代码中有 `selectedMode` 但未找到模式切换时的二次确认弹窗。
- **建议修复:** 切换到 live 模式时增加 `ElMessageBox.confirm` 二次确认，明确告知"实盘模式将使用真实资金"。
- **影响:** 高——可能导致实盘误操作。

---

## P1: 体验问题或缺失功能

### P1-1: StrategyConfigPanel 交易参数显示混乱（小数 vs 百分比）
- **文件:** `components/ultrashort/StrategyConfigPanel.vue` L~130-155
- **问题:** 止损/止盈/仓位等参数在表单中是小数（0.03），右侧 unit 标注为 `%`，用户需要心算 `0.03 = 3%`。虽然标题栏有 `(止损3.0%, 止盈7.0%...)` 提示，但输入框本身显示 0.03 极不直观。
- **建议修复:** 方案A: 将表单值改为百分比（3, 7, 35），提交时除以100；方案B: 在输入框右侧动态显示转换值如 `= 3.0%`。
- **影响:** 用户容易输入错误参数，导致回测结果偏差。

### P1-2: BacktestResultPanel 策略对比 Tab 在仅1个策略时显示空
- **文件:** `components/ultrashort/BacktestResultPanel.vue` L~策略对比Tab
- **问题:** 策略对比 Tab 在只有1个策略时显示 `ElEmpty: 至少启用2个策略才显示对比`，但 Tab 本身仍然存在，用户点击后才知道没用。体验差。
- **建议修复:** 当只有1个策略时隐藏策略对比 Tab，或在 Tab 上显示提示 badge。
- **影响:** 低——但影响用户探索体验。

### P1-3: CockpitView 实时刷新间隔不可配置
- **文件:** `views/monitor/CockpitView.vue` L~refreshTimer
- **问题:** 驾驶舱的自动刷新间隔硬编码（未看到具体值，但缺乏用户可调选项）。高频刷新可能造成不必要的服务器压力，低频刷新可能错过实时信号。
- **建议修复:** 在设置面板中增加刷新间隔选项（5s/10s/30s/1min）。
- **影响:** 中等——影响实时监控效果。

### P1-4: BacktestHistoryPanel 对比功能最多3条限制无解释
- **文件:** `components/backtest/BacktestHistoryPanel.vue` L~toggleCompare
- **问题:** `selectedForCompare.length < 3` 硬编码了最多3条对比，但 UI 上没有说明为什么限制3条，且超过3条后点击卡片无反馈。
- **建议修复:** 选择第4条时显示 toast 提示"最多可对比3条记录"。
- **影响:** 低——用户可能困惑。

### P1-5: AnsiLogPanel 实时模式日志无 ANSI 颜色渲染
- **文件:** `components/backtest/AnsiLogPanel.vue` L~renderedLogs
- **问题:** `renderedLogs` 只做了 HTML 转义（`&`, `<`, `>`），但后端日志中包含 ANSI 颜色码（如 `\033[32m`），这些在 UI 上显示为乱码或被忽略。
- **建议修复:** 使用 `ansi-to-html` 库或将 ANSI 颜色码转换为 `<span style="color:...">` 标签。
- **影响:** 中等——日志可读性差，关键信息（成功/失败/警告）无法颜色区分。

### P1-6: DataStatusPanel 热力图在深色模式下颜色反转
- **文件:** `components/ultrashort/DataStatusPanel.vue` L~heatmapOption
- **问题:** 热力图 `visualMap.inRange.color` 使用了 `var(--stock-up)` → `var(--stock-down)` 渐变。在深色模式下，中国股市的"红涨绿跌"语义保持，但热力图的语义是"覆盖率0%→100%"，用 stock-up(绿)→stock-down(红) 表示从低到高，在深色模式下绿→红可能不太直观。
- **建议修复:** 使用通用语义色（蓝→绿→黄→红），而非股市色。
- **影响:** 低——但在深色模式下可能混淆。

### P1-7: StockDetailView 和 StrategyListView 是旧版页面未适配新主题
- **文件:** `views/stock/StockDetailView.vue`, `views/strategy/StrategyListView.vue`, `views/strategy/StrategyDetailView.vue`
- **问题:** 这些页面使用旧版样式变量（如 `var(--border-color)`, `var(--bg-primary)`, `var(--text-primary)` 等），与主框架的 CSS 变量命名不一致（主框架用 `var(--el-border-color)`, `var(--el-bg-color)` 或 `var(--border-default)`, `var(--bg-elevated)` 等），导致深色/浅色主题切换时样式可能不一致。
- **建议修复:** 统一 CSS 变量命名，使用项目主题系统定义的变量。
- **影响:** 中等——主题切换后可能样式错乱。

### P1-8: CockpitView 紧急平仓按钮位置不够醒目
- **文件:** `views/monitor/CockpitView.vue` L~紧急平仓
- **问题:** 紧急平仓按钮虽然在顶部状态栏，但与其他按钮样式类似，可能在紧急情况下不够醒目。
- **建议修复:** 增大按钮尺寸，使用醒目的红色背景 + 白色文字 + 闪烁动画，并固定在页面右上角（即使滚动也可见）。
- **影响:** 中等——紧急情况下可能错过操作窗口。

### P1-9: BacktestResultPanel 交易记录表格无分页
- **文件:** `components/ultrashort/BacktestResultPanel.vue` L~ElTable max-height="500"
- **问题:** 交易记录表格使用 `max-height="500"` + 内部滚动，当交易笔数较多（如 200+）时，全部数据加载到 DOM，可能导致页面卡顿。
- **建议修复:** 使用 Element Plus 的 `pagination` 组件，每页显示 50 条。
- **影响:** 中等——大量交易时页面性能下降。

### P1-10: 移动端适配缺失
- **文件:** 所有页面
- **问题:** 只有 `UltraShortBacktestViewV2.vue` 有 `@media (max-width: 1000px)` 的响应式样式，其他页面完全没有移动端适配。CockpitView 和 MarketMonitorView 的3列布局在手机上会挤压变形。
- **建议修复:** 
  - CockpitView/MarketMonitorView: 小屏幕下改为单列布局
  - BacktestResultPanel: KPI strip 改为 2列/4行网格
  - StrategyConfigPanel: grid-cols-2 改为在小屏幕下 grid-cols-1
- **影响:** 中等——移动端体验极差。

### P1-11: 回测历史对比面板缺少净值曲线对比
- **文件:** `components/backtest/BacktestHistoryPanel.vue` L~compareMetrics
- **问题:** 对比面板只显示 KPI 数值对比表格，缺少净值曲线叠加图。对于评估不同参数组合的效果，曲线对比比数值对比更直观。
- **建议修复:** 在对比面板中增加 ECharts 叠加折线图（需要后端支持从历史结果中提取净值序列）。
- **影响:** 中等——核心功能缺失。

### P1-12: SystemStatusView 风控参数 stop_loss_pct 格式不统一
- **文件:** `views/system/SystemStatusView.vue` L~fetchRiskConfig
- **问题:** 代码注释 `【V59修复】stop_loss_pct可能来自不同API,小数(0.03)或百分比(3.0)` 说明后端返回格式不统一，前端做了 `slVal < 1 ? slVal : slVal / 100` 的自适应。但这个 heuristics 不靠谱——如果 stop_loss 是 100%，会被当成 1.0 处理成 1.0（正确），但如果是 50% 会被当成 0.5（错误的小数）。
- **建议修复:** 与后端约定统一返回小数格式（0.03），前端去掉 heuristics。或使用明确的 `unit` 字段标识。
- **影响:** 高——可能导致风控参数配置错误。

---

## P2: UI细节和优化建议

### P2-1: BacktestResultPanel KPI strip 在窄屏下换行不美观
- **文件:** `components/ultrashort/BacktestResultPanel.vue` L~kpi-strip
- **问题:** 8个 KPI chip 使用 `flex-wrap: wrap`，窄屏下换行后对齐不一致（第二行可能只有2-3个chip）。
- **建议修复:** 使用 CSS Grid `grid-template-columns: repeat(auto-fill, minmax(90px, 1fr))` 替代 flex。
- **影响:** 极低——纯视觉。

### P2-2: StrategyConfigPanel 折叠面板标题过长
- **文件:** `components/ultrashort/StrategyConfigPanel.vue` L~computed标题
- **问题:** 交易参数标题 `(止损3.0%, 止盈7.0%, 持仓2天, 总仓80%, 单票35%, 佣金0.25‰, 印花税1.0‰, 滑点0.5‰)` 在窄屏下会溢出。
- **建议修复:** 增加标题 `text-overflow: ellipsis; overflow: hidden; white-space: nowrap` 样式，或缩短为 `(止损3%, 止盈7%, 2天, 80%, 35%)`。
- **影响:** 极低——窄屏下标题被截断。

### P2-3: FactorReferencePanel 硬编码因子列表
- **文件:** `components/ultrashort/FactorReferencePanel.vue` L~allFactors
- **问题:** 70+ 个因子全部硬编码在前端，与后端 `factor_library.py` 不同步。后端新增/删除因子后，前端不会自动更新。
- **建议修复:** 从后端 API 动态获取因子列表和描述，前端只做展示。
- **影响:** 低——信息可能过时。

### P2-4: BacktestSummaryTable 与 BacktestResultPanel KPI 重复
- **文件:** `components/backtest/BacktestSummaryTable.vue` vs `components/ultrashort/BacktestResultPanel.vue`
- **问题:** 两个组件都显示累计收益/年化/回撤/夏普/胜率/盈亏比等核心指标，内容高度重复。
- **建议修复:** SummaryTable 定位为"精简概要"（4列 Descriptions），ResultPanel KPI strip 定位为"快速扫描"（8个 chip），可以共存但需减少重复描述文字。
- **影响:** 极低——冗余但不影响功能。

### P2-5: MainLayout 侧边栏固定定位导致内容区域偏移
- **文件:** `layouts/MainLayout.vue` L~sidebar
- **问题:** 侧边栏使用 `position: fixed`，但主内容区可能缺少对应的 `margin-left` 来补偿宽度，导致内容被侧边栏遮挡。
- **建议修复:** 在 `main-container` 上增加 `margin-left: 200px`（展开）或 `margin-left: 64px`（折叠），或使用 CSS 变量动态设置。
- **影响:** 低——可能在特定分辨率下出现布局问题。

### P2-6: SearchBar 无防抖处理（已在代码中修复）
- **文件:** `components/common/SearchBar.vue`
- **问题:** 代码中已使用 `useDebounceFn` 实现 300ms 防抖，此项无问题。
- **状态:** ✅ 已修复

### P2-7: CockpitView 盈亏曲线 x 轴标签重叠
- **文件:** `views/monitor/CockpitView.vue` L~pnlOption
- **问题:** 盈亏曲线图 x 轴标签为时间字符串（如 "14:30"），数据点较多时标签重叠不可读。
- **建议修复:** 增加 `xAxis.axisLabel.rotate: 30` 或 `axisLabel.interval: 'auto'`，以及 `dataZoom` 支持缩放。
- **影响:** 低——图表可读性差。

### P2-8: DbAdminView 清空集合操作虽有二次确认但无操作日志
- **文件:** `views/admin/DbAdminView.vue` L~handleClearCollection
- **问题:** 清空 MongoDB 集合是高危操作，虽然有二次确认，但缺少操作审计日志。如果误操作，无法追溯是谁、何时操作的。
- **建议修复:** 在操作成功后记录操作日志（发送到后端保存），或至少在前端 localStorage 记录。
- **影响:** 低——但安全最佳实践。

### P2-9: 所有图表 tooltip 在移动端不可点击
- **文件:** 所有使用 ECharts 的组件
- **问题:** ECharts 的 tooltip 在触摸屏上需要长按才能显示，体验不如桌面端。且 tooltip 可能被手指遮挡。
- **建议修复:** 在移动端使用 ECharts 的 `trigger: 'click'` 替代 `trigger: 'axis'`，或在 tooltip 外增加详情卡片。
- **影响:** 低——移动端体验。

### P2-10: BacktestResultPanel 交易记录排序方向不明确
- **文件:** `components/ultrashort/BacktestResultPanel.vue` L~filteredTrades
- **问题:** 默认按 `buy_date` 降序（最新在前），但 UI 上没有明确告知用户当前排序方式，且无法切换排序方向。
- **建议修复:** 在表格上方增加排序选项（按日期/收益率/持仓天数），或在表格列头增加可点击排序。
- **影响:** 极低——功能已部分支持（sortable 列）。

### P2-11: StrategyEditView 权重滑块总和未校验
- **文件:** `views/strategy/StrategyEditView.vue` L~权重配置
- **问题:** 4个权重滑块（基本面/技术面/舆情/估值）各自独立，总和可以超过 100%。没有实时显示总和或校验。
- **建议修复:** 实时显示权重总和，超过100%时高亮警告，或使用联动滑块确保总和=100%。
- **影响:** 低——但不合理的权重配置可能导致策略效果异常。

### P2-12: MarketMonitorView 信号剩余时间计算依赖客户端时钟
- **文件:** `views/monitor/MarketMonitorView.vue` L~sigRemaining
- **问题:** `signalRemaining` 使用 `Date.now()` (客户端时间) 与 `created_at` (服务器时间戳) 对比。如果客户端时钟偏差较大，剩余时间显示不准确。
- **建议修复:** 从服务器响应头获取服务器时间，计算偏移量后修正。
- **影响:** 低——大多数情况下客户端时钟偏差<1秒。

### P2-13: CockpitView 管道可视化缺少数值标注
- **文件:** `views/monitor/CockpitView.vue` L~管道层级
- **问题:** 9层管道可视化只显示通过/拒绝状态（颜色），但没有显示具体数量（如"30→28→25→..."），用户需要点进信号详情才能看到。
- **建议修复:** 在每个管道层级的图标旁标注 `输入N→输出M` 数量。
- **影响:** 低——信息密度可提升。

### P2-14: 所有页面缺少键盘快捷键
- **文件:** 全局
- **问题:** 没有全局键盘快捷键支持。常用操作如"提交回测"（Ctrl+Enter）、"刷新"（F5/Ctrl+R）、"切换Tab"等无法键盘操作。
- **建议修复:** 在 UltraShortBacktestViewV2 中增加 Ctrl+Enter 提交回测快捷键，CockpitView 中增加 Esc 关闭弹窗等。
- **影响:** 极低——效率提升。

### P2-15: CockpitView/MarketMonitorView WebSocket 重连不提示用户
- **文件:** `views/monitor/CockpitView.vue`, `views/monitor/MarketMonitorView.vue` L~ws
- **问题:** WebSocket 断开后自动重连，但 UI 上没有明确的连接状态指示。用户可能不知道数据已停止更新。
- **建议修复:** 在顶部状态栏增加 WebSocket 连接状态指示器（🟢已连接 / 🟡重连中 / 🔴已断开）。
- **影响:** 低——但影响信任度。

### P2-16: BacktestHistoryPanel 对比面板最佳值标注不够醒目
- **文件:** `components/backtest/BacktestHistoryPanel.vue` L~isBestInCompare
- **问题:** 最佳值使用 `::after { content: ' ★' }` 标注，但 ★ 符号在深色模式下可能不够醒目。
- **建议修复:** 改用背景高亮（如 `background: var(--success-bg)`）+ 粗体，而非仅文字后缀。
- **影响:** 极低——纯视觉。

---

## 总结

| 级别 | 数量 | 关键问题 |
|------|------|---------|
| P0 | 5 | 驾驶舱盈亏计算错误、策略编辑组件注册、实盘模式无确认、风控参数格式不统一 |
| P1 | 12 | 参数显示不直观、移动端适配、日志ANSI渲染、交易记录无分页、对比缺净值曲线 |
| P2 | 16 | 标题溢出、图表标签重叠、因子硬编码、权重校验等UI细节 |

### 优先修复建议

1. **P0-1** CockpitView todayPnl fallback 计算修复（影响实盘决策）
2. **P0-2** StrategyEditView 组件注册（页面可能无法渲染）
3. **P0-5** 驾驶舱实盘模式切换二次确认（资金安全）
4. **P1-12** SystemStatusView 风控参数格式统一（可能导致参数错误）
5. **P1-1** StrategyConfigPanel 参数显示优化（用户最常交互的界面）
6. **P1-5** AnsiLogPanel ANSI 颜色渲染（日志可读性核心需求）
7. **P1-10** 移动端基础适配（响应式底线）
