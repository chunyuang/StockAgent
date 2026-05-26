# V61 前端UI审计报告

**审计日期**: 2026-05-27  
**审计范围**: `/StockAgent/frontend/src` 下所有Vue组件  
**审计人**: AI UI审计专家  
**总代码量**: ~12,000行Vue + ~2,000行TS/JS

---

## 审计概要

| 级别 | 数量 | 说明 |
|------|------|------|
| **P0 数据错误** | 3 | 数据显示不正确，影响投资决策 |
| **P1 功能缺陷** | 7 | 功能缺失或行为异常 |
| **P2 体验优化** | 12 | 响应式/交互/视觉可改进 |

---

## P0 数据错误（必须修复）

### P0-1: CockpitView 紧急平仓按钮在扫描器停止时仍可点击
**文件**: `views/monitor/CockpitView.vue`  
**问题**: 紧急平仓按钮的 `:disabled="!isRunning"` 阻止了停止状态下的紧急平仓，但实际上停止扫描器后持仓仍然存在，用户可能需要紧急平仓。  
**修复**:
```vue
<!-- 修改前 -->
<ElButton type="danger" size="small" class="emergency-btn" @click="emergencyLiquidate" :disabled="!isRunning">

<!-- 修改后 -->
<ElButton type="danger" size="small" class="emergency-btn" @click="emergencyLiquidate" :disabled="positions.length === 0">
```

### P0-2: MarketMonitorView 涨跌色反直觉
**文件**: `views/monitor/MarketMonitorView.vue`, `views/monitor/CockpitView.vue`  
**问题**: 中国A股市场约定"红涨绿跌"，但代码中：
- `var(--stock-down)` 被用于**盈利**（红色，正确）
- `var(--stock-up)` 被用于**亏损**（绿色，正确）

但在 `SignalTracePanel.vue` 中存在混乱：
```css
.up { color: var(--stock-up, #f56c6c); }   /* 涨用红色，命名up=涨，CSS var名stock-up=红 */
.down { color: var(--stock-down, #67c23a); } /* 跌用绿色，命名down=跌，CSS var名stock-down=绿 */
```
CSS变量命名 `--stock-up`/`--stock-down` 与中国市场的"涨红跌绿"语义相反（`--stock-up`实际是红色/盈利色，但英文up暗示"涨"），这会导致新开发者误用。  
**建议**: 在全局CSS中添加注释说明，并统一在模板中使用语义化class名（如 `.profit`/`.loss` 而非 `.up`/`.down`）。

### P0-3: BacktestResultPanel 累计收益月度计算方式可能产生误导
**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: `monthlyMergedData` 的月度收益用 `(end_value - start_value) / start_value` 计算，这是**单月收益**，但底部累计收益线用简单加和 `cumVal += r`。简单加和不等于复合收益，长期来看会有明显偏差。  
**修复**:
```typescript
// 修改前
const cumReturns: number[] = []
let cumVal = 0
for (const r of returns) {
  cumVal += r
  cumReturns.push(+cumVal.toFixed(2))
}

// 修改后：用净值连乘计算累计收益
const cumReturns: number[] = []
let cumVal = 1.0  // 初始净值1.0
for (const r of returns) {
  cumVal *= (1 + r / 100)  // 月度收益百分比→小数
  cumReturns.push(+((cumVal - 1) * 100).toFixed(2))  // 转回百分比
}
```

---

## P1 功能缺陷

### P1-1: StrategyEditView 更新模式未调用API
**文件**: `views/strategy/StrategyEditView.vue` L180-184  
**问题**: 编辑模式下 `handleSubmit` 只有 `ElMessage.success('策略更新成功')`，没有实际调用后端API。
```typescript
// 修改前
if (isEdit.value) {
  ElMessage.success('策略更新成功')  // 假更新！
}

// 修改后
if (isEdit.value) {
  await strategyApi.updateStrategy(strategyId.value!, formData.value)
  ElMessage.success('策略更新成功')
}
```

