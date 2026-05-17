# 前端审查报告 v3 — 实盘交易界面

**审查日期**: 2026-05-18  
**分支**: feature/live-trading  
**审查范围**: 实盘交易相关前端6个核心文件  

---

## 一、问题列表

### 🔴 P0 — 严重问题（影响核心功能或数据安全）

#### P0-1: LiveTradingView 已废弃但仍存在，与 MarketMonitorView 功能重叠
- **文件**: `LiveTradingView.vue` (481行)
- **描述**: 路由已将 `/live-trading` 重定向到 `/monitor`，但该文件仍存在于代码库中。它使用完全不同的API（`tradingApi` vs `api`），不同的数据模型（`TradingSignal` vs `ScanSignal`），不同的交易流程。维护两套代码容易造成混淆，且 LiveTradingView 的API端点（`/trading/signals`, `/trading/accounts`）可能已不存在或与Scanner API不一致。
- **修复方案**: 删除 `LiveTradingView.vue`，确认所有路由指向 `/monitor`。如有独特功能（如调度器控制），迁移到 MarketMonitorView。

#### P0-2: 交易确认弹窗的 onConfirm 是异步函数但无 loading 状态
- **文件**: `MarketMonitorView.vue` L141-145
- **描述**: `quickBuy` 和 `quickSell` 的 `onConfirm` 回调是 async 函数，但确认弹窗没有 loading 状态。用户可能重复点击"确认执行"按钮，导致重复下单。
- **修复方案**: 在确认弹窗中增加 `confirmLoading` ref，`onConfirm` 执行期间禁用按钮并显示 loading。

#### P0-3: 手动下单无二次确认
- **文件**: `MarketMonitorView.vue` L147 `executeManualTrade`
- **描述**: `quickBuy`/`quickSell` 有 `showConfirm` 二次确认，但手动下单直接执行，没有任何确认步骤。手动输入代码和数量更容易出错（如多打一个0），风险更大。
- **修复方案**: `executeManualTrade` 增加 `showConfirm` 确认弹窗，显示代码/方向/数量/价格。

#### P0-4: 一键清仓无确认弹窗
- **文件**: `MarketMonitorView.vue` L156 `sellAllPositions`
- **描述**: `sellAllPositions` 直接调用 API 清仓，没有任何确认步骤。这是最危险的操作之一，误触可能导致全部持仓被卖出。
- **修复方案**: 增加 `ElMessageBox.confirm` 或 `showConfirm`，显示持仓数量和总市值。

#### P0-5: 重置账户无确认弹窗
- **文件**: `MarketMonitorView.vue` L155 `resetAccount`
- **描述**: 重置账户会清空所有持仓和交易记录，但直接执行无确认。与"一键清仓"一样危险。
- **修复方案**: 增加 `ElMessageBox.confirm`，明确提示"将清空所有持仓和交易记录，不可恢复"。

---

### 🟠 P1 — 重要问题（影响用户体验或数据准确性）

#### P1-1: MarketMonitorView 单文件637行，职责过重
- **文件**: `MarketMonitorView.vue`
- **描述**: 包含信号列表、持仓监控、时间线、策略编辑、手动下单、涨跌停池、复盘报告、周报、9层调试、扫描Trace、交易审查、回测对比等12+功能模块，全部在一个文件中。模板、逻辑、样式都极长，难以维护。
- **修复方案**: 拆分为子组件：
  - `SignalList.vue` — 信号列表+筛选
  - `PositionMonitor.vue` — 持仓卡片+止损止盈
  - `TimelinePanel.vue` — 时间线+历史回放
  - `StrategyControl.vue` — 策略开关+编辑
  - `ManualTradeForm.vue` — 手动下单
  - `LimitPoolPanel.vue` — 涨跌停池
  - 各弹窗也独立为组件

#### P1-2: WebSocket 重连无指数退避，可能造成服务器压力
- **文件**: `MarketMonitorView.vue` L170 `connectWS`
- **描述**: WS断开后固定3秒重连，如果服务器长时间不可用，客户端会持续高频重连。
- **修复方案**: 实现指数退避重连（3s → 6s → 12s → 30s → 60s），连接成功后重置。

#### P1-3: WS消息处理中收到任何消息都触发 `fetchScanner()`
- **文件**: `MarketMonitorView.vue` L166-169
- **描述**: `scanner_signal`、`scanner_timeline`、`scanner_status` 三种消息类型都额外调用 `fetchScanner()`（5个API并发请求），在WS高频推送时会造成大量冗余请求。
- **修复方案**: WS消息只更新对应数据，不额外fetch。或加 debounce（如500ms内合并多次更新）。

