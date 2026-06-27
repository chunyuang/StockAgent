<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, LineChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { useChartColors } from './useChartColors'
import UnifiedDateBar from './components/UnifiedDateBar.vue'

use([CanvasRenderer, PieChart, LineChart, BarChart, TooltipComponent, LegendComponent, GridComponent])
import { GLOBAL_RISK } from '@/config/strategyDefaults'
import { useUnifiedData } from './composables/useUnifiedData'

const c = useChartColors().value
const loading = ref(false)
const kpiData = ref<any>(null)  // KPI/账户资金(仍从/analysis获取)
const activeSection = ref('overview')

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
const totalProfit = computed(() => totalAssets.value - 1000000)
const positionRatio = computed(() => totalAssets.value > 0 ? marketValue.value / totalAssets.value * 100 : 0)
const riskParams = GLOBAL_RISK  // 前端参数与后端strategy_defaults.py完全对齐(由sync脚本同步)
const brokenSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'broken'))
const nearSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'near'))

const fmt = (v: number) => `¥${((v || 0) / 10000).toFixed(2)}万`
const cls = (v: number) => v >= 0 ? 'up' : 'down'

const realizedPnl = computed(() => {
  const positions_pnl = positions.value.reduce((s: number, p: any) => s + (p.profit_amount || 0), 0)
  return totalProfit.value - positions_pnl
})

// ===== 资金曲线 (从daily trades构建) =====
const equityCurve = computed(() => {
  const dd = kpiData.value?.daily_detail || []
  if (!dd.length) return null
  // 从daily_detail构建累计净值曲线
  let cumPnl = 0
  const initial = 1000000
  const dates = dd.map((d: any) => d.date)
  const values = dd.map((d: any) => { cumPnl += d.profit || 0; return initial + cumPnl })
  const returns = values.map((v: number) => ((v / initial) - 1) * 100)
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(30,30,30,0.92)', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 } },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 }, axisLine: { lineStyle: { color: '#444' } } },
    yAxis: [
      { type: 'value', name: '净值¥', axisLabel: { fontSize: 10, formatter: (v: number) => (v/10000).toFixed(0)+'万' }, splitLine: { lineStyle: { color: '#333', type: 'dashed' } } },
      { type: 'value', name: '收益率%', position: 'right', axisLabel: { fontSize: 10, formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '总资产', type: 'line', data: values, smooth: 0.3, lineStyle: { width: 2, color: c.primary }, itemStyle: { color: c.primary }, symbol: 'circle', symbolSize: 6, areaStyle: { opacity: 0.08 } },
      { name: '收益率', type: 'line', data: returns, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 1, color: '#a855f7', type: 'dashed' }, itemStyle: { color: '#a855f7' }, symbol: 'none' },
    ],
  }
})

// ===== 每日盈亏柱状图 =====
const dailyPnlChart = computed(() => {
  const dd = kpiData.value?.daily_detail || []
  if (!dd.length) return null
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(30,30,30,0.92)', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 } },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: dd.map((d: any) => d.date), axisLabel: { fontSize: 10 }, axisLine: { lineStyle: { color: '#444' } } },
    yAxis: { type: 'value', name: '¥', axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#333', type: 'dashed' } } },
    series: [{ type: 'bar', data: dd.map((d: any) => d.profit || 0), itemStyle: { color: (p: any) => p.value >= 0 ? c.stockDown : c.stockUp, borderRadius: [2,2,0,0] }, label: { show: true, position: 'top', fontSize: 10, formatter: (p: any) => p.value >= 0 ? '+'+p.value : p.value } }],
  }
})

