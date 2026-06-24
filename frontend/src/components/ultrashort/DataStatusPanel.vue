<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElCard, ElProgress, ElTable, ElTableColumn, ElTag, ElButton, ElMessage, ElSwitch, ElTooltip } from 'element-plus'
import StrategyFactorPanel from './StrategyFactorPanel.vue'
// 数据可视化图表
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

interface DailyCoverage { date: string; total: number; factor_rate: number; groups: Record<string, number> }
interface CollectionInfo { count: number; date_range: { start: string; end: string } | null; error?: string }
interface DataSource { name: string; type: string; status: string; status_text: string; rate_limit: string; coverage: string; gotchas: string[]; scripts: string[] }
interface RecommendedRange { start: string; end: string; factor_rate: string }
interface StrategyItem { name: string; key: string; available: boolean; coverage: number; missing_factors: string[]; desc: string }
interface ActionItem { action: string; command: string; desc: string; priority: string; api?: string; note?: string }
interface DataAlignment { date: string; stock_daily_count: number; daily_basic_count: number; common: number; only_in_basic: number; only_in_daily: number; only_in_basic_samples: string[] }
interface HealthBreakdown { factor_score: number; factor_max: number; freshness_score: number; freshness_max: number; source_score: number; source_max: number }

interface DataStatus {
  health_score: number; health_breakdown: HealthBreakdown
  diagnostics: { level: string; message: string }[]
  collections: Record<string, CollectionInfo>; daily_coverage: DailyCoverage[]
  latest: { stock_daily: string | null; daily_basic: string | null }
  factor_groups: Record<string, number>; factor_detail_latest: Record<string, number>
  recommended_ranges: RecommendedRange[]; data_sources: DataSource[]
  strategy_availability: StrategyItem[]; action_items: ActionItem[]; data_alignment: DataAlignment
}

const props = defineProps<{
  visible?: boolean
}>()
const loading = ref(false)
const status = ref<DataStatus | null>(null)
const error = ref('')
const syncLoading = ref<string>('')  // 正在同步的action名
const syncTaskId = ref('')
const syncStatus = ref<any>(null)
const syncPollTimer = ref<any>(null)

const collectionNames: Record<string, string> = {
  stock_daily_ak_full: '日线行情(OHLCV)', daily_basic: '基础指标(PE/PB/市值)',
  index_daily: '指数日线', limit_list: '涨停池',
  limit_pool_down: '跌停池', backtest_tasks: '回测任务'
}

