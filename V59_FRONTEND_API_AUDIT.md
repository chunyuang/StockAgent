# V59 前端与API审计报告

**审计时间**: 2026-05-27  
**审计范围**: 前端8个视图 + 后端API层(scanner/backtest)  
**审计人**: subagent:frontend-api-review  

---

## 总览

| 等级 | 数量 | 说明 |
|------|------|------|
| **P0(数据错误)** | 3 | 显示数值与实际不一致 |
| **P1(功能缺陷)** | 5 | 功能异常或边界处理缺失 |
| **P2(体验优化)** | 8 | UI/UX/性能改进 |

---

## P0: 数据显示错误

### P0-1: CockpitView `quickBuySignal` 止损/止盈百分比×100错误

**文件**: `CockpitView.vue` L470-471  
**问题**: 从`/scanner/params/{strategy}`读取的`stop_loss_pct`/`take_profit_pct`已经是小数(0.03/0.07)，代码又×100变成300%/700%显示

```typescript
// 当前代码(错误)
const slPct = sp?.stop_loss_pct ? (sp.stop_loss_pct * 100).toFixed(1) : '3.0'
const tpPct = sp?.take_profit_pct ? (sp.take_profit_pct * 100).toFixed(1) : '7.0'
```

**修复**:
```typescript
// 修复: 如果值<1说明是小数，需要×100；如果>=1说明已是百分比
const slPct = sp?.stop_loss_pct 
  ? (sp.stop_loss_pct < 1 ? (sp.stop_loss_pct * 100).toFixed(1) : sp.stop_loss_pct.toFixed(1)) 
  : '3.0'
const tpPct = sp?.take_profit_pct 
  ? (sp.take_profit_pct < 1 ? (sp.take_profit_pct * 100).toFixed(1) : sp.take_profit_pct.toFixed(1)) 
  : '7.0'
```

**根因**: scanner API的`/params`端返回的是strategy_defaults.py中的原始小数(0.03)，但`/positions`端返回的`stop_loss_pct`已经是百分比(3.0)。两套API格式不一致。

---

### P0-2: CockpitView `todayPnl` 计算逻辑有数学错误

**文件**: `CockpitView.vue` L78-92  
**问题**: 已实现盈亏的计算公式有误 — `profit_pct / 100 * item.shares * item.price / (1 + item.profit_pct / 100)` 这个公式试图从卖出金额反推盈亏额，但实际上`item.price`是卖出价，`profit_pct`是盈亏比例，公式推导有误。

```typescript
// 当前代码(错误)
realized += item.profit_pct / 100 * item.shares * item.price / (1 + item.profit_pct / 100)
```

**分析**: 如果profit_pct=10, shares=1000, price=11(卖出价):
- 错误计算: 0.1 * 1000 * 11 / 1.1 = 1000 (应该是: (11-10)*1000 = 1000)
- 这个公式恰好对单笔正确，但它是用"卖出价反推"的巧合，而非正确逻辑

**更根本的问题**: 当`profit_pct`是从持仓浮盈来时（L90-91），没有profit_amount字段，fallback用`(current_price - cost_price) * shares`计算，这是正确的。但整个计算混合了"已实现"和"浮盈"两部分，命名和注释也容易误导。

**修复建议**: 直接使用`profit_amount`字段（API已提供），不要自己计算:
```typescript
const todayPnl = computed(() => {
  let total = 0
  // 从时间线获取已实现盈亏
  for (const item of timeline.value) {
    if (item.action === 'sell' && item.profit_amount != null) {
      total += item.profit_amount
    }
  }
  // 加上持仓浮盈(API已返回profit_amount)
  for (const pos of positions.value) {
    if (pos.profit_amount != null) total += pos.profit_amount
  }
  return total
})
```

---

### P0-3: BacktestResultPanel `riskBarWidth` 计算假设`stop_loss_pct`和`profit_pct`同量纲，实际不同

**文件**: `CockpitView.vue` L379-383  
**问题**: `riskBarWidth`和`riskBarClass`假设`pos.stop_loss_pct`和`pos.profit_pct`同量纲（都是百分比）。但从scanner API看，`stop_loss_pct`是百分比(3.0)，`profit_pct`也是百分比。这里的计算本身是正确的，但关键在于:

