<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent, MarkLineComponent, MarkAreaComponent, VisualMapComponent } from 'echarts/components'
import { useChartColors } from './useChartColors'

use([CanvasRenderer, PieChart, LineChart, BarChart, HeatmapChart, TooltipComponent, LegendComponent, GridComponent, MarkLineComponent, MarkAreaComponent, VisualMapComponent])
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
const benchmark = computed(() => kpiData.value?.benchmark || [])
const riskEvents = computed(() => kpiData.value?.risk_events || [])
const positions = computed(() => (kpiData.value?.account?.positions || []))

const fmtPnl = (v: number) => { if (v == null || isNaN(v)) return '¥0'; const abs = Math.abs(v), sign = v >= 0 ? '+' : '-'; if (abs >= 10000) return sign + '¥' + (abs/10000).toFixed(2) + '万'; return sign + '¥' + abs.toLocaleString() }
const fmtPct = (v: number) => { if (v == null || isNaN(v)) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
const cls = (v: number) => v >= 0 ? 'up' : 'down'

// ===== 1. 资金曲线 + 基准对比 =====
const equityChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  const bm = benchmark.value
  let cumPnl = 0; const initial = 1000000
  const dates = d.map((x: any) => x.date.slice(5))
  const values = d.map((x: any) => { cumPnl += x.profit || 0; return initial + cumPnl })
  const returns = values.map((v: number) => ((v / initial) - 1) * 100)
  // 沪深300收益曲线（对齐日期）
  const bmMap: any = {}; bm.forEach((b: any) => { bmMap[b.date] = b.cum_return })
  const bmReturns = d.map((x: any) => bmMap[x.date.replace(/-/g, '')] ?? null)
  const hasBm = bmReturns.some((v: any) => v !== null)
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0; const x = d[idx]; if (!x) return ''
        const v = values[idx]; const r = returns[idx]
        let s = `<div style="font-weight:600;margin-bottom:4px">${x.date}</div>`
        s += `<div>策略 <b style="color:${r>=0?'#f56c6c':'#409eff'}">${r>=0?'+':''}${r.toFixed(2)}%</b> ¥${v.toLocaleString()}</div>`
        if (hasBm && bmReturns[idx] != null) s += `<div>沪深300 <b style="color:#e6a23c">${fmtPct(bmReturns[idx])}</b></div>`
        s += `<div style="color:#aaa;font-size:11px">当日 ${fmtPnl(x.profit||0)}</div>`
        return s
      }
    },
    legend: { data: ['策略收益%', ...(hasBm ? ['沪深300%'] : [])], top: 2, right: 8, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 14, itemHeight: 7 },
    grid: { left: 50, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
    yAxis: { type: 'value', name: '收益率%', axisLabel: { fontSize: 10, color: '#aaa', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [
      { name: '策略收益%', type: 'line', data: returns, smooth: 0.3, lineStyle: { width: 2.5, color: c.primary }, itemStyle: { color: c.primary }, symbol: 'circle', symbolSize: 6,
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0.12)' }, { offset: 1, color: 'rgba(64,158,255,0)' }] } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#777' }, data: [{ yAxis: 0 }] }
      },
      ...(hasBm ? [{ name: '沪深300%', type: 'line', data: bmReturns, smooth: 0.3, lineStyle: { width: 1.5, color: '#e6a23c', type: 'dashed' }, itemStyle: { color: '#e6a23c' }, symbol: 'none' }] : []),
    ],
    animation: true, animationDuration: 600,
  }
})