async function fetchData() {
  loading.value = true; error.value = ''
  try {
    const res = await fetch('/api/v1/system/data-status')
    const json = await res.json()
    if (json.success) { status.value = json.data } else { error.value = json.message || '查询失败' }
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

// ===== 数据同步操作 =====
async function triggerSync(apiPath: string, actionName: string) {
  syncLoading.value = actionName
  syncStatus.value = null
  try {
    const res = await fetch(apiPath, { method: 'POST' })
    const json = await res.json()
    if (json.success) {
      syncTaskId.value = json.task_id
      startPolling()
    } else {
      syncLoading.value = ''
      ElMessage.error(json.message || '同步启动失败')
    }
  } catch (e: any) {
    syncLoading.value = ''
    ElMessage.error('请求失败: ' + e.message)
  }
}

function startPolling() {
  stopPolling()
  syncPollTimer.value = setInterval(async () => {
    if (!syncTaskId.value) { stopPolling(); return }
    try {
      const res = await fetch(`/api/v1/system/sync-status/${syncTaskId.value}`)
      const json = await res.json()
      if (json.success) {
        syncStatus.value = json.data
        if (json.data.status === 'success' || json.data.status === 'partial' || json.data.status === 'failed') {
          syncLoading.value = ''
          stopPolling()
          // 强制刷新数据状态(重新拉取API)
          await fetchData()
        }
      }
    } catch (e) { console.error('[DataStatusPanel]', e) }
  }, 2000)
}

function stopPolling() {
  if (syncPollTimer.value) { clearInterval(syncPollTimer.value); syncPollTimer.value = null }
}

function parseApiPath(api?: string): string | null {
  if (!api) return null
  // "POST /api/v1/system/sync-all" → "/api/v1/system/sync-all"
  const parts = api.split(' ')
  return parts.length > 1 ? parts[1] : api
}

function fmtDate(d: string) {
  if (!d || d.length !== 8) return d
  return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
}

// ===== 因子分组卡片数据 =====
const factorGroupCards = computed(() => {
  const detail = status.value?.factor_detail_latest
  if (!detail) return []
  const groups = [
    { key: 'basic', name: '基础', icon: '📈', factors: ['pct_chg', 'pre_close', 'open', 'high', 'low', 'close'] },
    { key: 'technical_ma', name: 'MA均线', icon: '〰️', factors: ['ma5', 'ma10', 'ma20', 'ma60'] },
    { key: 'volume', name: '量价', icon: '📊', factors: ['turnover_rate', 'volume_ratio', 'circ_mv'] },
    { key: 'limit', name: '涨跌停', icon: '🎯', factors: ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count'] },
    { key: 'technical_talib', name: 'TALib', icon: '🔬', factors: ['macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'], note: '回测时自动补算' },
  ]
  const nameMap: Record<string, string> = {
    pct_chg: '涨跌幅', pre_close: '前收盘', open: '开盘', high: '最高', low: '最低', close: '收盘',
    ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60',
    macd: 'MACD', rsi_6: 'RSI6', boll_upper: '布林上轨', atr: 'ATR', fear_greed_index: '恐贪指数',
    turnover_rate: '换手率', volume_ratio: '量比', circ_mv: '流通市值',
    is_limit_up: '涨停标记', is_limit_down: '跌停标记', first_limit_up: '首板标记', limit_up_count: '连板数',
  }
  return groups.map(g => {
    const factors = g.factors.map(f => ({ key: f, name: nameMap[f] || f, coverage: detail[f] ?? 0 }))
    const avgCov = factors.length ? Math.round(factors.reduce((s, f) => s + f.coverage, 0) / factors.length) : 0
    const missing = factors.filter(f => f.coverage < 90)
    return { ...g, factors, avgCov, missing, note: (g as any).note || '' }
  })
})

// ===== 因子覆盖率趋势图(替代热力图) =====
const factorTrendOption = computed(() => {
  const cov = status.value?.daily_coverage
  if (!cov?.length) return null
  const showDays = Math.min(cov.length, 60)
  const data = cov.slice(-showDays)
  const dates = data.map(c => `${c.date.slice(4,6)}/${c.date.slice(6,8)}`)

  const groupLabels: Record<string, string> = { basic: '基础', technical_ma: 'MA均线', volume: '量价', limit: '涨跌停' }
  const groupColors: Record<string, string> = { basic: '#409EFF', technical_ma: '#67C23A', volume: '#E6A23C', limit: '#F56C6C' }

  const series = Object.entries(groupLabels).map(([key, name]) => ({
    name,
    type: 'line' as const,
    data: data.map(c => c.groups[key] ?? 0),
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 2, color: groupColors[key] },
    itemStyle: { color: groupColors[key] },
  }))

  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}%` },
    legend: { data: Object.values(groupLabels), bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 40, right: 16, top: 10, bottom: 32 },
    dataZoom: [{ type: 'inside' }],
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { fontSize: 10, formatter: '{value}%' } },
    series,
  }
})

const collectionRows = computed(() => {
  if (!status.value?.collections) return []
  return Object.entries(status.value.collections).map(([k, v]) => ({ key: k, name: collectionNames[k] || k, count: v.count, dateStart: v.date_range?.start, dateEnd: v.date_range?.end, hasDate: v.date_range?.start && v.date_range.start.length === 8 }))
})

const healthScore = computed(() => status.value?.health_score || 0)
const healthStatus = computed(() => { const s = healthScore.value; if (s >= 80) return { text: '健康', color: 'var(--stock-down)' }; if (s >= 50) return { text: '部分可用', color: 'var(--el-color-warning)' }; return { text: '需补数据', color: 'var(--stock-up)' } })
const diagnosis = computed(() => { if (!status.value?.diagnostics) return []; return status.value.diagnostics.map(d => ({ level: d.level, text: d.message })) })

const factorDetailRows = computed(() => {
  const detail = status.value?.factor_detail_latest; if (!detail) return []
  const groupMap: Record<string, string[]> = { '基础': ['pct_chg', 'pre_close', 'open', 'high', 'low', 'close'], 'MA均线': ['ma5', 'ma10', 'ma20', 'ma60'], 'TALib(回测补)': ['macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'], '量价': ['turnover_rate', 'volume_ratio', 'circ_mv'], '涨跌停': ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count'] }
  const nameMap: Record<string, string> = { pct_chg: '涨跌幅', pre_close: '前收盘', open: '开盘', high: '最高', low: '最低', close: '收盘', ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60', macd: 'MACD', rsi_6: 'RSI6', boll_upper: '布林上轨', atr: 'ATR', fear_greed_index: '恐贪指数', turnover_rate: '换手率', volume_ratio: '量比', circ_mv: '流通市值', is_limit_up: '涨停标记', is_limit_down: '跌停标记', first_limit_up: '首板标记', limit_up_count: '连板数' }
  const rows: { group: string; name: string; key: string; coverage: number; status: string }[] = []
  for (const [group, factors] of Object.entries(groupMap)) { for (const f of factors) { const cov = detail[f] ?? 0; let st = 'ok'; if (cov < 50) st = 'danger'; else if (cov < 90) st = 'warning'; rows.push({ group, name: nameMap[f] || f, key: f, coverage: cov, status: st }) } }
  return rows
})

function covStatus(cov: number): { icon: string; color: string; label: string } {
  if (cov >= 90) return { icon: '✅', color: 'var(--stock-down)', label: '完整' }
  if (cov >= 50) return { icon: '⚠️', color: 'var(--el-color-warning)', label: '部分' }
  return { icon: '❌', color: 'var(--stock-up)', label: '缺失' }
}

const latestDateStr = computed(() => { const cov = status.value?.daily_coverage; return cov?.length ? fmtDate(cov[cov.length - 1]?.date || '') : '' })

function srcStatusColor(s: string) { return { ok: 'var(--stock-down)', limited: 'var(--el-color-warning)', degraded: 'var(--el-color-warning)', blocked: 'var(--stock-up)', disabled: 'var(--text-tertiary)' }[s] || 'var(--text-tertiary)' }
function srcStatusText(s: string) { return { ok: '✅可用', limited: '⚠️受限', degraded: '⚠️降级', blocked: '❌被封', disabled: '🚫停用' }[s] || s }

// 今日待办分组
const actionGroups = computed(() => {
  const items = status.value?.action_items || []
  const groups = [
    { key: 'must', label: '🔴 必须做', items: items.filter(i => i.priority === 'high') },
    { key: 'should', label: '🟡 建议做', items: items.filter(i => i.priority === 'medium') },
    { key: 'optional', label: '💤 可忽略', items: items.filter(i => i.priority === 'low' || i.priority === 'info' || i.priority === 'done') },
  ]
  return groups
})

function priorityIcon(p: string) {
  return { done: '✅', info: '💤', high: '🔴', medium: '🟡', low: '🔵' }[p] || '⚪'
}
// ===== 自动补全因子开关 =====
const autoFillEnabled = ref(localStorage.getItem('autoFillEnabled') === 'true')
const autoFillDetecting = ref(false)
const autoFillDetectResult = ref<any>(null)
const autoFillRunning = ref(false)
const autoFillTaskId = ref('')
const autoFillStatus = ref<any>(null)
const autoFillPollTimer = ref<any>(null)

function onAutoFillToggle(val: string | number | boolean) {
  const enabled = val === true || val === 'true'
  autoFillEnabled.value = enabled
  localStorage.setItem('autoFillEnabled', String(enabled))
  if (enabled) {
    // 开关打开时：先检测，再触发补全
    runAutoFill()
  }
}

async function runAutoFill() {
  // Step 1: 检测缺失
  autoFillDetecting.value = true
  autoFillDetectResult.value = null
  try {
    const res = await fetch('/api/v1/system/auto-fill-detect')
    const json = await res.json()
    if (json.success) {
      autoFillDetectResult.value = json.data
      if (json.data.total_missing_days === 0) {
        ElMessage.success('✅ 因子数据已完整，无需补全')
        autoFillDetecting.value = false
        return
      }
      // Step 2: 触发补全
      await triggerAutoFill()
    } else {
      ElMessage.error('检测失败: ' + (json.message || '未知错误'))
    }
  } catch (e: any) {
    ElMessage.error('检测请求失败: ' + e.message)
  } finally {
    autoFillDetecting.value = false
  }
}

async function triggerAutoFill() {
  autoFillRunning.value = true
  autoFillStatus.value = null
  try {
    const res = await fetch('/api/v1/system/auto-fill-trigger', { method: 'POST' })
    const json = await res.json()
    if (json.success) {
      autoFillTaskId.value = json.task_id
      startAutoFillPolling()
      ElMessage.info('🔄 自动补全已启动...')
    } else {
      autoFillRunning.value = false
      ElMessage.error(json.message || '补全启动失败')
    }
  } catch (e: any) {
    autoFillRunning.value = false
    ElMessage.error('补全请求失败: ' + e.message)
  }
}

function startAutoFillPolling() {
  stopAutoFillPolling()
  autoFillPollTimer.value = setInterval(async () => {
    if (!autoFillTaskId.value) { stopAutoFillPolling(); return }
    try {
      const res = await fetch(`/api/v1/system/sync-status/${autoFillTaskId.value}`)
      const json = await res.json()
      if (json.success) {
        autoFillStatus.value = json.data
        if (['success', 'partial', 'failed'].includes(json.data.status)) {
          autoFillRunning.value = false
          stopAutoFillPolling()
          // 刷新数据状态
          await fetchData()
          // 重新检测看还有没有缺失
          if (autoFillEnabled.value && json.data.status === 'success') {
            const detectRes = await fetch('/api/v1/system/auto-fill-detect')
            const detectJson = await detectRes.json()
            if (detectJson.success) {
              autoFillDetectResult.value = detectJson.data
            }
          }
          if (json.data.status === 'success') {
            ElMessage.success('✅ 因子自动补全完成！')
          } else if (json.data.status === 'partial') {
            ElMessage.warning('⚠️ 因子补全部分完成')
          } else {
            ElMessage.error('❌ 因子补全失败')
          }
        }
      }
    } catch (e) { console.error('[DataStatusPanel]', e) }
  }, 3000)
}

function stopAutoFillPolling() {
  if (autoFillPollTimer.value) { clearInterval(autoFillPollTimer.value); autoFillPollTimer.value = null }
}

const autoFillStepLabel: Record<string, string> = {
  detect: '🔍 检测缺失因子',
  basic_factors: '📐 补算基础因子',
  daily_bar: '📊 同步日线数据',
  daily_basic: '📈 同步基础指标',
  index_daily: '📉 同步指数日线',
  limit_pools: '🎯 补涨跌停池',
  derived_factors: '🧮 补算衍生因子',
}

onMounted(() => { fetchData(); if (autoFillEnabled.value) runAutoFill() })
onUnmounted(() => { stopPolling(); stopAutoFillPolling() })
// 当面板变为可见时，如果还没有数据则加载
watch(() => props.visible, (v) => { if (v && !status.value) fetchData() })
</script>

<template>
  <div class="data-status-panel" v-loading="loading" element-loading-text="正在加载数据状态..." element-loading-background="rgba(255,255,255,0.7)">
    <!-- 顶部概览 -->
    <div class="status-header">
      <div class="health-gauge">
        <ElProgress type="circle" :percentage="healthScore" :width="80" :stroke-width="8" :color="healthStatus.color">
          <template #default><span :style="{ color: healthStatus.color, fontWeight: 700, fontSize: '16px' }">{{ healthScore }}</span></template>
        </ElProgress>
        <div class="health-label" :style="{ color: healthStatus.color }">{{ healthStatus.text }}</div>
      </div>
      <div class="summary-cards">
        <div class="s-card"><div class="s-label">日线最新</div><div class="s-value">{{ fmtDate(status?.latest?.stock_daily || '') }}</div></div>
        <div class="s-card"><div class="s-label">基础指标最新</div><div class="s-value">{{ fmtDate(status?.latest?.daily_basic || '') }}</div></div>
        <div class="s-card"><div class="s-label">日线总记录</div><div class="s-value">{{ (status?.collections?.stock_daily_ak_full?.count || 0).toLocaleString() }}</div></div>
        <div class="s-card"><div class="s-label">交易日天数</div><div class="s-value">{{ status?.daily_coverage?.length || 0 }}</div></div>
      </div>
      <div class="health-breakdown" v-if="status?.health_breakdown">
        <div class="hb-item"><span class="hb-label">因子完整</span><div class="hb-bar"><div class="hb-fill" :style="{ width: (status.health_breakdown.factor_score / status.health_breakdown.factor_max * 100) + '%', background: 'var(--stock-down)' }"></div></div><span class="hb-val">{{ status.health_breakdown.factor_score }}/{{ status.health_breakdown.factor_max }}</span></div>
        <div class="hb-item"><span class="hb-label">数据新鲜</span><div class="hb-bar"><div class="hb-fill" :style="{ width: (status.health_breakdown.freshness_score / status.health_breakdown.freshness_max * 100) + '%', background: 'var(--el-color-primary)' }"></div></div><span class="hb-val">{{ status.health_breakdown.freshness_score }}/{{ status.health_breakdown.freshness_max }}</span></div>
        <div class="hb-item"><span class="hb-label">数据源</span><div class="hb-bar"><div class="hb-fill" :style="{ width: (status.health_breakdown.source_score / status.health_breakdown.source_max * 100) + '%', background: 'var(--el-color-warning)' }"></div></div><span class="hb-val">{{ status.health_breakdown.source_score }}/{{ status.health_breakdown.source_max }}</span></div>
      </div>
      <!-- 自动补全开关 -->
      <div class="auto-fill-control">
        <div class="afc-header">
          <ElTooltip content="开启后自动检测并补全最近缺失的因子数据（MA/量比/涨跌停/竞价涨幅等）" placement="top">
            <span class="afc-label">🔄 自动补全因子</span>
          </ElTooltip>
          <ElSwitch v-model="autoFillEnabled" @change="onAutoFillToggle" :loading="autoFillDetecting || autoFillRunning" />
        </div>
        <!-- 检测结果 -->
        <div v-if="autoFillDetectResult" class="afc-detect">
          <div v-if="autoFillDetectResult.total_missing_days === 0" class="afc-complete">✅ 因子数据完整</div>
          <template v-else>
            <div class="afc-missing-summary">
              ⚠️ 近{{ autoFillDetectResult.checked_dates }}个交易日中，<b>{{ autoFillDetectResult.total_missing_days }}</b>天有因子缺失
            </div>
            <div v-if="autoFillDetectResult.missing_fields?.length" class="afc-missing-fields">
              <span v-for="mf in autoFillDetectResult.missing_fields.slice(0, 6)" :key="mf.field" class="afc-field-tag">
                {{ mf.field }} <small>({{ mf.total_missing }}条)</small>
              </span>
              <span v-if="autoFillDetectResult.missing_fields.length > 6" class="afc-field-more">
                +{{ autoFillDetectResult.missing_fields.length - 6 }}更多
              </span>
            </div>
          </template>
        </div>
        <!-- 补全进度 -->
        <div v-if="autoFillRunning || autoFillStatus" class="afc-progress" :class="{'afc-fail': autoFillStatus?.status === 'failed', 'afc-ok': autoFillStatus?.status === 'success'}">
          <div v-if="autoFillRunning" class="afc-running">
            ⏳ {{ autoFillStatus?.current_step ? autoFillStepLabel[autoFillStatus.current_step] || autoFillStatus.current_step : '正在补全...' }}
          </div>
          <div v-if="autoFillStatus" class="afc-detail">
            <span>状态: <b>{{ autoFillStatus.status === 'running' ? '🔄 执行中' : autoFillStatus.status === 'success' ? '✅ 完成' : autoFillStatus.status === 'partial' ? '⚠️ 部分完成' : '❌ 失败' }}</b></span>
            <div v-if="autoFillStatus.results" class="afc-steps">
              <div v-for="(r, ri) in autoFillStatus.results" :key="ri" class="afc-step" :class="r.success ? 'step-ok' : 'step-fail'">
                {{ autoFillStepLabel[r.step] || r.step }}: {{ r.success ? '✅' : '❌' }} {{ r.message || '' }}
              </div>
            </div>
          </div>
        </div>
        <!-- 手动补全按钮 -->
        <ElButton v-if="!autoFillEnabled && !autoFillRunning" size="small" type="primary" plain @click="runAutoFill" :loading="autoFillDetecting" style="margin-top: 6px">
          🔍 检测并补全
        </ElButton>
      </div>
    </div>

    <!-- P0: 今日待办 -->
    <ElCard v-if="status?.action_items?.length" style="margin-top: 12px">
      <template #header><span>📋 今日待办</span></template>
      <!-- 按优先级分组 -->
      <template v-for="group in actionGroups" :key="group.key">
        <div v-if="group.items.length" class="action-group">
          <div class="action-group-title" :class="'ag-' + group.key">
            {{ group.label }}
          </div>
          <div class="action-items">
            <div v-for="(item, i) in group.items" :key="i" class="action-item" :class="'action-' + item.priority">
              <span class="action-icon">{{ priorityIcon(item.priority) }}</span>
              <div class="action-content">
                <div class="action-top-row">
                  <span class="action-title">{{ item.action }}</span>
                  <ElButton
                    v-if="item.api && (item.priority === 'high' || item.priority === 'medium')"
                    size="small"
                    :type="item.priority === 'high' ? 'primary' : 'default'"
                    :loading="syncLoading === item.action"
                    @click="triggerSync(parseApiPath(item.api)!, item.action)"
                  >
                    {{ item.priority === 'high' ? '🚀 执行' : '▶ 执行' }}
                  </ElButton>
                </div>
                <div class="action-desc">{{ item.desc }}</div>
                <div v-if="item.note" class="action-note">💡 {{ item.note }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
      <!-- 同步进度 -->
      <div v-if="syncLoading || syncStatus" class="sync-progress" :class="{'sync-fail': syncStatus?.status === 'failed', 'sync-ok': syncStatus?.status === 'success'}">
        <div v-if="syncLoading" class="sync-running">⏳ 正在执行 {{ syncLoading }}...</div>
        <div v-if="syncStatus" class="sync-detail">
          <span>状态: <b>{{ syncStatus.status === 'running' ? '🔄 执行中' : syncStatus.status === 'success' ? '✅ 完成' : syncStatus.status === 'partial' ? '⚠️ 部分完成' : '❌ 失败' }}</b></span>
          <span v-if="syncStatus.current_step">当前步骤: {{ syncStatus.current_step }}</span>
          <span v-if="syncStatus.message" class="sync-msg">{{ syncStatus.message }}</span>
          <div v-if="syncStatus.results" class="sync-steps">
            <div v-for="(r, ri) in syncStatus.results" :key="ri" class="sync-step" :class="r.success ? 'step-ok' : 'step-fail'">
              {{ r.step }}: {{ r.success ? '✅' : '❌' }} {{ r.message || '' }}
            </div>
          </div>
        </div>
      </div>
    </ElCard>

    <!-- P0: 策略可用性 -->
    <ElCard v-if="status?.strategy_availability?.length" style="margin-top: 12px">
      <template #header><span>🎯 策略可用性</span></template>
      <div class="strategy-grid">
        <div v-for="st in status.strategy_availability" :key="st.key" class="strategy-card" :class="st.available ? 'st-ok' : 'st-blocked'">
          <div class="st-header">
            <span class="st-icon">{{ st.available ? '✅' : '⚠️' }}</span>
            <span class="st-name">{{ st.name }}</span>
            <ElTag :type="st.available ? 'success' : 'warning'" size="small">{{ st.coverage }}%</ElTag>
          </div>
          <div class="st-desc">{{ st.desc }}</div>
          <div v-if="st.missing_factors.length" class="st-missing">缺少: {{ st.missing_factors.join(', ') }}</div>
        </div>
      </div>
    </ElCard>

    <!-- ===== 因子状态仪表盘(替代热力图) ===== -->
    <div v-if="factorGroupCards.length" class="factor-dashboard">
      <div class="fd-title">📊 因子状态 <span class="fd-date">{{ latestDateStr }}</span></div>
      <div class="fd-cards">
        <div v-for="g in factorGroupCards" :key="g.key" class="fd-group" :class="'fdg-' + g.key">
          <div class="fdg-header">
            <span class="fdg-icon">{{ g.icon }}</span>
            <span class="fdg-name">{{ g.name }}</span>
            <span class="fdg-pct" :style="{ color: covStatus(g.avgCov).color }">{{ g.avgCov }}%</span>
          </div>
          <div class="fdg-bar">
            <div class="fdg-bar-fill" :style="{ width: g.avgCov + '%', background: covStatus(g.avgCov).color }"></div>
          </div>
          <div class="fdg-factors">
            <span v-for="f in g.factors" :key="f.key" class="fdg-factor" :class="{ ok: f.coverage >= 90, warn: f.coverage >= 50 && f.coverage < 90, bad: f.coverage < 50 }">
              {{ f.name }} <b>{{ f.coverage }}%</b>
            </span>
          </div>
          <div v-if="g.note" class="fdg-note">{{ g.note }}</div>
        </div>
      </div>
    </div>

    <!-- ===== 因子覆盖率趋势 ===== -->
    <ElCard v-if="factorTrendOption" style="margin-top: 12px">
      <template #header><span>📈 因子覆盖率趋势</span></template>
      <VChart :option="factorTrendOption" autoresize style="height: 220px; width: 100%" />
    </ElCard>

    <!-- 问题诊断 -->
    <div v-if="diagnosis.length" class="diagnosis-box">
      <div class="diag-title">⚠️ 数据问题</div>
      <div v-for="(issue, i) in diagnosis" :key="i" class="diag-item" :class="'diag-' + issue.level">
        {{ issue.level === 'red' ? '🔴' : issue.level === 'yellow' ? '🟡' : '🔴' }} {{ issue.text }}
      </div>
    </div>

    <!-- 推荐回测区间 -->
    <ElCard v-if="status?.recommended_ranges?.length" style="margin-top: 12px">
      <template #header><span>🎯 推荐回测区间</span></template>
      <div class="recommended-ranges">
        <div v-for="(r, i) in status.recommended_ranges" :key="i" class="range-card">
          <div class="range-dates">{{ fmtDate(r.start) }} ~ {{ fmtDate(r.end) }}</div>
          <ElTag type="success" size="small">因子{{ r.factor_rate }}</ElTag>
        </div>
      </div>
    </ElCard>
    <ElCard v-else style="margin-top: 12px">
      <template #header><span>🎯 推荐回测区间</span></template>
      <div style="color: var(--el-color-warning); font-size: 13px">当前无因子覆盖率≥70%的连续区间，请检查数据补全情况。</div>
    </ElCard>

    <!-- P1: 数据对齐 -->
    <ElCard v-if="status?.data_alignment?.date" style="margin-top: 12px">
      <template #header><span>🔗 数据对齐 ({{ fmtDate(status.data_alignment.date) }})</span></template>
      <div class="alignment-row">
        <div class="align-block"><div class="align-label">日线数据</div><div class="align-count">{{ status.data_alignment.stock_daily_count }}</div></div>
        <div class="align-vs"><div class="align-common">共同 {{ status.data_alignment.common }}</div><div class="align-arrow">⟷</div></div>
        <div class="align-block"><div class="align-label">日基础数据</div><div class="align-count">{{ status.data_alignment.daily_basic_count }}</div></div>
      </div>
      <div class="align-detail" v-if="status.data_alignment.only_in_basic > 0">
        <ElTag type="warning" size="small">日基础数据独有 {{ status.data_alignment.only_in_basic }} 只</ElTag>
        <span class="align-samples">(停牌/非A股: {{ status.data_alignment.only_in_basic_samples.join(', ') }}...)</span>
      </div>
      <div class="align-detail" v-if="status.data_alignment.only_in_daily > 0">
        <ElTag type="danger" size="small">日线数据独有 {{ status.data_alignment.only_in_daily }} 只</ElTag>
      </div>
    </ElCard>

    <!-- 数据集概览 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🗄️ 数据集概览</span></template>
      <ElTable :data="collectionRows" size="small" border stripe>
        <ElTableColumn prop="name" label="名称" width="180" />
        <ElTableColumn prop="key" label="集合" width="200" />
        <ElTableColumn label="记录数" width="100"><template #default="{ row }">{{ row.count.toLocaleString() }}</template></ElTableColumn>
        <ElTableColumn label="日期区间" min-width="220">
          <template #default="{ row }">
            <span v-if="row.hasDate" style="font-family: monospace; font-size: 13px">{{ fmtDate(row.dateStart) }} ~ {{ fmtDate(row.dateEnd) }}</span>
            <span v-else style="color: var(--text-tertiary)">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="80">
          <template #default="{ row }">
            <ElTag v-if="row.key === 'stock_daily_ak_full' && row.count > 400000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'daily_basic' && row.count > 2000000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'index_daily' && row.count > 1000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'limit_list' && row.count > 40000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'limit_pool_down' && row.count < 10" type="danger" size="small">缺失</ElTag>
            <ElTag v-else-if="row.count > 0" type="success" size="small">有数据</ElTag>
            <ElTag v-else type="info" size="small">空</ElTag>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- P1: 因子详情 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🔍 因子明细 ({{ latestDateStr }})</span></template>
      <div v-if="factorDetailRows.length" class="factor-detail-grid">
        <template v-for="(row, i) in factorDetailRows" :key="i">
          <div v-if="i === 0 || row.group !== factorDetailRows[i-1].group" class="fd-group-header">{{ row.group }}</div>
          <div class="fd-row">
            <span class="fd-name">{{ row.name }}</span>
            <div class="fd-bar-wrap"><div class="fd-bar" :style="{ width: row.coverage + '%', background: row.status === 'ok' ? 'var(--stock-down)' : row.status === 'warning' ? 'var(--el-color-warning)' : 'var(--stock-up)' }"></div></div>
            <span class="fd-pct" :style="{ color: row.status === 'ok' ? 'var(--stock-down)' : row.status === 'warning' ? 'var(--el-color-warning)' : 'var(--stock-up)' }">{{ row.coverage }}%</span>
          </div>
        </template>
      </div>
    </ElCard>

    <!-- 数据源 -->
    <ElCard style="margin-top: 12px">
      <template #header><div style="display:flex;justify-content:space-between;align-items:center"><span>📡 数据源状态</span><ElButton size="small" @click="fetchData" :loading="loading">🔄 刷新</ElButton></div></template>
      <div class="source-grid">
        <div v-for="src in status?.data_sources || []" :key="src.name" class="source-card" :class="'src-' + src.status">
          <div class="src-header"><span class="src-name">{{ src.name }}</span><span class="src-status" :style="{ color: srcStatusColor(src.status) }">{{ srcStatusText(src.status) }}</span></div>
          <div class="src-type">{{ src.type }}</div>
          <div class="src-detail" v-if="src.status_text">{{ src.status_text }}</div>
          <div class="src-detail"><b>限制:</b> {{ src.rate_limit }}</div>
          <div class="src-detail"><b>覆盖:</b> {{ src.coverage }}</div>
          <div class="src-gotchas" v-if="src.gotchas?.length"><div class="src-gotchas-title">⚠️ 注意:</div><div v-for="(g, i) in src.gotchas" :key="i" class="src-gotcha">• {{ g }}</div></div>
          <div class="src-scripts" v-if="src.scripts?.length"><span class="src-scripts-label">脚本:</span><code v-for="s in src.scripts" :key="s" class="src-script">{{ s }}</code></div>
        </div>
      </div>
    </ElCard>

    <!-- 策略因子关系+流程 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🔄 策略因子关系</span></template>
      <StrategyFactorPanel />
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.data-status-panel { padding: 0; min-width: 0; }
.status-header { display: flex; gap: 20px; align-items: center; padding: 16px; background: var(--el-fill-color-lighter); border-radius: 8px; flex-wrap: wrap; min-width: 0; }
.health-gauge { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.health-label { font-size: 13px; font-weight: 600; }
.summary-cards { display: flex; gap: 16px; flex: 1 1 auto; flex-wrap: wrap; min-width: 0; }
.s-card { display: flex; flex-direction: column; min-width: 100px; padding: 8px 16px; border-radius: 6px; background: var(--bg-elevated); }
.s-label { font-size: 11px; color: var(--el-text-color-secondary); }
.s-value { font-size: 18px; font-weight: 700; color: var(--el-text-color-primary); margin-top: 2px; }
.health-breakdown { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
.hb-item { display: flex; align-items: center; gap: 6px; }
.hb-label { font-size: 11px; color: var(--text-tertiary); width: 52px; text-align: right; }
.hb-bar { flex: 1; height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; min-width: 60px; }
.hb-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.hb-val { font-size: 11px; color: var(--text-secondary); width: 36px; }

/* 因子仪表盘 */
.factor-dashboard { margin-top: 12px; }
.fd-title { font-size: 15px; font-weight: 700; color: var(--text-primary); margin-bottom: 10px; }
.fd-date { font-size: 12px; color: var(--text-tertiary); font-weight: 400; margin-left: 6px; }
.fd-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr)); gap: 10px; }
.fd-group { padding: 12px 14px; border-radius: 8px; border: 1px solid var(--border-default); background: var(--bg-elevated); transition: border-color 0.2s; }
.fd-group:hover { border-color: var(--primary-400); }
.fdg-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.fdg-icon { font-size: 18px; }
.fdg-name { font-weight: 700; font-size: 14px; flex: 1; }
.fdg-pct { font-weight: 800; font-size: 18px; }
.fdg-bar { height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; margin-bottom: 8px; }
.fdg-bar-fill { height: 100%; border-radius: 3px; transition: width 0.4s; }
.fdg-factors { display: flex; flex-wrap: wrap; gap: 4px; }
.fdg-factor { font-size: 11px; padding: 2px 7px; border-radius: 4px; background: var(--bg-muted); }
.fdg-factor b { margin-left: 2px; }
.fdg-factor.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.fdg-factor.warn { color: var(--el-color-warning); background: var(--warning-bg); }
.fdg-factor.bad { color: var(--stock-up); background: var(--stock-up-bg); }
.fdg-note { font-size: 11px; color: var(--text-tertiary); margin-top: 6px; font-style: italic; }

/* 自动补全控制 */
.auto-fill-control {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 220px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}
.afc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}
.afc-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  cursor: help;
}
.afc-detect {
  font-size: 12px;
}
.afc-complete {
  color: var(--stock-down);
  font-weight: 600;
}
.afc-missing-summary {
  color: var(--el-color-warning);
  font-weight: 500;
}
.afc-missing-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.afc-field-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--warning-bg);
  color: var(--el-color-warning);
}
.afc-field-tag small {
  opacity: 0.7;
}
.afc-field-more {
  font-size: 11px;
  color: var(--text-tertiary);
}
.afc-progress {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
}
.afc-ok { background: var(--success-bg); border: 1px solid var(--success-bg); }
.afc-fail { background: var(--error-bg); border: 1px solid var(--error-bg); }
.afc-running { color: var(--primary-500); font-weight: 600; }
.afc-detail { display: flex; flex-direction: column; gap: 4px; color: var(--text-secondary); }
.afc-steps { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.afc-step { font-size: 11px; padding: 2px 6px; border-radius: 3px; }
.step-ok { background: var(--success-bg); color: var(--success); }
.step-fail { background: var(--error-bg); color: var(--error); }
.action-items { display: flex; flex-direction: column; gap: 8px; }
.action-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 12px; border-radius: 6px; }
.action-high { background: var(--stock-up-bg); border-left: 3px solid var(--stock-up); }
.action-medium { background: var(--warning-bg); border-left: 3px solid var(--el-color-warning); }
.action-done { background: var(--stock-down-bg); border-left: 3px solid var(--stock-down); }
.action-info { background: var(--bg-muted); border-left: 3px solid var(--text-tertiary); }
.action-icon { font-size: 16px; margin-top: 1px; }
.action-content { flex: 1; }
.action-title { font-weight: 600; font-size: 14px; }
.action-top-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.action-desc { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }
.action-note { font-size: 11px; color: var(--primary-500); margin-top: 4px; padding: 4px 8px; background: var(--bg-active); border-radius: 4px; }

/* 待办分组 */
.action-group { margin-bottom: 8px; }
.action-group:last-child { margin-bottom: 0; }
.action-group-title { font-size: 13px; font-weight: 700; padding: 4px 0; margin-bottom: 4px; }
.ag-must { color: var(--stock-up); }
.ag-should { color: var(--el-color-warning); }
.ag-optional { color: var(--text-tertiary); }
.action-low { background: var(--bg-muted); border-left: 3px solid var(--text-tertiary); }

/* 同步进度 */
.sync-progress { margin-top: 12px; padding: 10px 14px; border-radius: 6px; }
.sync-ok { background: var(--success-bg); border: 1px solid var(--success-bg); }
.sync-fail { background: var(--error-bg); border: 1px solid var(--error-bg); }
.sync-running { color: var(--primary-500); font-size: 13px; font-weight: 600; }
.sync-detail { font-size: 12px; color: var(--text-secondary); display: flex; flex-direction: column; gap: 4px; }
.sync-msg { color: var(--stock-up); font-weight: 600; }
.sync-steps { display: flex; gap: 12px; margin-top: 4px; }
.sync-step { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.step-ok { background: var(--success-bg); color: var(--success); }
.step-fail { background: var(--error-bg); color: var(--error); }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); gap: 10px; }
.strategy-card { padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default); }
.st-ok { border-color: var(--success); background: var(--success-bg); }
.st-blocked { border-color: var(--warning); background: var(--warning-bg); }
.st-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.st-icon { font-size: 16px; }
.st-name { font-weight: 700; font-size: 14px; flex: 1; }
.st-desc { font-size: 11px; color: var(--text-tertiary); }
.st-missing { font-size: 11px; color: var(--el-color-warning); margin-top: 4px; }
.alignment-row { display: flex; align-items: center; justify-content: center; gap: 16px; padding: 12px 0; flex-wrap: wrap; min-width: 0; }
.align-block { text-align: center; min-width: 100px; }
.align-label { font-size: 12px; color: var(--text-tertiary); }
.align-count { font-size: 22px; font-weight: 700; }
.align-vs { text-align: center; }
.align-common { font-size: 12px; color: var(--stock-down); font-weight: 600; }
.align-arrow { font-size: 20px; color: var(--text-quaternary, var(--text-muted)); }
.align-detail { margin-top: 8px; display: flex; align-items: center; gap: 6px; }
.align-samples { font-size: 11px; color: var(--text-tertiary); }
.factor-detail-grid { display: flex; flex-direction: column; gap: 2px; }
.fd-group-header { font-size: 12px; font-weight: 700; color: var(--text-secondary); padding: 6px 0 2px 0; border-top: 1px solid var(--border-default); margin-top: 4px; }
.fd-group-header:first-child { border-top: none; margin-top: 0; }
.fd-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.fd-name { font-size: 12px; color: var(--text-secondary); width: 60px; text-align: right; }
.fd-bar-wrap { flex: 1; height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; }
.fd-bar { height: 100%; border-radius: 3px; transition: width 0.3s; }
.fd-pct { font-size: 11px; width: 40px; text-align: right; font-weight: 600; }
.diagnosis-box { margin-top: 12px; padding: 12px 16px; background: var(--stock-up-bg); border-radius: 6px; border-left: 4px solid var(--stock-up); }
.diag-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.diag-item { font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; padding-left: 8px; }
.diag-warn { color: var(--text-secondary); }
.recommended-ranges { display: flex; gap: 12px; flex-wrap: wrap; }
.range-card { display: flex; align-items: center; gap: 10px; padding: 10px 18px; border-radius: 6px; background: var(--stock-down-bg); border: 1px solid var(--stock-down-bg); }
.range-dates { font-size: 15px; font-weight: 600; font-family: monospace; }
.source-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 12px; }
.source-card { padding: 12px 14px; border-radius: 8px; border: 1px solid var(--border-default); background: var(--bg-elevated); transition: border-color 0.2s;
  &.src-blocked { border-color: var(--stock-up); background: var(--stock-up-bg); }
  &.src-disabled { border-color: var(--border-muted); opacity: 0.6; }
  &.src-ok { border-color: var(--stock-down); }
  &.src-limited, &.src-degraded { border-color: var(--el-color-warning); background: var(--warning-bg); } }
.src-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.src-name { font-weight: 700; font-size: 14px; }
.src-status { font-size: 12px; font-weight: 600; }
.src-type { font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px; }
.src-detail { font-size: 12px; color: var(--text-secondary); margin-bottom: 3px; line-height: 1.5; }
.src-gotchas { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--border-default); }
.src-gotchas-title { font-size: 12px; font-weight: 600; color: var(--el-color-warning); margin-bottom: 2px; }
.src-gotcha { font-size: 11px; color: var(--text-secondary); line-height: 1.6; }
.src-scripts { margin-top: 6px; }
.src-scripts-label { font-size: 11px; color: var(--text-tertiary); }
.src-script { font-size: 11px; background: var(--bg-muted); padding: 1px 5px; border-radius: 3px; margin-right: 4px; }
</style>