#### P1-4: 信号列表无虚拟滚动，大量信号时性能问题
- **文件**: `MarketMonitorView.vue` 信号列表区域
- **描述**: 信号用 `v-for` 直接渲染，如果全市场扫描产生数百个信号，DOM节点过多会导致卡顿。
- **修复方案**: 使用虚拟滚动（如 `vue-virtual-scroller`）或限制显示数量（如只显示前50条+分页）。

#### P1-5: 持仓卡片排序逻辑在模板中
- **文件**: `MarketMonitorView.vue` 持仓区域
- **描述**: `[...positions].sort((a, b) => a.profit_pct - b.profit_pct)` 在模板中直接计算，每次渲染都会创建新数组并排序。
- **修复方案**: 提取为 computed 属性 `sortedPositions`。

#### P1-6: PositionDetailTable 和 PositionSummaryCards 未被 MarketMonitorView 使用
- **文件**: `PositionDetailTable.vue`, `PositionSummaryCards.vue`
- **描述**: MarketMonitorView 自己实现了持仓展示（卡片形式），而这两个组件是 LiveTradingView 的配套组件。路由已重定向，这两个组件成为死代码。
- **修复方案**: 要么删除，要么将 PositionDetailTable/PositionSummaryCards 集成到 MarketMonitorView 的持仓区域（提供表格/卡片两种视图切换）。

#### P1-7: 手动下单缺少价格输入和验证
- **文件**: `MarketMonitorView.vue` L146-149
- **描述**: 手动下单表单有 `price` 字段但UI中无价格输入框（只有代码、方向、数量）。`manualTrade.price` 默认为0，市价单传0可能被后端拒绝或以0价格成交。
- **修复方案**: 增加价格输入框，或明确标注"市价单"并确保后端支持 price=0 的市价逻辑。

#### P1-8: LiveTradingView 使用原生 fetch 而非 api client
- **文件**: `LiveTradingView.vue` L221-244
- **描述**: `loadSchedulerStatus`、`toggleScheduler`、`triggerPhase` 直接用 `fetch('/api/v1/...')`，绕过了统一的 API client（无 JWT 注入、无错误处理、无 Token 刷新）。
- **修复方案**: 改用 `api.get()`/`api.post()`。如果此文件被废弃则直接删除。

#### P1-9: 持仓卡片"距止损"计算逻辑可能不正确
- **文件**: `MarketMonitorView.vue` 持仓区域
- **描述**: `pos.profit_pct + (pos.stop_loss_pct || 3)` 这个公式含义不明确。如果 `profit_pct` 是当前盈亏百分比，`stop_loss_pct` 是止损百分比（如3%），那么"距止损"应该是 `profit_pct + stop_loss_pct`（当前盈利3% + 止损线-3% = 距止损6%），但这只在 `stop_loss_pct` 是正数时成立。如果后端返回的 `stop_loss_pct` 已经是负数，计算就错了。
- **修复方案**: 使用后端返回的 `stop_loss_price` 和 `current_price` 计算距离：`((current_price - stop_loss_price) / current_price * 100).toFixed(1)%`。

#### P1-10: 策略编辑弹窗无参数校验
- **文件**: `MarketMonitorView.vue` 策略编辑弹窗
- **描述**: `saveStrategy` 直接将 `editParams` 和 `editRiskParams` 发送给后端，没有前端校验。用户可能输入超出范围的值（如止损-100%），导致后端异常。
- **修复方案**: 保存前校验参数范围（利用 `paramDescriptions` 中的 min/max），超出范围时提示用户。

---

### 🟡 P2 — 一般问题（可优化但不影响核心功能）

#### P2-1: 涨跌停池只显示前20条，无分页或"查看更多"
- **文件**: `MarketMonitorView.vue` 涨跌停池区域
- **描述**: `.slice(0, 20)` 硬编码截断，牛市涨停池可能超过100只，用户看不到完整数据。
- **修复方案**: 增加"展开更多"按钮，或改为虚拟滚动列表。

#### P2-2: 时间线区域高度固定180px，交易密集时信息密度低
- **文件**: `MarketMonitorView.vue` `.mm-footer`
- **描述**: 底部时间线 `max-height: 180px`，在交易密集时需要频繁滚动。且无法调整高度。
- **修复方案**: 增加拖拽调整高度功能，或提供"全屏时间线"按钮。

