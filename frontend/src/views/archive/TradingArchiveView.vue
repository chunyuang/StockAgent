<script setup lang="ts">
/**
 * 交易归档页面 — 按日期查看: 摘要/持仓/成交/风控/净值/日志
 * v3.0 — 重构: 新增风控/净值Tab, 净值曲线折叠面板, 策略中文映射
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Loading, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import {
  ElCard,
  ElSelect,
  ElOption,
  ElButton,
  ElIcon,
  ElTabs,
  ElTabPane,
  ElDescriptions,
  ElDescriptionsItem,
  ElTable,
  ElTableColumn,
  ElTag,
  ElEmpty,
  ElTooltip,
  ElDivider,
  ElPagination,
} from 'element-plus'
import { api } from '@/api'
import UnifiedDateBar from '@/components/UnifiedDateBar.vue'

// ==================== 状态 ====================

const dates = ref<number[]>([])
const latestDate = ref<number>(0)
const selectedDate = ref<number>(0)
const dateValue = ref('') // YYYYMMDD string for UnifiedDateBar

const dayData = ref<any>(null)
const equityCurve = ref<any>(null)
const riskDecisions = ref<any>(null)
const strategyStats = ref<any[]>([])
const loading = ref(false)
const activeTab = ref('summary')
const sparklineCollapsed = ref(false)

// 日志分页
const logPageSize = ref(50)
const logCurrentPage = ref(1)

// ==================== 格式化工具 ====================

function fmtMoney(val: number | undefined | null, unit: '万' | '亿' = '万', digits = 1): string {
  if (val == null) return '-'
  const v = unit === '亿' ? val / 1e8 : val / 1e4
  return v.toFixed(digits) + unit
}

function fmtPct(val: number | undefined | null): string {
  if (val == null) return '-'
  return val.toFixed(2) + '%'
}

function fmtPrice(val: number | undefined | null): string {
  if (val == null) return '-'
  return val.toFixed(2)
}

function fmtSignedPct(val: number | undefined | null): string {
  if (val == null) return '-'
  const sign = val > 0 ? '+' : ''
  return sign + val.toFixed(2) + '%'
}

function fmtSignedMoney(val: number | undefined | null, unit: '万' | '亿' = '万', digits = 2): string {
  if (val == null) return '-'
  const sign = val > 0 ? '+' : ''
  const v = unit === '亿' ? val / 1e8 : val / 1e4
  return sign + v.toFixed(digits) + unit
}

const strategyMap: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  dragon_head: '龙头低吸',
  limit_down_qiao: '跌停翘板',
}
function strategyCN(s: string | undefined): string {
  if (!s) return '-'
  return strategyMap[s] || s
}

const decisionTypeMap: Record<string, string> = {
  gap_stop_loss: '跳空止损',
  trailing_stop: '追踪止损',
  take_profit: '止盈',
  rapid_drop_stop: '快速跌幅',
  partial_take_profit: '分批止盈',
  intraday_profit_lock: '日内锁定',
  other_sell: '其他卖出',
  stop_loss: '止损',
}
function decisionTypeCN(s: string | undefined): string {
  if (!s) return '-'
  return decisionTypeMap[s] || s
}

function formatDateInt(d: number): string {
  const s = String(d)
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
}

// ==================== 计算 ====================

const summary = computed(() => dayData.value?.summary || {})

const pnlClass = computed(() => {
  const pnl = summary.value.realized_pnl
  if (pnl == null) return ''
  return pnl >= 0 ? 'pnl-win' : 'pnl-lose'
})

const positionRatio = computed(() => {
  const total = summary.value.total_assets
  const posVal = summary.value.position_value
  if (!total) return '-'
  return ((posVal / total) * 100).toFixed(1) + '%'
})

/** 净值曲线最近30天 sparkline 数据 */
const sparklineData = computed(() => {
  const perf = equityCurve.value?.performance
  if (!perf || perf.length === 0) return []
  const last30 = perf.slice(-30)
  return last30
})

const sparklineMin = computed(() => {
  const d = sparklineData.value
  if (!d.length) return 0
  return Math.min(...d.map((x: any) => x.total_assets || 0))
})
const sparklineMax = computed(() => {
  const d = sparklineData.value
  if (!d.length) return 0
  return Math.max(...d.map((x: any) => x.total_assets || 0))
})

/** 净值曲线Tab: 合并 performance + equity */
const mergedCurve = computed(() => {
  const perf = equityCurve.value?.performance || []
  const eq = equityCurve.value?.equity || []
  // Use performance as primary; attach equity fields by date match
  const eqMap = new Map<number, any>()
  for (const e of eq) {
    eqMap.set(e.date, e)
  }
  return perf.map((p: any) => {
    const e = eqMap.get(p.date) || {}
    return { ...p, ...e }
  })
})

