# StockAgent 前端 UI/UX 全面审查报告 V36

> 审查日期：2026-05-24  
> 审查范围：16个前端文件，~7500行Vue代码  
> 审查维度：视觉一致性 / 响应式 / 暗色模式 / 交互体验 / 数据展示 / 性能 / 可访问性

---

## 一、总览评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 视觉一致性 | ⭐⭐⭐ (3/5) | theme.scss设计系统完善但执行不力，98处硬编码颜色 |
| 响应式 | ⭐⭐⭐ (3/5) | MainLayout/回测页有响应式，MarketMonitor 3列布局窄屏崩坏 |
| 暗色模式 | ⭐⭐ (2/5) | 基础架构存在但MarketMonitor几乎不支持，243处硬编码色 |
| 交互体验 | ⭐⭐⭐⭐ (4/5) | 回测/监控核心交互良好，确认弹窗/过期倒计时等细节到位 |
| 数据展示 | ⭐⭐⭐⭐ (4/5) | 图表丰富，交易记录详尽，但部分表格信息密度过高 |
| 性能 | ⭐⭐⭐ (3/5) | MarketMonitor无虚拟滚动，825行单组件过大 |
| 可访问性 | ⭐⭐ (2/5) | 无ARIA标注，对比度不达标，无键盘导航 |

---

## 二、P0 必须修复（影响功能/可用性）

### P0-1: MarketMonitorView 暗色模式完全失效

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 98处硬编码颜色（#f5f7fa, #fff, #ebeef5, #303133等），暗色模式下整个页面白底白字，不可用  
**严重级别**: P0 — 暗色模式下页面不可用  
**修复方案**:

```scss
// 替换所有硬编码为CSS变量（示例）
// Before:
.mm { background: #f5f7fa; }
.mm-header { background: #fff; border-bottom: 1px solid #ebeef5; }
.st { color: #303133; }

// After:
.mm { background: var(--bg-base); }
.mm-header { background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); }
.st { color: var(--text-primary); }
```

需要替换的关键映射表（共98处）:

| 硬编码 | 替换为 | 用途 |
|--------|--------|------|
| `#f5f7fa` | `var(--bg-base)` | 页面背景 |
| `#fff` / `#ffffff` | `var(--bg-elevated)` | 卡片/弹窗背景 |
| `#fafbfc` | `var(--bg-secondary)` | 侧栏背景 |
| `#ebeef5` | `var(--border-default)` | 边框 |
| `#303133` | `var(--text-primary)` | 主文字 |
| `#909399` | `var(--text-tertiary)` | 辅助文字 |
| `#f56c6c` | `var(--stock-up)` | 涨/A股红 |
| `#67c23a` | `var(--stock-down)` | 跌/A股绿 |
| `#409eff` | `var(--primary-500)` | 主色/链接 |
| `#e6a23c` | `var(--warning)` | 警告色 |
| `#fef0f0` | `var(--stock-up-bg)` | 涨背景 |
| `#f0f9eb` | `var(--stock-down-bg)` | 跌背景 |
| `#fdf6ec` | `var(--warning-bg)` | 警告背景 |
| `#f4f4f5` | `var(--bg-muted)` | 标签背景 |

### P0-2: MarketMonitorView 3列布局窄屏（<1024px）崩坏

**文件**: `views/monitor/MarketMonitorView.vue` L553  
**问题**: `grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr)` 在768px下3列挤在一起，内容不可读  
**严重级别**: P0 — 平板/小屏完全不可用  
**修复方案**:

```scss
.mm-body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr);
  gap: 0;
  overflow: hidden;
  min-width: 0;
}

// 新增响应式断点
@media (max-width: 1024px) {
  .mm-body {
    grid-template-columns: 1fr;  // 单列堆叠
    overflow-y: auto;
  }
  .mm-left, .mm-right {
    border-right: none;
    border-left: none;
    border-bottom: 1px solid var(--border-default);
  }
}

@media (max-width: 1280px) and (min-width: 1025px) {
  .mm-body {
    grid-template-columns: minmax(140px, 1fr) minmax(200px, 3fr) minmax(250px, 4fr);
  }
}
```