#### P2-3: 信号过期倒计时每秒更新所有信号，性能浪费
- **文件**: `MarketMonitorView.vue` L126-128
- **描述**: `nowMs` 每秒更新触发所有信号的 `signalRemaining` 重新计算。如果信号很多，每秒都会触发大量DOM更新。
- **修复方案**: 只在信号数量>20时降低更新频率（如5秒），或使用 CSS animation 替代 JS 倒计时。

#### P2-4: 深色模式支持不完整
- **文件**: `MarketMonitorView.vue`
- **描述**: MainLayout 支持深色模式切换，但 MarketMonitorView 大量使用硬编码颜色（`#f5f7fa`, `#fff`, `#303133` 等），深色模式下显示异常。
- **修复方案**: 使用 CSS 变量（`var(--el-bg-color)` 等）替代硬编码颜色。

#### P2-5: 响应式布局在1024px以下直接变为单列，体验差
- **文件**: `MarketMonitorView.vue` `.mm-body` 响应式
- **描述**: `@media (max-width: 1024px)` 直接变为单列，三列内容堆叠后页面极长，且无Tab切换。
- **修复方案**: 移动端改为Tab布局（信号/持仓/策略三个Tab），而非简单堆叠。

#### P2-6: PositionDetailTable 的合计行格式化不完整
- **文件**: `PositionDetailTable.vue` L72
- **描述**: `summary-method` 返回的数组硬编码了11列，如果列顺序或数量变化，合计行会错位。
- **修复方案**: 使用列索引或列 prop 动态计算合计。

#### P2-7: PositionSummaryCards 的 KPI 网格在窄屏下6列→3列，但中间断点缺失
- **文件**: `PositionSummaryCards.vue`
- **描述**: 只有 `@media (max-width: 768px)` 一个断点，在768-1024px范围内6列KPI可能挤压变形。
- **修复方案**: 增加 `@media (max-width: 1024px)` 断点，4列布局。

#### P2-8: App.vue 的 auth check 在每次挂载时执行
- **文件**: `App.vue`
- **描述**: `onMounted` 中调用 `checkAuth()`，但路由守卫已经自动设置 mock token。如果 `checkAuth` 发起网络请求，每次页面刷新都会多一次请求。
- **修复方案**: 确认 `checkAuth` 的实现，如果只是检查 localStorage 则无问题；如果发起API请求则应优化。

#### P2-9: MainLayout 侧边栏固定定位但主内容区用 margin-left 偏移
- **文件**: `MainLayout.vue`
- **描述**: 侧边栏 `position: fixed`，主内容区 `margin-left` 动态计算。如果侧边栏折叠/展开动画与 margin 过渡不同步，会出现内容跳动。
- **修复方案**: 确保两者 transition duration 一致（当前都是0.3s，应无问题，但需注意 v-bind 的响应式更新时机）。

#### P2-10: LiveTradingView 的调度器控制功能在 MarketMonitorView 中缺失
- **文件**: `LiveTradingView.vue` Tab4
- **描述**: LiveTradingView 有完整的调度器控制面板（启动/停止/手动触发阶段/3阶段说明），MarketMonitorView 只有简单的启停按钮，缺少手动触发阶段功能。
- **修复方案**: 将调度器控制功能迁移到 MarketMonitorView 的策略控制区域，或作为独立Tab。

---

## 二、优化建议

### 🎯 交易操作用户体验

#### UX-1: 买入/卖出流程增加滑点提示
- **当前**: `quickBuy` 显示"买入 100股 × ¥12.34 ≈ ¥1234"，但实际成交可能有滑点。
- **建议**: 在确认弹窗中增加"预计滑点0.1%，实际成交价可能略高"的提示。

#### UX-2: 卖出按钮区分T+1和可卖
- **当前**: T+1持仓的卖出按钮显示 `disabled`，但用户不知道为什么不能卖。
- **建议**: T+1持仓显示"🔒 T+1"标签替代卖出按钮，hover时提示"当日买入的股票T+1日才可卖出"。

#### UX-3: 交易操作增加声音/震动反馈
- **建议**: 买入成功播放短促上升音效，卖出成功播放下降音效，止损触发播放警告音。可通过 Web Audio API 实现。

#### UX-4: 手动下单增加股票搜索
- **当前**: 手动下单只能输入代码，用户需要记住完整代码。
- **建议**: 增加搜索框，输入名称或代码前几位自动补全（从信号/持仓列表中匹配）。

### 📊 实时数据展示

#### UX-5: 信号卡片增加迷你分时图
- **建议**: 每个信号卡片右侧显示当日分时走势缩略图（sparkline），直观展示价格走势。

#### UX-6: 持仓卡片增加盈亏趋势
- **建议**: 持仓卡片显示最近5日盈亏变化趋势（小折线图），帮助判断是否应该继续持有。