/** 净值曲线条形图最大资产值（用于计算条宽） */
const curveBarMax = computed(() => {
  const data = mergedCurve.value
  if (!data.length) return 1
  return Math.max(...data.map((x: any) => x.total_assets || 0))
})

/** 策略胜率 */
const strategyWinRate = computed(() => {
  const stats = strategyStats.value
  if (!stats || stats.length === 0) return '-'
  let totalBuys = 0
  let totalSells = 0
  let totalWinSells = 0
  for (const s of stats) {
    totalBuys += s.buys || 0
    totalSells += s.sells || 0
    if ((s.pnl || 0) > 0) totalWinSells += s.sells || 0
  }
  if (totalSells === 0) return '-'
  return ((totalWinSells / totalSells) * 100).toFixed(0) + '%'
})

/** 日志分页 */
const pagedLogs = computed(() => {
  const logs = dayData.value?.logs || []
  const start = (logCurrentPage.value - 1) * logPageSize.value
  return logs.slice(start, start + logPageSize.value)
})

const logTotal = computed(() => (dayData.value?.logs || []).length)

/** 风控统计摘要 */
const riskSummary = computed(() => {
  const tc = riskDecisions.value?.type_counts || {}
  const total = riskDecisions.value?.total || 0
  return { typeCounts: tc, total }
})

// ==================== 行背景 ====================

function posRowClass({ row }: { row: any }): string {
  if (row.profit_pct > 0) return 'row-win'
  if (row.profit_pct < 0) return 'row-lose'
  return ''
}

function tradeRowClass({ row }: { row: any }): string {
  if (row.side === 'buy') return 'row-buy'
  if (row.side === 'sell') return 'row-sell'
  return ''
}

function riskRowClass({ row }: { row: any }): string {
  if (row.profit_pct > 0) return 'row-win'
  if (row.profit_pct < 0) return 'row-lose'
  return ''
}

function logRowClass({ row }: { row: any }): string {
  if (row.type === 'buy' || row.type === 'signal') return 'row-signal'
  if (row.type === 'sell' || row.type === 'risk') return 'row-risk'
  if (row.type === 'circuit') return 'row-circuit'
  return ''
}

// ==================== 数据拉取 ====================

async function fetchDates() {
  try {
    const res = await api.get('/trading-archive/dates')
    dates.value = res?.dates || []
    latestDate.value = res?.latest_date || 0
    if (dates.value.length > 0 && !selectedDate.value) {
      const d = dates.value[0]
      selectedDate.value = d
      dateValue.value = String(d)
      loadAllData(d)
    }
  } catch (e) {
    console.warn('加载归档日期失败', e)
  }
}

async function fetchDay(date: number) {
  if (!date) return
  loading.value = true
  dayData.value = null
  try {
    const res = await api.get(`/trading-archive/day/${date}`)
    dayData.value = res
  } catch (e) {
    console.warn('加载归档数据失败', e)
  } finally {
    loading.value = false
  }
}

async function fetchEquityCurve() {
  try {
    const res = await api.get('/trading-archive/equity-curve')
    // API返回 {success, data: {performance, equity}}
    equityCurve.value = res?.data || res
  } catch (e) {
    console.warn('加载净值曲线失败', e)
  }
}

async function fetchRiskDecisions(date: number) {
  try {
    const res = await api.get(`/trading-archive/risk-decisions/${date}`)
    // API返回 {success, data: {decisions, type_counts, total}}
    riskDecisions.value = res?.data || res
  } catch (e) {
    console.warn('加载风控数据失败', e)
  }
}

async function fetchStrategyStats(date: number) {
  try {
    const res = await api.get(`/trading-archive/strategy-stats/${date}`)
    // API返回 {success, data: [...]}
    const d = res?.data || res
    strategyStats.value = Array.isArray(d) ? d : []
  } catch (e) {
    console.warn('加载策略统计失败', e)
  }
}

function loadAllData(date: number) {
  logCurrentPage.value = 1
  fetchDay(date)
  fetchRiskDecisions(date)
  fetchStrategyStats(date)
  // 净值曲线只需加载一次
  if (!equityCurve.value) {
    fetchEquityCurve()
  }
}

// ==================== 日期导航 ====================

function onDateChange(dateStr: string) {
  if (!dateStr) return
  const d = Number(dateStr.replace(/-/g, ''))
  if (!d) return
  selectedDate.value = d
  loadAllData(d)
}