### P1-2: StockDetailView 价格方向判断缺少换手率等指标
**文件**: `views/stock/StockDetailView.vue`  
**问题**: `metrics-grid` 中"最高"用 `price-up`（红色）但"最低"用 `price-down`（绿色），这在中国市场中是反的：最高应该是红色（涨），最低应该是绿色（跌）。但实际上"最高/最低"本身不是涨跌，不应该用涨跌色。  
**修复**: 去掉不必要的涨跌色标注，所有指标用统一颜色。
```vue
<!-- 修改前 -->
<span class="metric-value price-up">{{ formatPrice(quote?.high) }}</span>
<span class="metric-value price-down">{{ formatPrice(quote?.low) }}</span>

<!-- 修改后 -->
<span class="metric-value">{{ formatPrice(quote?.high) }}</span>
<span class="metric-value">{{ formatPrice(quote?.low) }}</span>
```

### P1-3: CockpitView 今日盈亏计算逻辑有缺陷
**文件**: `views/monitor/CockpitView.vue` L133-155  
**问题**: `todayPnl` 计算中，`timeline` 的 `profit_pct` 反推盈亏额公式不正确：
```typescript
const costAmt = item.shares * item.price / (1 + item.profit_pct / 100)
```
这里 `item.price` 是卖出价，不是成本价，导致 `costAmt` 计算错误。  
**修复**: 优先使用后端返回的 `profit_amount`，如果没有则直接用 `profit_pct * shares * cost_price / 100`（需要 `cost_price` 字段）。
```typescript
// 修复: 如果有 profit_pct 和 shares，但需要 cost_price
if (item.profit_pct != null && item.shares > 0 && item.cost_price > 0) {
  realized += item.cost_price * item.shares * item.profit_pct / 100
}
```

### P1-4: MarketMonitorView 未清理WebSocket
**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: `connectWS` 中的 `wsDebounceTimer` 在组件卸载时未清理，可能导致内存泄漏。`onUnmounted` 中调用了 `disconnectWS()` 但该函数未清除 `wsDebounceTimer`。  
**修复**:
```typescript
function disconnectWS() {
  if (wsDebounceTimer) clearTimeout(wsDebounceTimer)  // 新增
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  if (ws) { ws.close(); ws = null }
}
```

### P1-5: BacktestResultPanel 导出CSV缺少BOM头
**文件**: `components/ultrashort/BacktestResultPanel.vue` L278  
**问题**: 虽然添加了 `\uFEFF` BOM头，但 CSV 中卖出原因的中文翻译可能包含逗号，未用引号包裹，导致Excel打开时列错位。  
**修复**:
```typescript
const rows = trades.map((t: any) => [
  t.buy_date || t.date || '', t.sell_date || '', t.ts_code || '', 
  t.name || t.stock_name || '',
  STRATEGY_NAMES[t.strategy] || t.strategy || '', 
  t.buy_price ?? '', t.sell_price ?? '',
  t.profit_pct != null ? t.profit_pct.toFixed(2) : '-',
  (t.profit_pct != null && t.shares && t.buy_price) ? (t.buy_price * t.shares * t.profit_pct / 100).toFixed(0) : '-',
  t.hold_days ?? 1, 
  `"${translateSellReason(t.sell_reason || t.reason)}"`  // 引号包裹含逗号的中文
])
```

### P1-6: UltraShortBacktestViewV2 WebSocket onerror 中重连闭包引用旧ws
**文件**: `views/backtest/UltraShortBacktestViewV2.vue` L260-290  
**问题**: `ws.onerror` 中创建的新 `newWs` 的 `newWs.onmessage = ws.onmessage` 将引用原 ws 的 onmessage 闭包。如果原 ws 已经被关闭，闭包中的 `backtestState` 引用虽然不会出错（因为是reactive），但 `ws.onmessage` 闭包中引用了原始 `ws` 变量来 `ws.close()`，重连后指向旧ws。  
**修复**: 将 onmessage 处理逻辑抽成独立函数，避免闭包问题。