#### UX-7: 时间线增加图形化展示
- **当前**: 时间线是纯文本列表。
- **建议**: 改为时间轴图形（竖线+节点），买入节点红色、卖出节点绿色，hover显示详情。

#### UX-8: 涨跌停池增加封板强度可视化
- **建议**: 涨停池每只股票显示封板资金柱状图，直观对比封板强度。

### 🛑 交易终止功能

#### UX-9: 停止扫描器增加确认和状态说明
- **当前**: 点击"⏹ 停止"直接停止，无确认。
- **建议**: 停止前确认"将停止扫描，已有持仓不受影响"。停止后状态栏显示"已暂停 — 持仓仍在监控中"或"已完全停止"。

#### UX-10: 增加紧急停止按钮
- **建议**: 在顶部状态栏增加醒目的"🚨 紧急停止"按钮（红色大按钮），一键停止扫描+清仓。需要二次确认。

#### UX-11: 熔断状态更醒目
- **当前**: 熔断只显示一个小Tag。
- **建议**: 熔断时顶部状态栏变红+闪烁，显示熔断原因和重置按钮。

### 📈 交易报告和总结

#### UX-12: 复盘报告增加图表
- **当前**: 复盘报告只有数字。
- **建议**: 增加当日盈亏分布饼图、策略收益柱状图、持仓热力图。

#### UX-13: 增加月度/季度报告
- **当前**: 只有日报和周报。
- **建议**: 增加月报和季报，展示长期趋势和策略稳定性。

#### UX-14: 绩效看板
- **建议**: 在持仓区域上方增加核心KPI看板：累计收益率、最大回撤、夏普比率、胜率、盈亏比，实时更新。

### ⚠️ 错误处理和边界情况

#### UX-15: 网络断开时明确提示
- **当前**: API请求失败只显示 ElMessage.error，用户可能不知道是网络问题。
- **建议**: 检测到网络断开时，顶部显示持久性警告条"⚠️ 网络已断开，数据可能不是最新"，恢复后自动消失。

#### UX-16: WebSocket 断开时降级提示
- **当前**: WS断开后静默重连，用户不知道实时推送已中断。
- **建议**: WS断开时状态栏显示"📡 实时推送已断开，正在重连..."，重连成功后显示"📡 已恢复实时推送"。

#### UX-17: 数据异常时防御性展示
- **建议**: 对关键数据（价格、盈亏）增加合理性检查。如 `current_price <= 0` 时显示"--"而非"¥0.00"，`profit_pct` 超过±20%时标红警告。

#### UX-18: API请求超时友好提示
- **当前**: 超时5分钟，用户可能以为卡死。
- **建议**: 长时间请求（如扫描）增加进度提示，或轮询状态而非等待。

### 🎨 视觉优化

#### UX-19: 信号卡片颜色编码优化
- **建议**: 不同策略的信号卡片左侧增加彩色竖条（与策略颜色对应），快速区分策略类型。

#### UX-20: 持仓盈亏热力图
- **建议**: 持仓列表背景色根据盈亏程度渐变（深绿→浅绿→浅红→深红），一眼看出持仓健康度。

#### UX-21: 顶部状态栏增加大盘指数
- **建议**: 在状态栏左侧增加上证/深证/创业板三个小指标，显示当日涨跌幅。

### ⚡ 性能优化

#### UX-22: 大数据量时使用虚拟滚动
- **建议**: 信号列表、持仓列表、时间线、涨跌停池都应考虑虚拟滚动，特别是信号可能超过100条。

#### UX-23: 减少不必要的API调用
- **建议**: `fetchAll` 一次调用5个API，但很多数据变化不频繁（如策略配置、数据源）。可以分级刷新：高频（5s）只刷新信号/持仓/时间线，低频（60s）刷新策略/数据源/涨跌停池。

#### UX-24: 图片/图标懒加载
- **建议**: 策略图标（emoji）虽然不需要懒加载，但如果未来增加股票logo，应使用懒加载。

---

## 三、代码质量问题

### CQ-1: MarketMonitorView 变量声明过于密集
- **位置**: L74-100
- **问题**: 大量 `ref` 和 `reactive` 声明挤在一起，没有分组注释，难以快速定位。
- **建议**: 按功能分组（状态类、数据类、UI控制类、弹窗类），每组之间加空行和注释。

### CQ-2: 重复的策略名称映射
- **问题**: `strategyNameMap` 在 `LiveTradingView.vue` 和 `PositionDetailTable.vue` 中各有一份，且内容不完全一致。
- **建议**: 提取到 `@/constants/strategy.ts` 统一管理。

