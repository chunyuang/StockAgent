<script setup lang="ts">
import { useChartColors } from './useChartColors'
/**
 * AnalysisTab — 市场监听结果分析
 * 参考BacktestResultPanel: KPI卡片→卖出分布条→分区导航→图表
 * 含: 日收益率、累计收益、绩效雷达、盈亏分布、交易占比、卖出原因、月度收益、策略贡献、持仓
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { ElButton, ElEmpty, ElDialog } from 'element-plus'
import { ref, computed, watch, onMounted, defineAsyncComponent } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart, RadarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent } from 'echarts/components'

use([CanvasRenderer, LineChart, BarChart, PieChart, RadarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent])
const c = useChartColors().value
const StrategyPerfBoard = defineAsyncComponent(() => import('./StrategyPerfBoard.vue'))

const m = useScannerMonitorInject()
const { activeTab } = m
const loading = ref(false)
// 【v2.9.97h-v11 恢复】默认不限日期，看全部历史数据 (06-23 03:51 cron auto-merge 此行被覆盖, 2026-06-23 手动恢复)
const selectedDate = ref('')  // 空字符串 = 全部历史
const rangeMode = ref<'all' | 'date'>('all')  // 'all'=全部 / 'date'=单日
const analysisData = ref<any>(null)
const activeSection = ref('overview')
const expandedCharts = ref<Record<string, boolean>>({})  // 每个图表独立折叠, 默认收起
function toggleChart(key: string) { expandedCharts.value[key] = !expandedCharts.value[key] }

/** 获取中国时区的日期字符串 YYYY-MM-DD */
function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const y = china.getFullYear()
  const m = String(china.getMonth() + 1).padStart(2, '0')
  const d = String(china.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

// date managed by UnifiedDateBar

async function fetchAnalysis() {
  loading.value = true
  try {
    // 【v2.9.97h-v11】全部模式不传 date，后端返回全部历史多日明细
    const url = rangeMode.value === 'date' && selectedDate.value
      ? `/scanner/analysis?date=${selectedDate.value.replace(/-/g, '')}`
      : `/scanner/analysis`
    const r = await api.get(url)
    const p = parseResponse(r)
    if (p.success) analysisData.value = p.data
    // 同步获取当日交易（用今天作默认，主表格不依赖这个）
    try {
      const today = getChinaDate().replace(/-/g, '')
      const d = rangeMode.value === 'date' && selectedDate.value ? selectedDate.value.replace(/-/g, '') : today
      const r2 = await api.get(`/unified/trades?date=${d}`)
      const p2 = parseResponse(r2)
      if (p2.success) dailyTrades.value = (p2.data?.trades || []).map((t: any) => ({ ...t, action: t.side }))
    } catch (e) { console.error('[AnalysisTab]', e) }
  } catch (e) { console.error('[Analysis]', e) }
  finally { loading.value = false }
}

function formatMoney(v: number): string {
  if (v == null) return '-'
  const abs = Math.abs(v)
  if (abs >= 10000) return (v / 10000).toFixed(1) + '万'
  return v.toFixed(0)
}

function onSwitchToAll() {
  rangeMode.value = 'all'
  selectedDate.value = ''
  fetchAnalysis()
}

function onDateChange(d: string) {
  rangeMode.value = 'date'
  selectedDate.value = d
  fetchAnalysis()
}

// 仅在Tab激活时自动刷新(不与UnifiedDateBar的change事件重复)
watch(activeTab, (t) => { if (t === 'analysis') fetchAnalysis() })

// 【v2.9.99-r11 fix】首次挂载时自动加载 (MarketMonitorView 用 v-if 渲染, 每次切Tab都重新挂载)
onMounted(() => {
  fetchAnalysis()
})

const kpi = computed(() => analysisData.value?.kpi || {})
const strategies = computed(() => analysisData.value?.strategy_contrib || [])
const sellReasons = computed(() => analysisData.value?.sell_reasons || [])
const monthly = computed(() => analysisData.value?.monthly || [])
const dailyDetail = computed(() => analysisData.value?.daily_detail || [])
const positions = computed(() => (analysisData.value?.positions || []).slice().sort((a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)))
const riskMonitor = computed(() => analysisData.value?.risk_monitor || {})
const stratPerfSummary = computed(() => {
  const ss = strategies.value
  if (!ss.length) return ''
  const totalTrades = ss.reduce((a: number, s: any) => a + (s.trades || 0), 0)
  const totalProfit = ss.reduce((a: number, s: any) => a + (s.profit || 0), 0)
  const avgWin = ss.reduce((a: number, s: any) => a + (s.win_rate || 0) * (s.trades || 0), 0) / (totalTrades || 1)
  const profitSign = totalProfit >= 0 ? '+' : ''
  return `${ss.length}策略 ${totalTrades}笔 胜率${isFinite(avgWin) ? avgWin.toFixed(0) : '0'}% ${profitSign}¥${(totalProfit / 10000).toFixed(1)}万`
})
const brokenStopLossCount = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'broken').length)
const totalReasonCount = computed(() => sellReasons.value.reduce((s: number, r: any) => s + r.count, 0) || 1)