### P1-7: SystemStatusView 格式化百分比的函数被ts-expect-error忽略
**文件**: `views/system/SystemStatusView.vue`  
**问题**: `formatPercent` 函数标记了 `@ts-expect-error unused`，说明函数未使用但保留。同时，表格中的百分比直接用 `row.cumulative_return.toFixed(2)%` 显示，没有用 `formatPercent` 函数，可能导致后端返回值已是百分比或小数时显示不一致。  
**修复**: 统一使用 `fmtPct` 风格函数，根据后端返回数据规范确定是否需要×100。

---

## P2 体验优化

### P2-1: CockpitView 三列布局在小屏幕上溢出
**文件**: `views/monitor/CockpitView.vue`  
**问题**: `.main-grid { grid-template-columns: 240px 1fr 280px }` 在1200px以下有响应式，但中间面板信号列表未设 `max-height` + `overflow-y: auto`，信号多时页面不可滚动。  
**建议**: 给 `.center-panel` 加 `overflow-y: auto; max-height: calc(100vh - 200px)`。

### P2-2: BacktestResultPanel 所有图表没有加载骨架
**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: 图表渲染前无loading状态，大数据量时会有空白闪烁。  
**建议**: VChart 外层加 `v-loading="!chartOption"` 或骨架屏。

### P2-3: StockDetailView K线图加载用随机高度骨架条
**文件**: `views/stock/StockDetailView.vue` L258  
**问题**: `<div v-for="i in 30" :key="i" class="skeleton-bar" :style="{ height: `${30 + Math.random() * 50}%` }" />` 用 `Math.random()` 导致每次渲染骨架条高度不同，SSR不友好且视觉抖动。  
**修复**: 用固定预设高度数组替代。
```typescript
const skeletonHeights = [45, 62, 38, 55, 70, 42, 58, 33, 65, 48, ...]  // 30个固定值
```

### P2-4: UltraShortBacktestViewV2 重复定义 .tab-content-full
**文件**: `views/backtest/UltraShortBacktestViewV2.vue`  
**问题**: `.tab-content-full` 在 `<style>` 中定义了两次，后者覆盖前者，多余的CSS。  
**修复**: 删除重复的定义。

### P2-5: BacktestHistoryPanel 策略标签在浅色主题下白字不可见
**文件**: `components/backtest/BacktestHistoryPanel.vue`  
**问题**: `strategyTag(sid).color` 用的是 `var(--warning)`/`var(--stock-up)` 等CSS变量值作为背景色，搭配 `color:var(--text-inverse)`（白色），但在浅色主题下某些颜色（如浅绿、浅黄）对比度不够。  
**建议**: 策略标签改用 `effect="plain"` 或深色背景确保白色文字可读。

### P2-6: StrategyListView 使用 Tailwind @apply 但项目不一定配置了Tailwind
**文件**: `views/strategy/StrategyListView.vue`  
**问题**: 大量使用 `@apply` 指令（如 `@apply min-h-screen p-6`），但项目其他组件用的是原生CSS/SCSS + CSS变量。如果Tailwind未安装或未正确配置，这些样式不会生效。  
**建议**: 统一使用CSS变量或SCSS，移除 `@apply`。

### P2-7: MarketMonitorView 代码超长（1027行），组件拆分不足
**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 超过1000行的单文件组件，包含大量内联函数和模板，难以维护。  
**建议**: 将信号列表、持仓列表、手动下单表单等拆成独立子组件。

### P2-8: SignalTracePanel 使用 `el-` 而非 `El` 前缀
**文件**: `views/monitor/SignalTracePanel.vue`  
**问题**: 使用 `<el-select>`, `<el-button>`, `<el-tabs>` 等kebab-case标签，而项目其他组件统一使用 `<ElSelect>`, `<ElButton>`, `<ElTabs>` PascalCase。虽然Vue两者都支持，但不一致。  
**建议**: 统一为PascalCase。

