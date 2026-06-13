<script setup lang="ts">
/**
 * AnalysisTab — 市场监听结果分析
 * 参考回测结果分析，含KPI卡片、策略贡献、卖出原因、月度收益、累计收益曲线、每日明细
 * v2.9.92h: 修复数据对齐、持仓数据、图表
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElTag, ElEmpty } from 'element-plus'
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent } from 'echarts/components'

use([CanvasRenderer, LineChart, BarChart, PieChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent])

const m = useScannerMonitorInject()
const { activeTab } = m

const loading = ref(false)
const dateRange = ref<[string, string] | null>(null)
const analysisData = ref<any>(null)
const selectedDay = ref('')

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
    if (dr && dr[0] && dr[1]) {
      url += `?start_date=${dr[0].replace(/-/g, '')}&end_date=${dr[1].replace(/-/g, '')}`
    }
    const r = await api.get(url)
    const p = parseResponse(r)
    if (p.success) analysisData.value = p.data
  } catch (e) { console.error('[Analysis]', e) }
  finally { loading.value = false }
}

onMounted(() => {
  if (!dateRange.value) dateRange.value = defaultDateRange()
  fetchAnalysis()
})
watch(activeTab, (t) => { if (t === 'analysis') fetchAnalysis() })

const kpi = computed(() => analysisData.value?.kpi || {})
const strategies = computed(() => analysisData.value?.strategy_contrib || [])
const sellReasons = computed(() => analysisData.value?.sell_reasons || [])
const monthly = computed(() => analysisData.value?.monthly || [])
const dailyDetail = computed(() => analysisData.value?.daily_detail || [])
const positions = computed(() => analysisData.value?.positions || [])
const totalReasonCount = computed(() => sellReasons.value.reduce((s: number, r: any) => s + r.count, 0) || 1)

// 累计收益曲线
const cumProfitChart = computed(() => {
  const dd = dailyDetail.value
  if (!dd.length) return null
  const dates = dd.map((d: any) => d.date)
  const cumProfits = dd.map((d: any) => d.cum_profit ?? d.profit)
  const dailyProfits = dd.map((d: any) => d.profit)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['每日盈亏', '累计盈亏'] },
    grid: { left: 60, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: '¥' },
      { type: 'value', name: '累计¥' },
    ],
    series: [
      { name: '每日盈亏', type: 'bar', data: dailyProfits, itemStyle: { color: (p: any) => p.value >= 0 ? '#f5222d' : '#52c41a' } },
      { name: '累计盈亏', type: 'line', yAxisIndex: 1, data: cumProfits, smooth: true, lineStyle: { width: 2 }, areaStyle: { opacity: 0.1 } },
    ],
  }
})

// 卖出原因饼图
const sellReasonChart = computed(() => {
  const rs = sellReasons.value
  if (!rs.length) return null
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}笔 ({d}%)' },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      label: { formatter: '{b}\n{c}笔', fontSize: 11 },
      data: rs.map((r: any) => ({
        name: r.reason, value: r.count,
        itemStyle: { color: r.profit >= 0 ? '#f5222d' : '#52c41a' }
      })),
    }],
  }
})

// 每日明细展开
const dailyTrades = ref<any[]>([])
const dailyTradesLoading = ref(false)
async function showDayDetail(date: string) {
  if (selectedDay.value === date) { selectedDay.value = ''; dailyTrades.value = []; return }
  selectedDay.value = date
  dailyTradesLoading.value = true
  try {
    const d = date.replace(/-/g, '')
    const r = await api.get(`/scanner/timeline/history?date=${d}`)
    const p = parseResponse(r)
    if (p.success) {
      dailyTrades.value = (p.data || []).filter((t: any) => t.action !== 'blocked')
    }
  } catch {} finally { dailyTradesLoading.value = false }
}
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll ana-wrap">
      <!-- 工具栏 -->
      <div class="ana-toolbar">
        <span class="ana-title">📊 结果分析</span>
        <ElDatePicker v-model="dateRange" type="daterange" start-placeholder="开始" end-placeholder="结束" size="small" value-format="YYYY-MM-DD" style="width:220px" :disabled-date="(d: Date) => d > new Date()" />
        <ElButton size="small" type="primary" @click="fetchAnalysis" :loading="loading">刷新</ElButton>
      </div>

      <div v-if="!analysisData && !loading" class="ana-empty"><ElEmpty description="点击刷新加载数据" /></div>
      <div v-if="loading" class="ana-loading">加载中...</div>

      <template v-if="analysisData && !loading">
        <!-- KPI -->
        <div class="ana-kpis">
          <div class="kpi-card" :class="kpi.total_profit >= 0 ? 'kpi-up' : 'kpi-down'">
            <div class="kpi-label">累计盈亏</div>
            <div class="kpi-val">¥{{ (kpi.total_profit || 0).toLocaleString() }}</div>
          </div>
          <div class="kpi-card" :class="(kpi.win_rate || 0) >= 50 ? 'kpi-up' : 'kpi-down'">
            <div class="kpi-label">胜率</div>
            <div class="kpi-val">{{ (kpi.win_rate || 0).toFixed(1) }}%</div>
          </div>
          <div class="kpi-card kpi-neutral"><div class="kpi-label">交易笔数</div><div class="kpi-val">{{ kpi.total_trades || 0 }}</div></div>
          <div class="kpi-card" :class="(kpi.profit_loss_ratio || 0) >= 2 ? 'kpi-up' : 'kpi-warn'"><div class="kpi-label">盈亏比</div><div class="kpi-val">{{ (kpi.profit_loss_ratio || 0).toFixed(2) }}</div></div>
          <div class="kpi-card kpi-warn"><div class="kpi-label">最大回撤</div><div class="kpi-val">{{ (kpi.max_drawdown || 0).toFixed(1) }}%</div></div>
          <div class="kpi-card kpi-neutral"><div class="kpi-label">均盈亏%</div><div class="kpi-val" :class="(kpi.avg_profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (kpi.avg_profit_pct || 0).toFixed(2) }}%</div></div>
        </div>

        <div class="ana-grid">
          <!-- 左栏 -->
          <div class="ana-col">
            <!-- 累计收益曲线 -->
            <div class="ana-panel">
              <div class="ana-sec">📈 每日盈亏 & 累计</div>
              <VChart v-if="cumProfitChart" :option="cumProfitChart" autoresize style="height:280px;width:100%" />
              <div v-else class="ana-empty-sm">暂无数据</div>
            </div>

            <!-- 每日明细 -->
            <div class="ana-panel">
              <div class="ana-sec">📋 每日明细 <span class="ana-stat">点击展开</span></div>
              <div v-if="!dailyDetail.length" class="ana-empty-sm">暂无数据</div>
              <table class="ana-tbl" v-else>
                <thead><tr><th>日期</th><th>笔数</th><th>胜率</th><th>盈亏</th></tr></thead>
                <tbody>
                  <template v-for="d in dailyDetail" :key="d.date">
                    <tr class="dl-row" :class="d.profit >= 0 ? 'row-up' : 'row-down'" @click="showDayDetail(d.date)" style="cursor:pointer">
                      <td>{{ d.date }} <span style="font-size:9px;color:var(--text-tertiary)">{{ selectedDay === d.date ? '▲' : '▼' }}</span></td>
                      <td>{{ d.trades }}</td>
                      <td :class="d.win_rate >= 50 ? 'up' : 'down'">{{ d.win_rate }}%</td>
                      <td :class="d.profit >= 0 ? 'up' : 'down'">¥{{ d.profit.toLocaleString() }}</td>
                    </tr>
                    <tr v-if="selectedDay === d.date">
                      <td colspan="4" style="padding:4px 8px;background:var(--bg-muted)">
                        <div v-if="dailyTradesLoading" style="font-size:11px;color:var(--text-tertiary)">加载中...</div>
                        <div v-else-if="!dailyTrades.length" style="font-size:11px;color:var(--text-tertiary)">无交易记录</div>
                        <table v-else class="sub-tbl">
                          <thead><tr><th>时间</th><th>方向</th><th>代码</th><th>名称</th><th>盈亏%</th><th>盈亏额</th></tr></thead>
                          <tbody>
                            <tr v-for="(t, i) in dailyTrades" :key="i">
                              <td>{{ t.time }}</td>
                              <td :class="t.action === 'buy' ? 'up' : t.action === 'sell' ? 'down' : ''">{{ t.action === 'buy' ? '买' : t.action === 'sell' ? '卖' : '⛔' }}</td>
                              <td>{{ t.ts_code?.slice(0,6) }}</td>
                              <td>{{ t.stock_name }}</td>
                              <td :class="(t.profit_pct ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_pct != null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(1) + '%' : '-' }}</td>
                              <td :class="(t.profit_amount ?? 0) >= 0 ? 'up' : 'down'">{{ t.profit_amount != null ? '¥' + t.profit_amount.toFixed(0) : '-' }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 右栏 -->
          <div class="ana-col">
            <!-- 策略贡献 -->
            <div class="ana-panel">
              <div class="ana-sec">🔄 策略贡献</div>
              <div v-if="!strategies.length" class="ana-empty-sm">暂无数据</div>
              <table class="ana-tbl" v-else>
                <thead><tr><th>策略</th><th>笔数</th><th>胜率</th><th>盈亏</th><th>均盈亏%</th></tr></thead>
                <tbody>
                  <tr v-for="s in strategies" :key="s.strategy" :class="s.profit >= 0 ? 'row-up' : 'row-down'">
                    <td class="td-strat">{{ s.strategy }}</td>
                    <td>{{ s.trades }}</td>
                    <td :class="s.win_rate >= 50 ? 'up' : 'down'">{{ s.win_rate.toFixed(1) }}%</td>
                    <td :class="s.profit >= 0 ? 'up' : 'down'">¥{{ s.profit.toLocaleString() }}</td>
                    <td :class="s.avg_profit_pct >= 0 ? 'up' : 'down'">{{ s.avg_profit_pct.toFixed(2) }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 卖出原因 -->
            <div class="ana-panel">
              <div class="ana-sec">📤 卖出原因</div>
              <div v-if="!sellReasons.length" class="ana-empty-sm">暂无数据</div>
              <div v-else class="reason-split">
                <div class="reason-chart">
                  <VChart v-if="sellReasonChart" :option="sellReasonChart" autoresize style="height:180px;width:100%" />
                </div>
                <div class="reason-list">
                  <div v-for="r in sellReasons" :key="r.reason" class="reason-row">
                    <span class="reason-name">{{ r.reason }}</span>
                    <span class="reason-count">{{ r.count }}笔</span>
                    <span class="reason-profit" :class="r.profit >= 0 ? 'up' : 'down'">{{ r.profit >= 0 ? '+' : '' }}¥{{ r.profit.toLocaleString() }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 当前持仓 -->
            <div class="ana-panel">
              <div class="ana-sec">💼 当前持仓 <span class="ana-stat">{{ positions.length }}只</span></div>
              <div v-if="!positions.length" class="ana-empty-sm">空仓或scanner未运行</div>
              <table class="ana-tbl" v-else>
                <thead><tr><th>代码</th><th>名称</th><th>盈亏%</th><th>市值</th></tr></thead>
                <tbody>
                  <tr v-for="p in positions" :key="p.ts_code" :class="p.profit_pct >= 0 ? 'row-up' : 'row-down'">
                    <td>{{ p.ts_code?.slice(0,6) }}</td>
                    <td>{{ p.stock_name }}</td>
                    <td :class="p.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct.toFixed(1) }}%</td>
                    <td>¥{{ (p.market_value || 0).toLocaleString() }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 月度 -->
            <div class="ana-panel" v-if="monthly.length > 1">
              <div class="ana-sec">📅 月度收益</div>
              <table class="ana-tbl">
                <thead><tr><th>月份</th><th>盈亏</th><th>累计</th><th>笔数</th><th>胜率</th></tr></thead>
                <tbody>
                  <tr v-for="m in monthly" :key="m.month" :class="m.profit >= 0 ? 'row-up' : 'row-down'">
                    <td>{{ m.month }}</td>
                    <td :class="m.profit >= 0 ? 'up' : 'down'">¥{{ m.profit.toLocaleString() }}</td>
                    <td :class="m.cum_profit >= 0 ? 'up' : 'down'">¥{{ m.cum_profit.toLocaleString() }}</td>
                    <td>{{ m.trades }}</td>
                    <td :class="m.win_rate >= 50 ? 'up' : 'down'">{{ m.win_rate }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
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

/* KPI */
.ana-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.kpi-card { background: var(--bg-muted); border-radius: 6px; padding: 10px 8px; text-align: center; }
.kpi-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 4px; }
.kpi-val { font-size: 15px; font-weight: 700; }
.kpi-up { border-left: 3px solid var(--stock-up); }
.kpi-down { border-left: 3px solid var(--stock-down); }
.kpi-warn { border-left: 3px solid var(--el-color-warning); }
.kpi-neutral { border-left: 3px solid var(--text-tertiary); }