// ===== 2. 每日盈亏 + 日收益率% =====
const dailyPnlChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  const profits = d.map((x: any) => x.profit || 0)
  const dailyRet = d.map((x: any) => { const p = x.profit || 0; return (p / 1000000) * 100 })
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0; const x = d[idx]; if (!x) return ''
        const v = x.profit || 0; const r = dailyRet[idx]
        return `<b>${x.date}</b><br/>盈亏 <b style="color:${v>=0?'#f56c6c':'#409eff'}">${fmtPnl(v)}</b><br/>日收益 <b>${r>=0?'+':''}${r.toFixed(3)}%</b><br/><span style="color:#aaa;font-size:11px">买${x.buys||0}笔 卖${x.sells||0}笔</span>`
      }
    },
    legend: { data: ['盈亏¥', '日收益%'], top: 2, right: 8, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 14, itemHeight: 7 },
    grid: { left: 56, right: 48, top: 30, bottom: 28 },
    xAxis: { type: 'category', data: d.map((x: any) => x.date.slice(5)), axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '盈亏¥', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => Math.abs(v) >= 10000 ? (v/10000).toFixed(1)+'万' : String(v) }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
      { type: 'value', name: '日收益%', position: 'right', axisLabel: { fontSize: 10, color: '#a855f7', formatter: '{value}%' }, splitLine: { show: false }, axisLine: { show: false } },
    ],
    series: [
      { name: '盈亏¥', type: 'bar', data: profits, itemStyle: { color: (p: any) => (p.value||0)>=0 ? 'rgba(245,108,108,0.7)' : 'rgba(64,158,255,0.6)', borderRadius: [3,3,0,0] }, barMaxWidth: 40, label: { show: true, position: (p: any) => (p.value||0)>=0?'top':'bottom', fontSize: 10, color: '#ccc', formatter: (p: any) => { const v=p.value||0; return v===0?'':fmtPnl(v) } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed' }, data: [{ yAxis: 0 }] }
      },
      { name: '日收益%', type: 'line', data: dailyRet, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 1.5, color: '#a855f7', type: 'dashed' }, itemStyle: { color: '#a855f7' }, symbol: 'none' },
    ],
    animation: true, animationDuration: 400,
  }
})

// ===== 3. 回撤曲线 + 最大回撤区间标注 =====
const drawdownChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  let peak = 1000000, cumPnl = 0, maxDD = 0, maxDDStart = 0, maxDDEnd = 0, ddStart = 0
  const dates = d.map((x: any) => x.date.slice(5))
  const drawdowns = d.map((x: any, i: number) => {
    cumPnl += x.profit || 0
    const eq = 1000000 + cumPnl; peak = Math.max(peak, eq)
    const dd = ((eq / peak) - 1) * 100
    if (dd < maxDD) { maxDD = dd; maxDDEnd = i; maxDDStart = ddStart }
    if (eq >= peak) ddStart = i + 1
    return dd
  })
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any[]) => { const idx = p[0]?.dataIndex ?? 0; return `<b>${d[idx]?.date||''}</b><br/>回撤 <b style="color:#409eff">${drawdowns[idx].toFixed(2)}%</b>` }
    },
    grid: { left: 50, right: 16, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
    yAxis: { type: 'value', name: '回撤%', axisLabel: { fontSize: 10, color: '#aaa', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [{
      type: 'line', data: drawdowns, smooth: 0.2, lineStyle: { width: 2, color: '#409eff' }, itemStyle: { color: '#409eff' }, symbol: 'circle', symbolSize: 5,
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0)' }, { offset: 1, color: 'rgba(64,158,255,0.2)' }] } },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed' }, data: [{ yAxis: 0 }] },
      markArea: maxDD < -0.01 ? { silent: true, data: [[{ xAxis: dates[maxDDStart] || dates[0], itemStyle: { color: 'rgba(245,108,108,0.1)' } }, { xAxis: dates[maxDDEnd] || dates[dates.length-1] }]] } : undefined,
    }],
    animation: true, animationDuration: 500,
  }
})

