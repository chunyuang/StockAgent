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
const closedTrades = computed(() => kpiData.value?.closed_trades || [])
const positions = computed(() => kpiData.value?.account?.positions || [])

const fmtPnl = (v: number) => { if (v == null || isNaN(v)) return '¥0'; const abs = Math.abs(v), sign = v >= 0 ? '+' : '-'; if (abs >= 10000) return sign + '¥' + (abs/10000).toFixed(2) + '万'; return sign + '¥' + abs.toLocaleString() }
const fmtPct = (v: number) => { if (v == null || isNaN(v)) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
const cls = (v: number) => v >= 0 ? 'up' : 'down'

// ===== 聚宽式三合一：净值+基准+回撤 =====
const overviewChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  const bm = benchmark.value
  let cumPnl = 0; const initial = 1000000
  let peak = initial, maxDD = 0, maxDDStart = 0, maxDDEnd = 0, ddStart = 0
  const dates = d.map((x: any) => x.date.slice(5))
  const values = d.map((x: any) => { cumPnl += x.profit || 0; return initial + cumPnl })
  const returns = values.map((v: number) => ((v / initial) - 1) * 100)
  const drawdowns = d.map((x: any, i: number) => {
    const eq = values[i]; peak = Math.max(peak, eq)
    const ddVal = ((eq / peak) - 1) * 100
    if (ddVal < maxDD) { maxDD = ddVal; maxDDEnd = i; maxDDStart = ddStart }
    if (eq >= peak) ddStart = i + 1
    return ddVal
  })
  const bmMap: any = {}; bm.forEach((b: any) => { bmMap[b.date] = b.cum_return })
  const bmReturns = d.map((x: any) => bmMap[x.date.replace(/-/g, '')] ?? null)
  const hasBm = bmReturns.some((v: any) => v !== null)
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0; const x = d[idx]; if (!x) return ''
        let s = `<div style="font-weight:600;margin-bottom:4px">${x.date}</div>`
        s += `<div>净值 <b>¥${values[idx].toLocaleString()}</b></div>`
        s += `<div>策略 <b style="color:${returns[idx]>=0?'#f56c6c':'#409eff'}">${fmtPct(returns[idx])}</b></div>`
        if (hasBm && bmReturns[idx] != null) s += `<div>沪深300 <b style="color:#e6a23c">${fmtPct(bmReturns[idx])}</b></div>`
        s += `<div>回撤 <b style="color:#409eff">${(drawdowns[idx]??0).toFixed(2)}%</b></div>`
        return s
      }
    },
    legend: { data: ['策略收益%', ...(hasBm ? ['沪深300%'] : []), '回撤%'], top: 2, right: 8, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 14, itemHeight: 7 },
    grid: [
      { left: 50, right: 16, top: 30, height: '55%' },   // 收益曲线
      { left: 50, right: 16, top: '72%', height: '22%' }, // 回撤
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, name: '收益率%', axisLabel: { fontSize: 10, color: '#aaa', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
      { type: 'value', gridIndex: 1, name: '回撤%', axisLabel: { fontSize: 10, color: '#409eff', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    ],
    series: [
      { name: '策略收益%', type: 'line', data: returns, xAxisIndex: 0, yAxisIndex: 0, smooth: 0.3, lineStyle: { width: 2.5, color: c.primary }, itemStyle: { color: c.primary }, symbol: 'circle', symbolSize: 6,
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0.12)' }, { offset: 1, color: 'rgba(64,158,255,0)' }] } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#777' }, data: [{ yAxis: 0 }] }
      },
      ...(hasBm ? [{ name: '沪深300%', type: 'line', data: bmReturns, xAxisIndex: 0, yAxisIndex: 0, smooth: 0.3, lineStyle: { width: 1.5, color: '#e6a23c', type: 'dashed' }, itemStyle: { color: '#e6a23c' }, symbol: 'none' }] : []),
      { name: '回撤%', type: 'line', data: drawdowns, xAxisIndex: 1, yAxisIndex: 1, smooth: 0.2, lineStyle: { width: 1.5, color: '#409eff' }, itemStyle: { color: '#409eff' }, symbol: 'none',
        areaStyle: { color: 'rgba(64,158,255,0.15)' },
        markArea: maxDD < -0.01 ? { silent: true, data: [[{ xAxis: dates[maxDDStart] || dates[0], itemStyle: { color: 'rgba(245,108,108,0.08)' } }, { xAxis: dates[maxDDEnd] || dates[dates.length-1] }]] } : undefined,
      },
    ],
    animation: true, animationDuration: 600,
  }
})