const dailyProfitChart = computed(() => {
  const dd = dailyDetail.value; if (!dd.length) return null
  return { tooltip: { trigger: 'axis' }, grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true }, xAxis: { type: 'category', data: dd.map((d: any) => d.date) }, yAxis: { type: 'value', name: '¥' }, dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 4 }], series: [{ type: 'bar', data: dd.map((d: any) => d.profit), itemStyle: { color: (p: any) => p.value >= 0 ? c.stockDown : c.stockUp }, label: { show: true, position: 'top', fontSize: 10 } }] }
})

const cumProfitChart = computed(() => {
  const dd = dailyDetail.value; if (!dd.length) return null
  const cumProfits: number[] = []; let cum = 0
  for (const d of dd) { cum += d.profit; cumProfits.push(cum) }
  return { tooltip: { trigger: 'axis' }, grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true }, xAxis: { type: 'category', data: dd.map((d: any) => d.date), boundaryGap: false }, yAxis: { type: 'value', name: '¥' }, series: [{ name: '累计盈亏', type: 'line', data: cumProfits, smooth: true, lineStyle: { width: 2 }, areaStyle: { opacity: 0.15 }, markPoint: { data: [{ type: 'max', name: '最高' }, { type: 'min', name: '最低' }] } }] }
})

const positionChart = computed(() => {
  const pos = positions.value; if (!pos.length) return null
  const names = pos.map((p: any) => (p.stock_name || p.ts_code?.slice(0, 6)).substring(0, 4))
  return { tooltip: { trigger: 'axis' }, grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true }, xAxis: { type: 'category', data: names }, yAxis: { type: 'value', name: '盈亏%', axisLabel: { formatter: '{value}%' } }, series: [{ type: 'bar', data: pos.map((p: any) => p.profit_pct || 0), itemStyle: { color: (p: any) => p.value >= 0 ? c.stockDown : c.stockUp }, label: { show: true, position: 'top', formatter: '{c}%', fontSize: 10 } }] }
})

const strategyPieChart = computed(() => {
  const ss = strategies.value; if (!ss.length) return null
  return { tooltip: { trigger: 'item', formatter: '{b}: {c}笔 ({d}%)' }, series: [{ type: 'pie', radius: ['35%', '65%'], label: { formatter: '{b}\n{c}笔', fontSize: 11 }, data: ss.map((s: any) => ({ name: m.strategyCN(s.strategy) || s.strategy, value: s.trades, itemStyle: { color: s.profit >= 0 ? c.stockDown : c.stockUp } })) }] }
})

const sellReasonChart = computed(() => {
  const rs = sellReasons.value; if (!rs.length) return null
  const colors: Record<string, string> = { '止损': c.stockUp, '冲高回落': c.warning, '利润保护': c.primary, '止盈': c.stockDown, '到期': c.warning }
  return { tooltip: { trigger: 'item', formatter: '{b}: {c}笔 ({d}%)' }, legend: { bottom: 0, textStyle: { fontSize: 11 } }, series: [{ type: 'pie', radius: ['35%', '65%'], label: { formatter: '{b}\n{c}笔', fontSize: 11 }, data: rs.map((r: any) => ({ name: r.reason, value: r.count, itemStyle: { color: colors[r.reason] || c.textTertiary } })) }] }
})

const radarChart = computed(() => {
  const k = kpi.value; if (!k.total_trades) return null
  const ddCtrl = Math.max(0, 100 - Math.abs(k.max_drawdown || 0))
  const maxPLR = Math.max(5, Math.ceil(Math.abs(k.profit_loss_ratio || 0)) + 1)
  const sharpe = Math.max(0, Math.min(k.sharpe_ratio || 0, 5))
  return { tooltip: { trigger: 'item' }, radar: { indicator: [{ name: '胜率(%)', max: 100 }, { name: '盈亏比', max: maxPLR }, { name: '回撤控制', max: 100 }, { name: 'Sharpe', max: 5 }, { name: '盈亏因子', max: Math.max(3, Math.ceil((k.profit_factor || 0)) + 1) }] }, series: [{ type: 'radar', data: [{ name: '组合绩效', value: [k.win_rate || 0, k.profit_loss_ratio || 0, ddCtrl, sharpe, k.profit_factor || 0] }] }] }
})