const posPie = computed(() => {
  const pos = positions.value
  if (!pos.length) return null
  const up = pos.filter((p: any) => (p.profit_pct ?? 0) >= 0)
  const down = pos.filter((p: any) => (p.profit_pct ?? 0) < 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#999' } },
    series: [{
      type: 'pie', radius: ['35%', '65%'], center: ['50%', '45%'],
      label: { formatter: '{b}\n{d}%', fontSize: 10, color: '#999' },
      data: [
        ...(up.length ? [{ value: Math.round(up.reduce((s: number, p: any) => s + p.market_value, 0)), name: '盈利持仓', itemStyle: { color: c.stockDown } }] : []),
        ...(down.length ? [{ value: Math.round(down.reduce((s: number, p: any) => s + p.market_value, 0)), name: '亏损持仓', itemStyle: { color: c.stockUp } }] : []),
        { value: Math.round(availableCash.value), name: '可用现金', itemStyle: { color: '#909399' } },
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
      <div class="at-kpi-c"><div class="at-kpi-l">总资产</div><div class="at-kpi-v">¥{{ totalAssets.toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">可用现金</div><div class="at-kpi-v">¥{{ availableCash.toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">持仓市值</div><div class="at-kpi-v">¥{{ marketValue.toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">总盈亏</div><div :class="['at-kpi-v', cls(totalProfit)]">{{ totalProfit >= 0 ? '+' : '' }}¥{{ Math.abs(totalProfit).toLocaleString() }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">收益率</div><div :class="['at-kpi-v', cls(totalProfit)]">{{ (totalProfit / 1000000 * 100).toFixed(2) }}%</div></div>
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
      <!-- 资金曲线 -->
      <div class="at-card" style="margin-bottom:6px">
        <div class="at-card-t">📈 资金曲线 <span style="font-weight:400;font-size:10px;color:var(--text-tertiary)">初始¥100万</span></div>
        <VChart v-if="equityCurve" :option="equityCurve" autoresize style="height:200px;width:100%" />
        <div v-else class="at-empty">无历史数据</div>
      </div>
      <!-- 每日盈亏 -->
      <div class="at-card" style="margin-bottom:6px">
        <div class="at-card-t">📊 每日盈亏</div>
        <VChart v-if="dailyPnlChart" :option="dailyPnlChart" autoresize style="height:160px;width:100%" />
        <div v-else class="at-empty">无交易数据</div>
      </div>
      <div class="at-row2">
        <div class="at-card">
          <div class="at-card-t">🥧 资产分布</div>
          <VChart v-if="posPie" :option="posPie" autoresize style="height:260px;width:100%" />
          <div v-else class="at-empty">空仓</div>
        </div>
        <div class="at-card">
          <div class="at-card-t">📋 盈亏构成</div>
          <div class="at-scroll">
            <div class="at-eq-row at-eq-head"><span>项目</span><span>金额</span></div>
            <div class="at-eq-row"><span>初始资金</span><span>¥1,000,000</span></div>
            <div class="at-eq-row"><span>已实现盈亏</span><span :class="cls(kpiData?.kpi?.total_profit||0)">{{ ((kpiData?.kpi?.total_profit||0) >= 0 ? '+' : '') }}¥{{ Math.abs(kpiData?.kpi?.total_profit||0).toLocaleString() }}</span></div>
            <div class="at-eq-row at-eq-sep"><span style="font-size:11px;color:var(--text-tertiary)">── 未实现盈亏(浮盈浮亏) ──</span><span></span></div>
            <div v-for="p in positions" :key="p.ts_code" class="at-eq-row">
              <span class="at-eq-name">{{ p.stock_name || p.ts_code?.slice(0,6) }}</span>
              <span :class="cls(p.profit_amount || 0)">{{ (p.profit_amount || 0) >= 0 ? '+' : '' }}¥{{ ((p.profit_amount || 0) / 10000).toFixed(2) }}万</span>
            </div>
            <div class="at-eq-row at-eq-total"><span>当前总资产</span><span>¥{{ (totalAssets || 0).toLocaleString() }}</span></div>
          </div>
        </div>
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
                <span class="pos-pnl-pct">{{ (Number(p.profit_pct) || 0) >= 0 ? '+' : '' }}{{ (Number(p.profit_pct) || 0).toFixed(1) }}%</span>
                <span class="pos-pnl-amt">{{ (p.profit_amount || 0) >= 0 ? '+' : '' }}¥{{ Math.abs(p.profit_amount || 0).toLocaleString() }}</span>
              </div>
            </div>
            <!-- Row 2: Key numbers -->
            <div class="pos-metrics">
              <div class="pos-m"><span class="pos-ml">成本</span><span>¥{{ p.cost_price?.toFixed(2) }}</span></div>
              <div class="pos-m"><span class="pos-ml">现价</span><span>¥{{ p.current_price?.toFixed(2) }}</span></div>
              <div class="pos-m"><span class="pos-ml">止损</span><span :class="p.stop_loss_status === 'broken' ? 'down' : 'muted'">¥{{ p.stop_loss_price?.toFixed(2) || '-' }}</span></div>
              <div class="pos-m"><span class="pos-ml">数量</span><span>{{ p.shares }}</span></div>
              <div class="pos-m"><span class="pos-ml">市值</span><span>¥{{ (p.market_value || 0).toLocaleString() }}</span></div>
              <div class="pos-m"><span class="pos-ml">仓位</span><span>{{ totalAssets > 0 ? ((p.market_value || 0) / totalAssets * 100).toFixed(1) : 0 }}%</span></div>
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
                  <div class="pd-cell"><span class="pd-cl">浮盈亏</span><span :class="cls(detailData.summary?.holding_profit_pct || 0)">{{ (detailData.summary?.holding_profit_pct || 0).toFixed(1) }}%</span></div>
                  <div class="pd-cell"><span class="pd-cl">浮盈亏额</span><span :class="cls(detailData.summary?.holding_profit_amount || 0)">¥{{ (detailData.summary?.holding_profit_amount || 0).toLocaleString() }}</span></div>
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
.at-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; }
.at-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.at-tag { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: var(--bg-muted); color: var(--text-tertiary); }
.at-tag-danger { color: var(--stock-up); background: rgba(8,153,129,0.1); }
.at-tag-warn { color: #e6a23c; background: rgba(230,162,60,0.1); }
.at-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }

/* 2-col grid */
.at-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* Scrollable equity breakdown */
.at-scroll { max-height: 320px; overflow-y: auto; }
.at-eq-row { display: flex; justify-content: space-between; padding: 3px 6px; border-bottom: 1px solid var(--border-light); font-size: 12px; }
.at-eq-head { font-weight: 600; color: var(--text-tertiary); font-size: 11px; border-bottom: 2px solid var(--border); }
.at-eq-name { max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.at-eq-sep { text-align: center; color: var(--text-tertiary); border-bottom: none; }
.at-eq-total { font-weight: 700; border-top: 2px solid var(--border); border-bottom: none; margin-top: 2px; }

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