// ===== 每日盈亏 =====
const dailyPnlChart = computed(() => {
  const d = dd.value; if (!d.length) return null
  const profits = d.map((x: any) => x.profit || 0)
  const dailyRet = d.map((x: any) => ((x.profit || 0) / 1000000) * 100)
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
      { type: 'value', name: '盈亏¥', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => Math.abs(v)>=10000?(v/10000).toFixed(1)+'万':String(v) }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
      { type: 'value', name: '日收益%', position: 'right', axisLabel: { fontSize: 10, color: '#a855f7', formatter: '{value}%' }, splitLine: { show: false }, axisLine: { show: false } },
    ],
    series: [
      { name: '盈亏¥', type: 'bar', data: profits, itemStyle: { color: (p: any) => (p.value||0)>=0?'rgba(245,108,108,0.7)':'rgba(64,158,255,0.6)', borderRadius: [3,3,0,0] }, barMaxWidth: 40, label: { show: true, position: (p: any) => (p.value||0)>=0?'top':'bottom', fontSize: 10, color: '#ccc', formatter: (p: any) => { const v=p.value||0; return v===0?'':fmtPnl(v) } }, markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed' }, data: [{ yAxis: 0 }] } },
      { name: '日收益%', type: 'line', data: dailyRet, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 1.5, color: '#a855f7', type: 'dashed' }, itemStyle: { color: '#a855f7' }, symbol: 'none' },
    ],
    animation: true, animationDuration: 400,
  }
})