/* 双栏 */
.ana-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ana-col { display: flex; flex-direction: column; gap: 8px; }

/* 面板 */
.ana-panel { background: var(--bg-base, var(--bg-muted)); border: 1px solid var(--border-default); border-radius: 6px; padding: 8px 10px; }
.ana-sec { font-size: 12px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.ana-stat { font-size: 10px; color: var(--text-tertiary); font-weight: 400; }

/* 表格 — 用table替代div-grid确保对齐 */
.ana-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.ana-tbl th { text-align: left; font-size: 10px; color: var(--text-tertiary); font-weight: 600; padding: 4px 6px; border-bottom: 1px solid var(--border-light); }
.ana-tbl td { padding: 3px 6px; border-bottom: 1px solid var(--border-light); }
.ana-tbl tr:hover { background: var(--bg-muted); }
.row-up > td { border-left: 2px solid var(--stock-up); }
.row-down > td { border-left: 2px solid var(--stock-down); }
.td-strat { font-weight: 600; }

/* 子表格(每日展开) */
.sub-tbl { width: 100%; border-collapse: collapse; font-size: 10px; }
.sub-tbl th { text-align: left; font-size: 9px; color: var(--text-tertiary); padding: 2px 4px; }
.sub-tbl td { padding: 2px 4px; }

/* 卖出原因 */
.reason-split { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.reason-list { display: flex; flex-direction: column; gap: 4px; }
.reason-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.reason-name { min-width: 48px; font-weight: 600; }
.reason-count { font-size: 10px; color: var(--text-tertiary); }
.reason-profit { font-weight: 600; font-size: 11px; }

.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

@media (max-width: 900px) {
  .ana-kpis { grid-template-columns: repeat(3, 1fr); }
  .ana-grid { grid-template-columns: 1fr; }
  .reason-split { grid-template-columns: 1fr; }
}
</style>