### P2-9: BacktestResultPanel 缺少NaN/Infinity保护
**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: `fmtPct` 只检查了 `isNaN`，但未检查 `Infinity`。后端可能返回 `Infinity`（如除零）。  
**修复**:
```typescript
function fmtPct(val: number | undefined | null): string {
  if (val == null || isNaN(val) || !isFinite(val)) return '--'
  return val.toFixed(2) + '%'
}
```

### P2-10: CockpitView 追踪止损标记位置硬编码
**文件**: `views/monitor/CockpitView.vue` L210  
**问题**: `trailBarPos` 函数最终 `return Math.max(5, Math.min(95, 50))` 硬编码返回50，追踪止损标记永远在中间，没有实际意义。  
**建议**: 正确计算追踪止损在风险条上的相对位置，或暂时移除该标记避免误导。

### P2-11: StockChart 组件未处理空数组
**文件**: `components/charts/StockChart.vue`  
**问题**: 当 `data` 为空数组时，`option` 返回 `{}`，VChart 可能渲染空白而非空状态。模板中有 `v-if="data.length > 0"` 保护，但如果数据从非空变为空，中间可能闪烁。  
**建议**: 添加过渡动画或loading状态。

### P2-12: SettingsView 过于简单
**文件**: `views/settings/SettingsView.vue`  
**问题**: 只有120行，仅包含主题和通知开关。缺少回测相关设置（如默认日期范围、默认策略选择、WebSocket配置等）。  
**建议**: 考虑添加常用默认值配置，减少每次回测的配置工作量。

---

## 回测与实盘UI一致性审查

### 一致性问题1: 止损止盈百分比单位不统一
- **回测** (`BacktestResultPanel`): `stop_loss_pct` 后端返回已是百分比（如3.0表示3%），直接 `toFixed(2)%` 显示
- **实盘** (`CockpitView`): `pos.stop_loss_pct` 有时是小数（0.03），有时是百分比（3.0），V59修复中做了兼容检测
- **风险**: 用户在不同页面看到的同一个持仓止损值可能不同

### 一致性问题2: 策略名称展示方式
- **回测**: `strategyDisplayName()` 去除emoji前缀，如"半路追涨"
- **实盘** (`CockpitView`): `strategyCN()` 从 `strategyMeta` 获取，可能带emoji
- **建议**: 统一使用 `strategyDisplayName()` 函数

### 一致性问题3: 盈亏额计算
- **回测** (`BacktestResultPanel`): `row.buy_price * row.shares * row.profit_pct / 100`
- **实盘** (`CockpitView`): 使用 `profit_amount` 字段或反推
- **建议**: 统一优先使用后端 `profit_amount` 字段

---

## 数据显示正确性专项

### 回测结果核心指标验证

| 指标 | 后端格式 | 前端处理 | 正确性 |
|------|---------|---------|--------|
| total_return | 百分比(如147.86) | `fmtPct()` 直接加% | ✅ 正确 |
| annualized_return | 百分比 | `fmtPct()` 直接加% | ✅ 正确 |
| max_drawdown | 百分比 | `fmtPct()` 直接加% | ✅ 正确 |
| win_rate | 百分比 | `fmtPct()` 直接加% | ✅ 正确 |
| sharpe_ratio | 小数 | `.toFixed(2)` | ✅ 正确 |
| net_value_series[].net_value | 归一化(1.0起始) | 直接用 | ✅ 正确 |
| net_value_series[].daily_profit | 归一化(÷initial_cash) | ×100转% | ✅ 正确 |
| drawdown_series[].drawdown | 小数(0.0368=3.68%) | ×100转% | ✅ 正确 |
| position_series[].value | 小数(0.188=18.8%) | ×100转% | ✅ 正确 |
| monthly_profit | 小数(-0.011=-1.11%) | ×100转% | ✅ 正确 |
| merged_trades[].profit_pct | 百分比 | 直接用 | ✅ 正确 |
| factor_contribution | 小数(0.5=50%) | ×100转% | ✅ 正确 |
| benchmark_data[].pct_chg | 百分比 | ÷100再累乘 | ✅ 正确 |

