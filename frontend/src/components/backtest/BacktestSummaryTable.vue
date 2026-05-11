<script setup lang="ts">
/**
 * BacktestSummaryTable - 回测结果展示总结表格
 *
 * 展示回测完成后的核心绩效指标、风险指标、交易统计、策略对比等，
 * 提供结构化的数据展示而非散落的图表。
 *
 * 设计原则：
 * - 信息密度高，一眼看清回测质量
 * - 关键指标颜色编码（红/绿/灰）
 * - 策略级对比表格
 * - 交易记录可筛选/排序
 * - CSV 导出
 */
import { ref, computed } from 'vue'
import {
  ElCard,
  ElTable,
  ElTableColumn,
  ElTooltip,
  ElEmpty,
  ElButton,
  ElInput,
  ElSelect,
  ElOption,
  ElDescriptions,
  ElDescriptionsItem,
  ElRow,
  ElCol,
} from 'element-plus'
import { Download } from '@element-plus/icons-vue'

const props = defineProps<{
  /** 回测结果对象（与 backtestResult 完全对应） */
  result: any
}>()

// ==================== 核心指标计算 ====================

/** 关键绩效指标（顶部摘要卡片） */
const kpiMetrics = computed(() => {
  const r: any = props.result
  if (!r) return []

  // 去重：performance 对象和根层级可能重复包含同一指标，优先取根层级值
  // 同时收集所有已显示的指标 key，防止重复
  const seen = new Set<string>()
  const metrics: Array<{label: string; value: string; raw: number; color: string; icon: string; desc: string}> = []

  const addMetric = (label: string, value: string, raw: number, color: string, icon: string, desc: string, key: string) => {
    if (!seen.has(key)) {
      seen.add(key)
      metrics.push({ label, value, raw, color, icon, desc })
    }
  }

  // 后端数据: 顶层有 total_return/annualized_return/max_drawdown/win_rate/sharpe_ratio
  // metrics.risk 有 volatility_pct/calmar_ratio/sortino_ratio/profit_loss_ratio
  // metrics.returns 有 annual_return_pct/benchmark_return_pct/alpha_pct
  const risk = r.metrics?.risk || {}
  const ret = r.metrics?.returns || {}

  addMetric('总收益率', fmtPct(r.total_return), r.total_return, colorBySign(r.total_return), '📈', '回测期间策略的总收益', 'total_return')
  addMetric('年化收益率', fmtPct(r.annualized_return ?? ret.annual_return_pct), r.annualized_return ?? ret.annual_return_pct, colorBySign(r.annualized_return ?? ret.annual_return_pct), '📊', '折算为年度的收益率', 'annual_return')
  addMetric('最大回撤', fmtPct(r.max_drawdown, true), r.max_drawdown, '#f56c6c', '📉', '净值从最高点到最低点的最大跌幅', 'max_drawdown')
  addMetric('夏普比率', fmtNum(r.sharpe_ratio), r.sharpe_ratio, r.sharpe_ratio >= 1 ? '#67c23a' : r.sharpe_ratio >= 0 ? '#e6a23c' : '#f56c6c', '⚖️', '单位风险获得的超额收益', 'sharpe_ratio')
  addMetric('胜率', fmtPct(r.win_rate), r.win_rate, r.win_rate >= 50 ? '#67c23a' : '#f56c6c', '🎯', '盈利交易占总交易的比例', 'win_rate')
  addMetric('盈亏比', fmtNum(risk.profit_loss_ratio ?? r.profit_loss_ratio), risk.profit_loss_ratio ?? r.profit_loss_ratio, (risk.profit_loss_ratio ?? r.profit_loss_ratio) >= 1.5 ? '#67c23a' : (risk.profit_loss_ratio ?? r.profit_loss_ratio) >= 1 ? '#e6a23c' : '#f56c6c', '💰', '平均盈利与平均亏损之比', 'profit_loss_ratio')
  addMetric('卡玛比率', fmtNum(risk.calmar_ratio ?? r.calmar_ratio), risk.calmar_ratio ?? r.calmar_ratio, (risk.calmar_ratio ?? r.calmar_ratio) >= 1 ? '#67c23a' : (risk.calmar_ratio ?? r.calmar_ratio) >= 0 ? '#e6a23c' : '#f56c6c', '🔥', '年化收益 / 最大回撤', 'calmar_ratio')
  addMetric('索提诺比率', fmtNum(risk.sortino_ratio ?? r.sortino_ratio), risk.sortino_ratio ?? r.sortino_ratio, (risk.sortino_ratio ?? r.sortino_ratio) >= 1 ? '#67c23a' : (risk.sortino_ratio ?? r.sortino_ratio) >= 0 ? '#e6a23c' : '#f56c6c', '🛡️', '只考虑下行风险的夏普比率', 'sortino_ratio')

  // 补充: 波动率/信息比率/基准收益/Alpha(从metrics取)
  if (risk.volatility_pct != null) {
    addMetric('波动率', fmtPct(risk.volatility_pct), risk.volatility_pct, '#909399', '〰️', '收益率的标准差', 'volatility')
  }
  if (ret.benchmark_return_pct != null) {
    addMetric('基准收益', fmtPct(ret.benchmark_return_pct), ret.benchmark_return_pct, colorBySign(ret.benchmark_return_pct), '📏', '沪深300同期收益', 'benchmark_return')
  }
  if (ret.alpha_pct != null) {
    addMetric('Alpha', fmtPct(ret.alpha_pct), ret.alpha_pct, colorBySign(ret.alpha_pct), 'α', '超额收益(组合-基准)', 'alpha')
  }

  return metrics
})