// ===== 4. 月度收益热力图 =====
const monthlyChart = computed(() => {
  const m = monthly.value; if (!m.length) return null
  const years = [...new Set(m.map((d: any) => d.month.slice(0, 4)))]
  const data = m.map((d: any) => [parseInt(d.month.slice(5)) - 1, years.indexOf(d.month.slice(0, 4)), d.profit || 0])
  const maxVal = Math.max(...data.map((d: any) => Math.abs(d[2])), 1)
  return {
    tooltip: { backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => { const d = p.data; if (!d) return ''; const mi = m.find((x: any) => parseInt(x.month.slice(5))-1===d[0] && x.month.slice(0,4)===years[d[1]]); return `<b>${mi?.month||''}</b><br/>盈亏 <b style="color:${d[2]>=0?'#f56c6c':'#409eff'}">${fmtPnl(d[2])}</b><br/>交易${mi?.trades||0}笔 · 胜率${mi?.win_rate!=null?mi.win_rate+'%':'-'}` }
    },
    grid: { left: 40, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category', data: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'], axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'category', data: years, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    visualMap: { min: -maxVal, max: maxVal, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, show: false, inRange: { color: ['#409eff', '#1a1a2e', '#f56c6c'] } },
    series: [{ type: 'heatmap', data, label: { show: true, fontSize: 10, formatter: (p: any) => { const v = p.data[2]; return v === 0 ? '-' : (v >= 0 ? '+' : '') + (Math.abs(v) >= 10000 ? (v/10000).toFixed(1)+'万' : String(Math.round(v))) }, color: '#ccc' }, itemStyle: { borderWidth: 2, borderColor: '#1a1a2e' } }]
  }
})

// ===== 5. 策略贡献(堆叠式) =====
const stratChart = computed(() => {
  const s = stratContrib.value; if (!s.length) return null
  const sorted = [...s].sort((a: any, b: any) => (b.profit||0) - (a.profit||0))
  const colors = ['#f56c6c', '#e6a23c', '#409eff', '#67c23a', '#a855f7']
  return {
    tooltip: { backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => `<b>${p.name}</b><br/>盈亏 <b style="color:${colors[p.dataIndex%colors.length]}">${fmtPnl(p.value||0)}</b><br/>交易${p.data?.trades||0}笔 · 胜率${p.data?.win_rate!=null?p.data.win_rate+'%':'-'} · 均盈${p.data?.avg_profit_pct!=null?fmtPct(p.data.avg_profit_pct):'-'}`
    },
    grid: { left: 80, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'value', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => Math.abs(v)>=10000?(v/10000).toFixed(1)+'万':String(v) }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } } },
    yAxis: { type: 'category', data: sorted.map((d: any) => d.strategy), axisLabel: { fontSize: 11, color: '#ccc' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    series: [{ type: 'bar', data: sorted.map((d: any, i: number) => ({ value: d.profit||0, trades: d.trades, win_rate: d.win_rate, avg_profit_pct: d.avg_profit_pct, itemStyle: { color: colors[i%colors.length] } })), borderRadius: [0,3,3,0], barMaxWidth: 28, label: { show: true, position: (p: any) => (p.value||0)>=0?'right':'left', fontSize: 10, color: '#ccc', formatter: (p: any) => fmtPnl(p.value||0) } }]
  }
})

// ===== 6. 卖出归因 =====
const reasonChart = computed(() => {
  const r = sellReasons.value; if (!r.length) return null
  const sorted = [...r].sort((a: any, b: any) => (b.profit||0) - (a.profit||0))
  const colors = ['#f56c6c', '#e6a23c', '#409eff', '#909399', '#67c23a', '#a855f7']
  return {
    tooltip: { backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => `<b>${p.name}</b><br/>盈亏 <b style="color:${colors[p.dataIndex%colors.length]}">${fmtPnl(p.value||0)}</b><br/>触发${p.data?.count||0}次`
    },
    legend: { bottom: 0, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 10, itemHeight: 8 },
    series: [{ type: 'pie', radius: ['30%','60%'], center: ['50%','42%'], label: { formatter: (p: any) => `${p.name}\n${fmtPnl(p.value||0)}`, fontSize: 10, color: '#ccc', lineHeight: 14 }, labelLine: { lineStyle: { color: '#555' } }, itemStyle: { borderColor: '#1a1a2e', borderWidth: 2 }, emphasis: { label: { fontSize: 12, fontWeight: 'bold' } },
      data: sorted.map((d: any, i: number) => ({ value: d.profit||0, name: d.reason, count: d.count, itemStyle: { color: colors[i%colors.length] } }))
    }]
  }
})

