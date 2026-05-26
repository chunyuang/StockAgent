# V60 前端UI审查报告

> 审查范围：18个前端文件（回测7个+实盘4个+通用4个+API/Config 3个）
> 审查时间：2026-05-27
> 审查重点：数据显示正确性、交互体验、视觉效果、功能完整性、回测-实盘一致性

---

## 数据显示Bug（必须修复）

### BUG-1: SystemStatusView 百分比显示未做小数/百分比归一化
- **文件**: `SystemStatusView.vue:148-168`
- **问题**: `cumulative_return`、`win_rate`、`max_drawdown` 直接调用 `.toFixed(2)%`，但后端返回值可能是小数（0.7328=73.28%）也可能是百分比（73.28）。当前代码无论哪种都直接加`%`，如果后端返回小数则显示为 `0.73%` 而非 `73.28%`。而同系统的 BacktestResultPanel 明确注释"后端已是百分比形式"。
- **修复建议**: 确认 `/system/strategy-stats` 接口返回格式。如果返回小数，需 `×100`；如果返回百分比，当前代码正确。建议统一与回测模块一致（百分比格式），并在API文档中明确标注。

### BUG-2: SystemStatusView 风控配置输入框单位歧义
- **文件**: `SystemStatusView.vue:206-220`
- **问题**: `enhanced_stop_loss_pct` 以小数存储（0.08），输入框 `ElInputNumber` 的 min=0.01, max=0.5, step=0.01，但旁边百分比标注用 `×100` 显示（8%）。用户可能困惑：输入0.08还是8？当前逻辑是输入0.08显示8%，对非技术用户不直观。
- **修复建议**: 改为用户友好的百分比输入：`v-model` 绑定到 `×100` 后的值，min=1, max=50, step=1，提交时 `÷100` 还原。与 CockpitView 参数面板保持一致。

### BUG-3: CockpitView 今日盈亏计算存在精度问题
- **文件**: `CockpitView.vue` (todayPnl computed)
- **问题**: 卖出盈亏 fallback 计算用 `costAmt = shares * price / (1 + profit_pct / 100)`，但 `price` 是卖出价而非买入价，用此反推买入金额存在舍入误差。且如果 `profit_pct` 很小接近0时除法不稳定。注释标注了 V59 修复优先使用 `profit_amount`，但 fallback 路径仍有风险。
- **修复建议**: 1) 确保后端始终返回 `profit_amount` 字段；2) fallback 中从 PositionInfo 的 `cost_price` 和 `shares` 计算而非反推。

### BUG-4: MarketMonitorView 持仓排序 buy_time 字段不存在
- **文件**: `MarketMonitorView.vue` (sortedPositions computed)
- **问题**: `posSort.value === 'time'` 时排序用 `b.buy_time`，但 `PositionInfo` 接口定义中没有 `buy_time` 字段。实际排序会全部返回 undefined，导致排序无效。
- **修复建议**: 使用 `buy_date` 或后端实际返回的字段名，或在 `PositionInfo` 接口中添加 `buy_time` 字段。

### BUG-5: BacktestResultPanel 月度累计收益用简单加法而非连乘
- **文件**: `BacktestResultPanel.vue` (monthlyReturnChartOption computed)
- **问题**: 累计收益用 `cumVal += r` 简单加法计算，但月度收益率是百分比，正确累计应该用连乘：`cumVal = (1 + r/100) * cumVal - 1`。对于小月度收益（1-3%），加法和连乘差异不大；但对于大收益月份（20%+），加法会显著低估累计值。
- **修复建议**: 改为连乘计算：
  ```typescript
  let cumVal = 0
  for (const r of returns) {
    cumVal = (1 + cumVal / 100) * (1 + r / 100) - 1
    cumReturns.push(+cumVal.toFixed(2))
  }
  ```
  或者更好的方式：直接从 net_value_series 取月末值计算真实累计收益。

