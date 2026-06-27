<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent, MarkLineComponent, VisualMapComponent } from 'echarts/components'
import { useChartColors } from './useChartColors'

use([CanvasRenderer, PieChart, LineChart, BarChart, HeatmapChart, TooltipComponent, LegendComponent, GridComponent, MarkLineComponent, VisualMapComponent])

import { useUnifiedData } from './composables/useUnifiedData'

const c = useChartColors().value
const loading = ref(false)
const kpiData = ref<any>(null)
const unified = useUnifiedData()

const fetchKpi = async () => {
  loading.value = true
  try {
    const res = await fetch('/api/v1/scanner/analysis').then(r => r.json())
    kpiData.value = res.data || {}
  } catch (e) { console.error(e) }
  loading.value = false
}

onMounted(fetchKpi)
watch(() => unified.currentDate.value, () => { fetchKpi() })

const kpi = computed(() => kpiData.value?.kpi || {})
const dd = computed(() => kpiData.value?.daily_detail || [])
const monthly = computed(() => kpiData.value?.monthly || [])
const stratContrib = computed(() => kpiData.value?.strategy_contrib || [])
const sellReasons = computed(() => kpiData.value?.sell_reasons || [])

// ===== 格式化 =====
const fmtPnl = (v: number) => {
  if (v == null || isNaN(v)) return '¥0'
  const abs = Math.abs(v), sign = v >= 0 ? '+' : '-'
  if (abs >= 10000) return sign + '¥' + (abs / 10000).toFixed(2) + '万'
  return sign + '¥' + abs.toLocaleString()
}
const fmtPct = (v: number) => {
  if (v == null || isNaN(v)) return '-'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}
const cls = (v: number) => v >= 0 ? 'up' : 'down'

// ===== 1. 月度收益热力图 =====
const monthlyChart = computed(() => {
  const m = monthly.value
  if (!m.length) return null
  // Build year-month grid
  const years = [...new Set(m.map((d: any) => d.month.slice(0, 4)))]
  const data = m.map((d: any) => {
    const y = years.indexOf(d.month.slice(0, 4))
    const mon = parseInt(d.month.slice(5)) - 1
    return [mon, y, d.profit || 0]
  })
  const maxVal = Math.max(...data.map((d: any) => Math.abs(d[2])), 1)
  return {
    tooltip: {
      backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => {
        const d = p.data; if (!d) return ''
        const mItem = m.find((x: any) => parseInt(x.month.slice(5)) - 1 === d[0] && x.month.slice(0, 4) === years[d[1]])
        return `<b>${mItem?.month || ''}</b><br/>盈亏 <b style="color:${d[2]>=0?'#f56c6c':'#409eff'}">${fmtPnl(d[2])}</b><br/>交易${mItem?.trades||0}笔 · 胜率${mItem?.win_rate!=null?mItem.win_rate+'%':'-'}`
      }
    },
    grid: { left: 40, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category', data: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'], axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'category', data: years, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    visualMap: { min: -maxVal, max: maxVal, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, show: false, inRange: { color: ['#409eff', '#1a1a2e', '#f56c6c'] } },
    series: [{ type: 'heatmap', data, label: { show: true, fontSize: 10, formatter: (p: any) => { const v = p.data[2]; return v === 0 ? '-' : (v >= 0 ? '+' : '') + (Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + '万' : String(Math.round(v))) }, color: '#ccc' }, itemStyle: { borderWidth: 2, borderColor: '#1a1a2e' } }]
  }
})

// ===== 2. 策略贡献图 =====
const stratChart = computed(() => {
  const s = stratContrib.value
  if (!s.length) return null
  const sorted = [...s].sort((a: any, b: any) => (b.profit || 0) - (a.profit || 0))
  return {
    tooltip: {
      backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => `<b>${p.name}</b><br/>盈亏 <b style="color:${(p.value||0)>=0?'#f56c6c':'#409eff'}">${fmtPnl(p.value||0)}</b><br/>交易${p.data?.trades||0}笔 · 胜率${p.data?.win_rate!=null?p.data.win_rate+'%':'-'} · 均盈${p.data?.avg_profit_pct!=null?fmtPct(p.data.avg_profit_pct):'-'}`
    },
    grid: { left: 80, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'value', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => Math.abs(v) >= 10000 ? (v / 10000).toFixed(1) + '万' : String(v) }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } } },
    yAxis: { type: 'category', data: sorted.map((d: any) => d.strategy), axisLabel: { fontSize: 11, color: '#ccc' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    series: [{ type: 'bar', data: sorted.map((d: any) => ({ value: d.profit || 0, trades: d.trades, win_rate: d.win_rate, avg_profit_pct: d.avg_profit_pct })), itemStyle: { color: (p: any) => (p.value || 0) >= 0 ? 'rgba(245,108,108,0.7)' : 'rgba(64,158,255,0.6)', borderRadius: [0, 3, 3, 0] }, barMaxWidth: 28, label: { show: true, position: (p: any) => (p.value || 0) >= 0 ? 'right' : 'left', fontSize: 10, color: '#ccc', formatter: (p: any) => fmtPnl(p.value || 0) } }]
  }
})