const monthlyChart = computed(() => {
  const mm = monthly.value; if (!mm.length) return null
  return { tooltip: { trigger: 'axis' }, legend: { data: ['月度收益', '累计收益'] }, grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true }, xAxis: { type: 'category', data: mm.map((m: any) => m.month) }, yAxis: [{ type: 'value', name: '月度¥' }, { type: 'value', name: '累计¥', position: 'right' }], series: [{ name: '月度收益', type: 'bar', data: mm.map((m: any) => m.profit), itemStyle: { color: (p: any) => p.value >= 0 ? c.stockDown : c.stockUp }, label: { show: true, position: 'top', fontSize: 10 } }, { name: '累计收益', type: 'line', yAxisIndex: 1, data: mm.map((m: any) => m.cum_profit), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: c.primary } }] }
})

const profitDistChart = computed(() => {
  const k = kpi.value; if (!k.total_trades) return null
  // 盈亏分布直方图 (按profit_pct分桶)
  const buckets = ['<-5%', '-5~-2%', '-2~0%', '0~2%', '2~5%', '>5%']
  const counts = [0, 0, 0, 0, 0, 0]
  // 从sell records按profit_pct分桶 (用KPI的win/loss count近似)
  const wins = k.win_count || 0; const losses = k.loss_count || 0
  const avgWin = k.avg_win_pct || 0; const avgLoss = k.avg_loss_pct || 0
  // 简化：用均值近似分桶
  if (avgWin >= 5) counts[5] = wins; else if (avgWin >= 2) counts[4] = wins; else counts[3] = wins
  if (avgLoss <= -5) counts[0] = losses; else if (avgLoss <= -2) counts[1] = losses; else counts[2] = losses
  const colors = [c.stockUp, c.stockUp, 'rgba(245,108,108,0.4)', 'rgba(103,194,58,0.4)', c.stockDown, c.stockDown]
  return { tooltip: { trigger: 'axis' }, grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true }, xAxis: { type: 'category', data: buckets, axisLabel: { fontSize: 10 } }, yAxis: { type: 'value', name: '笔数', minInterval: 1 }, series: [{ type: 'bar', data: counts.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })), label: { show: true, position: 'top', fontSize: 10 } }] }
})

const selectedDay = ref('')
const dailyTrades = ref<any[]>([])
const dailyTradesLoading = ref(false)

// 个股详情
const stockDetailVisible = ref(false)
const stockDetail = ref<any>(null)
const stockDetailLoading = ref(false)
async function showStockDetail(tsCode: string) {
  stockDetailVisible.value = true; stockDetailLoading.value = true; stockDetail.value = null
  try { const r = await api.get(`/scanner/analysis/stock/${tsCode}`); const p = parseResponse(r); if (p.success) stockDetail.value = p.data } catch (e) { console.error('[AnalysisTab]', e) } finally { stockDetailLoading.value = false }
}