从`/positions` API返回: `stop_loss_pct: 3.0` (百分比)  
从`/position-risk/` API接受: `stop_loss_pct: 0.03` (小数)  

CockpitView L511正确地做了 `/100` 转换。但fallback路径(L354)直接用`pos.stop_loss_pct`赋值给`posRiskSL`，如果API格式变化会导致错误。

**实际影响**: 当前工作正确，但脆弱。建议在scanner API层面统一返回格式。

---

## P1: 功能缺陷

### P1-1: CockpitView `savePosRisk` 回写后未更新positions列表的风控参数

**文件**: `CockpitView.vue` L506-518  
**问题**: 保存风控后只更新了`posDetailData`，但positions数组中的`stop_loss_pct`/`take_profit_pct`未同步更新，导致风险进度条下次渲染仍用旧值。

```typescript
// 当前代码: 只更新了弹窗数据
posDetailData.value.position.stop_loss_pct = posRiskSL.value
posDetailData.value.position.take_profit_pct = posRiskTP.value
// 缺少: 更新positions列表中对应条目
```

**修复**:
```typescript
// 更新positions列表
const idx = positions.value.findIndex(p => p.ts_code === posDetailData.value.ts_code)
if (idx >= 0) {
  positions.value[idx].stop_loss_pct = posRiskSL.value
  positions.value[idx].take_profit_pct = posRiskTP.value
}
```

---

### P1-2: MarketMonitorView 103KB单文件组件，性能隐患

**文件**: `MarketMonitorView.vue` (103KB, ~1025行)  
**问题**: 巨大的单文件组件，所有逻辑、模板、样式均在一个文件中。包含大量computed属性和复杂交互逻辑。

**建议**: 拆分为:
- `MarketMonitorView.vue` — 主布局+路由
- `useMarketMonitor.ts` — 状态管理(composable)
- `StrategyControlPanel.vue` — 左列策略控制
- `SignalListPanel.vue` — 中列信号+行情
- `PositionPanel.vue` — 右列持仓
- `TimelineBar.vue` — 底部时间线

---

### P1-3: BacktestResultPanel 缺少对`null`/`undefined`数据的保护性处理

**文件**: `BacktestResultPanel.vue` 多处  
**问题**: 以下场景缺少null保护:

1. L287: `result.net_value_series.map(...)` — 如果`net_value_series`为空数组，`Math.min(...netValues)`返回Infinity
2. L359-361: `dp.map((v: any) => +((v) * 100).toFixed(4))` — 如果`daily_profit`为null，结果为NaN
3. L127: `+((data.end_value - data.start_value) / data.start_value * 100).toFixed(2)` — start_value为0时除零

**修复**: 添加null过滤和默认值:
```typescript
// L287: net_value过滤
const netValues = result.net_value_series
  .filter((d: any) => d.net_value != null)
  .map((d: any) => +(d.net_value).toFixed(4))

// L361: daily_profit过滤
const values = dp
  .filter((v: any) => v != null && !isNaN(v))
  .map((v: any) => +(v * 100).toFixed(4))

// L127: 避免除零
return_pct: data.start_value > 0 
  ? +((data.end_value - data.start_value) / data.start_value * 100).toFixed(2) 
  : 0,
```

---

### P1-4: SignalTracePanel `formatPct` 无null保护

**文件**: `SignalTracePanel.vue` L156  
**问题**: `pct_chg`为null时`v.toFixed(1)`会抛错

```typescript
// 当前代码
function formatPct(v) {
  if (v === null || v === undefined) return '-'
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
}
```

这里已有null保护，但`pct_chg`为0时不显示符号(应为`+0.0%`而非`0.0%`)。轻微问题，建议统一。

---

### P1-5: BacktestResultPanel benchmark净值计算未处理缺失日期

**文件**: `BacktestResultPanel.vue` L298-310  
**问题**: 基准净值线用`bdMap.get(String(d))`查找，如果回测日期范围内某天没有benchmark数据，pct为undefined，`cumBench *= (1 + pct / 100)`会得到`NaN * number = NaN`，整条基准线变成NaN。

