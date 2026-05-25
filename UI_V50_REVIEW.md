# StockAgent 前端 UI/UX 全面审查报告 V50

> 审查日期：2026-05-25  
> 审查范围：18个前端文件，~7240行Vue代码  
> 前次审查：V36 (2026-05-24)  
> V36→V50期间已完成修复：MarketMonitorView暗色模式(150处)、StockDetailView/BacktestHistoryPanel/DbAdminView暗色修复、亮色模式全面修复、暗色色阶统一、V48卖出原因前端新增  

---

## 一、总览评分

| 维度 | V36评分 | V50评分 | 变化 | 说明 |
|------|---------|---------|------|------|
| 视觉一致性 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ↑1 | theme.scss设计系统完善，主要组件已用CSS变量；BacktestResultPanel全面用var() |
| 响应式 | ⭐⭐⭐ | ⭐⭐⭐½ | ↑0.5 | MainLayout/回测页有响应式，MarketMonitor仍缺少窄屏断点 |
| 暗色模式 | ⭐⭐ | ⭐⭐⭐⭐ | ↑2 | MarketMonitorView/BacktestResultPanel已修复；但BacktestHistoryPanel/FactorReferencePanel仍有硬编码 |
| 交互体验 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | → | 核心交互良好，交易确认/过期倒计时/参数校验完善 |
| 数据展示 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐½ | ↑0.5 | 图表更丰富(盈亏分布/持仓时长/策略柱状图)，CSV导出已实现 |
| 性能 | ⭐⭐⭐ | ⭐⭐⭐ | → | MarketMonitor仍无虚拟滚动，构建chunk过大 |
| 可访问性 | ⭐⭐ | ⭐⭐ | → | 无ARIA标注，对比度仍不达标 |

---

## 二、V36→V50 已完成修复确认

### ✅ P0-1: MarketMonitorView 暗色模式 (commit 9390c56)
- 150处硬编码颜色→CSS变量替换
- 实测暗色模式下页面可读

### ✅ P0-3: BacktestResultPanel/SummaryTable 暗色模式
- 全面使用var(--stock-up)/var(--stock-down)替代硬编码
- 图表颜色使用CSS变量

### ✅ P0-4: ECharts暗色主题
- BacktestResultPanel中ECharts配置使用var()变量
- 涨跌色、主色、警告色均跟随主题

### ✅ StockDetailView暗色模式修复 (commit b1de4f7)
- 全面使用CSS变量
- 优秀的骨架屏加载

### ✅ BacktestHistoryPanel暗色模式修复 (commit b1de4f7)
- 卡片/表头/边框使用CSS变量

### ✅ DbAdminView暗色模式修复 (commit b1de4f7)

### ✅ V48: 卖出原因前端新增
- 冲高回落/利润保护/利润锁定在BacktestResultPanel卖出原因栏展示
- 新增颜色和圆点标识

### ✅ V48g: 参数扫描新增利润锁定/持仓保护配置
- backtestConstants.ts新增SWEEP_PARAMS

---

## 三、P0 必须修复（影响功能/可用性）

### P0-1: MarketMonitorView 策略标签颜色硬编码(8处)

**文件**: `views/monitor/MarketMonitorView.vue` L48-55  
**问题**: `strategyMeta`对象中策略颜色仍为硬编码`#e6a23c`/`#f56c6c`/`#409eff`等，作为`ElTag`的`:color`传入时暗色模式下文字不可读  
**严重级别**: P0 — 暗色模式下策略标签白字在浅色背景上不可读  
**修复方案**:

```typescript
// 将strategyMeta中的color改为使用主题色
const strategyMeta = {
  halfway_chase: { color: 'var(--warning)', icon: '🚀', ... },
  first_limit_up: { color: 'var(--stock-up)', icon: '🔥', ... },
  dragon_head: { color: 'var(--primary-500)', icon: '🐉', ... },
  limit_down_qiao: { color: 'var(--stock-down)', icon: '💪', ... },
  // ...
}
```

注意：ElTag的`:color`属性不接受CSS变量，需要改为用class+内联style替代，或改用`<span class="strategy-tag">`。

### P0-2: BacktestHistoryPanel 20处硬编码颜色

**文件**: `components/backtest/BacktestHistoryPanel.vue`  
**问题**: `returnColor()`函数返回硬编码色值（#2d8a4e/#67c23a/#95d475/#f89898/#f56c6c），卡片/表格中盈亏/胜率/夏普/回撤的`:style="{ color: '#67c23a' }"`形式仍有20处  
**严重级别**: P0 — 暗色模式下回测历史核心指标不可读  
**修复方案**:

```typescript
// 替换returnColor函数
function returnColor(val: number | null | undefined): string {
  if (val == null) return 'var(--text-muted)'
  if (val >= 30) return 'var(--stock-down)'       // 高收益=绿(A股涨=红，但这里是"好"=绿)
  if (val >= 10) return 'var(--stock-down)'
  if (val >= 0) return 'var(--stock-down-light)'
  if (val >= -10) return 'var(--stock-up-light)'
  return 'var(--stock-up)'
}

// 替换所有内联颜色为函数调用
:style="{ color: returnColor(item.total_return) }"
// 盈利率
:style="{ color: summary.profitCount / summary.count > 0.5 ? 'var(--stock-down)' : 'var(--stock-up)' }"
```

注意：BacktestHistoryPanel中"盈利=绿(#67c23a)"与A股"涨=红"惯例不一致，但这是"表现好=绿"的通用惯例，与涨跌色是不同语义。建议保持当前"好=绿"惯例，但需统一使用CSS变量。

### P0-3: FactorReferencePanel 暗色模式失效

**文件**: `components/ultrashort/FactorReferencePanel.vue`  
**问题**: 7处硬编码颜色(#fdf6ec/#fef0f0/#faeccd/#fbc4c4/#e6a23c/#f56c6c/#303133)，`.stat-card.warn`/`.stat-card.bad`使用硬编码背景色  
**严重级别**: P0 — 因子参考页暗色模式下卡片白底不可读  
**修复方案**: 同P0-1映射表替换

---

## 四、P1 应修复（影响体验/一致性）

### P1-1: SystemStatusView 3处硬编码颜色

**文件**: `views/system/SystemStatusView.vue`  
**问题**: `.page-title { color: #303133 }`, `.positive { color: #67c23a }`, `.negative { color: #f56c6c }`  
**修复方案**:
```scss
.page-title { color: var(--text-primary); }
.positive { color: var(--stock-down); }  // 保持"正=绿"惯例
.negative { color: var(--stock-up); }
```

### P1-2: DbAdminView 操作按钮列过宽(480px)

**文件**: `views/admin/DbAdminView.vue` L348  
**问题**: `<ElTableColumn label="操作" width="480" fixed="right">` 4个emoji按钮占480px，宽屏下挤压数据列  
**修复方案**: 改为`min-width="320"`或使用ElDropdown下拉菜单

### P1-3: DbAdminView JSON结果无语法高亮

**文件**: `views/admin/DbAdminView.vue`  
**问题**: `<pre class="result-json">{{ JSON.stringify(...) }}</pre>` 大结果不可读  
**修复方案**: 添加简易JSON高亮函数（无需新依赖）

### P1-4: SettingsView 暗色主题切换不生效

**文件**: `views/settings/SettingsView.vue`  
**问题**: `preferences.theme`只存userStore但未调用`themeStore.setTheme()`，保存设置后实际主题不变  
**修复方案**:
```typescript
import { useThemeStore } from '@/stores'
const themeStore = useThemeStore()
async function savePreferences() {
  if (preferences.theme) themeStore.setTheme(preferences.theme as any)
  // ...
}
```
同时添加"跟随系统"选项。

### P1-5: MarketMonitorView 涨跌色A股语义不一致

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: `.up { color: var(--stock-up) }` `.down { color: var(--stock-down) }` 是正确的A股红涨绿跌，但变量名up/down容易与"盈/亏"混淆  
**修复方案**: 添加语义化CSS类名别名，逐步替换：
```scss
.stock-up, .price-rise { color: var(--stock-up) !important; }
.stock-down, .price-fall { color: var(--stock-down) !important; }
.profit-positive { color: var(--stock-up) !important; }
.profit-negative { color: var(--stock-down) !important; }
```

### P1-6: BacktestHistoryPanel 涨跌色语义不统一

**文件**: `components/backtest/BacktestHistoryPanel.vue`  
**问题**: `strategyColors`中`limit_down_qiao: '#67c23a'`(绿)，而A股跌停=绿=跌。作为策略标识色可以保留，但与DataStatusPanel/MarketMonitorView中"绿=跌"语义冲突  
**修复方案**: 策略标识色使用功能色（warning/primary等）而非涨跌色，避免语义混淆：
```typescript
const strategyColors = {
  halfway_chase: 'var(--warning)',
  first_limit_up: 'var(--stock-up)',
  dragon_head: 'var(--primary-500)',
  limit_down_qiao: 'var(--stock-down)',
  limit_up_open: 'var(--text-tertiary)',
}
```

### P1-7: MarketMonitorView 3列布局窄屏崩坏

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: `grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr)` 在768px下3列挤在一起，内容不可读  
**修复方案**:
```scss
@media (max-width: 1024px) {
  .mm-body {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}
@media (max-width: 1280px) and (min-width: 1025px) {
  .mm-body {
    grid-template-columns: minmax(140px, 1fr) minmax(200px, 3fr) minmax(250px, 4fr);
  }
}
```

### P1-8: MarketMonitorView 持仓止损警示不足

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 止损价/止盈价只在小字中显示，接近止损时无明显警示（已有`.rd.danger`但效果不明显）  
**修复方案**: 距止损<1%时红色边框+脉冲动画

---

## 五、P2 改进建议（提升品质）

### P2-1: MarketMonitorView 786行单组件过于庞大

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 包含策略编辑、交易确认、复盘报告、9层调试、手动下单等多个子功能  
**修复方案**: 拆分为子组件（StrategyEditDialog/ManualTradeForm/DailyReportDialog/LayerDebugDialog等）

### P2-2: MarketMonitorView 信号列表无虚拟滚动

**文件**: `views/monitor/MarketMonitorView.vue`  
**问题**: 信号多时（100+）DOM节点过多  
**修复方案**: 引入vue-virtual-scroller或ElTable虚拟滚动

### P2-3: 路由页面标题重复

**文件**: `router/index.ts` + `MainLayout.vue` + 各View  
**问题**: MainLayout显示`route.meta.title`作为header标题，但SystemStatusView/DbAdminView内部又有`.page-title`，双重标题  
**修复方案**: 统一由MainLayout显示标题，各页面内部不再重复

### P2-4: 缺少空状态处理

**文件**: DataStatusPanel / FactorReferencePanel / StockDetailView  
**问题**: 部分组件数据加载失败无友好提示  
**修复方案**: 添加`ElEmpty`组件和错误重试按钮

### P2-5: 可访问性缺失

**文件**: 所有组件  
**问题**: 无ARIA标注、对比度不达标(#909399在#fff上3.3:1，需4.5:1)、无键盘导航  
**修复方案**: 添加ARIA标注，提高对比度，添加焦点状态

### P2-6: 构建chunk过大

**问题**: `npm run build`输出"Some chunks are larger than 500 kB"  
**修复方案**: 使用动态import()和manualChunks分割

### P2-7: BacktestResultPanel 涨跌色A股惯例

**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: 正收益用`var(--stock-down)`(绿)，负收益用`var(--stock-up)`(红)，与A股"红涨绿跌"惯例相反。当前用"绿=好"通用惯例  
**修复方案**: 这是一个设计决策——当前代码统一使用"绿=好"惯例（BacktestResultPanel/BacktestHistoryPanel/DataStatusPanel一致），与MarketMonitorView的"红=涨/绿=跌"不同。建议在结果面板中改用A股惯例：正收益=红(var(--stock-up))，负收益=绿(var(--stock-down))，与MarketMonitorView统一。

### P2-8: ECharts tooltip暗色模式

**文件**: `components/ultrashort/BacktestResultPanel.vue`  
**问题**: ECharts tooltip默认白色背景，暗色模式下刺眼。当前部分图表已使用var()但tooltip背景色未跟随  
**修复方案**: 在所有图表配置中添加tooltip背景色使用chart-tooltip变量

---

## 六、逐组件评价

### 1. MainLayout.vue ✅ 良好 (⭐⭐⭐⭐)
- 侧边栏收起/展开平滑动画
- 暗色/亮色切换有动画过渡
- 900px以下自动收起侧边栏
- 使用CSS变量，主题跟随正确
- **问题**: `.logo-text { color: white }` 硬编码

### 2. UltraShortBacktestViewV2.vue ✅ 良好 (⭐⭐⭐⭐)
- Tab切换设计清晰，自定义tab按钮风格统一
- 配置面板收起/展开按钮有阴影层次
- 运行中状态脉冲动画
- WebSocket→轮询降级策略完善
- 1000px以下自动切换为上下布局
- **问题**: 运行状态条已用var()（V47修复确认）

### 3. BacktestResultPanel.vue ✅ 良好 (⭐⭐⭐⭐)
- 全面使用CSS变量（39处硬编码已修复）
- 图表类型丰富(净值/回撤/日收益/仓位/雷达/因子贡献/月度收益/盈亏分布/持仓时长/策略柱状图)
- CSV导出功能完整
- 交易记录搜索/筛选/排序功能完整
- 卖出原因翻译表详尽(含V48新增利润锁定)
- **问题**: 1128行略长，涨跌色使用"绿=好"惯例

### 4. BacktestHistoryPanel.vue ⚠️ 需改进 (⭐⭐⭐)
- 卡片/表格双视图切换
- 对比功能(3条对比)
- 排序/筛选功能完善
- **问题**: 20处硬编码颜色(P0-2)，strategyColors硬编码(P1-6)

### 5. StrategyConfigPanel.vue ✅ 良好 (⭐⭐⭐⭐)
- 无硬编码颜色，使用CSS变量
- 677行略长，策略配置折叠项多时滚动体验一般

### 6. DataStatusPanel.vue ✅ 良好 (⭐⭐⭐⭐)
- 全面使用CSS变量（V47修复确认）
- 健康评分/数据源/策略可用性展示完善
- 同步进度实时展示

### 7. FactorReferencePanel.vue ⚠️ 需改进 (⭐⭐⭐)
- 因子分类展示清晰
- **问题**: 7处硬编码颜色(P0-3)，暗色模式失效

### 8. MarketMonitorView.vue ⚠️ 需改进 (⭐⭐⭐)
- V47暗色模式修复后大部分已用CSS变量
- 确认弹窗/信号过期倒计时/参数校验等交互良好
- **问题**: 策略标签颜色8处硬编码(P0-1)，3列布局窄屏崩坏(P1-7)，786行单组件(P2-1)

### 9. StockDetailView.vue ✅ 优秀 (⭐⭐⭐⭐½)
- 专业金融风格，全面使用CSS变量
- 骨架屏加载(shimmer动画)
- AI分析按钮品牌色渐变(唯一保留硬编码)
- 900px/640px响应式断点
- 价格区域涨跌色跟随主题

### 10. DbAdminView.vue ⚠️ 需改进 (⭐⭐⭐)
- 基本功能完整
- **问题**: 操作按钮列480px过宽(P1-2)，JSON无高亮(P1-3)，actions-grid中h4硬编码color:#303133

### 11. SystemStatusView.vue ⚠️ 需改进 (⭐⭐⭐)
- 基本功能完整
- **问题**: 3处硬编码颜色(P1-1)，双重标题(P2-3)

### 12. SettingsView.vue ⚠️ 需改进 (⭐⭐⭐)
- **问题**: 暗色主题切换不生效(P1-4)，缺少"跟随系统"选项，宽屏max-width:900px浪费空间

---

## 七、整体优化建议

### 建议1: 创建全局涨跌色工具函数

```typescript
// utils/stockColors.ts
export function getProfitColor(value: number): string {
  return value >= 0 ? 'var(--stock-up)' : 'var(--stock-down)'
}
export function getPerformanceColor(value: number): string {
  // "好=绿"惯例(BacktestHistoryPanel)
  if (value >= 30) return 'var(--stock-down)'
  if (value >= 10) return 'var(--stock-down)'
  if (value >= 0) return 'var(--stock-down-light)'
  if (value >= -10) return 'var(--stock-up-light)'
  return 'var(--stock-up)'
}
```

### 建议2: 统一涨跌色语义

当前两套惯例并存：
- **A股涨跌色**: MarketMonitorView — 红=涨，绿=跌
- **绩效好坏色**: BacktestResultPanel/HistoryPanel — 绿=好(盈利)，红=差(亏损)

建议：结果面板改用A股惯例（正收益=红），与实盘监控统一。

### 建议3: 响应式断点统一

| 组件 | 当前断点 | 建议 |
|------|----------|------|
| MainLayout | 900px | 900px |
| UltraShortBacktestViewV2 | 1000px | 1000px |
| MarketMonitorView | 无 | 1024px/1280px |
| StockDetailView | 900px/640px | 900px/640px |

### 建议4: MarketMonitorView组件拆分计划

| 新组件 | 行数(估) | 优先级 |
|--------|----------|--------|
| StrategyEditDialog.vue | ~120 | P2 |
| ManualTradeForm.vue | ~80 | P2 |
| DailyReportDialog.vue | ~80 | P2 |
| LayerDebugDialog.vue | ~80 | P3 |
| TradeConfirmDialog.vue | ~40 | P3 |
| ScanTraceDialog.vue | ~60 | P3 |

---

## 八、修复优先级汇总

| 级别 | 数量 | 预估工时 |
|------|------|----------|
| P0 | 3项 | 4小时 |
| P1 | 8项 | 8小时 |
| P2 | 8项 | 10小时 |
| **总计** | **19项** | **22小时** |

### P0修复顺序建议
1. P0-1: MarketMonitorView 策略标签颜色（影响暗色模式可用性）
2. P0-2: BacktestHistoryPanel 硬编码颜色（影响暗色模式核心指标）
3. P0-3: FactorReferencePanel 暗色模式（影响参考页面可用性）

---

*审查完毕。本报告仅做审查，未修改任何代码。*
