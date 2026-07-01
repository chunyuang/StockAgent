<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, LineChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent, MarkLineComponent } from 'echarts/components'
import { useChartColors } from './useChartColors'
import UnifiedDateBar from './components/UnifiedDateBar.vue'

use([CanvasRenderer, PieChart, LineChart, BarChart, TooltipComponent, LegendComponent, GridComponent, MarkLineComponent])
import { GLOBAL_RISK } from '@/config/strategyDefaults'
import { useUnifiedData } from './composables/useUnifiedData'

const c = useChartColors().value
const loading = ref(false)
const kpiData = ref<any>(null)  // KPI/账户资金(仍从/analysis获取)
const activeSection = ref('overview')
const equityExpanded = ref(false)
const dailyPnlExpanded = ref(false)

/** 获取中国时区的日期字符串 YYYY-MM-DD */
function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  // 【v2.9.98修复】用本地日期组件而非toISOString()，避免UTC时区偏移
  // toISOString()返回UTC时间，UTC+8凌晨0-8点会返回前一天的日期
  const y = china.getFullYear()
  const m = String(china.getMonth() + 1).padStart(2, '0')
  const d = String(china.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const selectedDate = ref('')  // 空字符串=全部历史
const rangeMode = ref<'all' | 'date'>('all')  // 默认全部历史
// date managed by UnifiedDateBar

// 【v2.9.97d】统一数据层: 持仓从 unified 读取(唯一真相源)
const unified = useUnifiedData()

// 切换section时滚动到顶部
watch(activeSection, () => {
  const el = document.querySelector('.at')
  if (el) el.scrollTop = 0
})
const expandedCode = ref<string | null>(null)
const detailData = ref<any>(null)
const detailLoading = ref(false)

const fetchKpi = async () => {
  loading.value = true
  try {
    // 【v2.9.98zf】全部模式不传date，后端返回全部历史数据
    const d = selectedDate.value.replace(/-/g, '')
    const url = rangeMode.value === 'date' && d
      ? `/api/v1/scanner/analysis?date=${d}`
      : `/api/v1/scanner/analysis`
    const res = await fetch(url).then(r => r.json())
    kpiData.value = res.data || {}
    unified.setDate(d || getChinaDate().replace(/-/g, ''))
  } catch (e) { console.error(e) }
  loading.value = false
}

// 日期变更回调
const onDateChange = (_date: string, _dateApi: string) => {
  rangeMode.value = 'date'
  selectedDate.value = _date
  fetchKpi()
}

function onSwitchToAll() {
  rangeMode.value = 'all'
  selectedDate.value = ''
  fetchKpi()
}

const toggleDetail = async (code: string) => {
  if (expandedCode.value === code) {
    expandedCode.value = null
    detailData.value = null
    return
  }
  expandedCode.value = code
  detailLoading.value = true
  try {
    const res = await fetch(`/api/v1/scanner/analysis/stock/${code}`).then(r => r.json())
    detailData.value = res.data || {}
  } catch (e) { console.error(e) }
  detailLoading.value = false
}

onMounted(fetchKpi)

// 【v2.9.97g】监听全局日期变更
watch(() => unified.currentDate.value, () => { fetchKpi() })

const acc = computed(() => kpiData.value?.account || {})
const riskMonitor = computed(() => kpiData.value?.risk_monitor || {})
const positions = computed(() => {
  // 【v2.9.97d】持仓统一从 unified 获取(唯一真相源: broker_positions)
  return (unified.positions.value || []).slice().sort((a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0))
})
const totalAssets = computed(() => acc.value.total_assets || 0)
const availableCash = computed(() => acc.value.available_cash || 0)
const marketValue = computed(() => acc.value.market_value || positions.value.reduce((s: number, p: any) => s + (p.market_value || 0), 0))
const totalProfit = computed(() => kpiData.value?.kpi?.total_pnl_all ?? (totalAssets.value - 1000000) ?? 0)
const positionRatio = computed(() => (totalAssets.value ?? 0) > 0 ? (marketValue.value ?? 0) / (totalAssets.value ?? 1) * 100 : 0)
const riskParams = GLOBAL_RISK  // 前端参数与后端strategy_defaults.py完全对齐(由sync脚本同步)
const brokenSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'broken'))
const nearSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'near'))

const fmt = (v: number) => `¥${((v || 0) / 10000).toFixed(2)}万`
const cls = (v: number) => v >= 0 ? 'up' : 'down'