**关键发现**: BacktestResultPanel 顶部的数据格式注释（L1-L15）与代码实现一致，数据转换逻辑正确。这是整个前端最关键的部分，目前没有发现数据格式错误。

---

## 性能问题

### 1. CockpitView 持仓列表无虚拟滚动
**文件**: `views/monitor/CockpitView.vue`  
持仓列表 `.pos-list` 直接 `v-for` 渲染所有持仓，截断为8个。如果持仓数很多，底部还有"共N只"提示，但8个截断是合理的。**无严重性能问题。**

### 2. BacktestResultPanel 交易记录无虚拟滚动
**文件**: `components/ultrashort/BacktestResultPanel.vue`  
交易表格有 `max-height="500"` 但未用虚拟滚动，300+笔交易时可能有性能问题。  
**建议**: 引入 `el-table-v2` 虚拟滚动或分页。

### 3. requestAnimationFrame 防抖已实现
**文件**: `views/backtest/UltraShortBacktestViewV2.vue` L387  
`addLog` 已使用 `requestAnimationFrame` 防抖，高频日志不会导致DOM频繁更新。✅

---

## 可访问性问题

### 1. 缺少 aria-label
大部分按钮仅使用 emoji 图标，没有 `aria-label`：
```vue
<!-- 当前 -->
<ElButton size="small" @click="quickSell(pos)">卖</ElButton>
<!-- 建议 -->
<ElButton size="small" @click="quickSell(pos)" aria-label="快捷卖出">卖</ElButton>
```

### 2. 颜色对比度
`.kpi-label` (11px, `var(--text-tertiary)`) 在浅色主题下可能对比度不足（WCAG AA要求4.5:1）。  
**建议**: 将字号提升到12px，或加深颜色。

### 3. 键盘导航
自定义Tab按钮（`.tab-btn`）不支持键盘导航（无 `tabindex`、`role="tab"`、`aria-selected`）。
```vue
<!-- 建议 -->
<button :class="['tab-btn', ...]" role="tab" :aria-selected="activeMainTab === 'config'" 
  @click="activeMainTab = 'config'" @keydown.enter="activeMainTab = 'config'">
```

---

## 修复优先级建议

| 优先级 | 修复项 | 预计工时 |
|--------|--------|---------|
| **立即** | P0-3 累计收益计算修正 | 30min |
| **立即** | P1-1 StrategyEditView API调用 | 20min |
| **尽快** | P0-1 紧急平仓按钮逻辑 | 10min |
| **尽快** | P1-3 今日盈亏计算修复 | 30min |
| **尽快** | P1-4 WebSocket内存泄漏 | 15min |
| **本周** | P1-5 CSV导出引号包裹 | 10min |
| **本周** | P2-9 NaN/Infinity保护 | 10min |
| **本周** | P0-2 涨跌色命名统一 | 2h（全局） |
| **迭代** | P2-7 组件拆分 | 4h |
| **迭代** | P2-6 移除Tailwind依赖 | 2h |

---

## 总结

1. **回测结果数据展示**是整个系统最关键的部分，目前 BacktestResultPanel 的数据格式转换逻辑**正确**，注释与代码一致，这是最令人放心的部分。

2. **实盘监控**（CockpitView/MarketMonitorView）存在几个功能性缺陷，特别是今日盈亏计算和紧急平仓按钮逻辑，需要尽快修复。

3. **代码质量**方面，MarketMonitorView 过于臃肿（1027行），StrategyListView 错误使用了 Tailwind，SignalTracePanel 组件命名风格不统一——这些都是技术债务。

4. **一致性**方面，止损止盈百分比在回测和实盘之间的单位处理已经做了兼容（V59修复），但策略名称展示和盈亏额计算仍有不统一之处。

5. **总体评价**: 前端代码质量中等偏上，核心数据展示逻辑正确，主要问题集中在实盘监控和边缘case处理上。