### BUG-6: StrategyConfigPanel 参数值显示混乱（小数 vs 百分比）
- **文件**: `StrategyConfigPanel.vue` + `strategyDefaults.ts`
- **问题**: 策略参数以小数存储（如 `stop_loss_pct: 0.03`），但 SWEEP_PARAMS 的 `factor: 100` 暗示前端需要 `×100` 转换。StrategyConfigPanel 直接展示小数（0.03），用户看到"止损 0.03"而非"止损 3%"。这与 BacktestResultPanel 的 fmtPct 处理不一致。
- **修复建议**: 在参数配置面板中统一做 `×100` 显示转换，附加 `%` 单位。可参考 SWEEP_PARAMS 的 factor 定义统一处理。

### BUG-7: BacktestHistoryPanel total_return 字段不一致
- **文件**: `BacktestHistoryPanel.vue` + `backtest.ts` (BacktestHistoryItem)
- **问题**: API 类型定义中同时有 `total_return_pct`、`total_return`、`final_value` 三个字段，历史面板使用哪个不确定。如果 `total_return` 是小数而 `total_return_pct` 是百分比，混用会导致 `0.73%` vs `73.28%` 的显示错误。
- **修复建议**: 统一使用 `total_return_pct`（百分比形式），废弃 `total_return`，或明确文档化两者关系。

---

## 交互体验改进

### UX-1: 回测参数配置缺少预设方案
- **文件**: `StrategyConfigPanel.vue`
- **问题**: 用户每次回测需要手动调整多个参数，没有"一键还原默认"或"预设方案"功能。常见场景：调整参数后发现效果不好，想回到已知好的配置。
- **建议**: 1) 添加"恢复默认值"按钮；2) 支持保存/加载参数预设（如"激进型"/"稳健型"）；3) 记住上次成功的参数配置。

### UX-2: 回测历史缺少对比功能
- **文件**: `BacktestHistoryPanel.vue`
- **问题**: 历史列表只能查看单条记录详情，无法选择2-3条记录进行指标对比。用户需要频繁切换才能比较不同参数的效果。
- **建议**: 添加多选模式，选中后弹出对比面板（净值曲线叠加、指标并列对比表）。

### UX-3: 交易记录表格列过多，水平滚动体验差
- **文件**: `BacktestResultPanel.vue` (交易记录 Tab)
- **问题**: 交易记录有13列（买入日/卖出日/代码/名称/策略/买入价/卖出价/盈亏额/收益率/持仓天数/股数/卖出原因），在小屏幕上需要大量水平滚动。关键列（收益率/卖出原因）可能被遮挡。
- **建议**: 1) 默认隐藏低频列（股数/买入价/卖出价），用"列设置"让用户自选；2) 或改为卡片模式，每笔交易一张小卡片，信息更紧凑。

### UX-4: 日志面板缺少时间跳转
- **文件**: `AnsiLogPanel.vue`
- **问题**: 回测日志可能有数千行，用户需要手动滚动查找特定日期/策略的日志。虽然支持日期和策略筛选，但不支持跳转到特定序号或搜索结果的上/下一条。
- **建议**: 1) 添加"跳转到第N行"输入框；2) 搜索结果高亮并支持上/下一条导航；3) 添加错误行快捷跳转（只看ERROR/WARNING）。

### UX-5: 市场监控页面信息密度过高
- **文件**: `MarketMonitorView.vue`
- **问题**: 3列布局包含策略控制、信号、持仓、涨跌停池、时间线等大量信息，在1920px屏幕上每个区域空间有限，内容被压缩。信号列表尤其拥挤。
- **建议**: 1) 信号列表改为虚拟滚动，避免DOM过多；2) 涨跌停池默认折叠，点击展开；3) 策略控制区域可拖拽调整高度。