const fmtMoney = (v: number) => {
  if (v == null || isNaN(v)) return '¥0'
  const abs = Math.abs(v), sign = v >= 0 ? '' : '-'
  if (abs >= 10000) return sign + '¥' + (abs/10000).toFixed(2) + '万'
  return sign + '¥' + abs.toLocaleString()
}
const fmtPnl = (v: number) => {
  if (v == null || isNaN(v)) return '¥0'
  const abs = Math.abs(v), sign = v >= 0 ? '+' : '-'
  if (abs >= 10000) return sign + '¥' + (abs/10000).toFixed(2) + '万'
  return sign + '¥' + abs.toLocaleString()
}
const fmtPct = (v: number) => {
  if (v == null || isNaN(v)) return '-'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

const realizedPnl = computed(() => {
  // 已实现盈亏 = 后端KPI的total_profit(从卖出记录修正后汇总)
  // 不用 totalProfit - positions_pnl，那个公式把浮盈浮亏加了两次
  return kpiData.value?.kpi?.total_profit || 0
})
const unrealizedPnl = computed(() => {
  return kpiData.value?.kpi?.unrealized_pnl || positions.value.reduce((s: number, p: any) => s + (p.profit_amount || 0), 0)
})

// ===== 资金曲线 =====
const equityCurve = computed(() => {
  const dd = kpiData.value?.daily_detail || []
  if (!dd.length) return null
  let cumPnl = 0
  const initial = 1000000
  const dates = dd.map((d: any) => d.date.slice(5))
  const values = dd.map((d: any) => { cumPnl += d.profit || 0; return initial + cumPnl })
  const returns = values.map((v: number) => ((v / initial) - 1) * 100)
  return {
    tooltip: {
      trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0; const d = dd[idx]; if (!d) return ''
        const v = values[idx]; const r = returns[idx]
        return `<div style="font-weight:600;margin-bottom:4px">${d.date}</div>` +
          `<div>总资产 <b style="color:#fff">¥${v.toLocaleString()}</b></div>` +
          `<div>收益率 <b style="color:${r>=0?'#f56c6c':'#409eff'}">${r>=0?'+':''}${r.toFixed(2)}%</b></div>` +
          `<div style="color:#aaa;font-size:11px;margin-top:2px">当日 ${fmtPnl(d.profit||0)} · 买${d.buys||0}笔 卖${d.sells||0}笔</div>`
      }
    },
    legend: { data: ['总资产','收益率%'], top: 2, right: 8, textStyle: { fontSize: 10, color: '#999' }, itemWidth: 14, itemHeight: 7 },
    grid: { left: 60, right: 54, top: 30, bottom: 28 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false }, boundaryGap: false },
    yAxis: [
      { type: 'value', name: '净值', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => (v/10000).toFixed(1)+'万' }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
      { type: 'value', name: '收益率%', position: 'right', axisLabel: { fontSize: 10, color: '#a855f7', formatter: (v: number) => v.toFixed(1)+'%' }, splitLine: { show: false }, axisLine: { show: false } },
    ],
    series: [
      { name: '总资产', type: 'line', data: values, smooth: 0.3, lineStyle: { width: 2.5, color: c.primary }, itemStyle: { color: c.primary }, symbol: 'circle', symbolSize: 7,
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(64,158,255,0.15)' }, { offset: 1, color: 'rgba(64,158,255,0)' }] } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#666', type: 'dotted', width: 1 }, label: { fontSize: 9, color: '#888', position: 'insideStartTop' }, data: [{ yAxis: initial, label: { formatter: '初始 ¥100万' } }] }
      },
      { name: '收益率%', type: 'line', data: returns, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 1.5, color: '#a855f7', type: 'dashed' }, itemStyle: { color: '#a855f7' }, symbol: 'none',
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#777' }, data: [{ yAxis: 0, label: { formatter: '0%' } }] }
      },
    ],
    animation: true, animationDuration: 600,
  }
})