### CQ-3: API路径硬编码
- **问题**: `scannerApi = '/scanner'`, `configApi = '/strategy-config'` 硬编码在组件中。
- **建议**: 提取到 `@/api/modules/scanner.ts`，与其他API模块统一管理。

### CQ-4: 类型定义重复
- **问题**: `ScanSignal`, `PositionInfo`, `TimelineItem` 等接口在 MarketMonitorView 中内联定义，与 `api/types.ts` 和 `api/modules/trading.ts` 中的类型重复且不一致。
- **建议**: 统一到 `@/api/types.ts`，组件中 import 使用。

### CQ-5: CSS类名过短且无命名空间
- **问题**: `.mm`, `.sl`, `.st`, `.qa`, `.mf` 等类名过短，容易与全局样式冲突。
- **建议**: 使用 BEM 命名或增加前缀，如 `.monitor__signal-list`, `.monitor__strategy-control`。

### CQ-6: LiveTradingView 的 `loadAll` 中 `loadPool` 失败被静默忽略
- **位置**: LiveTradingView.vue L100-104
- **问题**: `loadPool` 的 catch 块为空，用户看不到任何错误提示。
- **建议**: 至少 `console.error` 或显示 ElMessage。

---

## 四、优先级排序

| 优先级 | 编号 | 简述 | 预估工时 |
|--------|------|------|----------|
| 🔴 P0 | P0-2 | 交易确认弹窗无loading防重复 | 0.5h |
| 🔴 P0 | P0-3 | 手动下单无确认 | 0.5h |
| 🔴 P0 | P0-4 | 一键清仓无确认 | 0.5h |
| 🔴 P0 | P0-5 | 重置账户无确认 | 0.5h |
| 🔴 P0 | P0-1 | 删除废弃LiveTradingView | 1h |
| 🟠 P1 | P1-3 | WS消息去重/debounce | 1h |
| 🟠 P1 | P1-2 | WS重连指数退避 | 0.5h |
| 🟠 P1 | P1-7 | 手动下单增加价格输入 | 1h |
| 🟠 P1 | P1-9 | 距止损计算修正 | 0.5h |
| 🟠 P1 | P1-5 | 持仓排序提取computed | 0.5h |
| 🟠 P1 | P1-10 | 策略编辑参数校验 | 1h |
| 🟠 P1 | P1-6 | 处理死代码组件 | 1h |
| 🟠 P1 | P1-1 | MarketMonitorView拆分 | 4h |
| 🟠 P1 | P1-4 | 信号列表虚拟滚动 | 2h |
| 🟠 P1 | P1-8 | LiveTradingView改用api client | (如删除则不需要) |
| 🟡 P2 | P2-1~P2-10 | 各项一般问题 | 4h |
| 🎯 UX | UX-15~UX-18 | 错误处理增强 | 3h |
| 🎯 UX | UX-9~UX-11 | 交易终止优化 | 2h |
| 🎯 UX | UX-12~UX-14 | 报告增强 | 3h |
| 🎯 UX | UX-1~UX-4 | 交易UX优化 | 2h |
| 🎯 UX | UX-5~UX-8 | 数据展示优化 | 4h |
| 🎯 UX | UX-19~UX-21 | 视觉优化 | 2h |
| 🎯 UX | UX-22~UX-24 | 性能优化 | 3h |

---

## 五、总结

### 核心发现
1. **安全隐患**: 4个危险操作（手动下单、一键清仓、重置账户、确认弹窗无loading）缺少防护，可能导致误操作造成资金损失。
2. **代码冗余**: LiveTradingView 已废弃但仍存在，PositionDetailTable/PositionSummaryCards 是死代码，策略名称映射和类型定义重复。
3. **性能隐患**: MarketMonitorView 637行单文件、WS消息处理冗余fetch、信号列表无虚拟滚动。
4. **功能缺失**: 调度器控制面板（LiveTradingView独有）在 MarketMonitorView 中缺失。

### 建议执行顺序
1. **Phase 1 (2h)**: 修复P0安全问题 — 确认弹窗loading、手动下单确认、清仓/重置确认
2. **Phase 2 (4h)**: 清理冗余 — 删除LiveTradingView、处理死代码组件、统一类型和常量
3. **Phase 3 (4h)**: 修复P1功能问题 — WS优化、距止损计算、参数校验、手动下单价格
4. **Phase 4 (8h)**: 重构 — MarketMonitorView拆分子组件、虚拟滚动
5. **Phase 5 (8h)**: UX增强 — 错误处理、交易终止、报告图表