### P0-3: BacktestResultPanel/SummaryTable 暗色模式部分失效

**文件**: `components/ultrashort/BacktestResultPanel.vue` (39处), `components/backtest/BacktestSummaryTable.vue` (12处)  
**问题**: 大量 `color: #67c23a` / `color: #f56c6c` 硬编码，暗色模式下对比度不足  
**严重级别**: P0 — 暗色模式下关键数据不可读  
**修复方案**:

```vue
<!-- Before -->
<span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c' }">

<!-- After -->
<span :class="row.total_return >= 0 ? 'stock-down' : 'stock-up'" :style="{ fontWeight: 600 }">
```

注意：A股市红色=涨(#f56c6c→var(--stock-up))、绿色=跌(#67c23a→var(--stock-down))。当前BacktestSummaryTable中正收益用#67c23a(绿)，虽与A股惯例相反，但对应的是"盈利=绿"的Element Plus惯例。需统一为A股惯例（盈利=红），使用`var(--stock-up)`表示正收益。

### P0-4: ECharts图表硬编码颜色不跟随暗色主题

**文件**: `UltraShortBacktestViewV2.vue` L644-657, `BacktestResultPanel.vue` 多处  
**问题**: ECharts配置中颜色全硬编码（`#67c23a`, `#409eff`, `#f56c6c`等），暗色模式下图表背景透明但数据线颜色不变，网格线和文字可能不可读  
**严重级别**: P0 — 暗色模式下图表不可读  
**修复方案**:

```typescript
// 创建统一的ECharts主题配置
const chartThemeColors = computed(() => ({
  up: getComputedStyle(document.documentElement).getPropertyValue('--stock-up').trim(),
  down: getComputedStyle(document.documentElement).getPropertyValue('--stock-down').trim(),
  primary: getComputedStyle(document.documentElement).getPropertyValue('--primary-500').trim(),
  text: getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim(),
  axis: getComputedStyle(document.documentElement).getPropertyValue('--chart-axis').trim(),
  grid: getComputedStyle(document.documentElement).getPropertyValue('--chart-grid').trim(),
}))

// 在图表配置中使用
const sweepChartOption = computed(() => {
  const tc = chartThemeColors.value
  return {
    // ...
    xAxis: { axisLine: { lineStyle: { color: tc.axis } } },
    yAxis: { splitLine: { lineStyle: { color: tc.grid } } },
    series: [
      { lineStyle: { color: tc.down }, itemStyle: { color: tc.down } },  // A股绿=涨
      { lineStyle: { color: tc.primary }, itemStyle: { color: tc.primary } },
      { lineStyle: { color: tc.up, type: 'dashed' }, itemStyle: { color: tc.up } },  // A股红=跌/回撤
    ]
  }
})
```

---

## 三、P1 应修复（影响体验/一致性）

### P1-1: MarketMonitorView 涨跌色方向与A股惯例不一致

**文件**: `views/monitor/MarketMonitorView.vue` L539-540  
**问题**: `.up { color: #f56c6c; }` `.down { color: #67c23a; }` — 这里up=红、down=绿，是正确的A股惯例。但变量名`up/down`容易与"盈/亏"混淆。而BacktestSummaryTable中盈利用`#67c23a`(绿)是反的。  
**严重级别**: P1 — 全系统涨跌色不统一  
**修复方案**:

```scss
// 统一为A股语义化类名
.stock-up, .price-rise { color: var(--stock-up) !important; }    /* 红色=涨 */
.stock-down, .price-fall { color: var(--stock-down) !important; } /* 绿色=跌 */
.profit-positive { color: var(--stock-up) !important; }           /* 红色=盈利 */
.profit-negative { color: var(--stock-down) !important; }         /* 绿色=亏损 */

// 逐步替换现有 .up/.down 类名
```

### P1-2: UltraShortBacktestViewV2 运行状态/耗时样式硬编码

**文件**: `views/backtest/UltraShortBacktestViewV2.vue` L970-989  
**问题**: `.running-status` 背景用 `linear-gradient(#e6f7ff, #bae7ff)` 和 `color: #1890ff`，`.execution-time` 用 `background: #f0f9eb; color: #67c23a`，暗色模式下不可读  
**严重级别**: P1  
**修复方案**:

```scss
.running-status {
  padding: 10px 20px;
  background: var(--info-bg);
  border: 1px solid var(--primary-200);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--primary-500);
  animation: pulse 2s infinite;
}
.execution-time {
  padding: 8px 20px;
  background: var(--stock-down-bg);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--stock-down);
}
```

### P1-3: DbAdminView 操作按钮列过宽

**文件**: `views/admin/DbAdminView.vue`  
**问题**: 操作列 `width="480"` 包含4个emoji按钮，宽屏下挤压数据列，窄屏下溢出  
**严重级别**: P1  
**修复方案**:

```vue
<!-- 方案1: 按钮列自适应，固定右侧 -->
<ElTableColumn label="操作" min-width="320" fixed="right">

<!-- 方案2: 窄屏下收起为下拉菜单 -->
<ElTableColumn label="操作" width="100" fixed="right">
  <template #default="{ row }">
    <ElDropdown trigger="click">
      <ElButton size="small">操作 ▼</ElButton>
      <template #dropdown>
        <ElDropdownMenu>
          <ElDropdownItem @click="handleCheckMissing">🔍 检查缺失</ElDropdownItem>
          <ElDropdownItem @click="openDeduplicateDialog(row.name)">🧹 去重</ElDropdownItem>
          <ElDropdownItem @click="openClearDateDialog(row.name)">📅 按日期清空</ElDropdownItem>
          <ElDropdownItem @click="handleClearCollection(row.name)" divided>🗑️ 清空全部</ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>
  </template>
</ElTableColumn>
```

### P1-4: DbAdminView JSON结果无语法高亮

**文件**: `views/admin/DbAdminView.vue`  
**问题**: 操作结果用 `<pre>` 原始展示JSON，无高亮、无折叠，大结果不可读  
**严重级别**: P1  
**修复方案**:

```vue
<!-- 方案1: 简易高亮（无需新依赖） -->
<pre class="result-json" v-html="highlightJson(JSON.stringify(operationResult, null, 2))"></pre>

<script>
function highlightJson(json: string): string {
  return json
    .replace(/("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?)/g, (match) => {
      let cls = 'json-number'  // 数字
      if (/:$/.test(match)) cls = 'json-key'     // key
      else if (/^"/.test(match)) cls = 'json-string'  // string
      return `<span class="${cls}">${match}</span>`
    })
    .replace(/\b(true|false|null)\b/g, '<span class="json-bool">$1</span>')
    .replace(/\b(-?\d+\.?\d*([eE][+-]?\d+)?)\b/g, '<span class="json-number">$1</span>')
}
</script>

<style scoped lang="scss">
.result-json {
  :deep(.json-key) { color: var(--primary-500); }
  :deep(.json-string) { color: var(--stock-down); }
  :deep(.json-number) { color: var(--warning); }
  :deep(.json-bool) { color: var(--stock-up); }
}
</style>
```

### P1-5: SystemStatusView 页面标题字体过大

**文件**: `views/system/SystemStatusView.vue`  
**问题**: `.page-title { font-size: 20px; }` 与其他页面一致但视觉上与mainLayout的header page-title(16px)重复，造成双重标题  
**严重级别**: P1  
**修复方案**:

```scss
// 方案1: 去掉页面内标题（MainLayout已有），用描述替代
.page-header {
  .page-title { display: none; }  // 由MainLayout header显示
  .page-description {
    font-size: 13px;
    color: var(--text-tertiary);
    margin: 0 0 16px 0;
  }
}

// 方案2: 如果保留，缩小为副标题
.page-header .page-title { font-size: 16px; font-weight: 600; }
```

### P1-6: SettingsView 宽屏浪费空间+无暗色主题生效

**文件**: `views/settings/SettingsView.vue`  
**问题**: `max-width: 900px` 宽屏下大量留白；暗色主题切换只存store但未实际调用themeStore  
**严重级别**: P1  
**修复方案**:

```vue
<script setup lang="ts">
import { useThemeStore } from '@/stores'
const themeStore = useThemeStore()

// 主题选择变更时实际切换
function onThemeChange(theme: string) {
  themeStore.setTheme(theme)
  preferences.value.theme = theme
}
</script>

<template>
  <ElFormItem label="主题">
    <ElRadioGroup v-model="preferences.theme" @change="onThemeChange">
      <ElRadio value="light">浅色</ElRadio>
      <ElRadio value="dark">深色</ElRadio>
      <ElRadio value="system">跟随系统</ElRadio>
    </ElRadioGroup>
  </ElFormItem>
</template>
```

### P1-7: DataStatusPanel 硬编码颜色29处

**文件**: `components/ultrashort/DataStatusPanel.vue`  
**问题**: 29处硬编码颜色(#67c23a, #f56c6c, #e6a23c, #409eff等)，暗色模式失效  
**严重级别**: P1  
**修复方案**: 同P0-1的映射表，批量替换为CSS变量

### P1-8: BacktestHistoryPanel 硬编码颜色19处

**文件**: `components/backtest/BacktestHistoryPanel.vue`  
**问题**: 同上，19处硬编码  
**严重级别**: P1  
**修复方案**: 同P0-1的映射表

### P1-9: MarketMonitorView 涨停池缺少视觉层次

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 涨停池/跌停池列表是平铺的文本列表，无热度/封单额视觉层次，无法快速识别强势股  
**严重级别**: P1  
**修复方案**:

```vue
<!-- 添加封单额热力条 -->
<div v-for="item in limitPools[limitPoolTab]" :key="item.ts_code" class="pool-item">
  <div class="pool-main">
    <span class="code">{{ item.ts_code }}</span>
    <span class="name">{{ item.name }}</span>
    <span :class="item.pct_chg >= 0 ? 'stock-up' : 'stock-down'" class="pct">
      {{ item.pct_chg >= 0 ? '+' : '' }}{{ item.pct_chg?.toFixed(1) }}%
    </span>
  </div>
  <!-- 热力条：封单额越大越红 -->
  <div v-if="item.fd_amount" class="heat-bar">
    <div class="heat-fill" :style="{
      width: Math.min(item.fd_amount / maxFdAmount * 100, 100) + '%',
      background: 'var(--stock-up)'
    }"></div>
  </div>
  <div class="pool-meta">
    <span v-if="item.fd_amount">封单{{ (item.fd_amount / 10000).toFixed(0) }}万</span>
    <span v-if="item.limit_times">{{ item.limit_times }}连板</span>
  </div>
</div>
```

### P1-10: MarketMonitorView 持仓卡片止损显示不佳

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 止损价/止盈价只在小字中显示，接近止损时无明显警示  
**严重级别**: P1  
**修复方案**:

```vue
<!-- 距止损<1%时红色边框+闪烁 -->
<div class="pos-card" :class="{ 'danger-near': distanceToStopLoss(pos).replace('%','') < 1 }">
  <!-- 现有内容 -->
  <div class="pos-risk">
    <span class="rl stop-price">止损 ¥{{ pos.stop_loss_price?.toFixed(2) }}</span>
    <span class="rl profit-price">止盈 ¥{{ pos.take_profit_price?.toFixed(2) }}</span>
    <span class="rd" :class="{ danger: parseFloat(distanceToStopLoss(pos)) < 1 }">
      距止损 {{ distanceToStopLoss(pos) }}
    </span>
  </div>
</div>

<style>
.pos-card.danger-near {
  border-color: var(--stock-up) !important;
  animation: blink 2s infinite;
}
@keyframes blink {
  0%, 100% { border-color: var(--stock-up); }
  50% { border-color: transparent; }
}
</style>
```

---

## 四、P2 改进建议（提升品质）

### P2-1: MarketMonitorView 手动下单布局过密

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 手动下单表单各输入框间距仅4px，移动端误触率高  
**修复方案**: `gap: 4px` → `gap: 8px`，输入框最小高度36px

### P2-2: MarketMonitorView 825行单组件过于庞大

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 单文件825行，包含策略编辑、交易确认、复盘报告、9层调试、手动下单等多个子功能  
**修复方案**: 拆分为子组件：
- `StrategyEditDialog.vue` — 策略参数编辑
- `ManualTradeForm.vue` — 手动下单
- `DailyReportDialog.vue` — 复盘报告
- `LayerDebugDialog.vue` — 9层调试
- `TradeConfirmDialog.vue` — 交易确认

### P2-3: MarketMonitorView 信号列表无虚拟滚动

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 信号多时（100+）DOM节点过多，滚动卡顿  
**修复方案**: 引入 `vue-virtual-scroller` 或使用 `ElTable` 的虚拟滚动模式

```vue
<RecycleScroller
  :items="filteredSignals"
  :item-size="40"
  key-field="ts_code"
  v-slot="{ item: sig }"
>
  <!-- 现有信号行内容 -->
</RecycleScroller>
```

### P2-4: DbAdminView stats-grid 固定4列

**文件**: `views/admin/DbAdminView.vue`  
**问题**: `grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))` 在宽屏下4列均匀分布但浪费空间  
**修复方案**: 改为2行布局，第一行大指标，第二行小指标：

```scss
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}
```

### P2-5: SystemStatusView 统计网格不弹性

**文件**: `views/system/SystemStatusView.vue`  
**问题**: 策略表格无水平滚动，窄屏下列挤压  
**修复方案**: 添加 `ElTable` 的 `max-height` 和列宽自适应

### P2-6: BacktestResultPanel 图表暗色模式tooltip背景不跟随

**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: ECharts tooltip 默认白色背景，暗色模式下刺眼  
**修复方案**: 在所有图表配置中添加：

```typescript
tooltip: {
  backgroundColor: 'var(--chart-tooltip-bg)',
  borderColor: 'var(--chart-tooltip-border)',
  textStyle: { color: 'var(--chart-tooltip-text)' }
}
```
注意：ECharts不支持CSS变量，需在computed中读取计算值。

### P2-7: 路由页面标题重复

**文件**: `router/index.ts` + `MainLayout.vue`  
**问题**: MainLayout显示 `route.meta.title` 作为header标题，但SystemStatusView/DbAdminView内部又有`.page-title` h1标签，双重标题  
**修复方案**: 统一由MainLayout显示标题，各页面内部不再重复

### P2-8: 缺少空状态处理

**文件**: 多个组件  
**问题**: DataStatusPanel无数据时无提示，FactorReferencePanel加载失败无反馈  
**修复方案**: 添加 `ElEmpty` 组件：

```vue
<ElEmpty v-if="!data || data.length === 0" description="暂无数据" />
```

### P2-9: 可访问性缺失

**文件**: 所有组件  
**问题**: 
- 无ARIA标注（按钮只有emoji，screen reader无法理解）
- 对比度不达标（#909399在#fff背景上对比度3.3:1，需4.5:1）
- 无键盘导航（Tab/Enter无法操作自定义按钮）
- 焦点状态缺失

**修复方案**:
```vue
<!-- 添加ARIA标注 -->
<button class="config-toggle-btn" 
  @click="configCollapsed = !configCollapsed" 
  :aria-label="configCollapsed ? '展开配置面板' : '收起配置面板'"
  :aria-expanded="!configCollapsed">
  {{ configCollapsed ? '▶' : '◀' }}
</button>

<!-- 提高对比度：#909399 → #64748b (4.6:1 on white) -->
// theme.scss: --text-tertiary: #64748b (已经是，但组件中硬编码的#909399需替换)

<!-- 添加焦点状态 -->
.tab-btn:focus-visible {
  outline: 2px solid var(--primary-500);
  outline-offset: 2px;
}
```

### P2-10: BacktestResultPanel 涨跌色与A股惯例不一致

**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: 正收益用绿色(#67c23a)，与A股"红涨绿跌"惯例相反。这是沿用了Element Plus的"绿色=好"惯例。  
**修复方案**: 统一使用 `var(--stock-up)`（红色）表示正收益，`var(--stock-down)`（绿色）表示负收益，与MarketMonitorView保持一致。

---

## 五、逐组件评价

### 1. MainLayout.vue ✅ 良好

**评分**: ⭐⭐⭐⭐  
**优点**: 
- 侧边栏收起/展开平滑动画
- 暗色/亮色切换按钮有动画过渡
- 900px以下自动收起侧边栏
- 使用CSS变量，主题跟随正确

**问题**:
- 侧边栏`position: fixed` + `margin-left`方案在CSS Grid时代不够优雅
- logo区域暗色模式下 `.logo-text { color: white }` 硬编码

### 2. UltraShortBacktestViewV2.vue ✅ 良好

**评分**: ⭐⭐⭐⭐  
**优点**:
- Tab切换设计清晰，自定义tab按钮风格统一
- 配置面板收起/展开按钮有阴影层次
- 运行中状态脉冲动画明显
- WebSocket→轮询降级策略完善
- 1000px以下自动切换为上下布局

**问题**:
- 运行状态条背景硬编码蓝色渐变（暗色不可读）
- 扫描图表颜色硬编码
- `config-left` 宽度 `clamp(340px, 35vw, 520px)` 在1440px下510px，策略配置折叠项多时需大量滚动

### 3. BacktestResultPanel.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**优点**:
- 图表类型丰富（净值/回撤/月度/雷达/因子贡献）
- 交易记录搜索/筛选功能完整
- 卖出原因翻译表详尽
- TOP5盈亏展示

**问题**:
- 39处硬编码颜色
- 图表tooltip暗色模式不跟随
- 涨跌色与A股惯例不一致
- 1128行单组件，建议拆分图表子组件

### 4. StrategyConfigPanel.vue ✅ 良好

**评分**: ⭐⭐⭐⭐  
**优点**: 无硬编码颜色，使用CSS变量  
**问题**: 677行略长，策略配置折叠项多时滚动体验一般

### 5. DataStatusPanel.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**问题**: 29处硬编码颜色，暗色模式完全失效

### 6. FactorReferencePanel.vue ✅ 尚可

**评分**: ⭐⭐⭐  
**问题**: 322行，功能简单但缺少空状态和加载态

### 7. StrategyFactorPanel.vue ✅ 尚可

**评分**: ⭐⭐⭐  
**问题**: 同上

### 8. AnsiLogPanel.vue ✅ 良好

**评分**: ⭐⭐⭐⭐  
**优点**: 终端风格日志面板，ANSI颜色渲染  
**问题**: 字体略小（12px → 建议13px），暗色模式下需确认背景色

### 9. BacktestHistoryPanel.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**问题**: 19处硬编码颜色

### 10. BacktestSummaryTable.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**问题**: 12处硬编码颜色，涨跌色与A股惯例不一致

### 11. MarketMonitorView.vue ❌ 需大改

**评分**: ⭐⭐  
**问题**: 
- 98处硬编码颜色，暗色模式完全不可用
- 825行单组件，严重超长
- 3列布局窄屏崩坏
- 无虚拟滚动
- 涨停池缺少视觉层次
- 持仓止损警示不足

### 12. DbAdminView.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**问题**: 操作按钮列过宽、JSON无高亮、stats-grid弹性不足、3处硬编码

### 13. SystemStatusView.vue ✅ 尚可

**评分**: ⭐⭐⭐  
**问题**: 双重标题、3处硬编码、表格窄屏挤压

### 14. SettingsView.vue ⚠️ 需改进

**评分**: ⭐⭐⭐  
**问题**: 暗色主题切换不生效、宽屏浪费空间、缺少"跟随系统"选项

---

## 六、整体优化建议

### 建议1: 创建全局涨跌色工具函数

```typescript
// utils/stockColors.ts
export function getProfitColor(value: number): string {
  return value >= 0 ? 'var(--stock-up)' : 'var(--stock-down)'
}

export function getProfitClass(value: number): string {
  return value >= 0 ? 'stock-up' : 'stock-down'
}

export function getProfitBgClass(value: number): string {
  return value >= 0 ? 'stock-up-bg' : 'stock-down-bg'
}

// ECharts专用（CSS变量 → 计算值）
export function getChartColor(varName: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
}
```

### 建议2: ECharts暗色主题配置文件

```typescript
// config/echartsTheme.ts
import type { ComposeOption } from 'echarts/core'

export function getEChartsBaseTheme(): Record<string, any> {
  const root = document.documentElement
  const s = (v: string) => getComputedStyle(root).getPropertyValue(v).trim()
  
  return {
    color: [s('--primary-500'), s('--stock-down'), s('--stock-up'), s('--warning'), s('--info')],
    backgroundColor: 'transparent',
    textStyle: { color: s('--text-secondary'), fontFamily: s('--font-sans') },
    title: { textStyle: { color: s('--text-primary') } },
    legend: { textStyle: { color: s('--text-secondary') } },
    tooltip: {
      backgroundColor: s('--chart-tooltip-bg'),
      borderColor: s('--chart-tooltip-border'),
      textStyle: { color: s('--chart-tooltip-text') }
    },
    xAxis: {
      axisLine: { lineStyle: { color: s('--chart-axis') } },
      splitLine: { lineStyle: { color: s('--chart-grid') } }
    },
    yAxis: {
      axisLine: { lineStyle: { color: s('--chart-axis') } },
      splitLine: { lineStyle: { color: s('--chart-grid') } }
    }
  }
}
```

### 建议3: MarketMonitorView组件拆分计划

| 新组件 | 来源 | 行数(估) |
|--------|------|----------|
| StrategyCardList.vue | 策略卡片列表 | ~80 |
| StrategyEditDialog.vue | 策略参数编辑 | ~120 |
| SignalList.vue | 信号列表+筛选 | ~100 |
| PositionCardList.vue | 持仓卡片列表 | ~100 |
| ManualTradeForm.vue | 手动下单 | ~80 |
| LimitPoolList.vue | 涨跌停池 | ~60 |
| TimelinePanel.vue | 时间线 | ~60 |
| TradeConfirmDialog.vue | 交易确认 | ~40 |
| DailyReportDialog.vue | 复盘报告 | ~80 |
| WeeklyReportDialog.vue | 周报 | ~60 |
| LayerDebugDialog.vue | 9层调试 | ~80 |
| ScanTraceDialog.vue | 扫描链路 | ~60 |
| TradeDetailDialog.vue | 交易详情 | ~40 |
| TradeAuditDialog.vue | 交易审查 | ~40 |
| CompareDialog.vue | 实盘vs回测 | ~40 |

### 建议4: 响应式断点统一

当前各组件断点不一致：
- MainLayout: 900px
- UltraShortBacktestViewV2: 1000px
- MarketMonitorView: 无断点

建议统一为theme.scss中的断点：
```scss
$breakpoints: (
  'sm': 640px,   // 手机横屏
  'md': 768px,   // 平板竖屏
  'lg': 1024px,  // 平板横屏/小笔记本
  'xl': 1280px,  // 标准笔记本
  '2xl': 1536px  // 大屏
);
```

### 建议5: 暗色模式审查清单

对所有组件执行以下检查：
1. ✅ 背景色：是否使用 `var(--bg-*)`
2. ✅ 文字色：是否使用 `var(--text-*)`
3. ✅ 边框色：是否使用 `var(--border-*)`
4. ✅ 涨跌色：是否使用 `var(--stock-*)`
5. ✅ 功能色：是否使用 `var(--success/warning/error/info)`
6. ✅ ECharts：tooltip/axis/grid是否跟随主题
7. ✅ 内联style：`:style="{ color: '#xxx' }"` 是否替换为class
8. ✅ 动态class：`condition ? '#67c23a' : '#f56c6c'` 是否替换为class

---

## 七、修复优先级汇总

| 级别 | 数量 | 预估工时 |
|------|------|----------|
| P0 | 4项 | 8小时 |
| P1 | 10项 | 12小时 |
| P2 | 10项 | 8小时 |
| **总计** | **24项** | **28小时** |

### P0修复顺序建议
1. P0-1: MarketMonitorView 硬编码颜色替换（最大影响面）
2. P0-3: BacktestResultPanel/SummaryTable 硬编码替换
3. P0-4: ECharts暗色主题
4. P0-2: MarketMonitorView 窄屏响应式

---

*审查完毕。本报告仅做审查，未修改任何代码。*