// ===== 每日盈亏柱状图 =====
const dailyPnlChart = computed(() => {
  const dd = kpiData.value?.daily_detail || []
  if (!dd.length) return null
  const profits = dd.map((d: any) => d.profit || 0)
  return {
    tooltip: {
      trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0; const d = dd[idx]; if (!d) return ''
        const v = d.profit || 0
        return `<div style="font-weight:600;margin-bottom:4px">${d.date}</div>` +
          `<div>盈亏 <b style="color:${v>=0?'#f56c6c':'#409eff'}">${fmtPnl(v)}</b></div>` +
          `<div style="color:#aaa;font-size:11px">买入 ${d.buys||0}笔 · 卖出 ${d.sells||0}笔${d.win_rate!=null?' · 胜率'+d.win_rate+'%':''}</div>`
      }
    },
    grid: { left: 60, right: 16, top: 24, bottom: 28 },
    xAxis: { type: 'category', data: dd.map((d: any) => d.date.slice(5)), axisLabel: { fontSize: 10, color: '#888' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '盈亏', axisLabel: { fontSize: 10, color: '#aaa', formatter: (v: number) => { if(Math.abs(v)>=10000) return (v/10000).toFixed(1)+'万'; return String(v) } }, splitLine: { lineStyle: { color: '#2a2a2a', type: 'dashed' } }, axisLine: { show: false } },
    series: [{
      type: 'bar', data: profits,
      itemStyle: { color: (p: any) => (p.value||0)>=0 ? 'rgba(245,108,108,0.7)' : 'rgba(64,158,255,0.6)', borderRadius: [3,3,0,0] },
      barMaxWidth: 48,
      label: { show: true, position: (p: any) => (p.value||0)>=0 ? 'top' : 'bottom', fontSize: 10, color: '#ccc', formatter: (p: any) => { const v=p.value||0; return v===0?'':fmtPnl(v) } },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#555', type: 'dashed', width: 1 }, data: [{ yAxis: 0 }] }
    }],
    animation: true, animationDuration: 400,
  }
})