// ===== 月度收益 =====
const monthlyChart = computed(() => {
  const m = monthly.value; if (!m.length) return null
  const years = [...new Set(m.map((d: any) => d.month.slice(0, 4)))]
  const data = m.map((d: any) => [parseInt(d.month.slice(5))-1, years.indexOf(d.month.slice(0,4)), d.profit||0])
  const maxVal = Math.max(...data.map((d: any) => Math.abs(d[2])), 1)
  return {
    tooltip: { backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => { const d=p.data; if(!d) return ''; const mi=m.find((x:any)=>parseInt(x.month.slice(5))-1===d[0]&&x.month.slice(0,4)===years[d[1]]); return `<b>${mi?.month||''}</b><br/>盈亏 <b style="color:${d[2]>=0?'#f56c6c':'#409eff'}">${fmtPnl(d[2])}</b><br/>交易${mi?.trades||0}笔 · 胜率${mi?.win_rate!=null?mi.win_rate+'%':'-'}` }
    },
    grid: { left: 40, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'category', data: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'], axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'category', data: years, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    visualMap: { min: -maxVal, max: maxVal, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, show: false, inRange: { color: ['#409eff', '#1a1a2e', '#f56c6c'] } },
    series: [{ type: 'heatmap', data, label: { show: true, fontSize: 10, formatter: (p: any) => { const v=p.data[2]; return v===0?'-':(v>=0?'+':'')+(Math.abs(v)>=10000?(v/10000).toFixed(1)+'万':String(Math.round(v))) }, color: '#ccc' }, itemStyle: { borderWidth: 2, borderColor: '#1a1a2e' } }]
  }
})

// ===== 策略贡献 =====
const stratChart = computed(() => {
  const s = stratContrib.value; if (!s.length) return null
  const sorted = [...s].sort((a: any, b: any) => (b.profit||0)-(a.profit||0))
  const colors = ['#f56c6c','#e6a23c','#409eff','#67c23a','#a855f7']
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

// ===== 卖出归因 =====
const reasonChart = computed(() => {
  const r = sellReasons.value; if (!r.length) return null
  const sorted = [...r].sort((a: any, b: any) => (b.profit||0)-(a.profit||0))
  const colors = ['#f56c6c','#e6a23c','#409eff','#909399','#67c23a','#a855f7']
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

// ===== 盈亏分布 =====
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

// ===== 资产分布(按个股) =====
const assetPie = computed(() => {
  const pos = positions.value
  const cash = kpiData.value?.account?.available_cash || 0
  if (!pos.length && !cash) return null
  const items = pos.map((p: any) => ({ value: Math.round(p.market_value||0), name: (p.stock_name||p.ts_code?.slice(0,6))+' '+(p.profit_pct||0).toFixed(1)+'%', itemStyle: { color: (p.profit_pct||0)>=0?'#f56c6c':'#409eff' } }))
  if (cash > 0) items.push({ value: Math.round(cash), name: '可用现金', itemStyle: { color: '#909399' } })
  return {
    tooltip: { trigger: 'item', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 }, formatter: (p: any) => `<b>${p.name}</b><br/>¥${p.value.toLocaleString()} (${(p.percent??0).toFixed(1)}%)` },
    legend: { bottom: 0, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 10, itemHeight: 8, type: 'scroll' },
    series: [{ type: 'pie', radius: ['30%','60%'], center: ['50%','42%'], label: { formatter: (p: any) => `${p.name.split(' ')[0]}\n¥${(p.value/10000).toFixed(1)}万`, fontSize: 9, color: '#ccc', lineHeight: 13 }, labelLine: { lineStyle: { color: '#555' } }, itemStyle: { borderColor: '#1a1a2e', borderWidth: 2 }, emphasis: { label: { fontSize: 11, fontWeight: 'bold' } }, data: items }]
  }
})

// ===== 聚宽式指标表：3组 =====
const metricGroups = computed(() => {
  const k = kpi.value
  return [
    { title: '📈 收益指标', items: [
      { name: '累计收益率', value: fmtPct((k.total_pnl_all||0)/1000000*100), desc: '策略总收益' },
      { name: '已实现盈亏', value: fmtPnl(k.total_profit||0), desc: '已平仓' },
      { name: '未实现盈亏', value: fmtPnl(k.unrealized_pnl||0), desc: '持仓浮盈浮亏' },
      { name: '期望值', value: fmtPnl(k.expectancy||0), desc: '每笔期望盈亏' },
    ]},
    { title: '⚠️ 风险指标', items: [
      { name: '最大回撤', value: '-'+(k.max_drawdown||0).toFixed(2)+'%', desc: '历史最大' },
      { name: '夏普比率', value: (k.sharpe_ratio||0).toFixed(2), desc: '风险调整收益(>1优)', cls: (k.sharpe_ratio||0)>=1?'up':'down' },
      { name: '索提诺比率', value: (k.sortino_ratio||0).toFixed(2), desc: '仅下行风险(>1优)', cls: (k.sortino_ratio||0)>=1?'up':'down' },
      { name: '卡尔马比率', value: (k.calmar_ratio||0).toFixed(2), desc: '收益/最大回撤(>3优)', cls: (k.calmar_ratio||0)>=3?'up':'down' },
    ]},
    { title: '⚡ 效率指标', items: [
      { name: '盈亏因子', value: (k.profit_factor||0).toFixed(2), desc: '总盈利/总亏损(>1优)', cls: (k.profit_factor||0)>=1?'up':'down' },
      { name: '胜率', value: (k.win_rate||0).toFixed(1)+'%', desc: `${k.win_count||0}胜/${k.loss_count||0}负` },
      { name: '盈亏比', value: (k.profit_loss_ratio||0).toFixed(2), desc: '平均盈利/平均亏损', cls: (k.profit_loss_ratio||0)>=1?'up':'down' },
      { name: '均盈/均亏', value: `${(k.avg_win_pct||0).toFixed(2)}%/${(k.avg_loss_pct||0).toFixed(2)}%`, desc: '单笔平均' },
      { name: '连赢/连亏', value: `${k.max_consec_win||0}/${k.max_consec_loss||0}`, desc: '最大连续' },
      { name: '总交易', value: String(k.total_trades||0), desc: '笔' },
    ]},
  ]
})
</script>

<template>
  <div class="perf" v-loading="loading">
    <!-- ===== 聚宽式概览：净值+基准+回撤 三合一 ===== -->
    <div class="perf-section">
      <div class="perf-section-t">📊 策略概览 <span class="perf-hint">净值曲线 · 沪深300基准 · 回撤</span></div>
      <VChart v-if="overviewChart" :option="overviewChart" autoresize style="height:320px;width:100%" />
      <div v-else class="perf-empty">无数据</div>
    </div>

    <!-- ===== 聚宽式指标表：3组 ===== -->
    <div class="metric-grid">
      <div v-for="g in metricGroups" :key="g.title" class="metric-group">
        <div class="metric-group-t">{{ g.title }}</div>
        <div class="metric-table">
          <div v-for="item in g.items" :key="item.name" class="metric-row">
            <span class="metric-name">{{ item.name }}</span>
            <span :class="['metric-val', item.cls || '']">{{ item.value }}</span>
            <span class="metric-desc">{{ item.desc }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 每日盈亏 ===== -->
    <div class="perf-section">
      <div class="perf-section-t">📊 每日盈亏 <span class="perf-hint">盈亏¥ + 日收益率%</span></div>
      <VChart v-if="dailyPnlChart" :option="dailyPnlChart" autoresize style="height:200px;width:100%" />
      <div v-else class="perf-empty">无数据</div>
    </div>

    <!-- ===== 月度收益 + 资产分布 ===== -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">📅 月度收益</div>
        <VChart v-if="monthlyChart" :option="monthlyChart" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">无月度数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">🥧 资产分布 <span class="perf-hint">按个股</span></div>
        <VChart v-if="assetPie" :option="assetPie" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">空仓</div>
      </div>
    </div>

    <!-- ===== 策略贡献 + 卖出归因 ===== -->
    <div class="perf-row2">
      <div class="perf-card">
        <div class="perf-card-t">🎯 策略贡献</div>
        <VChart v-if="stratChart" :option="stratChart" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">无策略数据</div>
      </div>
      <div class="perf-card">
        <div class="perf-card-t">🔍 卖出归因</div>
        <VChart v-if="reasonChart" :option="reasonChart" autoresize style="height:180px;width:100%" />
        <div v-else class="perf-empty">无卖出数据</div>
      </div>
    </div>

    <!-- ===== 盈亏分布 ===== -->
    <div class="perf-card">
      <div class="perf-card-t">📊 盈亏分布</div>
      <VChart v-if="pnlDistChart" :option="pnlDistChart" autoresize style="height:160px;width:100%" />
      <div v-else class="perf-empty">无交易数据</div>
    </div>

    <!-- ===== 风控触发历史 ===== -->
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

    <!-- ===== 交易记录(已平仓) ===== -->
    <div class="perf-card">
      <div class="perf-card-t">📝 交易记录 <span class="perf-hint">已平仓{{ closedTrades.length }}笔 · 按盈亏排序</span></div>
      <div v-if="!closedTrades.length" class="perf-empty">暂无已平仓交易</div>
      <div v-else class="ct-list">
        <div class="ct-header">
          <span class="ct-code">代码</span>
          <span class="ct-name">名称</span>
          <span class="ct-strat">策略</span>
          <span class="ct-buy">买入</span>
          <span class="ct-sell">卖出</span>
          <span class="ct-qty">数量</span>
          <span class="ct-hold">持仓</span>
          <span class="ct-pnl">盈亏</span>
          <span class="ct-pnl-pct">收益率</span>
          <span class="ct-reason">卖出原因</span>
        </div>
        <div v-for="(t, i) in closedTrades" :key="i" :class="['ct-row', (t.profit_amount||0)>=0?'ct-win':'ct-loss']">
          <span class="ct-code">{{ t.ts_code?.slice(0,6) }}</span>
          <span class="ct-name">{{ t.stock_name }}</span>
          <span class="ct-strat">{{ t.strategy?.slice(0,4) }}</span>
          <span class="ct-buy">{{ t.buy_date?.slice(4) }}@¥{{ t.buy_price != null ? t.buy_price.toFixed(2) : '-' }}</span>
          <span class="ct-sell">{{ t.sell_date?.slice(4) }}@¥{{ t.sell_price != null ? t.sell_price.toFixed(2) : '-' }}</span>
          <span class="ct-qty">{{ t.qty }}</span>
          <span class="ct-hold">{{ t.hold_days!=null?t.hold_days+'天':'-' }}</span>
          <span :class="['ct-pnl', cls(t.profit_amount||0)]">{{ fmtPnl(t.profit_amount||0) }}</span>
          <span :class="['ct-pnl-pct', cls(t.profit_pct||0)]">{{ fmtPct(t.profit_pct||0) }}</span>
          <span class="ct-reason">{{ t.reason }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.perf { padding: 8px; flex: 1; overflow-y: auto; min-height: 0; }

/* Section (full width) */
.perf-section { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; margin-bottom: 8px; }
.perf-section-t { font-size: 14px; font-weight: 700; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.perf-hint { font-size: 10px; font-weight: 400; color: var(--text-tertiary); }

/* 聚宽式指标表 */
.metric-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.metric-group { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 8px 10px; }
.metric-group-t { font-size: 12px; font-weight: 700; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid var(--border-light); }
.metric-table { }
.metric-row { display: flex; align-items: baseline; gap: 6px; padding: 3px 0; font-size: 12px; }
.metric-name { color: var(--text-secondary); min-width: 72px; }
.metric-val { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 80px; }
.metric-desc { color: var(--text-tertiary); font-size: 10px; flex: 1; text-align: right; }

/* Row 2 */
.perf-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
.perf-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; margin-bottom: 8px; }
.perf-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.perf-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }

/* Risk events */
.re-list { max-height: 200px; overflow-y: auto; font-size: 12px; }
.re-item { display: flex; gap: 8px; padding: 3px 6px; border-bottom: 1px solid var(--border-light); align-items: center; }
.re-time { font-size: 10px; color: var(--text-tertiary); font-family: monospace; min-width: 140px; }
.re-code { min-width: 50px; }
.re-type { flex: 1; color: var(--text-secondary); }
.re-pnl { font-variant-numeric: tabular-nums; min-width: 80px; text-align: right; }


/* Closed trades table */
.ct-list { font-size: 11px; overflow-x: auto; }
.ct-header, .ct-row { display: grid; grid-template-columns: 50px 60px 42px 90px 90px 46px 36px 72px 58px 1fr; gap: 2px; padding: 3px 4px; align-items: center; border-bottom: 1px solid var(--border-light); }
.ct-header { font-weight: 600; color: var(--text-tertiary); font-size: 10px; position: sticky; top: 0; background: var(--bg-card); }
.ct-row { transition: background 0.15s; }
.ct-row:hover { background: rgba(255,255,255,0.03); }
.ct-win { border-left: 2px solid rgba(245,108,108,0.3); }
.ct-loss { border-left: 2px solid rgba(64,158,255,0.3); }
.ct-code { font-family: monospace; font-size: 10px; }
.ct-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ct-strat { color: var(--text-tertiary); font-size: 10px; }
.ct-buy, .ct-sell { font-variant-numeric: tabular-nums; font-size: 10px; }
.ct-qty { text-align: right; font-variant-numeric: tabular-nums; }
.ct-hold { text-align: center; color: var(--text-tertiary); }
.ct-pnl { font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.ct-pnl-pct { font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.ct-reason { color: var(--text-secondary); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.muted { color: var(--text-tertiary); }
</style>