### UX-6: 驾驶舱与市场监控功能重叠
- **文件**: `CockpitView.vue` vs `MarketMonitorView.vue`
- **问题**: 两个视图都包含信号、持仓、涨跌停池、时间线等核心功能，且代码大量重复。用户不清楚该用哪个，导航栏两个入口容易混淆。
- **建议**: 明确两者定位——驾驶舱聚焦"决策"（风控仪表盘+9层管道+参数热更新），市场监控聚焦"监控"（信号流+持仓实时状态）。在导航栏添加描述区分，或合并为一个页面的两个Tab。

### UX-7: 回测运行中无法调整参数
- **文件**: `UltraShortBacktestViewV2.vue`
- **问题**: 回测运行时（status=running），策略配置面板变灰不可编辑。如果用户想微调参数再跑一次，需要等当前回测完成、记住参数、再手动调整。缺乏"基于当前参数微调并重新运行"的快捷操作。
- **建议**: 在回测运行期间允许编辑参数（编辑不会影响正在运行的回测），添加"复制当前参数并重新回测"按钮。

---

## 视觉效果提升

### VIS-1: 暗色模式下图表颜色对比度不足
- **文件**: `BacktestResultPanel.vue`, `StockChart.vue`
- **问题**: 部分图表使用 CSS 变量（`var(--stock-down)` 等），暗色模式下如果变量未正确设置，颜色可能对比度不足。特别是 `stock-down-bg`（绿色背景区域）在深色背景上可能看不清。
- **建议**: 检查所有 `--stock-down`/`--stock-up` 及其 `-bg` 变量在暗色主题下的值，确保 WCAG AA 对比度标准（4.5:1）。可添加 `prefers-contrast: more` 媒体查询增强。

### VIS-2: KPI 指标卡片缺少视觉层级
- **文件**: `BacktestResultPanel.vue` (kpi-strip)
- **问题**: 8个KPI指标卡片平铺，没有主次之分。累计收益、夏普比率明显比信号数更重要，但视觉权重相同。
- **建议**: 1) 核心指标（累计收益/最大回撤/夏普）加大字号和宽度；2) 次要指标（信号数/交易笔数）缩小；3) 或用2行布局，第一行3个核心大卡片，第二行5个辅助小卡片。

### VIS-3: 交易记录正负颜色依赖全局变量
- **文件**: 多个文件
- **问题**: 盈利色用 `var(--stock-down)`（绿色，中国涨跌惯例），亏损色用 `var(--stock-up)`（红色）。但变量命名（stock-down=涨）对中国用户反直觉，代码可读性差。
- **建议**: 定义语义化变量名：`--color-profit`（盈利/红）、`--color-loss`（亏损/绿）、`--color-profit-bg`、`--color-loss-bg`，底层映射到实际颜色值。

### VIS-4: 策略配置面板缺少参数说明 Tooltip
- **文件**: `StrategyConfigPanel.vue`
- **问题**: 参数名称如 `min_correction_pct`、`hit_probability_normal` 对非技术用户不友好，且没有鼠标悬停说明。
- **建议**: 1) 为每个参数添加 Tooltip 说明（参考 FactorReferencePanel 的因子描述风格）；2) 参数名显示中文，代码用英文 key。

### VIS-5: 空状态设计不统一
- **文件**: 多个文件
- **问题**: 不同组件的空状态设计不一致：`AnsiLogPanel` 用自定义提示文字，`BacktestResultPanel` 用 `ElEmpty`，`SignalTracePanel` 用自定义CSS。图标大小、文字颜色、间距各不相同。
- **建议**: 创建统一的 `EmptyState` 组件，支持自定义图标、标题、描述、操作按钮。全局统一样式。

### VIS-6: 侧边栏菜单图标不统一
- **文件**: `MainLayout.vue`
- **问题**: 驾驶舱菜单项用 emoji（🚀）前缀，其他菜单项用 Element Plus 图标。视觉风格不统一。
- **建议**: 统一使用 Element Plus 图标或 SVG 图标，emoji 仅在数据展示区使用。

---

## 功能增强建议