function goPrevDate() {
  const idx = dates.value.indexOf(selectedDate.value)
  if (idx > 0) {
    const d = dates.value[idx - 1]
    selectedDate.value = d
    dateValue.value = String(d)
    loadAllData(d)
  }
}

function goNextDate() {
  const idx = dates.value.indexOf(selectedDate.value)
  if (idx < dates.value.length - 1) {
    const d = dates.value[idx + 1]
    selectedDate.value = d
    dateValue.value = String(d)
    loadAllData(d)
  }
}

function displayDate(d: number): string {
  const s = String(d)
  return `${s.slice(4, 6)}/${s.slice(6, 8)}`
}

// ==================== 生命周期 ====================

onMounted(() => {
  fetchDates()
})
</script>

<template>
  <div class="archive-page">
    <!-- ===== 顶部导航栏 ===== -->
    <div class="top-bar">
      <div class="top-bar-left">
        <div class="date-nav">
          <ElButton size="small" :disabled="dates.indexOf(selectedDate) <= 0" @click="goPrevDate">
            <ElIcon><ArrowLeft /></ElIcon>
          </ElButton>
          <span class="date-display">{{ displayDate(selectedDate) }}</span>
          <ElButton size="small" :disabled="dates.indexOf(selectedDate) >= dates.length - 1" @click="goNextDate">
            <ElIcon><ArrowRight /></ElIcon>
          </ElButton>
        </div>
        <UnifiedDateBar v-model="dateValue" @change="onDateChange" />
      </div>

      <div class="top-bar-overview" :class="pnlClass" v-if="summary.total_assets">
        <div class="ov-item">
          <span class="ov-label">总资产</span>
          <span class="ov-value">{{ fmtMoney(summary.total_assets) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">盈亏</span>
          <span class="ov-value pnl">{{ fmtSignedMoney(summary.realized_pnl) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">仓位%</span>
          <span class="ov-value">{{ positionRatio }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">持仓</span>
          <span class="ov-value">{{ summary.position_count || 0 }}只</span>
        </div>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="center-hint">
      <ElIcon class="is-loading" :size="24"><Loading /></ElIcon>
      <span>加载中...</span>
    </div>

    <!-- 无数据 -->
    <div v-else-if="!dayData && !loading" class="center-hint">
      <ElEmpty description="请选择交易日查看归档数据" />
    </div>

    <!-- ===== 归档主体 ===== -->
    <div v-else-if="dayData" class="archive-body">

      <!-- ===== 净值曲线折叠面板 ===== -->
      <ElCard class="sparkline-card" shadow="never">
        <div class="sparkline-header" @click="sparklineCollapsed = !sparklineCollapsed">
          <span class="sparkline-title">📈 净值曲线</span>
          <span class="sparkline-toggle">{{ sparklineCollapsed ? '展开' : '收起' }}</span>
        </div>
        <div v-if="!sparklineCollapsed && sparklineData.length" class="sparkline-body">
          <div class="sparkline-chart">
            <div
              v-for="(item, idx) in sparklineData"
              :key="idx"
              class="sparkline-bar-wrapper"
            >
              <ElTooltip :content="`${formatDateInt(item.date)}: ${fmtMoney(item.total_assets)} 回撤${fmtPct(item.drawdown_pct)}`" placement="top">
                <div
                  class="sparkline-bar"
                  :class="{
                    'bar-down': (item.drawdown_pct || 0) < -3,
                    'bar-up': (item.drawdown_pct || 0) >= 0
                  }"
                  :style="{
                    height: sparklineMax > sparklineMin
                      ? Math.max(4, ((item.total_assets - sparklineMin) / (sparklineMax - sparklineMin)) * 60) + 'px'
                      : '30px'
                  }"
                ></div>
              </ElTooltip>
            </div>
          </div>
          <div class="sparkline-axis">
            <span v-if="sparklineData.length">{{ formatDateInt(sparklineData[0]?.date) }}</span>
            <span v-if="sparklineData.length">近{{ sparklineData.length }}日</span>
            <span v-if="sparklineData.length">{{ formatDateInt(sparklineData[sparklineData.length - 1]?.date) }}</span>
          </div>
        </div>
        <div v-else-if="!sparklineCollapsed && !sparklineData.length" class="sparkline-empty">
          暂无净值数据
        </div>
      </ElCard>

      <!-- ===== 内容 Tabs ===== -->
      <ElTabs v-model="activeTab" type="border-card" class="archive-tabs">

        <!-- ========== 📋摘要 ========== -->
        <ElTabPane name="summary">
          <template #label><span>📋 摘要</span></template>

          <div class="summary-grid">
            <!-- 委托统计 -->
            <div class="summary-card card-blue">
              <div class="sc-header">
                <span class="sc-icon">📝</span>
                <span class="sc-title">委托统计</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>总委托</span><b>{{ summary.total_orders ?? '-' }}</b></div>
                <div class="sc-row sc-buy"><span>买入</span><b>{{ summary.buy_orders ?? '-' }}</b></div>
                <div class="sc-row sc-sell"><span>卖出</span><b>{{ summary.sell_orders ?? '-' }}</b></div>
                <div class="sc-row"><span>已成交</span><b class="ok">{{ summary.filled_orders ?? '-' }}</b></div>
                <div class="sc-row"><span>已取消</span><b class="muted">{{ summary.cancelled_orders ?? '-' }}</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row">
                  <span>成交率</span>
                  <b>{{ summary.total_orders ? ((summary.filled_orders / summary.total_orders) * 100).toFixed(0) + '%' : '-' }}</b>
                </div>
              </div>
            </div>

            <!-- 成交统计 -->
            <div class="summary-card card-orange">
              <div class="sc-header">
                <span class="sc-icon">📊</span>
                <span class="sc-title">成交统计</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>成交笔数</span><b>{{ summary.total_trades ?? '-' }}</b></div>
                <div class="sc-row sc-buy"><span>买入金额</span><b>{{ fmtMoney(summary.total_buy_amount) }}</b></div>
                <div class="sc-row sc-sell"><span>卖出金额</span><b>{{ fmtMoney(summary.total_sell_amount) }}</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row">
                  <span>已实现盈亏</span>
                  <b :class="summary.realized_pnl >= 0 ? 'ok' : 'err'">
                    {{ fmtSignedMoney(summary.realized_pnl) }}
                  </b>
                </div>
                <div class="sc-row sc-note">
                  <ElTooltip content="卖出成交的盈亏合计（含佣金），不含浮动盈亏" placement="top">
                    <span>💡仅含已平仓</span>
                  </ElTooltip>
                </div>
              </div>
            </div>

            <!-- 资金概况 -->
            <div class="summary-card card-green">
              <div class="sc-header">
                <span class="sc-icon">💰</span>
                <span class="sc-title">资金概况</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>总资产</span><b>{{ fmtMoney(summary.total_assets) }}</b></div>
                <div class="sc-row"><span>可用资金</span><b>{{ fmtMoney(summary.available_cash) }}</b></div>
                <div class="sc-row"><span>持仓市值</span><b>{{ fmtMoney(summary.position_value) }}</b></div>
                <div class="sc-row"><span>持仓数</span><b>{{ summary.position_count ?? '-' }}只</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row"><span>仓位比例</span><b>{{ positionRatio }}</b></div>
              </div>
            </div>

            <!-- 策略胜率 -->
            <div class="summary-card card-purple">
              <div class="sc-header">
                <span class="sc-icon">🎯</span>
                <span class="sc-title">策略胜率</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>总买入笔数</span><b>{{ strategyStats.reduce((a, s) => a + (s.buys || 0), 0) }}</b></div>
                <div class="sc-row"><span>总卖出笔数</span><b>{{ strategyStats.reduce((a, s) => a + (s.sells || 0), 0) }}</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row"><span>综合胜率</span><b :class="strategyWinRate !== '-' && Number(strategyWinRate) >= 50 ? 'ok' : 'err'">{{ strategyWinRate }}</b></div>
              </div>
            </div>
          </div>

          <!-- 策略统计表 -->
          <div v-if="strategyStats.length" class="strategy-stats-section">
            <h4 class="section-title">策略统计明细</h4>
            <ElTable :data="strategyStats" size="small" stripe class="archive-table">
              <ElTableColumn label="策略" min-width="120">
                <template #default="{ row }">{{ strategyCN(row.strategy) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="buys" label="买入次数" width="100" align="right" />
              <ElTableColumn prop="sells" label="卖出次数" width="100" align="right" />
              <ElTableColumn label="买入金额" width="120" align="right">
                <template #default="{ row }">{{ fmtMoney(row.buy_amount) }}</template>
              </ElTableColumn>
              <ElTableColumn label="卖出金额" width="120" align="right">
                <template #default="{ row }">{{ fmtMoney(row.sell_amount) }}</template>
              </ElTableColumn>
              <ElTableColumn label="盈亏" width="120" align="right">
                <template #default="{ row }">
                  <span :class="row.pnl >= 0 ? 'ok' : 'err'">{{ fmtSignedMoney(row.pnl) }}</span>
                </template>
              </ElTableColumn>
            </ElTable>
          </div>
        </ElTabPane>

        <!-- ========== 📊持仓 ========== -->
        <ElTabPane name="positions">
          <template #label>
            <span>📊 持仓 <ElTag v-if="dayData.positions?.length" size="small" round type="info">{{ dayData.positions.length }}</ElTag></span>
          </template>
          <div class="tab-note">按盈亏着色：盈利行浅绿底色，亏损行浅红底色</div>
          <ElTable :data="dayData.positions || []" size="small" stripe :row-class-name="posRowClass" class="archive-table">
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="策略" width="100">
              <template #default="{ row }">{{ strategyCN(row.strategy) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="quantity" label="数量" width="80" align="right" />
            <ElTableColumn label="成本" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.avg_cost) }}</template>
            </ElTableColumn>
            <ElTableColumn label="现价" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.current_price) }}</template>
            </ElTableColumn>
            <ElTableColumn label="市值" width="100" align="right">
              <template #default="{ row }">{{ fmtMoney(row.market_value) }}</template>
            </ElTableColumn>
            <ElTableColumn label="盈亏%" width="90" align="right" sortable>
              <template #default="{ row }">
                <span :class="row.profit_pct >= 0 ? 'ok' : 'err'">
                  {{ fmtSignedPct(row.profit_pct) }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="盈亏额" width="110" align="right">
              <template #default="{ row }">
                <span :class="row.profit_amount >= 0 ? 'ok' : 'err'">
                  {{ fmtSignedMoney(row.profit_amount) }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="止损价" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.stop_loss_price) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="buy_time" label="买入时间" width="160" />
            <ElTableColumn label="持有天数" width="90" align="right">
              <template #default="{ row }">{{ row.hold_days ?? '-' }}</template>
            </ElTableColumn>
          </ElTable>
          <div v-if="!dayData.positions?.length" class="center-hint">该日无持仓</div>
        </ElTabPane>

        <!-- ========== ✅成交 ========== -->
        <ElTabPane name="trades">
          <template #label>
            <span>✅ 成交 <ElTag v-if="dayData.trades?.length" size="small" round type="info">{{ dayData.trades.length }}</ElTag></span>
          </template>
          <div class="tab-note">买入行浅红底色，卖出行浅绿底色；盈亏仅卖出时显示</div>
          <ElTable :data="dayData.trades || []" size="small" stripe :row-class-name="tradeRowClass" class="archive-table">
            <ElTableColumn prop="fill_time" label="时间" width="160" />
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="方向" width="60" align="center">
              <template #default="{ row }">
                <span class="dir-badge" :class="row.side === 'buy' ? 'dir-buy' : 'dir-sell'">
                  {{ row.side === 'buy' ? '买' : '卖' }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="filled_qty" label="数量" width="80" align="right" />
            <ElTableColumn label="价格" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.filled_price) }}</template>
            </ElTableColumn>
            <ElTableColumn label="金额" width="100" align="right">
              <template #default="{ row }">{{ fmtMoney(row.filled_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="盈亏" width="110" align="right">
              <template #default="{ row }">
                <template v-if="row.side === 'sell'">
                  <span :class="row.profit_amount >= 0 ? 'ok' : 'err'">
                    {{ fmtSignedMoney(row.profit_amount) }}
                  </span>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="reason" label="原因" min-width="120" show-overflow-tooltip />
            <ElTableColumn label="策略" min-width="100">
              <template #default="{ row }">{{ strategyCN(row.strategy) }}</template>
            </ElTableColumn>
          </ElTable>
          <div v-if="!dayData.trades?.length" class="center-hint">该日无成交</div>
        </ElTabPane>

        <!-- ========== 🛡风控 ========== -->
        <ElTabPane name="risk">
          <template #label>
            <span>🛡 风控 <ElTag v-if="riskDecisions?.decisions?.length" size="small" round type="info">{{ riskDecisions.total }}</ElTag></span>
          </template>

          <!-- 风控统计摘要 -->
          <div v-if="riskSummary.total > 0" class="risk-summary-bar">
            <span class="risk-summary-label">风控决策汇总：</span>
            <template v-for="(count, key) in riskSummary.typeCounts" :key="key">
              <ElTag
                size="small"
                :type="key.includes('stop') ? 'danger' : key.includes('profit') ? 'success' : 'warning'"
                effect="plain"
                class="risk-badge"
              >
                {{ decisionTypeCN(key as string) }}×{{ count }}
              </ElTag>
            </template>
          </div>

          <div v-if="riskDecisions?.decisions?.length">
            <ElTable :data="riskDecisions.decisions" size="small" stripe :row-class-name="riskRowClass" class="archive-table">
              <ElTableColumn prop="timestamp" label="时间" width="180" />
              <ElTableColumn prop="ts_code" label="代码" width="110" />
              <ElTableColumn prop="stock_name" label="名称" width="80" />
              <ElTableColumn label="决策类型" width="100">
                <template #default="{ row }">
                  <ElTag
                    size="small"
                    :type="row.decision_type?.includes('stop') ? 'danger' : row.decision_type?.includes('profit') ? 'success' : 'warning'"
                    effect="plain"
                  >
                    {{ decisionTypeCN(row.decision_type) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="trigger_reason" label="触发原因" min-width="120" show-overflow-tooltip />
              <ElTableColumn label="成本价" width="80" align="right">
                <template #default="{ row }">{{ fmtPrice(row.cost_price) }}</template>
              </ElTableColumn>
              <ElTableColumn label="触发价" width="80" align="right">
                <template #default="{ row }">{{ fmtPrice(row.trigger_price) }}</template>
              </ElTableColumn>
              <ElTableColumn label="成交价" width="80" align="right">
                <template #default="{ row }">{{ fmtPrice(row.filled_price) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="quantity" label="数量" width="80" align="right" />
              <ElTableColumn label="盈亏%" width="90" align="right">
                <template #default="{ row }">
                  <span :class="row.profit_pct >= 0 ? 'ok' : 'err'">
                    {{ fmtSignedPct(row.profit_pct) }}
                  </span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="策略" min-width="100">
                <template #default="{ row }">{{ strategyCN(row.strategy) }}</template>
              </ElTableColumn>
            </ElTable>
          </div>
          <div v-else class="center-hint">该日无风控决策</div>
        </ElTabPane>

        <!-- ========== 📈净值 ========== -->
        <ElTabPane name="equity">
          <template #label><span>📈 净值</span></template>

          <div v-if="mergedCurve.length" class="equity-curve-section">
            <!-- CSS 条形图 -->
            <div class="css-chart">
              <div
                v-for="(item, idx) in mergedCurve"
                :key="idx"
                class="chart-row"
              >
                <span class="chart-label">{{ formatDateInt(item.date).slice(5) }}</span>
                <div class="chart-bar-track">
                  <ElTooltip
                    :content="`${formatDateInt(item.date)} 净值:${fmtPrice(item.net_value)} 回撤:${fmtPct(item.drawdown_pct)} 仓位:${fmtPct(item.position_ratio)}`"
                    placement="top"
                  >
                    <div
                      class="chart-bar-fill"
                      :class="{
                        'bar-profit': (item.drawdown_pct || 0) >= 0,
                        'bar-drawdown': (item.drawdown_pct || 0) < 0 && (item.drawdown_pct || 0) >= -3,
                        'bar-heavy-drawdown': (item.drawdown_pct || 0) < -3
                      }"
                      :style="{
                        width: Math.max(2, ((item.total_assets || 0) / curveBarMax) * 100) + '%'
                      }"
                    ></div>
                  </ElTooltip>
                </div>
                <span class="chart-value">{{ fmtMoney(item.total_assets) }}</span>
              </div>
            </div>

            <ElDivider />

            <!-- 数据表 -->
            <h4 class="section-title">净值曲线明细</h4>
            <ElTable :data="mergedCurve" size="small" stripe class="archive-table" max-height="500">
              <ElTableColumn label="日期" width="110">
                <template #default="{ row }">{{ formatDateInt(row.date) }}</template>
              </ElTableColumn>
              <ElTableColumn label="总资产" width="110" align="right">
                <template #default="{ row }">{{ fmtMoney(row.total_assets) }}</template>
              </ElTableColumn>
              <ElTableColumn label="净值" width="80" align="right">
                <template #default="{ row }">{{ fmtPrice(row.net_value) }}</template>
              </ElTableColumn>
              <ElTableColumn label="回撤%" width="90" align="right">
                <template #default="{ row }">
                  <span :class="(row.drawdown_pct || 0) < 0 ? 'err' : ''">{{ fmtPct(row.drawdown_pct) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="仓位%" width="80" align="right">
                <template #default="{ row }">{{ fmtPct(row.position_ratio) }}</template>
              </ElTableColumn>
              <ElTableColumn label="持仓数" width="70" align="right">
                <template #default="{ row }">{{ row.position_count ?? '-' }}</template>
              </ElTableColumn>
              <ElTableColumn label="已实现" width="100" align="right">
                <template #default="{ row }">
                  <span :class="row.realized_profit >= 0 ? 'ok' : 'err'">{{ fmtSignedMoney(row.realized_profit) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="未实现" width="100" align="right">
                <template #default="{ row }">
                  <span :class="row.unrealized_profit >= 0 ? 'ok' : 'err'">{{ fmtSignedMoney(row.unrealized_profit) }}</span>
                </template>
              </ElTableColumn>
            </ElTable>
          </div>
          <div v-else class="center-hint">暂无净值数据</div>
        </ElTabPane>

        <!-- ========== 📋日志 ========== -->
        <ElTabPane name="logs">
          <template #label>
            <span>📋 日志 <ElTag v-if="dayData.logs?.length" size="small" round type="info">{{ dayData.logs.length }}</ElTag></span>
          </template>
          <div class="tab-note">买卖信号浅绿、风控/卖出浅红、熔断浅橙 · 共{{ logTotal }}条，每页{{ logPageSize }}条</div>
          <ElTable :data="pagedLogs" size="small" stripe :row-class-name="logRowClass" class="archive-table">
            <ElTableColumn prop="timestamp" label="时间" width="180" />
            <ElTableColumn label="类型" width="80" align="center">
              <template #default="{ row }">
                <ElTag
                  size="small"
                  :type="row.type === 'buy' || row.type === 'signal' ? 'success' : row.type === 'sell' || row.type === 'risk' ? 'danger' : row.type === 'circuit' ? 'warning' : 'info'"
                  effect="plain"
                >
                  {{ row.type }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="message" label="内容" min-width="300" show-overflow-tooltip />
          </ElTable>
          <div v-if="logTotal > logPageSize" class="log-pagination">
            <ElPagination
              v-model:current-page="logCurrentPage"
              :page-size="logPageSize"
              :total="logTotal"
              layout="prev, pager, next"
              small
              background
            />
          </div>
          <div v-if="!dayData.logs?.length" class="center-hint">该日无日志记录</div>
        </ElTabPane>

      </ElTabs>
    </div>
  </div>
</template>

<style scoped lang="scss">
.archive-page {
  padding: 16px;
}

/* ===== 顶部导航栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;

  .top-bar-left {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }

  .date-nav {
    display: flex;
    align-items: center;
    gap: 4px;

    .date-display {
      font-size: 18px;
      font-weight: 700;
      font-family: 'Menlo', 'Monaco', monospace;
      min-width: 60px;
      text-align: center;
      color: var(--text-primary);
    }
  }
}

.top-bar-overview {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 10px 20px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  border-left: 4px solid var(--el-color-info);
  flex-wrap: wrap;

  &.pnl-win {
    border-left-color: var(--el-color-success);
    background: rgba(34, 197, 94, 0.04);
  }
  &.pnl-lose {
    border-left-color: var(--el-color-danger);
    background: rgba(239, 68, 68, 0.04);
  }

  .ov-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0 20px;
    min-width: 0;

    .ov-label {
      font-size: 11px;
      color: var(--text-tertiary);
      margin-bottom: 2px;
      white-space: nowrap;
    }
    .ov-value {
      font-size: 15px;
      font-weight: 700;
      font-family: 'Menlo', 'Monaco', monospace;
      white-space: nowrap;
    }
    .ov-value.pnl {
      font-size: 16px;
    }
  }

  .ov-sep {
    width: 1px;
    height: 28px;
    background: var(--border-lighter);
    flex-shrink: 0;
  }
}

.top-bar-overview.pnl-win .ov-value.pnl { color: var(--el-color-success); }
.top-bar-overview.pnl-lose .ov-value.pnl { color: var(--el-color-danger); }

@media (max-width: 768px) {
  .top-bar { flex-direction: column; align-items: stretch; }
  .top-bar-overview {
    .ov-sep { display: none; }
    .ov-item { padding: 4px 12px; }
  }
}

/* ===== 净值曲线折叠面板 ===== */
.sparkline-card {
  margin-bottom: 16px;
  border-radius: 10px;

  :deep(.el-card__body) {
    padding: 12px 16px;
  }
}

.sparkline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;

  .sparkline-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .sparkline-toggle {
    font-size: 12px;
    color: var(--el-color-primary);
  }
}

.sparkline-body {
  margin-top: 12px;
}

.sparkline-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 68px;
  padding: 4px 0;
  overflow: hidden;
}

.sparkline-bar-wrapper {
  flex: 1;
  display: flex;
  align-items: flex-end;
  min-width: 4px;
}

.sparkline-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s ease;
  cursor: pointer;

  &.bar-up { background: var(--el-color-success); opacity: 0.7; }
  &.bar-down { background: var(--el-color-danger); opacity: 0.7; }

  &:hover { opacity: 1; }
}

.sparkline-axis {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-quaternary);
  margin-top: 4px;
  font-family: 'Menlo', 'Monaco', monospace;
}

.sparkline-empty {
  margin-top: 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-quaternary);
  padding: 12px 0;
}