// ===== 7. 盈亏分布直方图 =====
const pnlDistChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  const profits = d.map((x: any) => x.profit||0).filter((v: number) => v !== 0)
  if (!profits.length) return null
  const min = Math.min(...profits), max = Math.max(...profits)
  const bc = Math.min(10, Math.max(3, profits.length))
  const step = (max-min)/bc || 1
  const buckets: number[] = new Array(bc).fill(0)
  const labels: string[] = []
  for (let i = 0; i < bc; i++) { const lo = min+i*step; labels.push(Math.abs(lo)>=10000?(lo/10000).toFixed(1)+'万':Math.round(lo).toString()) }
  profits.forEach((v: number) => { let idx = Math.floor((v-min)/step); if (idx>=bc) idx=bc-1; buckets[idx]++ })
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 }, formatter: (p: any[]) => `${p[0].name}附近: <b>${p[0].value}</b>次` },
    grid: { left: 40, right: 16, top: 20, bottom: 28 },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '次数', axisLabel: { fontSize: 10, color: '#aaa' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [{ type: 'bar', data: buckets, itemStyle: { color: 'rgba(168,85,247,0.6)', borderRadius: [3,3,0,0] }, barMaxWidth: 40, label: { show: true, position: 'top', fontSize: 10, color: '#ccc' } }]
  }
})

// ===== 8. 资产分布(按个股) =====
const assetPie = computed(() => {
  const pos = positions.value
  const cash = kpiData.value?.account?.available_cash || 0
  if (!pos.length && !cash) return null
  const items = pos.map((p: any) => ({ value: Math.round(p.market_value||0), name: (p.stock_name||p.ts_code?.slice(0,6))+' '+(p.profit_pct||0).toFixed(1)+'%', itemStyle: { color: (p.profit_pct||0)>=0 ? '#f56c6c' : '#409eff' } }))
  if (cash > 0) items.push({ value: Math.round(cash), name: '可用现金', itemStyle: { color: '#909399' } })
  return {
    tooltip: { trigger: 'item', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 }, formatter: (p: any) => `<b>${p.name}</b><br/>¥${p.value.toLocaleString()} (${p.percent.toFixed(1)}%)` },
    legend: { bottom: 0, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 10, itemHeight: 8, type: 'scroll' },
    series: [{ type: 'pie', radius: ['30%','60%'], center: ['50%','42%'], label: { formatter: (p: any) => `${p.name.split(' ')[0]}\n¥${(p.value/10000).toFixed(1)}万`, fontSize: 9, color: '#ccc', lineHeight: 13 }, labelLine: { lineStyle: { color: '#555' } }, itemStyle: { borderColor: '#1a1a2e', borderWidth: 2 }, emphasis: { label: { fontSize: 11, fontWeight: 'bold' } }, data: items }]
  }
})