const posPie = computed(() => {
  const pos = positions.value
  if (!pos.length) return null
  const up = pos.filter((p: any) => (p.profit_pct ?? 0) >= 0)
  const down = pos.filter((p: any) => (p.profit_pct ?? 0) < 0)
  const upVal = Math.round(up.reduce((s: number, p: any) => s + (p.market_value || 0), 0))
  const downVal = Math.round(down.reduce((s: number, p: any) => s + (p.market_value || 0), 0))
  const cashVal = Math.round(availableCash.value)
  return {
    tooltip: {
      trigger: 'item', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: '#555', textStyle: { color: '#eee', fontSize: 12 },
      formatter: (p: any) => `<b>${p.name}</b><br/>金额 ¥${p.value.toLocaleString()}<br/>占比 ${p.percent.toFixed(1)}%`
    },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#999' }, itemWidth: 10, itemHeight: 8 },
    series: [{
      type: 'pie', radius: ['38%', '68%'], center: ['50%', '44%'],
      label: { formatter: (p: any) => `${p.name}\n¥${(p.value/10000).toFixed(1)}万`, fontSize: 10, color: '#ccc', lineHeight: 14 },
      labelLine: { lineStyle: { color: '#555' } },
      itemStyle: { borderColor: '#1a1a1a', borderWidth: 2 },
      emphasis: { label: { fontSize: 12, fontWeight: 'bold' }, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
      data: [
        ...(up.length ? [{ value: upVal, name: '盈利持仓', itemStyle: { color: '#f56c6c' } }] : []),
        ...(down.length ? [{ value: downVal, name: '亏损持仓', itemStyle: { color: '#409eff' } }] : []),
        { value: cashVal, name: '可用现金', itemStyle: { color: '#909399' } },
      ]
    }]
  }
})
</script>

<template>
  <div class="at" v-loading="loading">
    <!-- Risk Alert -->
    <div v-if="riskMonitor.status && riskMonitor.status !== 'healthy'" class="at-alert">
      ⚠️ {{ riskMonitor.desc }}
      <span v-if="brokenSL.length"> | 🔴 {{ brokenSL.length }}只破止损</span>
    </div>

    <!-- KPI -->
    <div class="at-kpi-header">
      <span class="at-kpi-title">💼 账户</span>
      <UnifiedDateBar @change="onDateChange" />
      <ElButton size="small" :type="rangeMode==='all'?'primary':'default'" @click="onSwitchToAll">全部</ElButton>
      <ElButton size="small" @click="fetchKpi" :loading="loading">🔄</ElButton>
    </div>
    <div class="at-kpi">
      <div class="at-kpi-c"><div class="at-kpi-l">总资产</div><div class="at-kpi-v">¥{{ (totalAssets ?? 0).toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">可用现金</div><div class="at-kpi-v">¥{{ (availableCash ?? 0).toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">持仓市值</div><div class="at-kpi-v">¥{{ (marketValue ?? 0).toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">总盈亏</div><div :class="['at-kpi-v', cls(totalProfit ?? 0)]">{{ (totalProfit ?? 0) >= 0 ? '+' : '' }}¥{{ Math.abs(totalProfit ?? 0).toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">收益率</div><div :class="['at-kpi-v', cls(totalProfit ?? 0)]">{{ ((totalProfit ?? 0) / 1000000 * 100).toFixed(2) }}%</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">仓位</div><div class="at-kpi-v">{{ (positionRatio || 0).toFixed(1) }}%</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">持仓</div><div class="at-kpi-v">{{ positions.length }}只<el-badge v-if="brokenSL.length" :value="brokenSL.length" type="danger" style="margin-left:4px" /></div></div>
    </div>

    <!-- Section Nav -->
    <div class="at-nav">
      <button :class="['at-nav-b', activeSection === 'overview' && 'on']" @click="activeSection = 'overview'">📊 资产分布</button>
      <button :class="['at-nav-b', activeSection === 'positions' && 'on']" @click="activeSection = 'positions'">💼 持仓明细</button>
      <button :class="['at-nav-b', activeSection === 'risk' && 'on']" @click="activeSection = 'risk'">🛡️ 风控状态</button>
    </div>

    <!-- ===== Overview ===== -->
    <div v-show="activeSection === 'overview'" class="at-sec">
      <!-- 盈亏构成 + 资产分布 (最重要，放最前) -->
      <div class="at-row2">
        <div class="at-card">
          <div class="at-card-t">📋 盈亏构成</div>
          <div class="eq-table">
            <div class="eq-row eq-head"><span class="eq-label">项目</span><span class="eq-val">金额</span><span class="eq-pct">占比</span></div>
            <div class="eq-row"><span class="eq-label">初始资金</span><span class="eq-val">¥1,000,000</span><span class="eq-pct muted">—</span></div>
            <div class="eq-row"><span class="eq-label">已实现盈亏</span><span :class="['eq-val', cls(realizedPnl ?? 0)]">{{ fmtPnl(realizedPnl ?? 0) }}</span><span class="eq-pct muted">{{ ((realizedPnl ?? 0) / 1000000 * 100).toFixed(2) }}%</span></div>
            <div class="eq-row"><span class="eq-label">未实现盈亏</span><span :class="['eq-val', cls(unrealizedPnl ?? 0)]">{{ fmtPnl(unrealizedPnl ?? 0) }}</span><span class="eq-pct muted">{{ ((unrealizedPnl ?? 0) / 1000000 * 100).toFixed(2) }}%</span></div>
            <div class="eq-sep"><span>── 持仓浮盈浮亏明细 ──</span></div>
            <div v-for="p in positions" :key="p.ts_code" class="eq-row eq-pos">
              <span class="eq-label"><span class="eq-pos-dot" :style="{background: (p.profit_pct||0)>=0?'#f56c6c':'#409eff'}"></span>{{ p.stock_name || p.ts_code?.slice(0,6) }}</span>
              <span :class="['eq-val', cls(p.profit_amount || 0)]">{{ fmtPnl(p.profit_amount || 0) }}</span>
              <span class="eq-pct" :class="cls(p.profit_pct || 0)">{{ fmtPct(p.profit_pct || 0) }}</span>
            </div>
            <div class="eq-row eq-total"><span class="eq-label">当前总资产</span><span class="eq-val">¥{{ (totalAssets ?? 0).toLocaleString() }}</span><span class="eq-pct">{{ fmtPct((totalProfit ?? 0) / 1000000 * 100) }}</span></div>
          </div>
        </div>
        <div class="at-card">
          <div class="at-card-t">🥧 资产分布</div>
          <VChart v-if="posPie" :option="posPie" autoresize style="height:240px;width:100%" />
          <div v-else class="at-empty">空仓</div>
        </div>
      </div>
      <!-- 折叠：资金曲线 -->
      <div class="review-section" style="cursor:pointer" @click="equityExpanded=!equityExpanded">
        <span class="section-title title-blue">📈 资金曲线 {{ equityExpanded?'▼':'▶' }}</span><span class="section-summary">已实现盈亏累计 · 当前¥{{ (totalAssets ?? 0).toLocaleString() }} · 总{{ fmtPct((totalProfit ?? 0) / 1000000 * 100) }}</span>
      </div>
      <div v-if="equityExpanded" class="at-card" style="margin-bottom:4px">
        <VChart v-if="equityCurve" :option="equityCurve" autoresize style="height:260px;width:100%" />
        <div v-else class="at-empty">无历史数据</div>
      </div>
      <!-- 折叠：每日盈亏 -->
      <div class="review-section" style="cursor:pointer" @click="dailyPnlExpanded=!dailyPnlExpanded">
        <span class="section-title title-purple">📊 每日盈亏 {{ dailyPnlExpanded?'▼':'▶' }}</span><span class="section-summary">{{ kpiData?.daily_detail?.length||0 }}个交易日</span>
      </div>
      <div v-if="dailyPnlExpanded" class="at-card" style="margin-bottom:4px">
        <VChart v-if="dailyPnlChart" :option="dailyPnlChart" autoresize style="height:220px;width:100%" />
        <div v-else class="at-empty">无交易数据</div>
      </div>
    </div>

    <!-- ===== Positions ===== -->
    <div v-show="activeSection === 'positions'" class="at-sec">
      <div v-if="!positions.length" class="at-empty">空仓</div>
      <div v-else class="at-card">
        <div class="at-card-t">💼 持仓明细 <span class="at-tag">{{ positions.length }}只</span>
          <span v-if="brokenSL.length" class="at-tag at-tag-danger">🔴 {{ brokenSL.length }}只破止损</span>
          <span v-if="nearSL.length" class="at-tag at-tag-warn">⚠ {{ nearSL.length }}只近止损</span>
          <span class="at-tag" style="margin-left:auto">点击行查看详情</span>
        </div>
        <!-- Cards layout instead of table -->
        <div class="pos-list">
          <div v-for="p in positions" :key="p.ts_code"
               :class="['pos-card', p.stop_loss_status === 'broken' ? 'pos-danger' : p.stop_loss_status === 'near' ? 'pos-warn' : '', expandedCode === p.ts_code ? 'pos-expanded' : '']"
               @click="toggleDetail(p.ts_code)">
            <!-- Row 1: Name + P&L -->
            <div class="pos-top">
              <div class="pos-name">
                <span class="pos-code">{{ p.ts_code?.slice(0,6) }}</span>
                <span class="pos-stock">{{ p.stock_name }}</span>
                <span v-if="p.stop_loss_status === 'broken'" class="sl-broken">🔴破止损</span>
                <span v-else-if="p.stop_loss_status === 'near'" class="sl-near">⚠近止损</span>
              </div>
              <div :class="['pos-pnl', cls(p.profit_pct || 0)]">
                <span class="pos-pnl-pct">{{ fmtPct(Number(p.profit_pct) || 0) }}</span>
                <span class="pos-pnl-amt">{{ fmtPnl(p.profit_amount || 0) }}</span>
              </div>
            </div>
            <!-- Row 2: Key numbers -->
            <div class="pos-metrics">
              <div class="pos-m"><span class="pos-ml">成本</span><span>¥{{ p.cost_price != null ? p.cost_price.toFixed(2) : '-' }}</span></div>
              <div class="pos-m"><span class="pos-ml">现价</span><span>¥{{ p.current_price != null ? p.current_price.toFixed(2) : '-' }}</span></div>
              <div class="pos-m"><span class="pos-ml">止损</span><span :class="p.stop_loss_status === 'broken' ? 'down' : 'muted'">¥{{ p.stop_loss_price != null ? p.stop_loss_price.toFixed(2) : '-' }}</span></div>
              <div class="pos-m"><span class="pos-ml">数量</span><span>{{ p.shares }}</span></div>
              <div class="pos-m"><span class="pos-ml">市值</span><span>¥{{ (p.market_value || 0).toLocaleString() }}</span></div>
              <div class="pos-m"><span class="pos-ml">仓位</span><span>{{ (totalAssets ?? 0) > 0 ? ((p.market_value || 0) / (totalAssets ?? 1) * 100).toFixed(1) : '0' }}%</span></div>
              <div class="pos-m" v-if="p.stop_loss_status === 'broken' && p.risk_monitor_desc"><span class="pos-ml">风控</span><span class="down" style="font-size:10px">⚠ {{ p.risk_monitor_desc }}</span></div>
            </div>
            <!-- Expand detail -->
            <div v-if="expandedCode === p.ts_code" class="pos-detail" @click.stop>
              <div v-if="detailLoading" style="text-align:center;padding:12px;color:var(--text-tertiary)">加载中...</div>
              <template v-else-if="detailData">
                <div class="pd-head">📋 {{ detailData.stock_name }} {{ detailData.ts_code }} 交易审查</div>
                <!-- Summary -->
                <div class="pd-grid">
                  <div class="pd-cell"><span class="pd-cl">策略</span><span>{{ detailData.strategy }}</span></div>
                  <div class="pd-cell"><span class="pd-cl">持仓量</span><span>{{ detailData.summary?.holding_qty }}</span></div>
                  <div class="pd-cell"><span class="pd-cl">均价</span><span>¥{{ detailData.summary?.avg_cost != null ? Number(detailData.summary.avg_cost).toFixed(2) : '-' }}</span></div>
                  <div class="pd-cell"><span class="pd-cl">现价</span><span>¥{{ detailData.summary?.current_price != null ? Number(detailData.summary.current_price).toFixed(2) : '-' }}</span></div>
                  <div class="pd-cell"><span class="pd-cl">浮盈亏</span><span :class="cls(detailData.summary?.holding_profit_pct ?? 0)">{{ (detailData.summary?.holding_profit_pct ?? 0).toFixed(1) }}%</span></div>
                  <div class="pd-cell"><span class="pd-cl">浮盈亏额</span><span :class="cls(detailData.summary?.holding_profit_amount ?? 0)">¥{{ (detailData.summary?.holding_profit_amount ?? 0).toLocaleString() }}</span></div>
                  <div class="pd-cell"><span class="pd-cl">持仓天数</span><span>{{ detailData.summary?.hold_days }}天</span></div>
                  <div class="pd-cell"><span class="pd-cl">市值</span><span>¥{{ (detailData.summary?.market_value || 0).toLocaleString() }}</span></div>
                </div>
                <!-- Trades -->
                <div class="pd-trade-head">📝 交易记录</div>
                <div v-for="(t, i) in detailData.trades" :key="i" class="pd-trade">
                  <span class="pd-trade-date">{{ t.date }} {{ t.time }}</span>
                  <span :class="t.action === 'buy' ? 'up' : 'down'" style="font-weight:600">{{ t.action === 'buy' ? '买入' : '卖出' }}</span>
                  <span>{{ t.shares }}股@¥{{ t.price?.toFixed(2) }}</span>
                  <span class="muted">¥{{ (t.amount || 0).toLocaleString() }}</span>
                  <span v-if="t.profit_pct != null" :class="cls(t.profit_pct)">{{ t.profit_pct >= 0 ? '+' : '' }}{{ t.profit_pct?.toFixed(1) }}%</span>
                  <span class="pd-trade-reason">{{ t.reason }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Risk ===== -->
    <div v-show="activeSection === 'risk'" class="at-sec">
      <div class="at-row2">
        <div class="at-card">
          <div class="at-card-t">🛡️ 系统风控</div>
          <div class="at-risk-row"><span>扫描器实例</span><span :class="riskMonitor.scanner_alive ? 'ok' : 'err'">{{ riskMonitor.scanner_alive ? '✅ 已创建' : '❌ 未创建' }}</span></div>
          <div class="at-risk-row"><span>扫描循环</span><span :class="riskMonitor.scan_loop_active ? 'ok' : 'err'">{{ riskMonitor.scan_loop_active ? '✅ 运行中' : '❌ 未启动' }}</span></div>
          <div class="at-risk-row"><span>风控线程</span><span :class="riskMonitor.risk_thread_alive ? 'ok' : 'err'">{{ riskMonitor.risk_thread_alive ? '✅ 运行中' : '❌ 未运行' }}</span></div>
          <div class="at-risk-row"><span>综合状态</span><span :class="riskMonitor.status === 'healthy' ? 'ok' : 'err'">{{ riskMonitor.desc || '未知' }}</span></div>
        </div>
        <div class="at-card">
          <div class="at-card-t">🔴 止损风险</div>
          <div class="at-risk-row"><span>🔴 破止损</span><span class="err">{{ brokenSL.length }}只 / ¥{{ Math.round(brokenSL.reduce((s: number, p: any) => s + Math.abs(p.profit_amount || 0), 0)).toLocaleString() }}</span></div>
          <div class="at-risk-row"><span>⚠️ 接近止损</span><span class="warn">{{ nearSL.length }}只</span></div>
          <div class="at-risk-row"><span>✅ 安全</span><span class="ok">{{ positions.length - brokenSL.length - nearSL.length }}只</span></div>
          <div v-if="brokenSL.length" class="at-broken-list">
            <div v-for="p in brokenSL" :key="p.ts_code" class="at-broken-item">{{ p.ts_code?.slice(0,6) }} {{ p.stock_name }} {{ (Number(p.profit_pct) || 0).toFixed(1) }}% (止损¥{{ p.stop_loss_price ?? '-' }})</div>
          </div>
        </div>
      </div>
      <!-- v2.9.92x: 风控参数概览(与回测对齐) → 三列网格布局 -->
      <div class="at-card" style="margin-top:6px">
        <div class="at-card-t">📐 风控参数 (与回测对齐)</div>
        <div class="at-param-grid">
          <div class="at-pg-item"><span class="at-pg-k">单票上限</span><span class="at-pg-v">{{ ((riskParams.max_position_per_stock ?? 0.35) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">总仓位上限</span><span class="at-pg-v">{{ ((riskParams.max_total_position ?? 0.75) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">默认止损</span><span class="at-pg-v">{{ ((riskParams.stop_loss_pct ?? 0.03) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">默认止盈</span><span class="at-pg-v">{{ ((riskParams.take_profit_pct ?? 0.10) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">流动性门槛</span><span class="at-pg-v">{{ riskParams.liquidity_threshold }}万</span></div>
          <div class="at-pg-item"><span class="at-pg-k">MA60过滤</span><span class="at-pg-v">{{ riskParams.enable_ma60_filter ? '✅' : '❌' }}</span></div>
          <div class="at-pg-item"><span class="at-pg-k">板块集中度</span><span class="at-pg-v">≤{{ riskParams.sector_concentration_top_n }}只/行业</span></div>
          <div class="at-pg-item"><span class="at-pg-k">冷却期</span><span class="at-pg-v">{{ riskParams.force_empty_cooldown_days ?? 2 }}天/≤{{ ((riskParams.force_empty_cooldown_position_cap ?? 0.6) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">次日高开卖</span><span class="at-pg-v">{{ ((riskParams.next_day_open_sell_pct || 0.02) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">持仓保护</span><span class="at-pg-v">{{ ((riskParams.hold_protection_threshold || 0) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">追踪止损</span><span class="at-pg-v">{{ ((riskParams.intraday_lock_pullback_pct || 0) * 100).toFixed(1) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">情绪:高潮/分化</span><span class="at-pg-v">{{ ((riskParams.sentiment_position_map?.rising || 1.0) * 100).toFixed(0) }}%/{{ ((riskParams.sentiment_position_map?.differentiation || 0.7) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">情绪:震荡/冰点</span><span class="at-pg-v">{{ ((riskParams.sentiment_position_map?.chaos || 0.5) * 100).toFixed(0) }}%/{{ ((riskParams.sentiment_position_map?.bearish || 0.3) * 100).toFixed(0) }}%</span></div>
          <div class="at-pg-item"><span class="at-pg-k">强制空仓-跌停</span><span class="at-pg-v">≥{{ riskParams.force_empty_limit_down }}只</span></div>
          <div class="at-pg-item"><span class="at-pg-k">强制空仓-大盘</span><span class="at-pg-v">跌幅≥{{ ((riskParams.force_empty_index_drop_pct ?? 0.03) * 100).toFixed(0) }}%</span></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.at { padding: 8px; flex: 1; overflow-y: auto; min-height: 0; }

/* Alert */
.at-alert { padding: 5px 10px; background: rgba(230,162,60,0.1); border: 1px solid rgba(230,162,60,0.3); border-radius: 4px; margin-bottom: 6px; font-size: 11px; color: #e6a23c; }

/* KPI - compact single row */
.at-kpi-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: nowrap; }
.at-kpi-title { font-size: 14px; font-weight: 700; }
.at-kpi { display: flex; gap: 2px; margin-bottom: 8px; flex-wrap: wrap; }
.at-kpi-c { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 4px; padding: 3px 8px; display: flex; align-items: baseline; gap: 3px; }
.at-kpi-l { font-size: 10px; color: var(--text-tertiary); }
.at-kpi-v { font-size: 12px; font-weight: 700; }

/* Nav */
.at-nav { display: flex; gap: 3px; margin-bottom: 6px; }
.at-nav-b { padding: 3px 8px; border: 1px solid var(--border); border-radius: 3px; background: transparent; color: var(--text-secondary); font-size: 11px; cursor: pointer; }
.at-nav-b:hover { background: var(--bg-hover); }
.at-nav-b.on { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }

/* Card */
.review-section { padding: 3px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 4px; margin-bottom: 2px; display: flex; align-items: baseline; gap: 4px; }
.section-title { font-size: 12px; font-weight: 600; }
.title-blue { color: #409eff; }
.title-purple { color: #a855f7; }
.at-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; }
.at-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.at-tag { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: var(--bg-muted); color: var(--text-tertiary); }
.at-tag-danger { color: var(--stock-up); background: rgba(8,153,129,0.1); }
.at-tag-warn { color: #e6a23c; background: rgba(230,162,60,0.1); }
.at-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }

/* 2-col grid */
.at-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* Scrollable equity breakdown */
.eq-table { font-size: 12px; }
.eq-row { display: flex; align-items: center; padding: 4px 6px; border-bottom: 1px solid var(--border-light); }
.eq-head { font-weight: 600; color: var(--text-tertiary); font-size: 11px; border-bottom: 2px solid var(--border); padding-bottom: 5px; }
.eq-label { flex: 1; min-width: 0; display: flex; align-items: center; gap: 4px; }
.eq-val { width: 90px; text-align: right; font-variant-numeric: tabular-nums; }
.eq-pct { width: 60px; text-align: right; font-variant-numeric: tabular-nums; font-size: 11px; }
.eq-pos-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.eq-sep { text-align: center; color: var(--text-tertiary); padding: 3px 6px; font-size: 11px; }
.eq-total { font-weight: 700; border-top: 2px solid var(--border); border-bottom: none; margin-top: 2px; padding-top: 5px; }
.section-summary { font-size: 11px; color: var(--text-tertiary); margin-left: 8px; }

/* ===== Position Cards ===== */
.pos-list { display: flex; flex-direction: column; gap: 5px; max-height: calc(100vh - 220px); overflow-y: auto; }
.pos-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 8px 10px; cursor: pointer; transition: border-color .15s; }
.pos-card:hover { border-color: var(--el-color-primary); }
.pos-card.pos-danger { border-left: 3px solid var(--stock-up); }
.pos-card.pos-warn { border-left: 3px solid #e6a23c; }
.pos-card.pos-expanded { border-color: var(--el-color-primary); }

.pos-top { display: flex; justify-content: space-between; align-items: center; }
.pos-name { display: flex; align-items: center; gap: 6px; }
.pos-code { font-size: 12px; color: var(--text-tertiary); font-family: monospace; }
.pos-stock { font-size: 13px; font-weight: 600; }
.pos-pnl { text-align: right; }
.pos-pnl-pct { font-size: 14px; font-weight: 700; margin-right: 6px; }
.pos-pnl-amt { font-size: 12px; }

.pos-metrics { display: flex; gap: 12px; margin-top: 4px; flex-wrap: wrap; }
.pos-m { font-size: 11px; color: var(--text-secondary); }
.pos-ml { color: var(--text-tertiary); margin-right: 2px; }

/* ===== Detail Panel ===== */
.pos-detail { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-light); }
.pd-head { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.pd-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px 12px; font-size: 12px; }
.pd-cell { display: flex; justify-content: space-between; padding: 3px 0; }
.pd-cl { color: var(--text-tertiary); }

.pd-trade-head { font-size: 12px; font-weight: 600; margin: 8px 0 4px; color: var(--text-secondary); }
.pd-trade { display: flex; gap: 8px; padding: 4px 6px; font-size: 12px; border-bottom: 1px solid var(--border-light); align-items: baseline; }
.pd-trade-date { font-family: monospace; color: var(--text-tertiary); font-size: 11px; min-width: 90px; }
.pd-trade-reason { color: var(--text-tertiary); font-size: 11px; flex: 1; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Color classes */
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.warn { color: #e6a23c; }
.muted { color: var(--text-tertiary); }
.b { font-weight: 600; }
.ok { color: var(--stock-down); font-weight: 500; }
.err { color: var(--stock-up); font-weight: 500; }

/* Stop-loss badges */
.sl-broken { color: var(--stock-up); font-weight: 600; font-size: 11px; }
.sl-near { color: #e6a23c; font-size: 11px; }
.sl-ok { color: var(--text-tertiary); font-size: 11px; }

/* Risk rows */
.at-risk-row { display: flex; justify-content: space-between; padding: 5px 6px; border-bottom: 1px solid var(--border-light); font-size: 12px; }
/* 风控参数网格 */
.at-param-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border-light); border: 1px solid var(--border-light); border-radius: 4px; overflow: hidden; }
.at-pg-item { background: var(--bg-card); padding: 6px 8px; display: flex; flex-direction: column; gap: 2px; }
.at-pg-k { font-size: 10px; color: var(--text-tertiary); }
.at-pg-v { font-size: 13px; font-weight: 600; }

/* Broken list */
.at-broken-list { margin-top: 6px; padding: 6px 8px; background: rgba(8,153,129,0.08); border-radius: 4px; }
.at-broken-item { font-size: 11px; color: var(--stock-up); padding: 1px 0; }
</style>