```typescript
// 当前代码
if (pct != null && !isNaN(pct)) {
  cumBench *= (1 + pct / 100)
}
```

这里已有null保护，但如果`pct`是字符串或其他非数字类型，`isNaN`检查不会捕获。此外，缺失日期的基准值应该沿用前值而非跳过(否则基准线会"跳空")。

**修复**:
```typescript
const pct = bdMap.get(String(d))
if (pct != null && typeof pct === 'number' && !isNaN(pct)) {
  cumBench *= (1 + pct / 100)
}
// 缺失日不push，让net_value和benchmark长度对齐
benchmarkValues.push(+cumBench.toFixed(4))
```

---

## P2: 体验优化

### P2-1: CockpitView 三列布局在窄屏下溢出

**文件**: `CockpitView.vue`  
**问题**: `.main-grid`使用CSS grid三列布局，但在<1200px宽度下三列挤在一起，文字截断，风险进度条几乎不可见。

**建议**: 添加响应式断点:
```scss
@media (max-width: 1200px) {
  .main-grid { grid-template-columns: 1fr; }
  .risk-panel, .center-panel, .right-panel { max-height: none; }
}
```

---

### P2-2: BacktestResultPanel KPI卡片在窄屏下挤压

**文件**: `BacktestResultPanel.vue` L731+  
**问题**: `.kpi-strip`用flex布局，8个KPI卡片在窄屏下会换行但间距不一致，`min-width: min(90px, 20%)`在小屏下仍然过宽。

**建议**: 
```scss
@media (max-width: 900px) {
  .kpi-strip { flex-wrap: wrap; }
  .kpi-chip { min-width: 80px; padding: 8px 12px; }
}
```

---

### P2-3: UltraShortBacktestViewV2 日志面板高度固定900px，内容少时浪费空间

**文件**: `UltraShortBacktestViewV2.vue` L757  
**问题**: `<AnsiLogPanel :height="900" />` 固定高度，回测初期日志少时大片空白。

**建议**: 改为`min-height: 200` + `max-height: 900`，或在日志少于20行时动态调整。

---

### P2-4: BacktestHistoryPanel 日期格式不统一

**文件**: `backtest/ultra_short.py` L280-285  
**问题**: `created_at`用`.isoformat()`返回`2026-05-27T02:11:00+08:00`格式，但前端直接显示此字符串，过长且含时区信息。

**建议**: 在API层或前端格式化为`05-27 02:11`简短格式。

---

### P2-5: CockpitView 自动刷新间隔5秒过于频繁

**文件**: `CockpitView.vue` L494  
**问题**: `refreshTimer = setInterval(..., 5000)` 每次刷新调用`fetchAll()`包含5个HTTP请求，在非交易时间无必要。

**建议**: 
- 交易时间内5秒
- 盘后/非交易时间改为30秒
- 页面不可见时暂停(`document.visibilityState`)

---

### P2-6: StrategyDetailView/EditView 使用旧版API

**文件**: `StrategyDetailView.vue`, `StrategyEditView.vue`  
**问题**: 这两个视图使用`strategyApi`/`stockApi`，是旧版单股分析策略的CRUD，与当前的超短策略系统完全无关。当前系统策略参数通过`/scanner/params`和`/strategy-config`管理。

**建议**: 标注为废弃或从路由中移除，避免用户误入。

---

### P2-7: SettingsView 功能过于简单

**文件**: `SettingsView.vue`  
**问题**: 只有主题切换和推送配置，缺少:
- 数据源配置（东方财富/量脉切换）
- 回测默认参数配置
- 账户初始资金设置
- 风控参数全局调整

**建议**: 整合当前分散在MarketMonitorView中的参数编辑功能。

---

### P2-8: Scanner API `/all` 端点返回所有持仓详情，大数据量时性能差

**文件**: `scanner.py` L92-135  
**问题**: `/scanner/all`每次返回全部signals+positions+timeline+orders，随着运行时间增长timeline可能非常大。

**建议**: 
- timeline只返回最近N条(当前已限制20条orders)
- 增加分页参数
- 或改为增量更新模式(只返回上次请求后的变化)

---

## 回测结果页面专项检查(V58数据格式)

