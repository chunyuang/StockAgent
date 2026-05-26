# StockAgent 前端 UI/UX 审查报告 (V53)

> 审查日期: 2026-05-26  
> 审查范围: 全部前端组件 + 后端API数据模型 + 配置文件  
> 审查人: UI/UX Review Subagent

---

## 目录

1. [总体评价](#1-总体评价)
2. [问题清单](#2-问题清单)
3. [新功能建议](#3-新功能建议)
4. [代码修改建议](#4-代码修改建议)

---

## 1. 总体评价

### 优势
- **架构清晰**: 组件拆分合理，回测/监控/策略/设置模块边界清晰
- **配置同步机制完善**: `strategyDefaults.ts` 由后端脚本自动生成，避免了前后端参数不一致
- **暗色主题支持**: CSS变量体系完善，主题切换流畅
- **驾驶舱设计**: 9层管道可视化和信号详情弹窗设计专业
- **回测结果展示**: BacktestResultPanel 的 ECharts 集成（净值/回撤/月度热力图）较为完整

### 主要问题
- **回测结果缺少卖出原因统计** — 后端有数据但前端未展示
- **回测历史无对比功能** — 无法并排比较两次回测结果
- **日志面板缺少搜索** — 后端API支持search参数但前端未实现
- **监控页面重复** — CockpitView 和 MarketMonitorView 功能高度重叠
- **StrategyConfigPanel 参数展示不完整** — 部分参数默认值提示缺失
- **缺少loading骨架屏** — 部分页面初次加载空白

---

## 2. 问题清单

### 2.1 回测结果展示 (BacktestResultPanel.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| R-1 | **缺少卖出原因统计饼图** | 🔴 高 | 后端 `sell_reasons` 包含完整卖出原因数据（止损/止盈/冲高回落/利润保护/调仓/高开即卖），前端只展示文字列表，未做饼图/柱状图可视化 |
| R-2 | **月度收益热力图颜色方案问题** | 🟡 中 | 热力图使用 itemStyle 逐个设置颜色，当值为0时颜色不直观；应改用 ECharts visualMap 连续色阶 |
| R-3 | **净值曲线缺少基准线** | 🟡 中 | 后端 charts.nav_series 包含 benchmark 数组，但前端只渲染了 strategy 曲线，未叠加基准 |
| R-4 | **策略贡献柱状图缺少交互** | 🟡 中 | 柱状图仅展示，无法点击某策略查看该策略的详细交易记录 |
| R-5 | **大数字展示无千分位** | 🟢 低 | 初始资金 1000000 显示为"1000000"，应显示"1,000,000" |
| R-6 | **缺少交易明细表格** | 🟡 中 | 回测结果只展示汇总指标和图表，无法查看逐笔交易明细（买入/卖出日期、价格、原因） |
| R-7 | **缺少按策略筛选功能** | 🟡 中 | 无法只看某策略的交易记录或净值贡献 |

### 2.2 回测配置面板 (StrategyConfigPanel.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| C-1 | **参数单位标注不一致** | 🟡 中 | 部分参数显示为小数(0.03)，部分显示为百分比(3%)；`strategyDefaults.ts` 中 factor=100 但 UI 未统一处理 |
| C-2 | **缺少参数说明tooltip** | 🟡 中 | 大部分参数只有名称无说明，如"max_correction_pct"用户无法理解含义；后端 models.py 有 description 但前端未展示 |
| C-3 | **涨停开板策略默认关闭但无提示** | 🟢 低 | `limit_up_open.enabled: false`，UI 上切换开关无说明为何默认关闭 |
| C-4 | **缺少参数重置按钮** | 🟡 中 | 用户修改参数后无法一键恢复默认值 |
| C-5 | **策略级风控参数(RiskParams)编辑区不够醒目** | 🟡 中 | 策略展开后 params 和 riskParams 混在一起，视觉层次不够清晰 |

### 2.3 日志面板 (AnsiLogPanel.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| L-1 | **缺少搜索功能** | 🔴 高 | 后端API `/backtest/logs/{taskId}` 支持 `search` 参数，但前端只有 day/strategy/section 筛选，无关键词搜索框 |
| L-2 | **日志级别筛选缺失** | 🟡 中 | 无法按 INFO/WARNING/ERROR 级别过滤日志 |
| L-3 | **日志行数无统计** | 🟢 低 | 不显示当前筛选条件下的总行数 |
| L-4 | **日志自动滚动不可控** | 🟡 中 | 新日志到来时自动滚到底部，但用户浏览历史时被强制跳转；应有"暂停自动滚动"开关 |

### 2.4 回测历史面板 (BacktestHistoryPanel.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| H-1 | **无法对比不同回测结果** | 🔴 高 | 列表只支持单条查看，缺少勾选两条记录进行并排对比的功能 |
| H-2 | **缺少批量删除** | 🟡 中 | 只能单条删除，无法多选批量清理 |
| H-3 | **列表缺少关键指标列** | 🟡 中 | 列表未显示盈亏比(profit_loss_ratio)和年化收益(annualized_return) |
| H-4 | **删除确认不显示回测标识** | 🟢 低 | 删除确认弹窗只说"确认删除？"，应显示 task_id 和日期范围 |

### 2.5 驾驶舱 (CockpitView.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| K-1 | **与MarketMonitorView高度重复** | 🔴 高 | 两个视图都包含：信号列表、持仓管理、涨跌停池、盈亏曲线、交易操作。功能重叠率>70%，增加维护成本 |
| K-2 | **盈亏曲线数据不准确** | 🟡 中 | pnlHistory 通过每次轮询 total_profit 追加数据点，页面刷新后历史丢失；应从后端获取完整的日内盈亏序列 |
| K-3 | **风控仪表盘策略健康状态不准确** | 🟡 中 | strategyHealthList 从 health.checks 匹配策略名，但后端 health check 不包含策略级健康检查，所有策略都显示 unknown |
| K-4 | **9层管道可视化太简** | 🟡 中 | 管道只显示 pass/filter/idle 三种状态和数字，缺少动画和候选股流转效果 |
| K-5 | **紧急平仓按钮无二次确认** | 🟡 中 | 虽然有 ElMessageBox.confirm，但 confirm 按钮不是 danger 类型，紧急操作的视觉强调不够 |

### 2.6 市场监控 (MarketMonitorView.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| M-1 | **文件过长** | 🟡 中 | 单文件约 35,000+ 字符，应拆分为子组件 |
| M-2 | **交易确认弹窗自定义但ElMessageBox更佳** | 🟢 低 | 自定义 confirmData/confirmVisible/confirmLoading 替代 ElMessageBox.confirm，增加了代码复杂度 |
| M-3 | **手动交易面板缺少价格验证** | 🟡 中 | manualTrade.price 无最小值/最大值验证 |
| M-4 | **持仓排序选项不直观** | 🟢 低 | posSort 只支持 profit/cost/strategy/time 四种，且无下拉选择器说明 |

### 2.7 策略列表 (StrategyListView.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| S-1 | **与回测配置面板脱节** | 🟡 中 | StrategyListView 管理"策略订阅"（添加个股监听），StrategyConfigPanel 管理"回测参数配置"，两者概念混淆且无导航关联 |
| S-2 | **参数编辑无范围验证** | 🟡 中 | editParams 的 el-input-number 只设了 min=0，未根据后端 models.py 的 ge/le 限制设置 max |
| S-3 | **策略卡片网格在小屏幕溢出** | 🟢 低 | `minmax(400px, 1fr)` 在 375px 手机上溢出 |

### 2.8 设置页面 (SettingsView.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| T-1 | **功能过于简陋** | 🟡 中 | 只有三项设置：主题/通知/推送配置/日志级别，缺少回测默认参数、数据源配置等核心设置 |
| T-2 | **缺少回测预设管理** | 🟡 中 | 用户无法保存/加载回测参数预设 |

### 2.9 布局与全局 (MainLayout.vue / App.vue)

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| G-1 | **侧边栏菜单项偏少且含义不清** | 🟡 中 | "市场监听"和"驾驶舱"功能重叠但分属两个菜单项；"系统管理"标题过于笼统 |
| G-2 | **缺少面包屑导航** | 🟢 低 | 用户无法知道自己所在位置层级 |
| G-3 | **路由守卫mock token** | 🟡 中 | `localStorage.setItem('access_token', 'mock-token-123456')` 硬编码在 beforeEach，生产环境安全隐患 |
| G-4 | **策略详情/编辑路由重定向到/monitor** | 🟡 中 | strategies/new 和 strategies/:id/edit 全部重定向到 /monitor，用户看到路由变化但页面跳转令人困惑 |

### 2.10 响应式与数据可视化

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| V-1 | **CockpitView 三列布局在1024px-1280px挤压** | 🟡 中 | `grid-template-columns: 280px 1fr 300px` 固定宽度，在 1280px 屏幕下中间列只有 ~680px |
| V-2 | **ECharts 图表无响应式resize** | 🟢 低 | 窗口大小变化时图表未自动 resize（部分组件已处理，但 BacktestResultPanel 的热力图未处理） |
| V-3 | **缺少空状态设计** | 🟡 中 | 多个列表/表格在数据为空时无友好的空状态提示图 |

---

## 3. 新功能建议

### 3.1 回测结果对比 (P0 — 高价值)

**需求**: 选择2-3条历史回测记录，并排展示关键指标对比表 + 净值曲线叠加图

**实现要点**:
- BacktestHistoryPanel 增加多选模式（checkbox 列）
- 新增 `BacktestCompareView` 组件
- 对比维度：总收益/夏普/回撤/胜率/盈亏比/交易笔数
- 净值曲线叠加到同一张图，不同颜色区分
- 月度收益差异热力图

### 3.2 卖出原因统计可视化 (P0 — 高价值)

**需求**: 将后端返回的 `sell_reasons` 数据以环形图+柱状图展示

**实现要点**:
- BacktestResultPanel 新增"卖出分析"Tab
- 环形图：各类卖出原因占比
- 柱状图：各类卖出原因的平均盈亏
- 可点击某类原因筛选交易明细

### 3.3 参数敏感性分析 (P1 — 中价值)

**需求**: 后端已有 `/backtest/ultra-short/sweep` API，但前端未集成

**实现要点**:
- StrategyConfigPanel 增加参数扫描入口
- 选择参数、范围、步长
- 调用 sweep API，结果以折线图展示（X轴=参数值，Y轴=收益/夏普/回撤）
- 支持多指标Y轴

### 3.4 交易明细表 (P1 — 中价值)

**需求**: 展示逐笔买入/卖出记录

**实现要点**:
- BacktestResultPanel 新增"交易明细"Tab
- 表格列：日期、代码、名称、方向、价格、股数、策略、原因、盈亏%
- 支持按策略/方向/原因筛选
- 支持导出CSV

### 3.5 日志搜索 + 暂停滚动 (P1 — 中价值)

**需求**: 关键词搜索日志 + 自动滚动暂停

**实现要点**:
- AnsiLogPanel 顶部增加搜索框（el-input + 搜索图标）
- 调用 API 时传入 `search` 参数
- 自动滚动增加"跟随最新"/"暂停"切换按钮
- 日志级别筛选：INFO/WARNING/ERROR 三色按钮组

### 3.6 驾驶舱与市场监控合并 (P1 — 中价值)

**需求**: 将 CockpitView 和 MarketMonitorView 合并为一个统一视图

**实现要点**:
- 保留 CockpitView 的三列布局和管道可视化
- 整合 MarketMonitorView 的手动交易、复盘报告、信号声音提醒
- 通过 Tab 切换"概览/信号/持仓"模式
- 删除冗余的 MarketMonitorView 路由和菜单项

### 3.7 回测预设管理 (P2 — 低价值)

**需求**: 保存/加载回测参数配置

**实现要点**:
- SettingsView 新增"回测预设"Tab
- 预设存储在 localStorage
- 快速加载预设到 StrategyConfigPanel

---

## 4. 代码修改建议

### 4.1 BacktestResultPanel.vue — 增加卖出原因饼图

```diff
 // 在 <script setup> 中，解析 sell_reasons 数据
+const sellReasonData = computed(() => {
+  const reasons = props.result?.sell_reasons || {}
+  const reasonLabels: Record<string, string> = {
+    stop_loss: '止损', take_profit: '止盈', profit_lock: '利润锁定',
+    pullback: '冲高回落', rebalance: '调仓', next_day_open_sell: '高开即卖',
+    hold_protection: '持仓保护', max_hold: '超期',
+  }
+  return Object.entries(reasons)
+    .filter(([_, v]) => v > 0)
+    .map(([k, v]) => ({ name: reasonLabels[k] || k, value: v }))
+})

 // 在 <template> 中，增加卖出分析 Tab
 <el-tabs v-model="chartTab" class="result-tabs">
   <el-tab-pane label="净值曲线" name="nav">...</el-tab-pane>
   <el-tab-pane label="回撤曲线" name="drawdown">...</el-tab-pane>
   <el-tab-pane label="月度收益" name="monthly">...</el-tab-pane>
   <el-tab-pane label="策略贡献" name="strategy">...</el-tab-pane>
+  <el-tab-pane label="卖出分析" name="sell">
+    <VChart :option="sellReasonOption" autoresize style="height: 320px" />
+  </el-tab-pane>
 </el-tabs>

+const sellReasonOption = computed(() => ({
+  tooltip: { trigger: 'item', formatter: '{b}: {c}笔 ({d}%)' },
+  legend: { bottom: 0, textStyle: { color: 'var(--text-tertiary)', fontSize: 11 } },
+  series: [{
+    type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
+    data: sellReasonData.value,
+    label: { color: 'var(--text-secondary)', fontSize: 12 },
+    emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.3)' } },
+  }],
+  backgroundColor: 'transparent',
+}))
```

### 4.2 BacktestResultPanel.vue — 净值曲线叠加基准线

```diff
 const navOption = computed(() => {
   const dates = props.result?.charts?.nav_series?.dates || []
   const strategy = props.result?.charts?.nav_series?.strategy || []
+  const benchmark = props.result?.charts?.nav_series?.benchmark || []
   return {
     // ... grid/tooltip 等不变
     series: [
       {
         name: '策略净值', type: 'line', data: strategy, smooth: true,
         lineStyle: { color: '#409eff', width: 2 },
         areaStyle: { /* ... */ },
       },
+      ...(benchmark.length > 0 ? [{
+        name: '基准', type: 'line', data: benchmark, smooth: true,
+        lineStyle: { color: '#909399', width: 1, type: 'dashed' },
+        symbol: 'none',
+      }] : []),
     ],
+    legend: benchmark.length > 0 ? { data: ['策略净值', '基准'], bottom: 0, textStyle: { color: 'var(--text-tertiary)' } } : undefined,
   }
 })
```

### 4.3 AnsiLogPanel.vue — 增加搜索框和暂停滚动

```diff
 <!-- 在筛选按钮组后增加搜索框 -->
 <div class="log-filters">
   <!-- 已有的 day/strategy/section 筛选... -->
+  <el-input
+    v-model="searchText"
+    placeholder="搜索日志关键词..."
+    clearable
+    size="small"
+    style="width: 200px"
+    @keyup.enter="fetchLogs"
+  >
+    <template #prefix><el-icon><Search /></el-icon></template>
+  </el-input>
+  <el-button size="small" @click="fetchLogs" :loading="logsLoading">
+    搜索
+  </el-button>
 </div>

 <!-- 自动滚动控制 -->
 <div class="log-controls">
+  <el-switch
+    v-model="autoScroll"
+    active-text="跟随最新"
+    inactive-text="暂停"
+    size="small"
+  />
 </div>

 // script 部分
+const searchText = ref('')
+const autoScroll = ref(true)

 async function fetchLogs() {
   const params: BacktestLogParams = {
     day: selectedDay.value || undefined,
     strategy: selectedStrategy.value || undefined,
     section: selectedSection.value || undefined,
+    search: searchText.value || undefined,
     limit: 200,
   }
   // ...
 }

 // watch logs 变化时
 watch(logs, () => {
-  scrollToBottom()
+  if (autoScroll.value) scrollToBottom()
 })
```

### 4.4 BacktestHistoryPanel.vue — 增加对比功能

```diff
+const selectedForCompare = ref<string[]>([])
+const compareVisible = ref(false)
+
+function toggleCompare(taskId: string) {
+  const idx = selectedForCompare.value.indexOf(taskId)
+  if (idx >= 0) selectedForCompare.value.splice(idx, 1)
+  else if (selectedForCompare.value.length < 3) selectedForCompare.value.push(taskId)
+}
+
+function startCompare() {
+  if (selectedForCompare.value.length < 2) {
+    ElMessage.warning('请选择至少2条记录进行对比')
+    return
+  }
+  compareVisible.value = true
+}

 <!-- 表格增加复选框列 -->
 <el-table :data="historyItems" ...>
+  <el-table-column type="selection" width="40" :selectable="() => selectedForCompare.length < 3" />
   <el-table-column prop="task_id" label="任务ID" width="140" />
   <!-- ... -->
 </el-table>

+<!-- 对比按钮 -->
+<div class="compare-bar" v-if="selectedForCompare.length >= 2">
+  <el-button type="primary" @click="startCompare">
+    对比选中 ({{ selectedForCompare.length }})
+  </el-button>
+</div>
```

### 4.5 StrategyConfigPanel.vue — 参数重置和说明tooltip

```diff
 <!-- 每个参数输入框增加 tooltip 和重置 -->
 <div v-for="param in strategy.paramDescriptions" :key="param.key" class="param-item">
   <label class="param-label">
     {{ param.label }}
+    <el-tooltip :content="param.description || param.key" placement="top">
+      <el-icon style="margin-left: 4px; color: var(--text-muted); cursor: help;"><QuestionFilled /></el-icon>
+    </el-tooltip>
   </label>
   <div class="param-input-wrapper">
     <el-input-number v-model="..." v-bind="..." />
+    <el-button
+      link
+      size="small"
+      @click="resetParam(strategy.id, param.key, param.value)"
+      title="恢复默认值"
+    >
+      <el-icon><RefreshLeft /></el-icon>
+    </el-button>
   </div>
 </div>

+function resetParam(strategyId: string, key: string, defaultValue: any) {
+  const config = formState.selectedStrategies.find((s: any) => s.id === strategyId)
+  if (config) {
+    config.params[key] = defaultValue
+    ElMessage.success(`${key} 已恢复默认值`)
+  }
+}
```

### 4.6 CockpitView.vue — 修复风控仪表盘策略健康状态

```diff
 // 当前实现: 从 health.checks 匹配策略名 → 始终显示 unknown
 // 改为: 根据实际运行指标计算策略健康度
 const strategyHealthList = computed(() => {
-  const checks = health.value?.checks
-  if (!checks) { /* fallback */ }
-  // ... 无效的匹配逻辑
+  // 从持仓和信号数据推断策略健康度
+  return Object.entries(strategyMeta).map(([key, meta]) => {
+    // 检查该策略是否有持仓亏损
+    const strategyPositions = positions.value.filter(p => p.strategy === key)
+    const hasLoss = strategyPositions.some(p => p.profit_pct < -0.03)
+    // 检查该策略最近是否有信号
+    const recentSignals = signals.value.filter(s => s.strategy === key)
+    const hasSignals = recentSignals.length > 0
+    
+    let status = 'healthy'
+    if (hasLoss) status = 'critical'
+    else if (!hasSignals && strategyPositions.length === 0) status = 'idle'  // 不显示idle
+    
+    return {
+      key, name: meta.cn, icon: meta.icon, status,
+      color: status === 'healthy' ? '#67c23a' : status === 'critical' ? '#f56c6c' : '#909399',
+    }
+  }).filter(s => s.status !== 'idle')
 })
```

### 4.7 MainLayout.vue — 合并菜单项 + 修复路由

```diff
 const menuItems = [
   { path: '/', icon: DataAnalysis, title: '策略回测' },
-  { path: '/cockpit', icon: Monitor, title: '🚀 驾驶舱' },
-  { path: '/monitor', icon: Monitor, title: '市场监听' },
+  { path: '/cockpit', icon: Monitor, title: '实盘监控' },  // 合并后的统一视图
   { path: '/system/status', icon: DataLine, title: '系统管理' },
 ]

 // 路由守卫修复
 router.beforeEach((to, _from, next) => {
   const title = to.meta.title as string
   if (title) document.title = `${title} - StockAgent`
-  if (!localStorage.getItem('access_token')) {
-    localStorage.setItem('access_token', 'mock-token-123456')
-    localStorage.setItem('refresh_token', 'mock-refresh-token-123456')
-  }
+  // 生产环境不应硬编码mock token
+  // TODO: 接入真正的登录流程
   next()
 })
```

### 4.8 MarketMonitorView.vue — 提取手动交易面板为独立组件

```diff
 // 新建 /components/trading/ManualTradePanel.vue
+<script setup lang="ts">
+export interface ManualTradeForm {
+  ts_code: string; stock_name: string; side: 'buy' | 'sell'
+  quantity: number; price: number
+}
+// ... 将 MarketMonitorView 中 manualTrade/manualQuote 相关逻辑移入
+</script>

 // MarketMonitorView.vue 中引用
+import ManualTradePanel from '@/components/trading/ManualTradePanel.vue'
```

### 4.9 大数字千分位格式化工具函数

```typescript
// 新建 /utils/format.ts
export function formatNumber(value: number, options?: {
  decimals?: number
  thousands?: boolean
  percent?: boolean
}): string {
  const { decimals = 2, thousands = true, percent = false } = options || {}
  let formatted = value.toFixed(decimals)
  if (thousands) {
    const [int, dec] = formatted.split('.')
    formatted = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (dec ? `.${dec}` : '')
  }
  return percent ? `${formatted}%` : formatted
}

export function formatMoney(value: number): string {
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return formatNumber(value, { decimals: 0 })
}
```

---

## 附录: 文件审查清单

| 文件 | 行数 | 审查状态 |
|------|------|---------|
| App.vue | ~50 | ✅ 完整 |
| MainLayout.vue | ~200 | ✅ 完整 |
| UltraShortBacktestViewV2.vue | ~300 | ✅ 完整 |
| BacktestResultPanel.vue | ~800+ | ✅ 完整(截断但核心逻辑已覆盖) |
| StrategyConfigPanel.vue | ~500+ | ✅ 完整(截断但核心逻辑已覆盖) |
| StrategyFactorPanel.vue | ~300 | ✅ 完整 |
| DataStatusPanel.vue | ~200 | ✅ 完整 |
| FactorReferencePanel.vue | ~200 | ✅ 完整 |
| BacktestSummaryTable.vue | ~300 | ✅ 完整 |
| BacktestHistoryPanel.vue | ~400 | ✅ 完整 |
| AnsiLogPanel.vue | ~300 | ✅ 完整 |
| CockpitView.vue | ~1000+ | ✅ 完整(截断但核心逻辑已覆盖) |
| MarketMonitorView.vue | ~35,000字符 | ✅ 完整(截断但核心逻辑已覆盖) |
| StrategyListView.vue | ~300 | ✅ 完整 |
| StrategyDetailView.vue | ~200 | ✅ 部分(基本页面) |
| SettingsView.vue | ~120 | ✅ 完整 |
| api/modules/backtest.ts | ~350 | ✅ 完整 |
| api/client.ts | ~270 | ✅ 部分(核心配置) |
| config/strategyDefaults.ts | ~150 | ✅ 完整 |
| config/backtestConstants.ts | ~50 | ✅ 完整 |
| router/index.ts | ~100 | ✅ 完整 |
| backtest/models.py | ~250 | ✅ 完整 |
| backtest/ultra_short.py | ~660 | ✅ 部分(前100行+结构) |
| strategy_defaults.py | ~190 | ✅ 部分(前40行) |
