<script setup lang="ts">
import { useChartColors } from './useChartColors'
/**
 * AnalysisTab — 市场监听结果分析
 * 参考BacktestResultPanel: KPI卡片→卖出分布条→分区导航→图表
 * 含: 日收益率、累计收益、绩效雷达、盈亏分布、交易占比、卖出原因、月度收益、策略贡献、持仓
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElEmpty, ElDialog } from 'element-plus'
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart, RadarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent } from 'echarts/components'

use([CanvasRenderer, LineChart, BarChart, PieChart, RadarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent])
const c = useChartColors().value

const m = useScannerMonitorInject()
const { activeTab } = m
const loading = ref(false)
const dateRange = ref<[string, string] | null>(null)
const analysisData = ref<any>(null)
const activeSection = ref('overview')

function defaultDateRange(): [string, string] {
  const now = new Date()
  const week = new Date(now.getTime() - 7 * 86400000)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  return [fmt(week), fmt(now)]
}

async function fetchAnalysis() {
  loading.value = true
  try {
    let url = '/scanner/analysis'
    const dr = dateRange.value
    if (dr && dr[0] && dr[1]) url += `?start_date=${dr[0].replace(/-/g, '')}&end_date=${dr[1].replace(/-/g, '')}`
    const r = await api.get(url)
    const p = parseResponse(r)
    if (p.success) analysisData.value = p.data
  } catch (e) { console.error('[Analysis]', e) }
  finally { loading.value = false }
}

onMounted(() => { if (!dateRange.value) dateRange.value = defaultDateRange(); fetchAnalysis() })
watch(activeTab, (t) => { if (t === 'analysis') fetchAnalysis() })

const kpi = computed(() => analysisData.value?.kpi || {})
const strategies = computed(() => analysisData.value?.strategy_contrib || [])
const sellReasons = computed(() => analysisData.value?.sell_reasons || [])
const monthly = computed(() => analysisData.value?.monthly || [])
const dailyDetail = computed(() => analysisData.value?.daily_detail || [])
const positions = computed(() => (analysisData.value?.positions || []).slice().sort((a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)))
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
  return { tooltip: { trigger: 'item', formatter: '{b}: {c}笔 ({d}%)' }, series: [{ type: 'pie', radius: ['35%', '65%'], label: { formatter: '{b}\n{c}笔', fontSize: 11 }, data: ss.map((s: any) => ({ name: s.strategy, value: s.trades, itemStyle: { color: s.profit >= 0 ? c.stockDown : c.stockUp } })) }] }
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
  return { tooltip: { trigger: 'item' }, radar: { indicator: [{ name: '胜率(%)', max: 100 }, { name: '盈亏比', max: maxPLR }, { name: '回撤控制', max: 100 }, { name: '均盈亏(%)', max: Math.max(10, Math.ceil(Math.abs(k.avg_profit_pct || 0)) + 3) }, { name: '交易数', max: Math.max(30, (k.total_trades || 0) + 10) }] }, series: [{ type: 'radar', data: [{ name: '组合绩效', value: [k.win_rate || 0, k.profit_loss_ratio || 0, ddCtrl, Math.abs(k.avg_profit_pct || 0), k.total_trades || 0] }] }] }
})

const monthlyChart = computed(() => {
  const mm = monthly.value; if (!mm.length) return null
  return { tooltip: { trigger: 'axis' }, legend: { data: ['月度收益', '累计收益'] }, grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true }, xAxis: { type: 'category', data: mm.map((m: any) => m.month) }, yAxis: [{ type: 'value', name: '月度¥' }, { type: 'value', name: '累计¥', position: 'right' }], series: [{ name: '月度收益', type: 'bar', data: mm.map((m: any) => m.profit), itemStyle: { color: (p: any) => p.value >= 0 ? c.stockDown : c.stockUp }, label: { show: true, position: 'top', fontSize: 10 } }, { name: '累计收益', type: 'line', yAxisIndex: 1, data: mm.map((m: any) => m.cum_profit), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: c.primary } }] }
})

const profitDistChart = computed(() => {
  const k = kpi.value; if (!k.total_trades) return null
  const wins = k.win_count || Math.round(k.total_trades * k.win_rate / 100)
  return { tooltip: { trigger: 'item' }, series: [{ type: 'pie', radius: ['35%', '65%'], label: { formatter: '{b}\n{c}笔', fontSize: 12 }, data: [{ name: '盈利', value: wins, itemStyle: { color: c.stockDown } }, { name: '亏损', value: k.loss_count || (k.total_trades - wins), itemStyle: { color: c.stockUp } }] }] }
})

const selectedDay = ref('')
const dailyTrades = ref<any[]>([])
const dailyTradesLoading = ref(false)
async function showDayDetail(date: string) {
  if (selectedDay.value === date) { selectedDay.value = ''; dailyTrades.value = []; return }
  selectedDay.value = date; dailyTradesLoading.value = true
  try { const d = date.replace(/-/g, ''); const r = await api.get(`/scanner/timeline/history?date=${d}`); const p = parseResponse(r); if (p.success) dailyTrades.value = (p.data || []).filter((t: any) => t.action !== 'blocked') } catch {} finally { dailyTradesLoading.value = false }
}

// 个股详情
const stockDetailVisible = ref(false)
const stockDetail = ref<any>(null)
const stockDetailLoading = ref(false)
async function showStockDetail(tsCode: string) {
  stockDetailLoading.value = true; stockDetailVisible.value = true; stockDetail.value = null
  try { const r = await api.get(`/scanner/analysis/stock/${tsCode}`); const p = parseResponse(r); if (p.success) stockDetail.value = p.data } catch {} finally { stockDetailLoading.value = false }
}
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll ana-wrap">
      <div class="ana-toolbar">
        <span class="ana-title">📊 结果分析</span>
        <ElDatePicker v-model="dateRange" type="daterange" start-placeholder="开始" end-placeholder="结束" size="small" value-format="YYYY-MM-DD" style="width:220px" :disabled-date="(d: Date) => d > new Date()" />
        <ElButton size="small" type="primary" @click="fetchAnalysis" :loading="loading">刷新</ElButton>
      </div>

      <div v-if="!analysisData && !loading" class="ana-empty"><ElEmpty description="点击刷新加载数据" /></div>
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
              <span class="reason-dot"></span>{{ r.reason }}{{ r.count }}笔({{ (r.count / totalReasonCount * 100).toFixed(0) }}%)
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
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title">📊 日收益率</div><VChart v-if="dailyProfitChart" :option="dailyProfitChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
            <div class="chart-half"><div class="chart-title">📈 累计盈亏</div><VChart v-if="cumProfitChart" :option="cumProfitChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
          </div>
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title">🎯 绩效雷达</div><VChart v-if="radarChart" :option="radarChart" autoresize style="height:300px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
            <div class="chart-half"><div class="chart-title">🍩 盈亏分布</div><VChart v-if="profitDistChart" :option="profitDistChart" autoresize style="height:300px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
          </div>
          <div class="chart-row">
            <div class="chart-half"><div class="chart-title">🔄 交易占比(策略)</div><VChart v-if="strategyPieChart" :option="strategyPieChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
            <div class="chart-half"><div class="chart-title">📤 卖出原因</div><VChart v-if="sellReasonChart" :option="sellReasonChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="暂无数据" :image-size="40" /></div>
          </div>
          <div v-if="monthly.length" class="chart-section"><div class="chart-title">📅 月度收益</div><VChart v-if="monthlyChart" :option="monthlyChart" autoresize style="height:300px;width:100%" /></div>
          <div v-if="strategies.length" class="chart-section">
            <div class="chart-title">🔄 策略贡献</div>
            <table class="ana-tbl"><thead><tr><th>策略</th><th>笔数</th><th>胜率</th><th>盈亏</th><th>均盈亏%</th></tr></thead><tbody>
              <tr v-for="s in strategies" :key="s.strategy" :class="s.profit >= 0 ? 'row-up' : 'row-down'"><td class="td-strat">{{ s.strategy }}</td><td>{{ s.trades }}</td><td :class="s.win_rate >= 50 ? 'up' : 'down'">{{ s.win_rate.toFixed(1) }}%</td><td :class="s.profit >= 0 ? 'up' : 'down'">¥{{ s.profit.toLocaleString() }}</td><td :class="s.avg_profit_pct >= 0 ? 'up' : 'down'">{{ s.avg_profit_pct.toFixed(2) }}%</td></tr>
            </tbody></table>
          </div>
        </div>

        <!-- ========== 持仓 ========== -->
        <div :class="['section-content', { 'section-hidden': activeSection !== 'position' }]">
          <div class="chart-section"><div class="chart-title">💼 持仓盈亏分布 <span class="ana-stat">{{ positions.length }}只</span></div><VChart v-if="positionChart" :option="positionChart" autoresize style="height:280px;width:100%" /><ElEmpty v-else description="空仓或无数据" :image-size="40" /></div>
          <div v-if="positions.length" class="chart-section">
            <div class="chart-title">📋 持仓明细</div>
            <table class="ana-tbl"><thead><tr><th>代码</th><th>名称</th><th>策略</th><th>数量</th><th>成本</th><th>最新收盘</th><th>盈亏%</th><th>盈亏额</th><th>市值</th><th></th></tr></thead><tbody>
              <tr v-for="p in positions" :key="p.ts_code" :class="p.profit_pct >= 0 ? 'row-up' : 'row-down'"><td>{{ p.ts_code?.slice(0,6) }}</td><td>{{ p.stock_name }}</td><td>{{ p.strategy }}</td><td>{{ p.shares }}</td><td>¥{{ p.cost_price }}</td><td>¥{{ p.current_price }}</td><td :class="p.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct.toFixed(1) }}%</td><td :class="p.profit_amount >= 0 ? 'up' : 'down'">¥{{ p.profit_amount.toLocaleString() }}</td><td>¥{{ p.market_value.toLocaleString() }}</td><td><ElButton size="small" text type="primary" @click="showStockDetail(p.ts_code)">详情</ElButton></td></tr>
            </tbody></table>
          </div>
        </div>

        <!-- ========== 明细 ========== -->
        <div :class="['section-content', { 'section-hidden': activeSection !== 'detail' }]">
          <div class="chart-section">
            <div class="chart-title">📋 每日明细 <span class="ana-stat">点击展开</span></div>
            <div v-if="!dailyDetail.length" class="ana-empty-sm">暂无数据</div>
            <table class="ana-tbl" v-else><thead><tr><th>日期</th><th>笔数</th><th>胜率</th><th>盈亏</th></tr></thead><tbody>
              <template v-for="d in dailyDetail" :key="d.date">
                <tr class="dl-row" :class="d.profit >= 0 ? 'row-up' : 'row-down'" @click="showDayDetail(d.date)" style="cursor:pointer"><td>{{ d.date }} <span style="font-size:9px;color:var(--text-tertiary)">{{ selectedDay === d.date ? '▲' : '▼' }}</span></td><td>{{ d.trades }}</td><td :class="d.win_rate >= 50 ? 'up' : 'down'">{{ d.win_rate }}%</td><td :class="d.profit >= 0 ? 'up' : 'down'">¥{{ d.profit.toLocaleString() }}</td></tr>
                <tr v-if="selectedDay === d.date"><td colspan="4" style="padding:4px 8px;background:var(--bg-muted)">
                  <div v-if="dailyTradesLoading" style="font-size:11px;color:var(--text-tertiary)">加载中...</div>
                  <div v-else-if="!dailyTrades.length" style="font-size:11px;color:var(--text-tertiary)">无交易记录</div>
                  <table v-else class="sub-tbl"><thead><tr><th>时间</th><th>方向</th><th>代码</th><th>名称</th><th>价格</th><th>数量</th><th>盈亏%</th><th>盈亏额</th><th>原因</th></tr></thead><tbody>
                    <tr v-for="(t, i) in dailyTrades" :key="i"><td>{{ t.time }}</td><td :class="t.action === 'buy' ? 'up' : t.action === 'sell' ? 'down' : ''">{{ t.action === 'buy' ? '买' : t.action === 'sell' ? '卖' : '⛔' }}</td><td>{{ t.ts_code?.slice(0,6) }}</td><td>{{ t.stock_name }}</td><td>{{ t.price }}</td><td>{{ t.shares }}</td><td :class="(t.profit_pct ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_pct != null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(1) + '%' : '-' }}</td><td :class="(t.profit_amount ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_amount != null ? '¥' + t.profit_amount.toFixed(0) : '-' }}</td><td style="font-size:10px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.reason || '-' }}</td></tr>
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
              <div class="sd-kpi-val">{{ stockDetail.summary.holding_profit_pct != null ? (stockDetail.summary.holding_profit_pct >= 0 ? '+' : '') + stockDetail.summary.holding_profit_pct.toFixed(1) + '%' : '--' }}</div>
            </div>
            <div class="sd-kpi" :class="stockDetail.summary.realized_profit >= 0 ? 'sd-up' : 'sd-down'">
              <div class="sd-kpi-label">已实现盈亏</div>
              <div class="sd-kpi-val">¥{{ stockDetail.summary.realized_profit.toLocaleString() }}</div>
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
                  <td :class="(t.profit_pct ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_pct != null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(1) + '%' : '-' }}</td>
                  <td :class="(t.profit_amount ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_amount != null ? '¥' + t.profit_amount.toFixed(0) : '-' }}</td>
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
.ana-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-default); }
.ana-title { font-size: 14px; font-weight: 700; }
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