// ===== 3. 卖出归因图 =====
const reasonChart = computed(() => {
  const r = sellReasons.value
  if (!r.length) return null
  const sorted = [...r].sort((a: any, b: any) => (b.profit || 0) - (a.profit || 0))
  const colors = ['#f56c6c', '#e6a23c', '#409eff', '#909399', '#67c23a', '#a855f7']
  return {
    tooltip: {
      backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => `<b>${p.name}</b><br/>盈亏 <b style="color:${colors[p.dataIndex%colors.length]}">${fmtPnl(p.value||0)}</b><br/>触发${p.data?.count||0}次`
    },
    legend: { bottom: 0, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 10, itemHeight: 8 },
    series: [{
      type: 'pie', radius: ['30%', '60%'], center: ['50%', '42%'],
      label: { formatter: (p: any) => `${p.name}\n${fmtPnl(p.value||0)}`, fontSize: 10, color: '#ccc', lineHeight: 14 },
      labelLine: { lineStyle: { color: '#555' } },
      itemStyle: { borderColor: '#1a1a2e', borderWidth: 2 },
      emphasis: { label: { fontSize: 12, fontWeight: 'bold' } },
      data: sorted.map((d: any, i: number) => ({ value: d.profit || 0, name: d.reason, count: d.count, itemStyle: { color: colors[i % colors.length] } }))
    }]
  }
})

// ===== 4. 回撤曲线 =====
const drawdownChart = computed(() => {
  const d = dd.value
  if (!d.length) return null
  let peak = 1000000
  let cumPnl = 0
  const dates = d.map((x: any) => x.date.slice(5))
  const drawdowns = d.map((x: any) => {
    cumPnl += x.profit || 0
    const equity = 1000000 + cumPnl
    peak = Math.max(peak, equity)
    return ((equity / peak) - 1) * 100
  })
  return {
    tooltip: {
      trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any[]) => { const idx = p[0]?.dataIndex ?? 0; const x = d[idx]; return `<b>${x?.date||''}</b><br/>回撤 <b style="color:#409eff">${drawdowns[idx].toFixed(2)}%</b>` }
    },
    grid: { left: 50, right: 16, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
    yAxis: { type: 'value', name: '回撤%', axisLabel: { fontSize: 10, color: '#aaa', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [{
      type: 'line', data: drawdowns, smooth: 0.2,
      lineStyle: { width: 2, color: '#409eff' }, itemStyle: { color: '#409eff' }, symbol: 'circle', symbolSize: 5,
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0)' }, { offset: 1, color: 'rgba(64,158,255,0.2)' }] } },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#777' }, data: [{ yAxis: 0 }] }
    }],
    animation: true, animationDuration: 500,
  }
})