// ===== KPI chips =====
const kpiChips = computed(() => {
  const k = kpi.value
  return [
    { label: '夏普比率', value: k.sharpe_ratio?.toFixed(2)||'-', sub: '风险调整收益', cls: (k.sharpe_ratio||0)>=1?'up':'down' },
    { label: '索提诺', value: k.sortino_ratio?.toFixed(2)||'-', sub: '仅下行风险', cls: (k.sortino_ratio||0)>=1?'up':'down' },
    { label: '卡尔马', value: k.calmar_ratio?.toFixed(2)||'-', sub: '收益/最大回撤', cls: (k.calmar_ratio||0)>=3?'up':'down' },
    { label: '盈亏因子', value: k.profit_factor?.toFixed(2)||'-', sub: '总盈利/总亏损', cls: (k.profit_factor||0)>=1?'up':'down' },
    { label: '胜率', value: (k.win_rate||0).toFixed(1)+'%', sub: `${k.win_count||0}胜/${k.loss_count||0}负 · 盈亏比${k.profit_loss_ratio?.toFixed(2)||'-'}`, cls: (k.win_rate||0)>=50?'up':'down' },
    { label: '最大回撤', value: '-'+(k.max_drawdown||0).toFixed(2)+'%', sub: '历史最大', cls: 'down' },
    { label: '连赢/连亏', value: `${k.max_consec_win||0}/${k.max_consec_loss||0}`, sub: '最大连续', cls: 'muted' },
    { label: '期望值', value: fmtPnl(k.expectancy||0), sub: '每笔期望盈亏', cls: (k.expectancy||0)>=0?'up':'down' },
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

    <!-- Row 1: 资金曲线+基准 + 每日盈亏+日收益% -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">📈 资金曲线 <span class="perf-hint">策略 vs 沪深300</span></div>
        <VChart v-if="equityChart" :option="equityChart" autoresize style="height:220px;width:100%" />
        <div v-else class="perf-empty">无数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">📊 每日盈亏 <span class="perf-hint">盈亏¥ + 日收益率%</span></div>
        <VChart v-if="dailyPnlChart" :option="dailyPnlChart" autoresize style="height:220px;width:100%" />
        <div v-else class="perf-empty">无数据</div>
      </div>
    </div>

    <!-- Row 2: 回撤曲线 + 资产分布(按个股) -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">📉 回撤曲线 <span class="perf-hint">红色区间=最大回撤</span></div>
        <VChart v-if="drawdownChart" :option="drawdownChart" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">无数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">🥧 资产分布 <span class="perf-hint">按个股</span></div>
        <VChart v-if="assetPie" :option="assetPie" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">空仓</div>
      </div>
    </div>

    <!-- Row 3: 月度收益 + 策略贡献 -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">📅 月度收益 <span class="perf-hint">热力图</span></div>
        <VChart v-if="monthlyChart" :option="monthlyChart" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">无月度数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">🎯 策略贡献 <span class="perf-hint">按策略</span></div>
        <VChart v-if="stratChart" :option="stratChart" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">无策略数据</div>
      </div>
    </div>

    <!-- Row 4: 卖出归因 + 盈亏分布 -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">🔍 卖出归因</div>
        <VChart v-if="reasonChart" :option="reasonChart" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">无卖出数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">📊 盈亏分布 <span class="perf-hint">直方图</span></div>
        <VChart v-if="pnlDistChart" :option="pnlDistChart" autoresize style="height:200px;width:100%" />
        <div v-else class="perf-empty">无交易数据</div>
      </div>
    </div>

    <!-- 风控触发历史 -->
    <div class="perf-card" v-if="riskEvents.length">
      <div class="perf-card-t">🛡️ 风控触发历史 <span class="perf-hint">最近{{ riskEvents.length }}条</span></div>
      <div class="re-list">
        <div v-for="(ev, i) in riskEvents" :key="i" class="re-item">
          <span class="re-time">{{ ev.timestamp?.slice(0,19) || ev.trade_date }}</span>
          <span class="re-code">{{ ev.ts_code?.slice(0,6) }}</span>
          <span class="re-type">{{ ev.decision_type || ev.reason || '-' }}</span>
          <span :class="['re-pnl', cls(ev.profit||0)]">{{ fmtPnl(ev.profit||0) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.perf { padding: 8px; flex: 1; overflow-y: auto; min-height: 0; }
.perf-kpi { display: flex; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
.perf-chip { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 5px; padding: 4px 10px; display: flex; flex-direction: column; align-items: center; min-width: 80px; }
.perf-chip-label { font-size: 10px; color: var(--text-tertiary); }
.perf-chip-value { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.perf-chip-sub { font-size: 9px; color: var(--text-tertiary); text-align: center; }
.perf-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.perf-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; margin-bottom: 0; }
.perf-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.perf-hint { font-size: 10px; font-weight: 400; color: var(--text-tertiary); }
.perf-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }
/* Risk events */
.re-list { max-height: 200px; overflow-y: auto; font-size: 12px; }
.re-item { display: flex; gap: 8px; padding: 3px 6px; border-bottom: 1px solid var(--border-light); align-items: center; }
.re-time { font-size: 10px; color: var(--text-tertiary); font-family: monospace; min-width: 140px; }
.re-code { min-width: 50px; }
.re-type { flex: 1; color: var(--text-secondary); }
.re-pnl { font-variant-numeric: tabular-nums; min-width: 80px; text-align: right; }
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.muted { color: var(--text-tertiary); }
</style>
