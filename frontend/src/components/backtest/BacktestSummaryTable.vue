<script setup lang="ts">
/**
 * BacktestSummaryTable - 回测结果精简概要卡片
 *
 * 定位：紧凑的核心指标一览，不与BacktestResultPanel重复
 * - 核心KPI指标（与ResultPanel KPI Strip对齐但更紧凑）
 * - 策略对比速览表
 * - 运行元信息（耗时/交易日/基准对比）
 *
 * 不包含：交易记录、TOP5、风险指标明细、图表（这些全在ResultPanel中）
 */
import { computed } from 'vue'
import { ElCard, ElDescriptions, ElDescriptionsItem, ElTable, ElTableColumn, ElTag } from 'element-plus'
import { STRATEGY_NAMES } from '@/config/backtestConstants'
// 【V66:UI增强】添加净值曲线缩略图
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{
  result: any
}>()

/** 核心绩效指标 */
const coreMetrics = computed(() => {
  const r: any = props.result
  if (!r) return []
  const risk = r.metrics?.risk || {}
  const ret = r.metrics?.returns || {}
  const nvsLen = r.net_value_series?.length || 0
  const items = [
    { label: '累计收益', value: fmtPct(r.total_return), color: colorSign(r.total_return) },
    { label: '年化收益', value: fmtPct(r.annualized_return), color: colorSign(r.annualized_return) },
    { label: '最大回撤', value: fmtPct(r.max_drawdown), color: '#f56c6c' },
    { label: '夏普比率', value: fmtNum(r.sharpe_ratio), color: r.sharpe_ratio >= 1 ? 'var(--stock-down)' : 'var(--warning)' },
    { label: '胜率', value: fmtPct(r.win_rate), color: r.win_rate >= 50 ? 'var(--stock-down)' : 'var(--stock-up)' },
    { label: '盈亏比', value: fmtNum(risk.profit_loss_ratio ?? r.profit_loss_ratio), color: (risk.profit_loss_ratio ?? r.profit_loss_ratio ?? 0) >= 2 ? 'var(--stock-down)' : 'var(--warning)' },
    { label: '交易笔数', value: String(r.total_trades ?? 0), color: 'var(--el-color-primary)' },
    { label: '信号数', value: String(r.total_signals ?? 0), color: 'var(--text-tertiary)' },
    { label: '索提诺', value: fmtNum(risk.sortino_ratio ?? r.sortino_ratio), color: (risk.sortino_ratio ?? r.sortino_ratio ?? 0) >= 2 ? 'var(--stock-down)' : 'var(--warning)' },
    { label: '卡玛', value: fmtNum(risk.calmar_ratio ?? r.calmar_ratio), color: (risk.calmar_ratio ?? r.calmar_ratio ?? 0) >= 1 ? 'var(--stock-down)' : 'var(--warning)' },
  ]
  if (ret.benchmark_return_pct != null) {
    items.push({ label: '基准收益', value: fmtPct(ret.benchmark_return_pct), color: colorSign(ret.benchmark_return_pct) })
  }
  if (ret.alpha_pct != null) {
    items.push({ label: '超额收益', value: fmtPct(ret.alpha_pct), color: colorSign(ret.alpha_pct) })
  }
  return items
})

/** 策略对比速览 */
const strategyData = computed(() => {
  const r = props.result
  if (!r?.strategy_results) return []
  return Object.entries(r.strategy_results).map(([key, s]: [string, any]) => ({
    key,
    strategy_name: s.strategy_name || STRATEGY_NAMES[key]?.replace(/^[\S]+\s/, '') || key,
    total_return: s.total_return,
    win_rate: s.win_rate,
    trades_count: s.trades_count,
    max_drawdown: s.max_drawdown,
  }))
})

/** 运行元信息 */
const metaInfo = computed(() => {
  const r: any = props.result
  if (!r) return null
  const nvsLen = r.net_value_series?.length || 0
  return {
    execution_time: r.execution_time_ms ? `${(r.execution_time_ms / 1000).toFixed(1)}秒` : '-',
    trading_days: nvsLen,
    initial_cash: r.initial_cash ? `¥${(r.initial_cash / 10000).toFixed(0)}万` : '-',
    final_value: r.final_value ? `¥${(r.final_value / 10000).toFixed(2)}万` : '-',
  }
})