async function showDayDetail(date: string) {
  if (selectedDay.value === date) { selectedDay.value = ''; dailyTrades.value = []; return }
  selectedDay.value = date; dailyTradesLoading.value = true
  // 【v2.9.97】切换到统一数据源
  try { const d = date.replace(/-/g, ''); const r = await api.get(`/unified/trades?date=${d}`); const p = parseResponse(r); if (p.success) dailyTrades.value = (p.data?.trades || []).map((t: any) => ({ ...t, action: t.side })) } catch (e) { console.error('[AnalysisTab]', e) } finally { dailyTradesLoading.value = false }
}
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll ana-wrap">
      <div class="ana-toolbar">
        <span class="ana-title">📊 结果分析</span>
        <span class="ana-range-hint" v-if="rangeMode === 'all'">全部历史</span>
        <span class="ana-range-hint" v-else-if="selectedDate">{{ selectedDate }} 单日</span>
        <ElButton size="small" :type="rangeMode === 'all' ? 'primary' : 'default'" @click="onSwitchToAll">📅 全部</ElButton>
        <UnifiedDateBar @change="onDateChange" />
        <ElButton size="small" @click="fetchAnalysis" :loading="loading">🔄</ElButton>
      </div>

      <div v-if="!analysisData && !loading" class="ana-empty"><ElEmpty description="暂无分析数据" /></div>
      <div v-if="loading" class="ana-loading">加载中...</div>

      <template v-if="analysisData && !loading">
        <!-- KPI卡片 -->
        <div class="kpi-strip">
          <div :class="['kpi-chip', (kpi.total_profit || 0) >= 0 ? 'kpi-positive' : 'kpi-negative']"><div class="kpi-icon">📈</div><div class="kpi-body"><span class="kpi-label">累计盈亏</span><span class="kpi-value">¥{{ (kpi.total_profit || 0).toLocaleString() }}</span></div></div>
          <div :class="['kpi-chip', (kpi.win_rate || 0) >= 50 ? 'kpi-positive' : 'kpi-negative']"><div class="kpi-icon">🎯</div><div class="kpi-body"><span class="kpi-label">胜率</span><span class="kpi-value">{{ (kpi.win_rate || 0).toFixed(1) }}%</span></div></div>
          <div class="kpi-chip kpi-neutral"><div class="kpi-icon">🔢</div><div class="kpi-body"><span class="kpi-label">交易笔数</span><span class="kpi-value">{{ kpi.total_trades || 0 }}</span></div></div>
          <div :class="['kpi-chip', (kpi.profit_loss_ratio || 0) >= 2 ? 'kpi-positive' : 'kpi-warning']"><div class="kpi-icon">⚖️</div><div class="kpi-body"><span class="kpi-label">盈亏比</span><span class="kpi-value">{{ (kpi.profit_loss_ratio || 0).toFixed(2) }}</span></div></div>
          <div class="kpi-chip kpi-warning"><div class="kpi-icon">⬇️</div><div class="kpi-body"><span class="kpi-label">最大回撤</span><span class="kpi-value">{{ (kpi.max_drawdown || 0).toFixed(1) }}%</span></div></div>
          <div class="kpi-chip kpi-neutral"><div class="kpi-icon">📊</div><div class="kpi-body"><span class="kpi-label">均盈亏%</span><span class="kpi-value" :class="(kpi.avg_profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (kpi.avg_profit_pct || 0).toFixed(2) }}%</span></div></div>
          <div class="kpi-chip kpi-accent"><div class="kpi-icon">✅</div><div class="kpi-body"><span class="kpi-label">均盈利%</span><span class="kpi-value up">{{ (kpi.avg_win_pct || 0).toFixed(2) }}%</span></div></div>
          <div class="kpi-chip kpi-warning"><div class="kpi-icon">❌</div><div class="kpi-body"><span class="kpi-label">均亏损%</span><span class="kpi-value down">{{ (kpi.avg_loss_pct || 0).toFixed(2) }}%</span></div></div>
        </div>

        <!-- 卖出分布条 -->
        <div v-if="sellReasons.length" class="sell-reason-bar">
          <span class="sell-reason-label">卖出分布</span>
          <div class="sell-reason-items">
            <span v-for="r in sellReasons" :key="r.reason" :class="['sell-reason-item', r.profit >= 0 ? 'reason-profit' : 'reason-loss']">
              <span class="reason-dot"></span>{{ r.reason }}{{ r.count }}笔({{ totalReasonCount > 0 ? (r.count / totalReasonCount * 100).toFixed(0) : '0' }}%)
            </span>
          </div>
        </div>

        <!-- 分区导航 -->
        <div class="section-nav">
          <button :class="['sec-btn', activeSection === 'overview' ? 'active' : '']" @click="activeSection = 'overview'">📈 概览</button>
          <button :class="['sec-btn', activeSection === 'position' ? 'active' : '']" @click="activeSection = 'position'">💼 持仓</button>
          <button :class="['sec-btn', activeSection === 'detail' ? 'active' : '']" @click="activeSection = 'detail'">📋 明细</button>
        </div>

        <!-- ========== 概览 ========== -->
        <div :class="['section-content', { 'section-hidden': activeSection !== 'overview' }]">
          <div class="chart-section">
            <div class="chart-title collapsible" @click="toggleChart('stratContrib')">🔄 策略贡献 <span class="collapse-summary">{{ strategies.length }}策略 {{ strategies.reduce((a:any,s:any)=>a+s.trades,0) }}笔</span> <span class="collapse-arrow">{{ expandedCharts.stratContrib ? '▲' : '▼' }}</span></div>
            <template v-if="expandedCharts.stratContrib">
            <table class="ana-tbl"><thead><tr><th>策略</th><th>笔数</th><th>胜率</th><th>盈亏</th><th>均盈亏%</th></tr></thead><tbody>
              <tr v-for="s in strategies" :key="s.strategy" :class="(s.profit || 0) >= 0 ? 'row-up' : 'row-down'"><td class="td-strat">{{ m.strategyCN(s.strategy) || s.strategy }}</td><td>{{ s.trades }}</td><td :class="(s.win_rate || 0) >= 50 ? 'up' : 'down'">{{ (s.win_rate || 0).toFixed(1) }}%</td><td :class="(s.profit || 0) >= 0 ? 'up' : 'down'">¥{{ (s.profit || 0).toLocaleString() }}</td><td :class="(s.avg_profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (s.avg_profit_pct || 0).toFixed(2) }}%</td></tr>
            </tbody></table>
            </template>
          </div>
          <div class="chart-section">
            <div class="chart-title collapsible" @click="toggleChart('stratPerf')">📊 策略绩效 <span class="collapse-summary">{{ stratPerfSummary }}</span> <span class="collapse-arrow">{{ expandedCharts.stratPerf ? '▲' : '▼' }}</span></div>
            <template v-if="expandedCharts.stratPerf">
            <StrategyPerfBoard />
            </template>
          </div>
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('dailyProfit')">📊 日收益率 <span class="collapse-arrow">{{ expandedCharts.dailyProfit ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.dailyProfit"><VChart v-if="dailyProfitChart" :option="dailyProfitChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('cumProfit')">📈 累计盈亏 <span class="collapse-arrow">{{ expandedCharts.cumProfit ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.cumProfit"><VChart v-if="cumProfitChart" :option="cumProfitChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
          </div>
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('radar')">🎯 绩效雷达 <span class="collapse-arrow">{{ expandedCharts.radar ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.radar"><VChart v-if="radarChart" :option="radarChart" autoresize style="height:300px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('profitDist')">🍩 盈亏分布 <span class="collapse-arrow">{{ expandedCharts.profitDist ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.profitDist"><VChart v-if="profitDistChart" :option="profitDistChart" autoresize style="height:300px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
          </div>
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('strategyPie')">🔄 交易占比(策略) <span class="collapse-arrow">{{ expandedCharts.strategyPie ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.strategyPie"><VChart v-if="strategyPieChart" :option="strategyPieChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
            <div class="chart-half"><div class="chart-title collapsible" @click="toggleChart('sellReason')">📤 卖出原因 <span class="collapse-arrow">{{ expandedCharts.sellReason ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.sellReason"><VChart v-if="sellReasonChart" :option="sellReasonChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></template></div>
          </div>
          <div v-if="monthly.length" class="chart-section"><div class="chart-title collapsible" @click="toggleChart('monthly')">📅 月度收益 <span class="collapse-arrow">{{ expandedCharts.monthly ? '▲' : '▼' }}</span></div><template v-if="expandedCharts.monthly"><VChart v-if="monthlyChart" :option="monthlyChart" autoresize style="height:300px;width:100%" /></template></div>
        </div>

        <!-- ========== 持仓 ========== -->
        <div :class="['section-content', { 'section-hidden': activeSection !== 'position' }]">
          <div class="chart-section"><div class="chart-title collapsible" @click="toggleChart('posDist')">💼 持仓盈亏分布 <span class="collapse-summary">{{ positions.length }}只{{ brokenStopLossCount > 0 ? ' 🔴' + brokenStopLossCount + '破止损' : '' }}</span> <span class="collapse-arrow">{{ expandedCharts.posDist ? '▲' : '▼' }}</span></div>
            <span v-if="expandedCharts.posDist && brokenStopLossCount > 0" class="ana-stat" style="color:var(--stock-up);background:var(--stock-up-dim,rgba(8,153,129,0.1))">🔴 {{ brokenStopLossCount }}只破止损</span>
            <span v-if="expandedCharts.posDist && riskMonitor.status && riskMonitor.status !== 'healthy'" class="ana-stat" style="color:#e6a23c;background:rgba(230,162,60,0.1)">⚠️ {{ riskMonitor.desc }}</span>
          <template v-if="expandedCharts.posDist"><VChart v-if="positionChart" :option="positionChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="空仓或无数据" :image-size="40" /></template></div>
          <div v-if="positions.length" class="chart-section">
            <div class="chart-title collapsible" @click="toggleChart('posDetail')">📋 持仓明细 <span class="collapse-summary">{{ positions.length }}只</span> <span class="collapse-arrow">{{ expandedCharts.posDetail ? '▲' : '▼' }}</span></div>
            <template v-if="expandedCharts.posDetail">
            <table class="ana-tbl"><thead><tr><th>代码</th><th>名称</th><th>策略</th><th>数量</th><th>成本</th><th>最新收盘</th><th>止损价</th><th>盈亏%</th><th>盈亏额</th><th>市值</th><th>状态</th><th></th></tr></thead><tbody>
              <tr v-for="p in positions" :key="p.ts_code" :class="(p.profit_pct || 0) >= 0 ? 'row-up' : 'row-down'"><td>{{ p.ts_code?.slice(0,6) }}</td><td>{{ p.stock_name }}</td><td>{{ m.strategyCN(p.strategy) || p.strategy }}</td><td>{{ p.shares }}</td><td>¥{{ p.cost_price || '-' }}</td><td>¥{{ p.current_price || '-' }}</td><td :style="{color: p.stop_loss_status === 'broken' ? 'var(--stock-up)' : p.stop_loss_status === 'near' ? '#e6a23c' : 'var(--text-tertiary)'}">¥{{ p.stop_loss_price || '-' }}</td><td :class="(p.profit_pct || 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (p.profit_pct || 0) >= 0 ? '+' : '' }}{{ (p.profit_pct || 0).toFixed(1) }}%</td><td :class="(p.profit_amount || 0) >= 0 ? 'up' : 'down'">¥{{ (p.profit_amount || 0).toLocaleString() }}</td><td>¥{{ (p.market_value || 0).toLocaleString() }}</td><td><span v-if="p.stop_loss_status === 'broken'" style="color:var(--stock-up);font-weight:600;font-size:11px">🔴破止损</span><span v-else-if="p.stop_loss_status === 'near'" style="color:#e6a23c;font-size:11px">⚠近止损</span><span v-else style="color:var(--text-tertiary);font-size:11px">安全</span><span v-if="p.risk_monitor_desc" :title="p.risk_monitor_desc" style="color:#e6a23c;font-size:10px;margin-left:2px">⚡</span></td><td><ElButton size="small" text type="primary" @click="showStockDetail(p.ts_code)">详情</ElButton></td></tr>
            </tbody></table>
            </template>
          </div>
        </div>

        <!-- ========== 明细 ========== -->
        <div :class="['section-content', { 'section-hidden': activeSection !== 'detail' }]">
          <div class="chart-section">
            <div class="chart-title">📋 每日明细 <span class="ana-stat">点击展开</span></div>
            <div v-if="!dailyDetail.length" class="ana-empty-sm">暂无数据</div>
            <table class="ana-tbl" v-else><thead><tr><th>日期</th><th>买</th><th>卖</th><th>胜率</th><th>盈亏</th></tr></thead><tbody>
              <template v-for="d in dailyDetail" :key="d.date">
                <tr class="dl-row" :class="(d.profit || 0) >= 0 ? 'row-up' : 'row-down'" @click="showDayDetail(d.date)" style="cursor:pointer"><td>{{ d.date }} <span style="font-size:9px;color:var(--text-tertiary)">{{ selectedDay === d.date ? '▲' : '▼' }}</span></td><td class="up">{{ d.buys ?? 0 }}</td><td class="down">{{ d.sells ?? 0 }}</td><td :class="(d.win_rate || 0) >= 50 ? 'up' : 'down'">{{ d.win_rate != null ? d.win_rate + '%' : '-' }}</td><td :class="(d.profit || 0) >= 0 ? 'up' : 'down'">¥{{ (d.profit || 0).toLocaleString() }}</td></tr>
                <tr v-if="selectedDay === d.date"><td colspan="4" style="padding:4px 8px;background:var(--bg-muted)">
                  <div v-if="dailyTradesLoading" style="font-size:11px;color:var(--text-tertiary)">加载中...</div>
                  <div v-else-if="!dailyTrades.length" style="font-size:11px;color:var(--text-tertiary)">无交易记录</div>
                  <table v-else class="sub-tbl"><thead><tr><th>时间</th><th>方向</th><th>代码</th><th>名称</th><th>价格</th><th>数量</th><th>盈亏%</th><th>盈亏额</th><th>原因</th></tr></thead><tbody>
                    <tr v-for="(t, i) in dailyTrades" :key="i"><td>{{ t.time }}</td><td :class="t.action === 'buy' ? 'up' : t.action === 'sell' ? 'down' : ''">{{ t.action === 'buy' ? '买' : t.action === 'sell' ? '卖' : '⛔' }}</td><td>{{ t.ts_code?.slice(0,6) }}</td><td>{{ t.stock_name }}</td><td>{{ t.price }}</td><td>{{ t.shares }}</td><td :class="(t.profit_pct ?? 0) >= 0 ? 'up' : 'down'">{{ t.action === 'sell' && t.profit_pct != null && t.profit_pct !== 0 ? (Number(t.profit_pct) >= 0 ? '+' : '') + Number(t.profit_pct).toFixed(1) + '%' : '-' }}</td><td :class="(t.profit_amount ?? 0) >= 0 ? 'up' : 'down'">{{ t.action === 'sell' && t.profit_amount != null && t.profit_amount !== 0 ? '¥' + Number(t.profit_amount).toFixed(0) : '-' }}</td><td style="font-size:10px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.reason || '-' }}</td></tr>
                  </tbody></table>
                </td></tr>
              </template>
            </tbody></table>
          </div>
        </div>
      </template>

      <!-- 个股详情弹窗 -->
      <ElDialog v-model="stockDetailVisible" :title="stockDetail ? `${stockDetail.ts_code} ${stockDetail.stock_name}` : '个股详情'" width="600px" destroy-on-close>
        <div v-if="stockDetailLoading" style="text-align:center;padding:40px">加载中...</div>
        <div v-else-if="stockDetail">
          <!-- 摘要 -->
          <div class="sd-summary">
            <div class="sd-kpi" :class="(stockDetail.summary.holding_profit_pct ?? 0) >= 0 ? 'sd-up' : 'sd-down'">
              <div class="sd-kpi-label">持仓盈亏</div>
              <div class="sd-kpi-val">{{ stockDetail.summary?.holding_profit_pct != null ? ((Number(stockDetail.summary.holding_profit_pct) >= 0 ? '+' : '') + Number(stockDetail.summary.holding_profit_pct).toFixed(1) + '%') : '--' }}</div>
            </div>
            <div class="sd-kpi" :class="stockDetail.summary.realized_profit >= 0 ? 'sd-up' : 'sd-down'">
              <div class="sd-kpi-label">已实现盈亏</div>
              <div class="sd-kpi-val">¥{{ (stockDetail.summary?.realized_profit || 0).toLocaleString() }}</div>
            </div>
            <div class="sd-kpi sd-neutral">
              <div class="sd-kpi-label">持仓/成本</div>
              <div class="sd-kpi-val">{{ stockDetail.summary.holding_qty }}股 / ¥{{ stockDetail.summary.avg_cost }}</div>
            </div>
            <div class="sd-kpi sd-neutral">
              <div class="sd-kpi-label">现价/市值</div>
              <div class="sd-kpi-val">¥{{ stockDetail.summary.current_price }} / ¥{{ stockDetail.summary.market_value?.toLocaleString() }}</div>
            </div>
            <div class="sd-kpi sd-neutral">
              <div class="sd-kpi-label">买卖次数</div>
              <div class="sd-kpi-val">{{ stockDetail.summary.buy_count }}买 / {{ stockDetail.summary.sell_count }}卖</div>
            </div>
            <div class="sd-kpi sd-neutral">
              <div class="sd-kpi-label">持有天数</div>
              <div class="sd-kpi-val">{{ stockDetail.summary.hold_days ?? '--' }}天</div>
            </div>
          </div>
          <!-- 交易记录 -->
          <div class="sd-trades">
            <div class="sd-trades-title">📋 交易记录</div>
            <table class="ana-tbl">
              <thead><tr><th>日期</th><th>时间</th><th>方向</th><th>数量</th><th>价格</th><th>盈亏%</th><th>盈亏额</th><th>原因</th></tr></thead>
              <tbody>
                <tr v-for="(t, i) in stockDetail.trades" :key="i" :class="t.action === 'buy' ? 'row-up' : 'row-down'">
                  <td>{{ t.date }}</td><td>{{ t.time }}</td>
                  <td :class="t.action === 'buy' ? 'up' : 'down'">{{ t.action === 'buy' ? '买入' : '卖出' }}</td>
                  <td>{{ t.shares }}</td><td>¥{{ t.price }}</td>
                  <td :class="(Number(t.profit_pct) || 0) >= 0 ? 'up' : 'down'">{{ t.action === 'sell' && t.profit_pct != null && t.profit_pct !== 0 ? (Number(t.profit_pct) >= 0 ? '+' : '') + Number(t.profit_pct).toFixed(1) + '%' : '-' }}</td>
                  <td :class="(Number(t.profit_amount) || 0) >= 0 ? 'up' : 'down'">{{ t.action === 'sell' && t.profit_amount != null && t.profit_amount !== 0 ? '¥' + Number(t.profit_amount).toFixed(0) : '-' }}</td>
                  <td style="font-size:10px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.reason || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </ElDialog>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ana-wrap { display: flex; flex-direction: column; gap: 8px; }
.ana-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-default); flex-wrap: nowrap; }
.ana-title { font-size: 14px; font-weight: 700; }
.ana-range-hint { font-size: 12px; color: var(--text-secondary); padding: 2px 8px; background: var(--bg-secondary); border-radius: 10px; border: 1px solid var(--border-default); }
.ana-empty { padding: 60px 0; text-align: center; }
.ana-empty-sm { padding: 16px 0; text-align: center; color: var(--text-tertiary); font-size: 11px; }
.ana-loading { padding: 40px 0; text-align: center; color: var(--text-tertiary); }
.ana-stat { font-size: 10px; color: var(--text-tertiary); font-weight: 400; }

.kpi-strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
.kpi-chip { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default); transition: box-shadow 0.2s, transform 0.15s; &:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); transform: translateY(-1px); } }
.kpi-icon { font-size: 20px; flex-shrink: 0; }
.kpi-body { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
.kpi-label { font-size: 11px; color: var(--text-tertiary); font-weight: 500; }
.kpi-value { font-size: 16px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
.kpi-positive { background: linear-gradient(135deg, rgba(103,194,58,0.08) 0%, rgba(103,194,58,0.02) 100%); border-color: rgba(103,194,58,0.2); .kpi-value { color: var(--stock-down); } }
.kpi-negative { background: linear-gradient(135deg, rgba(245,108,108,0.08) 0%, rgba(245,108,108,0.02) 100%); border-color: rgba(245,108,108,0.2); .kpi-value { color: var(--stock-up); } }
.kpi-warning { background: linear-gradient(135deg, rgba(230,162,60,0.08) 0%, rgba(230,162,60,0.02) 100%); border-color: rgba(230,162,60,0.2); .kpi-value { color: var(--el-color-warning); } }
.kpi-accent { background: linear-gradient(135deg, rgba(64,158,255,0.08) 0%, rgba(64,158,255,0.02) 100%); border-color: rgba(64,158,255,0.2); .kpi-value { color: var(--el-color-primary); } }
.kpi-neutral { background: var(--bg-muted); }

.sell-reason-bar { display: flex; align-items: center; gap: 16px; padding: 10px 16px; background: var(--bg-elevated, var(--bg-muted)); border-radius: 8px; border: 1px solid var(--border-default); font-size: 13px; flex-wrap: wrap; }
.sell-reason-label { font-weight: 700; font-size: 14px; flex-shrink: 0; }
.sell-reason-items { display: flex; gap: 14px; flex-wrap: wrap; }
.sell-reason-item { display: flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 12px; border: 1px solid var(--border-default); font-weight: 500; }
.reason-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.reason-profit { color: var(--stock-down); .reason-dot { background: var(--stock-down); } }
.reason-loss { color: var(--stock-up); .reason-dot { background: var(--stock-up); } }

.section-nav { display: flex; gap: 4px; margin-bottom: 8px; padding: 4px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.sec-btn { padding: 6px 14px; font-size: 13px; font-weight: 500; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; border-radius: 6px; transition: all 0.15s; white-space: nowrap; }
.sec-btn:hover { color: var(--el-color-primary); background: var(--bg-elevated, white); }
.sec-btn.active { color: var(--el-color-primary); background: var(--bg-elevated, white); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.section-content { animation: fadeIn 0.2s ease; }
.section-hidden { display: none; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.chart-section { margin-bottom: 12px; padding: 12px; border-radius: 8px; background: var(--bg-elevated, var(--bg-muted)); border: 1px solid var(--border-default); }
.chart-title.collapsible { cursor: pointer; user-select: none; &:hover { color: var(--el-color-primary); } }
.collapse-arrow { font-size: 9px; color: var(--text-tertiary); margin-left: 4px; }
.collapse-summary { font-size: 10px; color: var(--text-tertiary); margin-left: 6px; font-weight: 400; }
.chart-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.chart-half { padding: 12px; border-radius: 8px; background: var(--bg-elevated, var(--bg-muted)); border: 1px solid var(--border-default); }

.ana-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.ana-tbl th { text-align: left; font-size: 10px; color: var(--text-tertiary); font-weight: 600; padding: 4px 6px; border-bottom: 1px solid var(--border-light); }
.ana-tbl td { padding: 3px 6px; border-bottom: 1px solid var(--border-light); }
.ana-tbl tr:hover { background: var(--bg-muted); }
.row-up > td { border-left: 2px solid var(--stock-down); }
.row-down > td { border-left: 2px solid var(--stock-up); }
.td-strat { font-weight: 600; }
.sub-tbl { width: 100%; border-collapse: collapse; font-size: 10px; }
.sub-tbl th { text-align: left; font-size: 9px; color: var(--text-tertiary); padding: 2px 4px; }
.sub-tbl td { padding: 2px 4px; }

.up { color: var(--stock-down); }
.down { color: var(--stock-up); }

/* 个股详情弹窗 */
.sd-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 16px; }
.sd-kpi { padding: 10px; border-radius: 6px; text-align: center; border: 1px solid var(--border-default); }
.sd-kpi-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 4px; }
.sd-kpi-val { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.sd-up { background: rgba(103,194,58,0.06); .sd-kpi-val { color: var(--stock-down); } }
.sd-down { background: rgba(245,108,108,0.06); .sd-kpi-val { color: var(--stock-up); } }
.sd-neutral { background: var(--bg-muted); }
.sd-trades-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }

@media (max-width: 900px) {
  .chart-row { grid-template-columns: 1fr; }
  .kpi-strip { grid-template-columns: repeat(4, 1fr); }
}
</style>
