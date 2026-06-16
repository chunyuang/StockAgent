# 日期选择统一方案 — 市场监听7个Tab

## 现状问题

| Tab | 日期选择器 | 默认数据 | 历史支持 | 问题 |
|-----|-----------|---------|---------|------|
| **AccountTab** | ✅ ElDatePicker (单日) | 当日 | ✅ 有 | 日期选了但只影响持仓，KPI总是30天 |
| **AnalysisTab** | ✅ ElDatePicker (范围) | 近7天 | ✅ 有 | 用的是范围不是单日，和其他Tab不一致 |
| **ReviewTab** | ✅ ElDatePicker (单日) | 当日 | ✅ 有 | 月复盘要求有整月数据才显示 |
| **OpsTab** | ✅ 两个DatePicker | 当日 | ⚠️ 部分 | 有opsDate和historyDate两个，混乱 |
| **SentimentTab** | ✅ ElDatePicker (单日) | 当日 | ✅ 有 | 日内/日线模式切换，但日期含义不清 |
| **ScanTraceTab** | ✅ ElDatePicker (单日) | 最近有数据的日期 | ✅ 有 | 默认不是今天，而是最近有数据的日 |
| **PremarketTab** | ✅ ElDatePicker (单日) | 当日 | ✅ 有 | 历史回放标注清晰 |

### 核心问题
1. **格式不统一**：AccountTab用`YYYY-MM-DD`，其他用各种格式
2. **默认行为不一致**：有的默认今天，有的默认近7天，有的默认最近有数据
3. **交易日染色不一致**：只有ScanTraceTab和ReviewTab有，其他没有
4. **日期变更后数据刷新逻辑不同**：有的自动刷新，有的需手动点
5. **OpsTab有两个日期选择器**（opsDate + historyDate），功能重叠

## 设计方案

### 统一组件: `UnifiedDateBar.vue`

```
┌──────────────────────────────────────────────────┐
│  📅 [◀ 前一天] [2026-06-16 ▼] [后一天 ▶] [今天] │
│       12  13  14  15  16  17  18  19  20          │
│       ·   ●   ●   ·   ●   ●   ·   ·   ●          │
│       周一 周二 周三 周四 周五 周六 周日 ...       │
└──────────────────────────────────────────────────┘
```

**功能**：
1. **单日选择** (所有Tab统一为单日，AnalysisTab的7天范围改为KPI聚合逻辑)
2. **前/后一天导航** (快捷按钮)
3. **今天按钮** (一键回到今天)
4. **交易日染色** (调 `/unified/date-availability`，绿=有交易，灰=无数据，蓝=今天)
5. **周末置灰** (不可选)
6. **日期变更 → 自动刷新当前Tab数据**

### 每个Tab的行为规范

| Tab | 统一后默认 | 日期变更刷新 | API调用 |
|-----|-----------|-------------|---------|
| **AccountTab** | 今天 | `/analysis?start_date=D&end_date=D` + `/unified/positions?date=D` | KPI按选中日，持仓按选中日 |
| **AnalysisTab** | 今天 | `/analysis?start_date=D&end_date=D` + `/unified/trades?date=D` | KPI+持仓+每日明细都按选中日 |
| **ReviewTab** | 今天 | `/historical-review?date=D` | 复盘数据按选中日 |
| **OpsTab** | 今天 | `/timeline/history?days=1&date=D` + `/unified/trades?date=D` | 时间线+交易按选中日，**删除historyDate** |
| **SentimentTab** | 今天 | `/market-sentiment?date=D` | 情绪按选中日 |
| **ScanTraceTab** | 今天(无数据则最近有数据的) | `/scan-traces?date=D` | 扫描记录按选中日 |
| **PremarketTab** | 今天 | `/premarket-status?date=D` | 盘前数据按选中日 |

### 关键设计决策

1. **所有Tab用单日选择**：AnalysisTab原来是7天范围，改为选单日。KPI默认显示选中日的数据，"近期趋势"部分可以在组件内做7天聚合，不需要用户选范围。

2. **默认都是今天**：ScanTraceTab现在默认最近有数据日，改为默认今天。如果今天无数据，显示"今天无扫描记录"空状态，用户可导航到有数据的日期。

3. **交易日染色统一**：所有Tab共用`/unified/date-availability`返回的数据染色。不需要每个Tab各自查。

4. **日期变更自动刷新**：不需要用户点"刷新"按钮，日期变更时自动fetch。

5. **OpsTab删除historyDate**：只保留一个日期选择器，历史回放和当日操作共用。

## 实现步骤

### Phase 1: 后端 — 统一日期参数

1. `/analysis` 增加 `date` 单日参数 (现在只有 start_date/end_date)
2. `/daily-report` 增加 `date` 参数
3. `/timeline/history` 增加 `date` 精确日参数 (现在是 days 相对)
4. `/market-sentiment` 已有 date 参数 ✅
5. `/scan-traces` 已有 date 参数 ✅
6. `/premarket-status` 已有 date 参数 ✅

### Phase 2: 前端 — UnifiedDateBar组件

1. 创建 `src/views/monitor/composables/useUnifiedDateBar.ts`
   - date ref, 前后导航, 今天按钮
   - dateAvailability 数据 (调 /unified/date-availability)
   - cellClassFn (给ElDatePicker染色)

2. 创建 `src/views/monitor/components/UnifiedDateBar.vue`
   - 日期选择器 + 导航按钮 + 交易日染色
   - emit('change', date) 触发刷新

### Phase 3: 前端 — 7个Tab接入

1. AccountTab: 替换现有ElDatePicker为UnifiedDateBar
2. AnalysisTab: 替换范围选择为单日
3. ReviewTab: 替换现有ElDatePicker
4. OpsTab: 删除historyDate, 合并为单日
5. SentimentTab: 替换现有ElDatePicker
6. ScanTraceTab: 替换现有ElDatePicker, 改默认今天
7. PremarketTab: 替换现有ElDatePicker

### 工作量估算

- Phase 1 (后端): ~1h — 3个API加date参数
- Phase 2 (UnifiedDateBar): ~1h — 组件+composable
- Phase 3 (7个Tab接入): ~2h — 每个Tab ~15min
- **总计: ~4h**