/** 【V66:UI增强】净值+回撤缩略图 */
const netValueMiniOption = computed(() => {
  const r = props.result
  if (!r?.net_value_series || r.net_value_series.length === 0) return null
  const nvs = r.net_value_series.filter((d: any) => d.net_value != null && !isNaN(d.net_value))
  if (nvs.length < 2) return null
  const dates = nvs.map((d: any) => String(d.trade_date).slice(4)) // MM/DD
  const values = nvs.map((d: any) => +(d.net_value).toFixed(4))
  // drawdown
  const ddSeries = r.drawdown_series || []
  const ddMap = new Map(ddSeries.map((d: any) => [String(d.trade_date || d.date), d.drawdown ?? 0]))
  const drawdowns = nvs.map((d: any) => {
    const dd = ddMap.get(String(d.trade_date)) ?? 0
    return +(dd > 1 ? dd : dd * 100).toFixed(4)
  })
  return {
    tooltip: { trigger: 'axis', textStyle: { fontSize: 11 }, formatter: (p: any) => {
      let html = `${p[0].axisValue}<br/>`
      for (const s of p) {
        html += `${s.marker} ${s.seriesName}: ${s.value}${s.seriesName.includes('回撤') ? '%' : ''}<br/>`
      }
      return html
    }},
    grid: { left: 40, right: 40, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 9, color: 'var(--text-muted)', interval: Math.floor(dates.length / 5) }, axisLine: { lineStyle: { color: 'var(--border-default)' } } },
    yAxis: [
      { type: 'value', name: '净值', axisLabel: { fontSize: 9, color: 'var(--text-muted)' }, splitLine: { lineStyle: { color: 'var(--border-light)' } }, nameTextStyle: { fontSize: 9, color: 'var(--text-muted)' } },
      { type: 'value', name: '回撤%', position: 'right', axisLabel: { fontSize: 9, color: 'var(--text-muted)' }, splitLine: { show: false }, nameTextStyle: { fontSize: 9, color: 'var(--text-muted)' } },
    ],
    series: [
      { name: '净值', type: 'line', data: values, smooth: true, lineStyle: { width: 2, color: 'var(--el-color-primary)' }, itemStyle: { color: 'var(--el-color-primary)' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'var(--info-bg)' }, { offset: 1, color: 'transparent' }] } }, showSymbol: false },
      { name: '回撤(%)', type: 'line', yAxisIndex: 1, data: drawdowns, lineStyle: { width: 1, type: 'dashed', color: 'var(--stock-up)' }, itemStyle: { color: 'var(--stock-up)' }, areaStyle: { color: 'var(--stock-up-bg)' }, showSymbol: false },
    ],
  }
})

function fmtPct(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(2) + '%'
}

function fmtNum(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(2)
}

function colorSign(val: number | null | undefined): string {
  if (val == null) return 'var(--text-muted)'
  return val >= 0 ? 'var(--stock-down)' : 'var(--stock-up)'
}
</script>

<template>
  <div class="backtest-summary-compact" v-if="result">
    <!-- 【V66:UI增强】净值+回撤缩略图 -->
    <ElCard v-if="netValueMiniOption" shadow="hover" class="summary-card" style="margin-bottom: 12px">
      <template #header><span>📈 净值曲线 & 回撤</span></template>
      <VChart :option="netValueMiniOption" autoresize style="height: 240px; width: 100%" />
    </ElCard>

    <!-- 核心指标 Descriptions -->
    <ElCard shadow="hover" class="summary-card">
      <template #header>
        <div class="card-header">
          <span>📊 回测概要</span>
          <div v-if="metaInfo" class="meta-tags">
            <ElTag size="small" type="info">⏱ {{ metaInfo.execution_time }}</ElTag>
            <ElTag size="small" type="info">📅 {{ metaInfo.trading_days }}交易日</ElTag>
            <ElTag size="small">{{ metaInfo.initial_cash }} → {{ metaInfo.final_value }}</ElTag>
          </div>
        </div>
      </template>
      <ElDescriptions :column="4" border size="small">
        <ElDescriptionsItem
          v-for="m in coreMetrics"
          :key="m.label"
          :label="m.label"
        >
          <span :style="{ color: m.color, fontWeight: 600 }">{{ m.value }}</span>
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <!-- 策略对比速览 -->
    <ElCard v-if="strategyData.length > 1" shadow="hover" class="summary-card" style="margin-top: 12px">
      <template #header><span>🎯 策略对比速览</span></template>
      <ElTable :data="strategyData" size="small" border stripe>
        <ElTableColumn prop="strategy_name" label="策略" min-width="100" />
        <ElTableColumn label="累计盈利" min-width="90">
          <template #default="{ row }">
            <span :style="{ color: colorSign(row.total_return), fontWeight: 600 }">{{ fmtPct(row.total_return) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="胜率" min-width="80">
          <template #default="{ row }">
            <span :style="{ color: row.win_rate >= 50 ? 'var(--stock-down)' : 'var(--stock-up)' }">{{ fmtPct(row.win_rate) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="trades_count" label="交易" width="70" align="center" />
        <ElTableColumn label="最大回撤" min-width="90">
          <template #default="{ row }">
            <span style="color: var(--stock-up)">{{ fmtPct(row.max_drawdown) }}</span>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- 不足1年回测提示 -->
    <div v-if="(result?.net_value_series?.length || 0) < 250" class="disclaimer">
      ⚠️ 回测期不足1年，年化收益/卡玛比率等指标仅供参考，存在放大效应
    </div>
  </div>
</template>

<style scoped lang="scss">
.backtest-summary-compact {
  margin-bottom: 12px;
}
.summary-card {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 15px;
    flex-wrap: wrap;
    gap: 8px;
    min-width: 0;
    .meta-tags {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
  }
}
.disclaimer {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--warning-bg);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  font-size: 12px;
  color: var(--warning);
}
</style>