### 数据流追踪总结

| 字段 | 后端输出格式 | 前端转换 | 显示 | 状态 |
|------|-------------|----------|------|------|
| total_return | 百分比(102.08) | 直接用 | 102.08% | ✅ |
| win_rate | 百分比(73.08) | 直接用 | 73.08% | ✅ |
| max_drawdown | 百分比(2.82) | 直接用 | 2.82% | ✅ |
| sharpe_ratio | 原值(13.06) | 直接用 | 13.06 | ✅ |
| net_value | 归一化(1.0起始) | 直接用 | 曲线 | ✅ |
| daily_profit | 归一化(÷initial_cash) | ×100 | 百分比 | ✅ |
| drawdown | 小数(0.0282) | ×100 | 2.82% | ✅ |
| position.value | 小数(0.188) | ×100 | 18.8% | ✅ |
| monthly_profit | 小数(-0.011) | ×100 | -1.11% | ✅ |
| factor_contribution | 小数(0.5) | ×100 | 50% | ✅ |
| merged_trades.profit_pct | 百分比(-2.55) | 直接用 | -2.55% | ✅ |
| sell_reason | 中英文字符串 | translateSellReason | 中文 | ✅ |
| risk.volatility_pct | 百分比 | 直接用 | xx% | ✅ |
| risk.max_drawdown_pct | 百分比 | 直接用 | xx% | ✅ |

**结论**: 回测结果页面的数据格式处理**全部正确**。之前的formatReturn/formatRate双重×100问题已在V58之前修复。当前代码有清晰的注释说明每个字段的格式规范。

### 策略对比表数据路径

`strategy_results` → `Object.entries()` → `s.total_return`/`s.win_rate`/`s.trades_count`/`s.max_drawdown`/`s.avg_profit_pct`/`s.profit_loss_ratio`

这些字段在后端输出时已是百分比格式，前端直接使用fmtPct()，**正确**。

---

## CockpitView(实盘驾驶舱)专项检查

### 卖出按钮

**状态**: ✅ 基本正确  
`quickSell()` 调用`/scanner/trade`接口，传入`side: 'sell'`和`quantity: pos.available_qty`。有二次确认弹窗。T+1限制检查(`available_qty <= 0`时提示)。

**小问题**: 确认弹窗中`formatPct(pos.profit_pct)` — 如果`profit_pct`为null会显示`NaN%`。需要加null保护。

### 风险进度条

**状态**: ⚠️ 部分问题  
`riskBarWidth`计算: `current = profit_pct + slPct`, 然后`current / (slPct + tpPct) * 100`。

问题在于`slPct = Math.abs(pos.stop_loss_pct || 3)` — 从API返回的是正数百分比(3.0)，所以`Math.abs`是冗余但无害的。但当`pos.profit_pct`为负(如-5%)且止损为3%时:
- `current = -5 + 3 = -2`
- `width = max(0, min(100, -2/10*100)) = 0`

这是正确行为(已跌破止损线)。

### 持仓详情弹窗

**状态**: ✅ 基本正确  
风控保存: `posRiskSL.value / 100` 转为小数传给API，**正确**。

**问题**: fallback路径(L354)使用`pos.avg_cost`但PositionInfo接口中没有`avg_cost`字段(只有`cost_price`)。这会导致fallback时cost_price为undefined。

**修复**: L354 `cost_price: pos.avg_cost` → `cost_price: pos.cost_price`

---

## MarketMonitorView专项检查

### 信号显示

**状态**: ✅ 正确  
信号列表从`/scanner/all`获取，包含`pct_chg`、`volume_ratio`等因子。使用`signalFilter`按策略过滤，`sigRemaining`计算倒计时。

### 股价数据绑定

**状态**: ✅ 正确  
持仓的`current_price`由scanner在每次扫描时更新，通过5秒轮询刷新。

### 实时更新机制

**状态**: ⚠️ 混合模式  
同时使用WebSocket + 5秒轮询。WebSocket推送`scanner_signal`/`scanner_position`/`scanner_status`/`scanner_timeline`，轮询作为fallback。

**问题**: 两套更新可能冲突 — WebSocket推送更新了数据，轮询又用稍旧的数据覆盖。建议轮询仅在WebSocket断开时启用。