### FEAT-1: 回测结果一键应用到实盘参数
- **文件**: `BacktestResultPanel.vue` → `StrategyConfigPanel.vue`
- **问题**: 回测得出的最优参数无法一键同步到实盘。用户需要手动对比回测参数和实盘参数，逐个修改。
- **建议**: 在回测结果页添加"应用到实盘"按钮，点击后弹出参数对比确认框（回测值 vs 当前实盘值），确认后写入 ParamCenter(MongoDB)。

### FEAT-2: 回测历史结果对比视图
- **文件**: `BacktestHistoryPanel.vue`
- **问题**: 历史记录只有列表，无法视觉化对比多次回测的净值曲线和指标。
- **建议**: 支持多选历史记录，在叠加图中显示多条净值曲线，下方并排显示KPI对比表。

### FEAT-3: 交易记录点击跳转到K线图
- **文件**: `BacktestResultPanel.vue`, `StockChart.vue`
- **问题**: 交易记录中只有代码和价格，无法直观看到买卖点在K线上的位置。
- **建议**: 点击交易行展开详情，包含该股票在回测期间的K线图，买卖点用箭头标注。

### FEAT-4: 实时回测进度可视化
- **文件**: `UltraShortBacktestViewV2.vue`
- **问题**: 回测运行时只显示"运行中"状态和旋转图标，没有进度百分比或当前执行到哪一天。
- **建议**: 1) 后端返回当前处理日期/进度百分比；2) 前端显示进度条和"正在处理 2026-03-15..."状态；3) 实时日志流（当前 AnsiLogPanel 支持但未默认展示）。

### FEAT-5: 参数扫描结果热力图
- **文件**: `backtest.ts` (SweepResult)
- **问题**: 参数扫描返回离散值的结果，缺乏二维参数组合的可视化（如止损 vs 止盈的收益热力图）。
- **建议**: 支持双参数扫描，结果用热力图展示（X轴参数1，Y轴参数2，颜色=收益率/夏普）。

### FEAT-6: 数据状态面板缺少缺失数据提示
- **文件**: `DataStatusPanel.vue`
- **问题**: 只显示数据条数和时间范围，不提示哪些日期/股票的数据缺失。如果某天数据断档，用户无法直观发现。
- **建议**: 添加"数据完整性"检查：1) 对比交易日历，标红缺失的交易日；2) 显示连续缺失天数（如"3月15-17日缺失"）；3) 提供"补数据"快捷操作。

### FEAT-7: 策略因子面板缺少实时因子值
- **文件**: `StrategyFactorPanel.vue`
- **问题**: 因子面板只显示因子定义和参考范围，不显示当前选中股票的实时因子值。用户需要切换到其他页面查看。
- **建议**: 在因子卡片中添加"当前值"字段，从信号/持仓数据中读取并显示。

### FEAT-8: 驾驶舱缺少盈亏曲线历史
- **文件**: `CockpitView.vue`
- **问题**: pnlOption 的数据来源是从 /performance-history 拉取的快照，如果后端没有存储历史快照，则 fallback 用 timeline 构建（精度低）。
- **建议**: 后端定时保存账户快照到MongoDB，前端展示30天净值/回撤曲线。

---

## 回测-实盘UI一致性

### ALIGN-1: 策略参数配置界面不一致
- **文件**: `StrategyConfigPanel.vue` (回测) vs `MarketMonitorView.vue` (实盘编辑弹窗)
- **问题**: 回测的参数配置用独立面板，布局为表单式分组；实盘的参数编辑用 Dialog 弹窗+Tab 切换。参数项名称和顺序不完全一致（回测有 `min_close_rise_pct` 但实盘编辑器可能没有）。用户在回测调优后切换到实盘会找不到对应参数。
- **建议**: 抽取共享的 `StrategyParamForm` 组件，回测和实盘共用，确保参数列表和顺序完全一致。

