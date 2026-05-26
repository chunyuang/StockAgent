<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElCard, ElEmpty, ElProgress, ElTable, ElTableColumn, ElTag, ElButton, ElMessage } from 'element-plus'
import StrategyFactorPanel from './StrategyFactorPanel.vue'

interface DailyCoverage { date: string; total: number; factor_rate: number; groups: Record<string, number> }
interface CollectionInfo { count: number; date_range: { start: string; end: string } | null; error?: string }
interface DataSource { name: string; type: string; status: string; status_text: string; rate_limit: string; coverage: string; gotchas: string[]; scripts: string[] }
interface RecommendedRange { start: string; end: string; factor_rate: string }
interface StrategyItem { name: string; key: string; available: boolean; coverage: number; missing_factors: string[]; desc: string }
interface ActionItem { action: string; command: string; desc: string; priority: string; api?: string }
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
const factorDetailExpanded = ref(false)
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
    } catch { /* ignore poll errors */ }
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

const heatmapOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  const groups = ['basic', 'technical', 'volume', 'limit']
  const groupLabels: Record<string, string> = { basic: '基础', technical: '技术指标', volume: '量价', limit: '涨跌停' }
  const data: number[][] = []
  const yLabels = cov.map(c => `${c.date.slice(4,6)}/${c.date.slice(6,8)}`)
  cov.forEach((c, yi) => { groups.forEach((g, xi) => { data.push([xi, yi, c.groups[g] || 0]) }) })
  const needZoom = yLabels.length > 15
  const dataZoomY = needZoom ? [{ type: 'slider', yAxisIndex: 0, startValue: Math.max(0, yLabels.length - 30), endValue: yLabels.length - 1, right: 0, width: 16, top: 10, bottom: 30, borderColor: 'var(--border-default)', fillerColor: 'var(--info-bg)', handleStyle: { color: 'var(--el-color-primary)' }, labelFormatter: (v: number) => yLabels[v] || '' }] : []
  return {
    tooltip: { formatter: (p: any) => { const c = cov[p.data[1]]; const g = groups[p.data[0]]; return `${fmtDate(c.date)} ${groupLabels[g]}<br/>覆盖率: ${p.data[2]}%<br/>股票数: ${c.total}` } },
    grid: { left: 60, right: needZoom ? 36 : 30, top: 10, bottom: 30 }, dataZoom: dataZoomY,
    xAxis: { type: 'category', data: groups.map(g => groupLabels[g]), splitArea: { show: true }, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'category', data: yLabels, axisLabel: { fontSize: 10 } },
    visualMap: { min: 0, max: 100, inRange: { color: ['var(--stock-up)', 'var(--el-color-warning)', '#f5da55', '#95d475', 'var(--stock-down)'] }, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, text: ['100%', '0%'], textStyle: { fontSize: 10 } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (p: any) => p.data[2] > 0 ? `${p.data[2]}` : '', fontSize: 9, color: 'var(--text-primary)' }, itemStyle: { borderWidth: 1, borderColor: 'var(--bg-elevated)' } }]
  }
})

const stockCountOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  const totalDays = cov.length; const showDays = Math.min(totalDays, 60)
  const startPercent = ((totalDays - showDays) / totalDays) * 100
  return {
    tooltip: { trigger: 'axis' }, grid: { left: 50, right: 20, top: 20, bottom: 60 },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: startPercent, end: 100, height: 20, bottom: 8, borderColor: 'var(--border-default)', fillerColor: 'var(--info-bg)', handleStyle: { color: 'var(--el-color-primary)' }, labelFormatter: (v: number) => { const idx = Math.round(v / 100 * (cov.length - 1)); return cov[idx] ? `${cov[idx].date.slice(4,6)}/${cov[idx].date.slice(6,8)}` : '' } },
      { type: 'inside', xAxisIndex: 0 }
    ],
    xAxis: { type: 'category', data: cov.map(c => `${c.date.slice(4,6)}/${c.date.slice(6,8)}`), axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: [{ type: 'value', name: '股票数', min: 0, axisLabel: { fontSize: 10 } }, { type: 'value', name: '覆盖率%', min: 0, max: 100, axisLabel: { fontSize: 10 } }],
    series: [
      { name: '股票数', type: 'bar', data: cov.map(c => c.total), itemStyle: { color: 'var(--el-color-primary)' }, barMaxWidth: 20 },
      { name: '因子覆盖率', type: 'line', yAxisIndex: 1, data: cov.map(c => c.factor_rate), itemStyle: { color: 'var(--stock-down)' }, lineStyle: { width: 2 }, areaStyle: { color: 'rgba(103,194,58,0.1)' } }
    ]
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
  const groupMap: Record<string, string[]> = { '基础': ['pct_chg', 'pre_close', 'open', 'high', 'low', 'close'], '技术指标': ['ma5', 'macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'], '量价': ['turnover_rate', 'volume_ratio', 'circ_mv'], '涨跌停': ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count'] }
  const nameMap: Record<string, string> = { pct_chg: '涨跌幅', pre_close: '前收盘', open: '开盘', high: '最高', low: '最低', close: '收盘', ma5: 'MA5', macd: 'MACD', rsi_6: 'RSI6', boll_upper: '布林上轨', atr: 'ATR', fear_greed_index: '恐贪指数', turnover_rate: '换手率', volume_ratio: '量比', circ_mv: '流通市值', is_limit_up: '涨停标记', is_limit_down: '跌停标记', first_limit_up: '首板标记', limit_up_count: '连板数' }
  const rows: { group: string; name: string; key: string; coverage: number; status: string }[] = []
  for (const [group, factors] of Object.entries(groupMap)) { for (const f of factors) { const cov = detail[f] ?? 0; let st = 'ok'; if (cov < 50) st = 'danger'; else if (cov < 90) st = 'warning'; rows.push({ group, name: nameMap[f] || f, key: f, coverage: cov, status: st }) } }
  return rows
})

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
onMounted(fetchData)
onUnmounted(() => { stopPolling() })
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

    <!-- P1: 因子详情(可展开) -->
    <ElCard style="margin-top: 12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer" @click="factorDetailExpanded = !factorDetailExpanded">
          <span>📊 因子详情 ({{ latestDateStr }})</span>
          <span style="font-size: 12px; color: var(--text-tertiary)">{{ factorDetailExpanded ? '收起 ▲' : '展开 ▼' }}</span>
        </div>
      </template>
      <div v-if="factorDetailExpanded && factorDetailRows.length" class="factor-detail-grid">
        <template v-for="(row, i) in factorDetailRows" :key="i">
          <div v-if="i === 0 || row.group !== factorDetailRows[i-1].group" class="fd-group-header">{{ row.group }}</div>
          <div class="fd-row">
            <span class="fd-name">{{ row.name }}</span>
            <div class="fd-bar-wrap"><div class="fd-bar" :style="{ width: row.coverage + '%', background: row.status === 'ok' ? 'var(--stock-down)' : row.status === 'warning' ? 'var(--el-color-warning)' : 'var(--stock-up)' }"></div></div>
            <span class="fd-pct" :style="{ color: row.status === 'ok' ? 'var(--stock-down)' : row.status === 'warning' ? 'var(--el-color-warning)' : 'var(--stock-up)' }">{{ row.coverage }}%</span>
          </div>
        </template>
      </div>
      <div v-else-if="!factorDetailExpanded" style="color: var(--text-tertiary); font-size: 13px; text-align: center; padding: 4px 0">点击展开查看每个因子的覆盖率</div>
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
    <StrategyFactorPanel />
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