/** 风险指标明细 */
const riskMetrics = computed(() => {
  const r: any = props.result
  if (!r) return []

  const risk = r.metrics?.risk || {}
  const ret = r.metrics?.returns || {}
  return [
    { name: '波动率', value: fmtPct(risk.volatility_pct), desc: '收益率的标准差，衡量风险水平' },
    { name: '信息比率', value: fmtNum(risk.information_ratio), desc: '超额收益与跟踪误差的比值' },
    { name: '最大回撤', value: fmtPct(risk.max_drawdown_pct ?? r.max_drawdown, true), desc: '净值从最高点到最低点的最大跌幅' },
    { name: '夏普比率', value: fmtNum(risk.sharpe_ratio ?? r.sharpe_ratio), desc: '单位风险获得的超额收益' },
    { name: '索提诺比率', value: fmtNum(risk.sortino_ratio ?? r.sortino_ratio), desc: '只考虑下行风险的夏普比率' },
    { name: '卡玛比率', value: fmtNum(risk.calmar_ratio ?? r.calmar_ratio), desc: '年化收益/最大回撤' },
    { name: '基准收益', value: fmtPct(ret.benchmark_return_pct), desc: '沪深300同期收益' },
    { name: 'Alpha', value: fmtPct(ret.alpha_pct), desc: '超额收益(组合-基准)' },
  ]
})

/** 策略对比数据 */
const strategyCompareData = computed(() => {
  const r = props.result
  if (!r?.strategy_results) return []

  return Object.entries(r.strategy_results).map(([key, s]: [string, any]) => ({
    strategy_id: key as string,
    strategy_name: s.strategy_name || key,
    total_return: s.total_return,
    total_pnl_pct: s.total_pnl_pct,
    win_rate: s.win_rate,
    trades_count: s.trades_count,
    total_trades: s.total_trades,
    avg_hold_days: s.avg_hold_days,
  }))
})

/** 交易记录 */
const trades = computed(() => props.result?.merged_trades || props.result?.trades || [])

// 筛选
const searchKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')

const filteredTrades = computed(() => {
  let t = trades.value
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    t = t.filter((tr: any) =>
      tr.ts_code?.toLowerCase().includes(kw) ||
      tr.stock_name?.toLowerCase().includes(kw)
    )
  }
  if (filterStrategy.value) {
    t = t.filter((tr: any) => tr.strategy === filterStrategy.value)
  }
  if (filterProfit.value === 'profit') {
    t = t.filter((tr: any) => tr.profit_pct >= 0)
  } else if (filterProfit.value === 'loss') {
    t = t.filter((tr: any) => tr.profit_pct < 0)
  }
  return t
})

/** 策略名列表（用于筛选下拉） */
const strategyNames = computed(() => {
  const names = new Set(trades.value.map((t: any) => t.strategy).filter(Boolean))
  return [...names]
})

/** 盈利 TOP5 / 亏损 TOP5 */
const profitTop5 = computed(() => {
  return [...trades.value]
    .filter((t: any) => t.profit_pct > 0)
    .sort((a: any, b: any) => b.profit_pct - a.profit_pct)
    .slice(0, 5)
})

const lossTop5 = computed(() => {
  return [...trades.value]
    .filter((t: any) => t.profit_pct < 0)
    .sort((a: any, b: any) => a.profit_pct - b.profit_pct)
    .slice(0, 5)
})