---

## Scanner API快速扫描

### 端点完整性

| 端点 | 状态 | 备注 |
|------|------|------|
| GET /scanner/all | ✅ | 合并5个接口 |
| GET /scanner/status | ✅ | 含数据源+熔断 |
| GET /scanner/signals | ✅ | |
| GET /scanner/positions | ✅ | stop_loss_pct已是百分比 |
| GET /scanner/timeline | ✅ | |
| POST /scanner/start | ✅ | 含replay模式 |
| POST /scanner/stop | ✅ | |
| POST /scanner/trade | ✅ | 含T+1检查 |
| POST /scanner/scan-once | ✅ | |
| GET /scanner/health | ✅ | |
| POST /scanner/emergency-liquidate | ✅ | |
| GET /scanner/limit-pools | ✅ | |
| GET /scanner/scan-traces | ✅ | |
| GET /scanner/trade-detail/:ts_code | ✅ | |
| GET /scanner/trade-audit | ✅ | |
| GET /scanner/params | ✅ | 返回小数(0.03) |
| PUT /scanner/params/:strategy | ✅ | |
| GET /scanner/performance-history | ✅ | |
| PUT /scanner/position-risk/:ts_code | ✅ | 接受小数(0.03) |
| POST /scanner/daily-settlement | ✅ | |
| POST /scanner/reset | ✅ | |
| POST /scanner/sell-all | ✅ | |
| GET /scanner/quote/:ts_code | ✅ | |
| POST /scanner/circuit-breaker/pause | ✅ | |
| POST /scanner/circuit-breaker/reset | ✅ | |
| GET /scanner/daily-report | ✅ | |
| POST /scanner/snapshot | ✅ | |
| GET /scanner/trade-log | ✅ | CSV导出 |

### API格式不一致问题

1. **`/params`返回小数(0.03)** vs **`/positions`返回百分比(3.0)** — 前端需要记住哪个用哪种格式
2. **`/position-risk/`接受小数(0.03)** — 与`/positions`返回格式相反
3. **`profit_pct`在positions中是百分比(2.55)** vs **scanner内部PositionData是百分比(-3.0)** — 一致

**建议**: 在scanner API层统一所有pct字段为百分比格式，内部小数→输出时×100。这样前端不需要记忆不同端点的格式。

---

## 修复优先级排序

| 优先级 | 编号 | 描述 | 影响范围 |
|--------|------|------|----------|
| P0 | P0-1 | quickBuySignal止损止盈显示300%/700% | CockpitView |
| P0 | P0-2 | todayPnl计算逻辑有误 | CockpitView |
| P0 | P0-3 | position detail fallback用avg_cost(不存在) | CockpitView |
| P1 | P1-1 | savePosRisk未同步positions列表 | CockpitView |
| P1 | P1-2 | MarketMonitorView 103KB组件拆分 | 性能 |
| P1 | P1-3 | BacktestResultPanel null保护 | 回测页面 |
| P1 | P1-5 | benchmark净值缺失日NaN | 回测页面 |
| P2 | P2-1~P2-8 | UI/UX/性能优化 | 各页面 |

---

## 已确认正确的关键数据流

1. **回测结果百分比**: total_return/win_rate/max_drawdown/annualized_return — 后端已是百分比，前端直接`toFixed(2)+'%'` ✅
2. **net_value_series**: 已归一化(1.0起始)，前端直接用作Y轴 ✅
3. **drawdown_series**: 小数(0.0368)，前端×100转百分比 ✅
4. **daily_profit**: 已归一化(÷initial_cash)，前端×100转百分比 ✅
5. **merged_trades.profit_pct**: 已是百分比，前端直接用 ✅
6. **卖出原因翻译**: translateSellReason覆盖所有已知原因 ✅
7. **V58 SL/TP精度**: .toFixed(1)显示 ✅
8. **强空T+1翻译**: '强制空仓(延后)' → '强空T+1' ✅

---

*审计完成。建议优先修复P0-1(止损止盈显示错误)和P0-3(avg_cost字段不存在)，这两个问题用户在实盘驾驶舱中会直接看到。*