// ===== 5. 盈亏分布直方图 =====
const pnlDistChart = computed(() => {
  const d = dd.value
  if (!d.length) return null
  const profits = d.map((x: any) => x.profit || 0).filter((v: number) => v !== 0)
  if (!profits.length) return null
  // Simple histogram: bucket by range
  const min = Math.min(...profits), max = Math.max(...profits)
  const bucketCount = Math.min(10, Math.max(3, profits.length))
  const step = (max - min) / bucketCount || 1
  const buckets: number[] = new Array(bucketCount).fill(0)
  const labels: string[] = []
  for (let i = 0; i < bucketCount; i++) {
    const lo = min + i * step
    labels.push(Math.abs(lo) >= 10000 ? (lo / 10000).toFixed(1) + '万' : Math.round(lo).toString())
  }
  profits.forEach((v: number) => {
    let idx = Math.floor((v - min) / step)
    if (idx >= bucketCount) idx = bucketCount - 1
    buckets[idx]++
  })
  return {
    tooltip: {
      trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any[]) => `${p[0].name}附近: <b>${p[0].value}</b>次`
    },
    grid: { left: 40, right: 16, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '次数', axisLabel: { fontSize: 10, color: '#aaa' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [{ type: 'bar', data: buckets, itemStyle: { color: 'rgba(168,85,247,0.6)', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 40, label: { show: true, position: 'top', fontSize: 10, color: '#ccc' } }]
  }
})

// ===== KPI chips =====
const kpiChips = computed(() => {
  const k = kpi.value
  return [
    { label: '夏普比率', value: k.sharpe_ratio?.toFixed(2) || '-', sub: '风险调整收益', cls: (k.sharpe_ratio || 0) >= 1 ? 'up' : 'down' },
    { label: '索提诺', value: k.sortino_ratio?.toFixed(2) || '-', sub: '仅下行风险', cls: (k.sortino_ratio || 0) >= 1 ? 'up' : 'down' },
    { label: '卡尔马', value: k.calmar_ratio?.toFixed(2) || '-', sub: '收益/最大回撤', cls: (k.calmar_ratio || 0) >= 3 ? 'up' : 'down' },
    { label: '盈亏因子', value: k.profit_factor?.toFixed(2) || '-', sub: '总盈利/总亏损', cls: (k.profit_factor || 0) >= 1 ? 'up' : 'down' },
    { label: '胜率', value: (k.win_rate || 0).toFixed(1) + '%', sub: `${k.win_count || 0}胜/${k.loss_count || 0}负`, cls: (k.win_rate || 0) >= 50 ? 'up' : 'down' },
    { label: '最大回撤', value: '-' + (k.max_drawdown || 0).toFixed(2) + '%', sub: '历史最大', cls: 'down' },
    { label: '连赢/连亏', value: `${k.max_consec_win || 0}/${k.max_consec_loss || 0}`, sub: '最大连续', cls: 'muted' },
    { label: '期望值', value: fmtPnl(k.expectancy || 0), sub: '每笔期望盈亏', cls: (k.expectancy || 0) >= 0 ? 'up' : 'down' },
  ]
})
</script>

<template>
  <div class="perf" v-loading="loading">
    <!-- KPI chips -->
    <div class="perf-kpi">
      <div v-for="chip in kpiChips" :key="chip.label" class="perf-chip">
        <div class="perf-chip-label">{{ chip.label }}</div>
        <div :class="['perf-chip-value', chip.cls]">{{ chip.value }}</div>
        <div class="perf-chip-sub">{{ chip.sub }}</div>
      </div>
    </div>

    <!-- Row 1: 月度收益 + 策略贡献 -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">📅 月度收益</div>
        <VChart v-if="monthlyChart" :option="monthlyChart" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">无月度数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">🎯 策略贡献</div>
        <VChart v-if="stratChart" :option="stratChart" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">无策略数据</div>
      </div>
    </div>

    <!-- Row 2: 卖出归因 + 回撤曲线 -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">🔍 卖出归因</div>
        <VChart v-if="reasonChart" :option="reasonChart" autoresize style="height:220px;width:100%" />
        <div v-else class="perf-empty">无卖出数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">📉 回撤曲线</div>
        <VChart v-if="drawdownChart" :option="drawdownChart" autoresize style="height:220px;width:100%" />
        <div v-else class="perf-empty">无历史数据</div>
      </div>
    </div>

    <!-- Row 3: 盈亏分布 -->
    <div class="perf-card">
      <div class="perf-card-t">📊 盈亏分布</div>
      <VChart v-if="pnlDistChart" :option="pnlDistChart" autoresize style="height:180px;width:100%" />
      <div v-else class="perf-empty">无交易数据</div>
    </div>
  </div>
</template>

<style scoped>
.perf { padding: 8px; flex: 1; overflow-y: auto; min-height: 0; }

/* KPI chips */
.perf-kpi { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
.perf-chip { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 5px; padding: 4px 10px; display: flex; flex-direction: column; align-items: center; min-width: 80px; }
.perf-chip-label { font-size: 10px; color: var(--text-tertiary); }
.perf-chip-value { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.perf-chip-sub { font-size: 9px; color: var(--text-tertiary); }

/* Layout */
.perf-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.perf-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; }
.perf-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.perf-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }

/* Colors */
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.muted { color: var(--text-tertiary); }
</style>