/* ===== 通用 ===== */
.center-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: var(--text-quaternary);
  font-size: 14px;
}

/* ===== 摘要卡片 ===== */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}

@media (max-width: 1100px) {
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .summary-grid { grid-template-columns: 1fr; }
}

.summary-card {
  border-radius: 10px;
  padding: 14px 18px;
  border-left: 4px solid transparent;
  background: var(--el-fill-color-lighter);

  &.card-blue   { border-left-color: #409eff; }
  &.card-orange { border-left-color: #e6a23c; }
  &.card-green  { border-left-color: #67c23a; }
  &.card-purple { border-left-color: #9b59b6; }
}

.sc-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  .sc-icon { font-size: 15px; }
  .sc-title { font-size: 13px; font-weight: 600; }
}

.card-blue   .sc-title { color: #409eff; }
.card-orange .sc-title { color: #e6a23c; }
.card-green  .sc-title { color: #67c23a; }
.card-purple .sc-title { color: #9b59b6; }

.sc-body {
  .sc-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    padding: 2px 0;
    b { font-family: 'Menlo', 'Monaco', monospace; font-weight: 600; }
  }
  .sc-buy  { b { color: #f56c6c; } }
  .sc-sell { b { color: #67c23a; } }
  .sc-note { font-size: 12px; color: var(--text-quaternary); justify-content: flex-end; span { cursor: help; } }
  .sc-divider { margin: 6px 0; }
}

/* ===== 策略统计 ===== */
.strategy-stats-section {
  margin-top: 8px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

/* ===== 风控摘要条 ===== */
.risk-summary-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;

  .risk-summary-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
  }

  .risk-badge {
    font-family: 'Menlo', 'Monaco', monospace;
  }
}

/* ===== 净值曲线 CSS 图表 ===== */
.equity-curve-section {
  .css-chart {
    padding: 8px 0;
  }

  .chart-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 3px;

    .chart-label {
      font-size: 11px;
      font-family: 'Menlo', 'Monaco', monospace;
      color: var(--text-tertiary);
      width: 46px;
      text-align: right;
      flex-shrink: 0;
    }

    .chart-bar-track {
      flex: 1;
      height: 16px;
      background: var(--bg-muted);
      border-radius: 3px;
      overflow: hidden;
      position: relative;
    }

    .chart-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.3s ease;
      min-width: 2px;

      &.bar-profit { background: var(--el-color-success); opacity: 0.65; }
      &.bar-drawdown { background: var(--el-color-warning); opacity: 0.65; }
      &.bar-heavy-drawdown { background: var(--el-color-danger); opacity: 0.65; }

      &:hover { opacity: 1; }
    }

    .chart-value {
      font-size: 11px;
      font-family: 'Menlo', 'Monaco', monospace;
      color: var(--text-secondary);
      width: 65px;
      flex-shrink: 0;
    }
  }
}

/* ===== 日志分页 ===== */
.log-pagination {
  display: flex;
  justify-content: center;
  margin-top: 12px;
  padding: 8px 0;
}

/* ===== 通用表格 ===== */
.tab-note {
  font-size: 12px;
  color: var(--text-quaternary);
  margin-bottom: 8px;
  padding: 0 2px;
}

.archive-table {
  :deep(.row-win)   { background: rgba(34, 197, 94, 0.06) !important; }
  :deep(.row-lose)  { background: rgba(239, 68, 68, 0.06) !important; }
  :deep(.row-buy)   { background: rgba(245, 108, 108, 0.05) !important; }
  :deep(.row-sell)  { background: rgba(103, 194, 58, 0.05) !important; }
  :deep(.row-signal){ background: rgba(103, 194, 58, 0.06) !important; }
  :deep(.row-risk)  { background: rgba(245, 108, 108, 0.06) !important; }
  :deep(.row-circuit){ background: rgba(230, 162, 60, 0.06) !important; }
}

/* ===== 方向标记 ===== */
.dir-badge {
  display: inline-block;
  width: 28px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;

  &.dir-buy  { background: rgba(245, 108, 108, 0.12); color: #f56c6c; }
  &.dir-sell { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
}

/* ===== 通用着色 ===== */
.ok    { color: var(--el-color-success); }
.err   { color: var(--el-color-danger); }
.muted { color: var(--text-quaternary); }

/* ===== Tabs ===== */
.archive-tabs {
  border-radius: 10px;
  :deep(.el-tabs__content) { padding: 16px; }
}

/* ===== 响应式净值曲线 ===== */
@media (max-width: 600px) {
  .equity-curve-section .chart-row {
    .chart-label { width: 36px; font-size: 10px; }
    .chart-value { width: 50px; font-size: 10px; }
  }
}
</style>