// ==================== 格式化辅助 ====================

// 后端返回的百分比字段已经是百分比数值(如50.0=50%)，不需要再×100
function fmtPct(val: number, _alwaysNeg = false): string {
  if (val == null || isNaN(val)) return '--'
  const pct = val.toFixed(2)
  return `${pct}%`
}

function fmtNum(val: number): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(4)
}

function colorBySign(val: number): string {
  if (val > 0) return '#67c23a'
  if (val < 0) return '#f56c6c'
  return '#909399'
}

function profitCellStyle({ row }: { row: any }) {
  if (row.profit_pct > 0) return { color: '#67c23a', fontWeight: '600' }
  if (row.profit_pct < 0) return { color: '#f56c6c', fontWeight: '600' }
  return {}
}

// ==================== 导出 ====================

const handleExport = () => {
  if (!trades.value.length) return

  const headers = ['交易日期', '股票代码', '股票名称', '策略', '买入价', '卖出价', '收益率', '持仓天数']
  const rows = filteredTrades.value.map((t: any) => [
    t.buy_date || t.date, t.ts_code, t.name || t.stock_name, t.strategy, t.buy_price, t.sell_price,
    `${(t.profit_pct || 0).toFixed(2)}%`, t.hold_days,
  ])
  const csvContent = [headers.join(','), ...rows.map((r: any) => r.join(','))].join('\n')
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `回测交易记录_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
}
</script>

<template>
  <div class="backtest-summary" v-if="result">
    <!-- ========== 顶部 KPI 卡片 ========== -->
    <ElCard class="summary-section kpi-section" shadow="hover">
      <template #header>
        <div class="section-header">
          <span>📊 核心绩效指标</span>
        </div>
      </template>
      <div class="kpi-grid">
        <div
          v-for="metric in kpiMetrics"
          :key="metric.label"
          class="kpi-card"
        >
          <ElTooltip :content="metric.desc" placement="top">
            <div class="kpi-inner">
              <div class="kpi-icon">{{ metric.icon }}</div>
              <div class="kpi-content">
                <div class="kpi-label">{{ metric.label }}</div>
                <div class="kpi-value" :style="{ color: metric.color }">
                  {{ metric.value }}
                </div>
              </div>
            </div>
          </ElTooltip>
        </div>
      </div>
    </ElCard>

    <!-- ========== 风险指标 ========== -->
    <ElCard class="summary-section" shadow="hover">
      <template #header>
        <span>⚠️ 风险指标</span>
      </template>
      <ElDescriptions :column="3" border size="small">
        <ElDescriptionsItem
          v-for="m in riskMetrics"
          :key="m.name"
          :label="m.name"
        >
          <ElTooltip :content="m.desc" placement="top">
            <span>{{ m.value }}</span>
          </ElTooltip>
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <!-- ========== 策略对比表格 ========== -->
    <ElCard v-if="strategyCompareData.length" class="summary-section" shadow="hover">
      <template #header>
        <span>🎯 策略对比</span>
      </template>
      <ElTable :data="strategyCompareData" border size="small" stripe>
        <ElTableColumn prop="strategy_name" label="策略" min-width="120" fixed />
        <ElTableColumn label="平均收益率" min-width="110" sortable>
          <template #default="{ row }">
            <span :style="{ color: colorBySign(row.total_return), fontWeight: 600 }">
              {{ fmtPct(row.total_return) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="胜率" min-width="90" sortable>
          <template #default="{ row }">
            <span :style="{ color: row.win_rate >= 50 ? '#67c23a' : '#f56c6c' }">
              {{ fmtPct(row.win_rate) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="trades_count" label="交易次数" min-width="90" sortable />
        <ElTableColumn label="累计盈亏" min-width="100" sortable>
          <template #default="{ row }">
            <span :style="{ color: colorBySign(row.total_pnl_pct) }">
              {{ fmtPct(row.total_pnl_pct) }}
            </span>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- ========== 盈亏 TOP5 ========== -->
    <ElRow v-if="profitTop5.length || lossTop5.length" :gutter="16" class="summary-section">
      <ElCol :span="12">
        <ElCard shadow="hover">
          <template #header><span>🏆 盈利 TOP5</span></template>
          <ElTable :data="profitTop5" size="small" stripe>
            <ElTableColumn prop="ts_code" label="代码" width="100" />
            <ElTableColumn label="名称" width="80">
              <template #default="{ row }">{{ row.name || row.stock_name || '--' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" width="90" />
            <ElTableColumn label="收益率" width="90">
              <template #default="{ row }">
                <span style="color: #67c23a; font-weight: 600">
                  {{ row.profit_pct != null ? row.profit_pct.toFixed(2) + '%' : '--' }}
                </span>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElCard>
      </ElCol>
      <ElCol :span="12">
        <ElCard shadow="hover">
          <template #header><span>💥 亏损 TOP5</span></template>
          <ElTable :data="lossTop5" size="small" stripe>
            <ElTableColumn prop="ts_code" label="代码" width="100" />
            <ElTableColumn label="名称" width="80">
              <template #default="{ row }">{{ row.name || row.stock_name || '--' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" width="90" />
            <ElTableColumn label="收益率" width="90">
              <template #default="{ row }">
                <span style="color: #f56c6c; font-weight: 600">
                  {{ row.profit_pct != null ? row.profit_pct.toFixed(2) + '%' : '--' }}
                </span>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- ========== 交易记录 ========== -->
    <ElCard class="summary-section" shadow="hover">
      <template #header>
        <div class="section-header">
          <span>📋 交易记录 ({{ filteredTrades.length }} / {{ trades.length }})</span>
          <ElButton
            type="primary"
            :icon="Download"
            size="small"
            @click="handleExport"
            :disabled="!trades.length"
          >
            导出CSV
          </ElButton>
        </div>
      </template>

      <!-- 筛选栏 -->
      <div class="trade-filters">
        <ElInput
          v-model="searchKeyword"
          placeholder="🔍 搜索股票代码/名称"
          clearable
          size="small"
          style="width: 220px"
        />
        <ElSelect v-model="filterStrategy" placeholder="策略筛选" clearable size="small" style="width: 150px">
          <ElOption
            v-for="(name, idx) in strategyNames"
            :key="idx"
            :label="String(name)"
            :value="String(name)"
          />
        </ElSelect>
        <ElSelect v-model="filterProfit" placeholder="盈亏筛选" clearable size="small" style="width: 120px">
          <ElOption label="盈利" value="profit" />
          <ElOption label="亏损" value="loss" />
        </ElSelect>
      </div>

      <ElTable
        :data="filteredTrades"
        border
        size="small"
        stripe
        max-height="500"
        :cell-style="profitCellStyle"
        :default-sort="{ prop: 'date', order: 'descending' }"
      >
        <ElTableColumn label="买入日" width="100" sortable :sort-method="(a: any, b: any) => (a.buy_date || a.date || '').localeCompare(b.buy_date || b.date || '')">
          <template #default="{ row }">{{ row.buy_date || row.date }}</template>
        </ElTableColumn>
        <ElTableColumn label="卖出日" width="100">
          <template #default="{ row }">{{ row.sell_date || '--' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="ts_code" label="代码" width="100" />
        <ElTableColumn label="名称" width="80">
          <template #default="{ row }">{{ row.name || row.stock_name || '--' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="strategy" label="策略" width="90" />
        <ElTableColumn prop="buy_price" label="买入价" width="90" align="right">
          <template #default="{ row }">
            {{ row.buy_price?.toFixed(2) || '--' }}
          </template>
        </ElTableColumn>
        <ElTableColumn prop="sell_price" label="卖出价" width="90" align="right">
          <template #default="{ row }">
            {{ row.sell_price?.toFixed(2) || '--' }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="收益率" width="100" sortable :sort-method="(a: any, b: any) => a.profit_pct - b.profit_pct">
          <template #default="{ row }">
            {{ row.profit_pct != null ? row.profit_pct.toFixed(2) + '%' : '--' }}
          </template>
        </ElTableColumn>
        <ElTableColumn prop="hold_days" label="持仓天数" width="90" align="center" sortable />
      </ElTable>

      <ElEmpty v-if="!trades.length" description="暂无交易记录" />
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.backtest-summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-section {
  width: 100%;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 15px;
}

/* KPI 网格 */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;

  @media (max-width: 1200px) {
    grid-template-columns: repeat(2, 1fr);
  }
}

.kpi-card {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 14px 16px;
  transition: box-shadow 0.2s;

  &:hover {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  }
}

.kpi-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: help;
}

.kpi-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.kpi-content {
  min-width: 0;
}

.kpi-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.kpi-value {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

/* 交易筛选 */
.trade-filters {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
</style>