### ALIGN-2: 结果展示格式不统一
- **文件**: `BacktestResultPanel.vue` (回测) vs `CockpitView.vue` (实盘)
- **问题**: 回测的盈亏显示用 `fmtPct`（百分比+2位小数），实盘的持仓盈亏用 `.toFixed(1)%`（1位小数）。回测的金额显示从交易记录推算，实盘直接用 `profit_amount` 字段。格式差异导致用户在两个页面看到的数字精度不同。
- **建议**: 创建共享的 `formatUtils.ts`，统一百分比格式（2位小数）、金额格式（万元/元自动切换）、盈亏色逻辑。

### ALIGN-3: 策略中文名映射分散
- **文件**: `backtestConstants.ts` (STRATEGY_NAMES) vs `MarketMonitorView.vue` (strategyCN) vs `CockpitView.vue` (strategyMeta)
- **问题**: 策略中文名在3个地方分别定义，且内容不完全一致：
  - backtestConstants: `halfway_chase: '🏃‍♂️ 半路追涨'`
  - MarketMonitorView 引入 `strategyCN` from `@/utils/scanner`
  - CockpitView 引入 `strategyMeta` from `@/utils/scanner`
  如果新增策略，需要同步修改3处。
- **建议**: 统一到 `@/config/strategyDefaults.ts`（已有 STRATEGY_CONFIGS），中文名从中派生，其他地方引用。删除 `backtestConstants.ts` 中的 STRATEGY_NAMES，改为从 strategyDefaults 导入。

### ALIGN-4: 涨跌色方向全局不统一
- **文件**: 全局
- **问题**: CSS变量 `--stock-down` 在中国惯例下是"跌"（绿色），但代码中用它表示"盈利"（实际是涨）。变量名语义与业务含义不一致：
  - 回测: `var(--stock-down)` = 盈利色（红，中国涨=红）
  - 实盘: 同上
  - 但变量名"stock-down"暗示"下跌/绿"
- **建议**: 重命名为 `--color-profit`/`--color-loss`，底层值保持不变。详见 VIS-3。

### ALIGN-5: 数据源状态展示方式差异大
- **文件**: `DataStatusPanel.vue` (回测) vs `CockpitView.vue` 数据源卡片 (实盘)
- **问题**: 回测的数据状态面板用表格展示（数据源/条数/时间范围），实盘用小卡片+状态指示灯。用户无法快速判断两边数据是否一致。
- **建议**: 统一为卡片式展示，共享同一个数据源状态组件。

---

## 总结优先级

| 优先级 | 编号 | 简述 | 影响范围 |
|--------|------|------|---------|
| **P0** | BUG-5 | 月度累计收益计算错误（加法vs连乘） | 回测结果展示 |
| **P0** | BUG-1 | SystemStatusView百分比格式不确定 | 系统管理页 |
| **P0** | BUG-7 | 历史面板 total_return 字段歧义 | 回测历史 |
| **P1** | BUG-4 | 持仓排序 buy_time 字段不存在 | 实盘监控 |
| **P1** | BUG-6 | 参数配置显示0.03而非3% | 回测配置 |
| **P1** | BUG-2 | 风控输入框单位歧义 | 系统管理页 |
| **P1** | BUG-3 | 今日盈亏fallback精度问题 | 驾驶舱 |
| **P1** | ALIGN-3 | 策略中文名3处分散定义 | 全局维护性 |
| **P1** | ALIGN-1 | 回测/实盘参数配置不统一 | 用户体验 |
| **P2** | UX-1 | 参数配置缺预设方案 | 回测效率 |
| **P2** | UX-2 | 回测历史缺对比功能 | 回测效率 |
| **P2** | UX-3 | 交易记录列过多 | 信息密度 |
| **P2** | FEAT-1 | 回测结果一键应用实盘 | 工作流 |
| **P2** | VIS-2 | KPI卡片缺视觉层级 | 视觉效果 |
| **P3** | 其余 | 见各节详细说明 | 改善体验 |
