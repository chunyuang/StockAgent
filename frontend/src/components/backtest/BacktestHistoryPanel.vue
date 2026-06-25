<script setup lang="ts">
/**
 * BacktestHistoryPanel V6 - 回测历史列表（卡片+表格混合版）
 *
 * V6改进：
 * 1. 卡片式布局替代纯表格，策略信息完整展示不被截断
 * 2. 顶部汇总统计条简化更紧凑
 * 3. 每条记录用卡片展示，核心指标一目了然
 * 4. 保留表格模式可切换（紧凑/卡片）
 * 5. 放大缩小时自适应良好
 */
import { ref, onMounted, computed, watch } from 'vue'
import { getUltraShortHistory, deleteBacktestHistory, type BacktestHistoryItem } from '@/api/modules/backtest'
import { ElButton, ElTag, ElEmpty, ElMessageBox, ElMessage, ElCard } from 'element-plus'
import { View, Document, RefreshRight, Delete, Grid, List } from '@element-plus/icons-vue'
import { STRATEGY_NAMES } from '@/config/backtestConstants'
// 【V63修复:P1-11】对比面板增加收益柱状图
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const props = defineProps<{
  visible?: boolean
}>()

const emit = defineEmits<{
  (e: 'view-result', task: BacktestHistoryItem): void
  (e: 'view-logs', taskId: string): void
  (e: 'reuse-params', task: BacktestHistoryItem): void
}>()

const loading = ref(false)
const items = ref<BacktestHistoryItem[]>([])
const total = ref(0)
const viewMode = ref<'card' | 'table'>('card')

// 对比
const selectedForCompare = ref<string[]>([])
const showCompare = ref(false)
const compareItems = ref<BacktestHistoryItem[]>([])

// 多选删除
const deleteMode = ref(false)
const selectedForDelete = ref<Set<string>>(new Set())

function toggleDeleteMode() {
  deleteMode.value = !deleteMode.value
  if (!deleteMode.value) selectedForDelete.value.clear()
}

function toggleDeleteSelect(taskId: string) {
  if (selectedForDelete.value.has(taskId)) selectedForDelete.value.delete(taskId)
  else selectedForDelete.value.add(taskId)
}

function selectAllForDelete() {
  if (selectedForDelete.value.size === sortedItems.value.length) {
    selectedForDelete.value.clear()
  } else {
    selectedForDelete.value = new Set(sortedItems.value.map(i => i.task_id))
  }
}

async function batchDelete() {
  const count = selectedForDelete.value.size
  if (count === 0) return
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${count} 条回测记录？此操作不可恢复。`, '批量删除确认', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
  } catch (e) { /* user cancelled confirm */ console.debug('[BacktestHistory] batchDelete confirm cancelled'); return }
  loading.value = true
  let success = 0, fail = 0
  for (const taskId of selectedForDelete.value) {
    try { await deleteBacktestHistory(taskId); success++ }
    catch (e) { console.error('[backtestHistory] delete failed:', e); fail++ }
  }
  selectedForDelete.value.clear()
  deleteMode.value = false
  loading.value = false
  if (fail === 0) ElMessage.success(`已删除 ${success} 条记录`)
  else ElMessage.warning(`成功 ${success} 条，失败 ${fail} 条`)
  await loadHistory()
}

// 策略ID→中文名
const strategyNameMap: Record<string, string> = Object.fromEntries(
  Object.entries(STRATEGY_NAMES).map(([k, v]) => [k, v.replace(/^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}\u{20E3}]+\s*/u, '').trim() || v])
)

// 策略颜色映射(暗色模式安全)
const strategyColors: Record<string, string> = {
  halfway_chase: 'var(--warning)',
  first_limit_up: 'var(--stock-up)',
  dragon_head: 'var(--el-color-primary)',
  leader_buy_dip: 'var(--el-color-primary)',
  limit_down_qiao: 'var(--stock-down)',
  limit_up_open: 'var(--text-tertiary)',
}

// 【V66修复:P0-5】暗色模式下策略标签文字颜色适配
function strategyTagTextColor(_bgColor: string): string {
  // 在暗色模式下使用亮色文字以确保对比度
  return 'var(--text-primary)';
}

// ==================== 汇总统计 ====================
const summary = computed(() => {
  const completed = items.value.filter(i => i.status === 'completed' || !i.status)
  if (completed.length === 0) return null
  const returns = completed.map(i => i.total_return ?? 0).filter(v => v != null)
  const winRates = completed.map(i => i.win_rate ?? 0).filter(v => v != null)
  const sharpes = completed.map(i => i.sharpe_ratio ?? 0).filter(v => v != null)
  return {
    count: completed.length,
    bestReturn: returns.length ? Math.max(...returns) : 0,
    worstReturn: returns.length ? Math.min(...returns) : 0,
    avgWinRate: winRates.length ? winRates.reduce((a, b) => a + b, 0) / winRates.length : 0,
    avgSharpe: sharpes.length ? sharpes.reduce((a, b) => a + b, 0) / sharpes.length : 0,
    profitCount: returns.filter(v => v > 0).length,
    totalTrades: completed.map(i => i.total_trades ?? i.trades_count ?? 0).reduce((a, b) => a + b, 0),
  }
})

// 收益率在全部记录中的分位数
function returnPercentile(val: number | null | undefined): number {
  if (val == null) return 0
  const allReturns = items.value.map(i => i.total_return).filter((v): v is number => v != null)
  if (allReturns.length === 0) return 50
  const sorted = [...allReturns].sort((a, b) => a - b)
  const min = sorted[0], max = sorted[sorted.length - 1]
  if (max === min) return 50
  return Math.round(((val - min) / (max - min)) * 100)
}

function returnColor(val: number | null | undefined): string {
  if (val == null) return 'var(--text-muted)'
  if (val >= 30) return 'var(--stock-down)'
  if (val >= 10) return 'var(--stock-down-light)'
  if (val >= 0) return 'var(--stock-down-bg)'
  if (val >= -10) return 'var(--stock-up-light)'
  return 'var(--stock-up)'
}

// 排序
const sortKey = ref<'created_at' | 'total_return' | 'win_rate' | 'sharpe_ratio' | 'max_drawdown'>('created_at')
const sortDesc = ref(true)

function toggleSort(key: typeof sortKey.value) {
  if (sortKey.value === key) sortDesc.value = !sortDesc.value
  else { sortKey.value = key; sortDesc.value = key === 'created_at' ? true : false }
}

const sortedItems = computed(() => {
  const list = [...items.value]
  list.sort((a, b) => {
    const va = a[sortKey.value] ?? 0, vb = b[sortKey.value] ?? 0
    if (typeof va === 'string' && typeof vb === 'string') return sortDesc.value ? vb.localeCompare(va) : va.localeCompare(vb)
    return sortDesc.value ? (vb as number) - (va as number) : (va as number) - (vb as number)
  })
  return list
})

async function loadHistory() {
  loading.value = true
  try { const result = await getUltraShortHistory({ limit: 100 }); items.value = result.items; total.value = result.total }
  catch (e) { console.error('加载回测历史失败:', e) }
  finally { loading.value = false }
}

async function handleDelete(item: BacktestHistoryItem) {
  try { await ElMessageBox.confirm(`确定删除 ${item.start_date||'?'}~${item.end_date||'?'} 的回测记录？`, '删除确认', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) }
  catch (e) { console.debug('[BacktestHistory] delete confirm cancelled'); return }
  try { await deleteBacktestHistory(item.task_id); ElMessage.success('已删除'); await loadHistory() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

// 格式化
function formatReturn(val: number | null | undefined): string { if (val == null) return '-'; return `${val >= 0 ? '+' : ''}${val.toFixed(2)}%` }
function formatRate(val: number | null | undefined): string { if (val == null) return '-'; return `${val.toFixed(1)}%` }
function formatSharpe(val: number | null | undefined): string { if (val == null) return '-'; return val.toFixed(2) }
function formatDrawdown(val: number | null | undefined): string { if (val == null) return '-'; return `${val.toFixed(2)}%` }
function formatDate(iso: string | null): string { if (!iso) return '-'; return iso.slice(0, 10) }
function formatDuration(ms: number | null | undefined): string { if (ms == null) return '-'; if (ms < 1000) return `${ms}ms`; const s = Math.round(ms / 1000); if (s < 60) return `${s}秒`; return `${Math.floor(s/60)}分${s%60}秒` }
function strategyNames(strategies: string[] | undefined): string { if (!strategies || !strategies.length) return '-'; return strategies.map(s => strategyNameMap[s] || s).join('、') }
function strategyTag(sid: string) { return { name: strategyNameMap[sid] || sid, color: strategyColors[sid] || 'var(--text-tertiary)' } }

// 对比
function toggleCompare(taskId: string) {
  const idx = selectedForCompare.value.indexOf(taskId)
  if (idx >= 0) selectedForCompare.value.splice(idx, 1)
  else if (selectedForCompare.value.length < 3) selectedForCompare.value.push(taskId)
}
function openCompare() { compareItems.value = sortedItems.value.filter(i => selectedForCompare.value.includes(i.task_id)); showCompare.value = true }
function closeCompare() { showCompare.value = false; selectedForCompare.value = [] }
function isCompareSelected(taskId: string): boolean { return selectedForCompare.value.includes(taskId) }

const compareMetrics = [
  { key: 'date_range', label: '日期范围', format: (i: BacktestHistoryItem) => (i.start_date || '?') + ' ~ ' + (i.end_date || '?') },
  { key: 'total_return', label: '累计收益', format: (i: BacktestHistoryItem) => formatReturn(i.total_return), classFn: (i: BacktestHistoryItem) => i.total_return != null && i.total_return >= 0 ? 'text-green' : 'text-red' },
  { key: 'annualized_return', label: '年化收益', format: (i: BacktestHistoryItem) => i.annualized_return != null ? formatReturn(i.annualized_return) : '-' },
  { key: 'win_rate', label: '胜率', format: (i: BacktestHistoryItem) => formatRate(i.win_rate) },
  { key: 'sharpe_ratio', label: '夏普比率', format: (i: BacktestHistoryItem) => formatSharpe(i.sharpe_ratio) },
  { key: 'max_drawdown', label: '最大回撤', format: (i: BacktestHistoryItem) => formatDrawdown(i.max_drawdown), classFn: () => 'text-red' },
  { key: 'trades_count', label: '交易笔数', format: (i: BacktestHistoryItem) => String(i.total_trades ?? i.trades_count ?? '-') },
  { key: 'profit_loss_ratio', label: '盈亏比', format: (i: BacktestHistoryItem) => i.profit_loss_ratio?.toFixed(2) ?? '-' },
]
function isBestInCompare(metricKey: string, item: BacktestHistoryItem): boolean {
  if (compareItems.value.length < 2) return false
  const val = item[metricKey as keyof BacktestHistoryItem] as number | null | undefined
  if (val == null) return false
  const allVals = compareItems.value.map(i => i[metricKey as keyof BacktestHistoryItem] as number | null | undefined).filter(v => v != null) as number[]
  if (!allVals.length) return false
  if (metricKey === 'max_drawdown') return val === Math.min(...allVals)
  return val === Math.max(...allVals)
}

// 【V63修复:P1-11】对比面板收益柱状图
const compareChartOption = computed(() => {
  if (compareItems.value.length < 2) return null
  const names = compareItems.value.map(ci => strategyNames(ci.strategies) + ' (' + formatDate(ci.created_at).slice(5) + ')')
  const returns = compareItems.value.map(ci => ci.total_return ?? 0)
  const winRates = compareItems.value.map(ci => ci.win_rate ?? 0)
  const sharpes = compareItems.value.map(ci => ci.sharpe_ratio ?? 0)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['收益率(%)', '胜率(%)', '夏普'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: names },
    yAxis: [
      { type: 'value', name: '%', position: 'left' },
      { type: 'value', name: '夏普', position: 'right' }
    ],
    series: [
      { name: '收益率(%)', type: 'bar', data: returns, itemStyle: { color: 'var(--success)' } },
      { name: '胜率(%)', type: 'bar', data: winRates, itemStyle: { color: 'var(--el-color-primary)' } },
      { name: '夏普', type: 'bar', yAxisIndex: 1, data: sharpes, itemStyle: { color: 'var(--warning)' } },
    ]
  }
})

onMounted(loadHistory)
watch(() => props.visible, (v) => { if (v && !items.value.length) loadHistory() })
</script>

<template>
  <div class="history-panel" v-loading="loading" element-loading-text="正在加载回测历史...">

    <!-- 汇总统计条 -->
    <div v-if="summary" class="summary-bar">
      <div class="sm-item"><span class="sm-val">{{ summary.count }}</span><span class="sm-lbl">回测</span></div>
      <div class="sm-div" />
      <div class="sm-item"><span class="sm-val" :style="{ color: returnColor(summary.bestReturn) }">{{ formatReturn(summary.bestReturn) }}</span><span class="sm-lbl">最佳</span></div>
      <div class="sm-div" />
      <div class="sm-item"><span class="sm-val" :style="{ color: returnColor(summary.worstReturn) }">{{ formatReturn(summary.worstReturn) }}</span><span class="sm-lbl">最差</span></div>
      <div class="sm-div" />
      <div class="sm-item"><span class="sm-val">{{ formatRate(summary.avgWinRate) }}</span><span class="sm-lbl">均胜率</span></div>
      <div class="sm-div" />
      <div class="sm-item"><span class="sm-val">{{ formatSharpe(summary.avgSharpe) }}</span><span class="sm-lbl">均夏普</span></div>
      <div class="sm-div" />
      <div class="sm-item"><span class="sm-val" :style="{ color: summary.profitCount / summary.count > 0.5 ? 'var(--stock-down)' : 'var(--stock-up)' }">{{ (summary.profitCount / summary.count * 100).toFixed(0) }}%</span><span class="sm-lbl">盈利率</span></div>
    </div>

    <!-- 头部 -->
    <div class="history-header">
      <div class="hh-left">
        <h3>📊 回测历史 ({{ total }}条)</h3>
        <div class="view-toggle">
          <ElButton :type="viewMode === 'card' ? 'primary' : 'default'" size="small" :icon="Grid" @click="viewMode = 'card'" plain>卡片</ElButton>
          <ElButton :type="viewMode === 'table' ? 'primary' : 'default'" size="small" :icon="List" @click="viewMode = 'table'" plain>列表</ElButton>
        </div>
      </div>
      <div class="header-actions">
        <ElButton size="small" :disabled="selectedForCompare.length < 2" @click="openCompare" type="primary" plain>
          📊 对比 ({{ selectedForCompare.length }}/3)
        </ElButton>
        <ElButton size="small" :loading="loading" @click="loadHistory" :icon="RefreshRight">刷新</ElButton>
        <ElButton size="small" :type="deleteMode ? 'danger' : 'default'" @click="toggleDeleteMode" plain>{{ deleteMode ? '取消多选' : '🗑️ 多选删除' }}</ElButton>
      </div>
      <div v-if="deleteMode" class="delete-bar">
        <ElButton size="small" @click="selectAllForDelete" plain>{{ selectedForDelete.size === sortedItems.length ? '取消全选' : '全选' }}</ElButton>
        <span class="db-count">已选 <strong>{{ selectedForDelete.size }}</strong> 条</span>
        <ElButton size="small" type="danger" :disabled="selectedForDelete.size === 0" @click="batchDelete">🗑️ 删除选中</ElButton>
      </div>
    </div>

    <!-- 排序栏 -->
    <div class="sort-bar">
      <span class="sort-label">排序:</span>
      <ElButton v-for="sk in (['created_at', 'total_return', 'win_rate', 'sharpe_ratio', 'max_drawdown'] as const)" :key="sk"
        size="small" :type="sortKey === sk ? 'primary' : 'default'" @click="toggleSort(sk)" plain
      >
        {{ { created_at: '时间', total_return: '收益', win_rate: '胜率', sharpe_ratio: '夏普', max_drawdown: '回撤' }[sk] }}
        <span v-if="sortKey === sk">{{ sortDesc ? '↓' : '↑' }}</span>
      </ElButton>
    </div>

    <!-- 空状态 -->
    <ElEmpty v-if="!sortedItems.length && !loading" description="暂无回测记录">
      <template #description><p>暂无回测记录</p><p class="hint">提交一次回测后，历史记录将出现在这里</p></template>
    </ElEmpty>

    <!-- ===== 卡片视图 ===== -->
    <div v-if="sortedItems.length && viewMode === 'card'" class="card-list">
      <div v-for="item in sortedItems" :key="item.task_id" class="bt-card" :class="{ 'bt-selected': deleteMode ? selectedForDelete.has(item.task_id) : isCompareSelected(item.task_id), 'bt-failed': item.status === 'failed', 'bt-delete-selected': deleteMode && selectedForDelete.has(item.task_id) }" @click="deleteMode ? toggleDeleteSelect(item.task_id) : toggleCompare(item.task_id)">

        <!-- 卡片顶行: 状态 + 日期 + 耗时 -->
        <div class="bt-top">
          <div class="bt-top-left">
            <span v-if="deleteMode" class="delete-check" :class="{ checked: selectedForDelete.has(item.task_id) }">☑</span>
            <ElTag v-if="item.status === 'failed'" type="danger" size="small" effect="dark">失败</ElTag>
            <ElTag v-else-if="item.status === 'running'" type="warning" size="small" effect="dark">运行</ElTag>
            <ElTag v-else type="success" size="small" effect="plain">完成</ElTag>
            <span class="bt-date">{{ item.start_date || '?' }} ~ {{ item.end_date || '?' }}</span>
          </div>
          <div class="bt-top-right">
            <span class="bt-created">{{ formatDate(item.created_at) }}</span>
            <span v-if="item.execution_time_ms" class="bt-duration">⏱ {{ formatDuration(item.execution_time_ms) }}</span>
          </div>
        </div>

        <!-- 策略标签行 - 完整显示所有策略 -->
        <div class="bt-strategies">
          <ElTag v-for="sid in (item.strategies || [])" :key="sid" size="small" effect="plain" :color="strategyTag(sid).color" :style="{ color: strategyTagTextColor(strategyTag(sid).color), border: 'none', fontWeight: 600 }">
            {{ strategyTag(sid).name }}
          </ElTag>
          <span v-if="!item.strategies?.length" class="bt-no-strat">未指定策略</span>
        </div>

        <!-- 指标行: 收益 + 胜率 + 夏普 + 回撤 + 盈亏比 + 交易 -->
        <div class="bt-metrics">
          <div class="bt-metric bt-metric-main">
            <span class="bt-m-val" :style="{ color: returnColor(item.total_return) }">{{ formatReturn(item.total_return) }}</span>
            <span class="bt-m-lbl">收益</span>
            <!-- mini bar -->
            <div v-if="item.total_return != null" class="mini-bar">
              <div class="mini-bar-fill" :style="{ width: returnPercentile(item.total_return) + '%', background: returnColor(item.total_return) }" />
            </div>
          </div>
          <div class="bt-metric">
            <span class="bt-m-val" :style="{ color: (item.win_rate ?? 0) >= 50 ? 'var(--stock-down)' : 'var(--warning)' }">{{ formatRate(item.win_rate) }}</span>
            <span class="bt-m-lbl">胜率</span>
          </div>
          <div class="bt-metric">
            <span class="bt-m-val" :style="{ color: (item.sharpe_ratio ?? 0) >= 2 ? 'var(--stock-down)' : (item.sharpe_ratio ?? 0) >= 1 ? 'var(--warning)' : 'var(--stock-up)' }">{{ formatSharpe(item.sharpe_ratio) }}</span>
            <span class="bt-m-lbl">夏普</span>
          </div>
          <div class="bt-metric">
            <span class="bt-m-val" :style="{ color: (item.max_drawdown ?? 0) <= 5 ? 'var(--stock-down)' : (item.max_drawdown ?? 0) <= 10 ? 'var(--warning)' : 'var(--stock-up)' }">{{ formatDrawdown(item.max_drawdown) }}</span>
            <span class="bt-m-lbl">回撤</span>
          </div>
          <div class="bt-metric">
            <span class="bt-m-val">{{ item.profit_loss_ratio?.toFixed(2) ?? '-' }}</span>
            <span class="bt-m-lbl">盈亏比</span>
          </div>
          <div class="bt-metric">
            <span class="bt-m-val">{{ item.trades_count ?? item.total_trades ?? '-' }}</span>
            <span class="bt-m-lbl">交易</span>
          </div>
        </div>

        <!-- 操作行 -->
        <div class="bt-actions">
          <ElButton size="small" link type="primary" :icon="View" @click.stop="emit('view-result', item)">查看结果</ElButton>
          <ElButton size="small" link type="info" :icon="Document" @click.stop="emit('view-logs', item.task_id)">日志</ElButton>
          <ElButton size="small" link type="success" :icon="RefreshRight" @click.stop="emit('reuse-params', item)">复用参数</ElButton>
          <ElButton size="small" link type="danger" :icon="Delete" @click.stop="handleDelete(item)">删除</ElButton>
        </div>
      </div>
    </div>

    <!-- ===== 表格视图（紧凑） ===== -->
    <div v-if="sortedItems.length && viewMode === 'table'" class="table-view">
      <table class="bt-table">
        <thead>
          <tr>
            <th v-if="deleteMode" class="th-check">
              <span class="delete-check" :class="{ checked: selectedForDelete.size === sortedItems.length && sortedItems.length > 0 }" @click="selectAllForDelete">☑</span>
            </th>
            <th>状态</th>
            <th @click="toggleSort('created_at')" :class="{ active: sortKey === 'created_at' }">时间 {{ sortKey === 'created_at' ? (sortDesc ? '↓' : '↑') : '' }}</th>
            <th>日期范围</th>
            <th>策略</th>
            <th @click="toggleSort('total_return')" :class="{ active: sortKey === 'total_return' }">收益 {{ sortKey === 'total_return' ? (sortDesc ? '↓' : '↑') : '' }}</th>
            <th @click="toggleSort('win_rate')" :class="{ active: sortKey === 'win_rate' }">胜率 {{ sortKey === 'win_rate' ? (sortDesc ? '↓' : '↑') : '' }}</th>
            <th @click="toggleSort('sharpe_ratio')" :class="{ active: sortKey === 'sharpe_ratio' }">夏普 {{ sortKey === 'sharpe_ratio' ? (sortDesc ? '↓' : '↑') : '' }}</th>
            <th @click="toggleSort('max_drawdown')" :class="{ active: sortKey === 'max_drawdown' }">回撤 {{ sortKey === 'max_drawdown' ? (sortDesc ? '↓' : '↑') : '' }}</th>
            <th>盈亏比</th>
            <th>交易</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sortedItems" :key="item.task_id" :class="{ 'bt-selected': deleteMode ? selectedForDelete.has(item.task_id) : isCompareSelected(item.task_id) }" @click="deleteMode ? toggleDeleteSelect(item.task_id) : toggleCompare(item.task_id)">
            <td v-if="deleteMode" class="td-check">
              <span class="delete-check" :class="{ checked: selectedForDelete.has(item.task_id) }">☑</span>
            </td>
            <td>
              <ElTag v-if="item.status === 'failed'" type="danger" size="small" effect="dark">失败</ElTag>
              <ElTag v-else-if="item.status === 'running'" type="warning" size="small" effect="dark">运行</ElTag>
              <ElTag v-else type="success" size="small" effect="plain">完成</ElTag>
            </td>
            <td class="td-date">{{ formatDate(item.created_at) }}</td>
            <td class="td-mono">{{ item.start_date || '?' }} ~ {{ item.end_date || '?' }}</td>
            <td class="td-strategies">
              <ElTag v-for="sid in (item.strategies || [])" :key="sid" size="small" effect="plain" :color="strategyTag(sid).color" :style="{ color: strategyTagTextColor(strategyTag(sid).color), border: 'none', fontWeight: 600, margin: '1px 2px' }">
                {{ strategyTag(sid).name }}
              </ElTag>
            </td>
            <td :style="{ color: returnColor(item.total_return), fontWeight: 700 }">{{ formatReturn(item.total_return) }}</td>
            <td :style="{ color: (item.win_rate ?? 0) >= 50 ? 'var(--stock-down)' : 'var(--warning)' }">{{ formatRate(item.win_rate) }}</td>
            <td :style="{ color: (item.sharpe_ratio ?? 0) >= 2 ? 'var(--stock-down)' : (item.sharpe_ratio ?? 0) >= 1 ? 'var(--warning)' : 'var(--stock-up)' }">{{ formatSharpe(item.sharpe_ratio) }}</td>
            <td :style="{ color: (item.max_drawdown ?? 0) <= 5 ? 'var(--stock-down)' : (item.max_drawdown ?? 0) <= 10 ? 'var(--warning)' : 'var(--stock-up)' }">{{ formatDrawdown(item.max_drawdown) }}</td>
            <td>{{ item.profit_loss_ratio?.toFixed(2) ?? '-' }}</td>
            <td>{{ item.trades_count ?? item.total_trades ?? '-' }}</td>
            <td class="td-actions">
              <ElButton size="small" link type="primary" @click.stop="emit('view-result', item)">结果</ElButton>
              <ElButton size="small" link type="info" @click.stop="emit('view-logs', item.task_id)">日志</ElButton>
              <ElButton size="small" link type="success" @click.stop="emit('reuse-params', item)">复用</ElButton>
              <ElButton size="small" link type="danger" @click.stop="handleDelete(item)">删</ElButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 对比面板 -->
    <ElCard v-if="showCompare" shadow="hover" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap:wrap;gap:8px">
          <span style="font-weight: 600">📊 回测对比</span>
          <ElButton size="small" @click="closeCompare">关闭</ElButton>
        </div>
      </template>
      <div class="compare-grid">
        <!-- 【V63修复:P1-11】对比面板增加收益柱状图 -->
        <VChart v-if="compareChartOption" :option="compareChartOption" autoresize style="height: 280px; width: 100%; margin-bottom: 12px" />
        <table class="cmp-table">
          <thead><tr><th>指标</th><th v-for="ci in compareItems" :key="ci.task_id">{{ strategyNames(ci.strategies) }} ({{ formatDate(ci.created_at).slice(5) }})</th></tr></thead>
          <tbody>
            <tr v-for="m in compareMetrics" :key="m.key">
              <td class="cmp-label">{{ m.label }}</td>
              <td v-for="ci in compareItems" :key="ci.task_id" :class="{ 'best-val': isBestInCompare(m.key, ci) }" :style="{ color: m.classFn ? (m.classFn(ci) === 'text-green' ? 'var(--stock-down)' : m.classFn(ci) === 'text-red' ? 'var(--stock-up)' : '') : '' }">
                {{ m.format(ci) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </ElCard>
  </div>
</template>

<script lang="ts">
export default { name: 'BacktestHistoryPanel' }
</script>

<style scoped lang="scss">
.history-panel { background: var(--bg-elevated); border-radius: 8px; overflow: hidden; min-width: 0; }

/* 汇总统计条 */
.summary-bar {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  background: linear-gradient(135deg, var(--success-bg) 0%, var(--bg-muted) 50%, var(--error-bg) 100%);
  border-bottom: 1px solid var(--border-default); flex-wrap: wrap; min-width: 0;
}
.sm-item { display: flex; flex-direction: column; align-items: center; gap: 1px; }
.sm-val { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.sm-lbl { font-size: 10px; color: var(--text-tertiary); }
.sm-div { width: 1px; height: 24px; background: var(--border-muted); flex-shrink: 0; }

/* 头部 */
.history-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default);
  flex-wrap: wrap; gap: 8px; min-width: 0;
  h3 { margin: 0; font-size: 15px; color: var(--text-primary); font-weight: 600; }
  .hh-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .view-toggle { display: flex; gap: 0; }
  .header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
}

/* 排序栏 */
.sort-bar {
  display: flex; align-items: center; gap: 6px; padding: 6px 16px;
  background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-wrap: wrap; min-width: 0;
  .sort-label { font-size: 12px; color: var(--text-tertiary); white-space: nowrap; }
}

.hint { font-size: 13px; margin-top: 8px; color: var(--text-tertiary); }

/* ===== 卡片视图 ===== */
.card-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(380px, 100%), 1fr));
  gap: 10px; padding: 12px;
  max-height: calc(100vh - 280px); overflow-y: auto;
}
.bt-card {
  padding: 12px 14px; border-radius: 8px; border: 1px solid var(--border-default); background: var(--bg-elevated);
  transition: all 0.2s; cursor: pointer;
  &:hover { box-shadow: var(--shadow-md); border-color: var(--border-hover); }
  &.bt-selected { border-color: var(--primary-500); background: var(--bg-active); box-shadow: 0 0 0 1px var(--el-color-primary); }
  &.bt-failed { border-left: 3px solid var(--error); }
}

/* 卡片顶行 */
.bt-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 4px; min-width: 0; }
.bt-top-left, .bt-top-right { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.bt-date { font-family: monospace; font-size: 12px; color: var(--text-secondary); font-weight: 500; }
.bt-created { font-size: 11px; color: var(--text-tertiary); }
.bt-duration { font-size: 11px; color: var(--text-tertiary); }

/* 策略标签 */
.bt-strategies { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px; min-width: 0; }
.bt-no-strat { font-size: 12px; color: var(--text-muted); }

/* 指标 */
.bt-metrics {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  gap: 6px; margin-bottom: 8px; padding: 8px; background: var(--bg-muted); border-radius: 6px;
}
.bt-metric { display: flex; flex-direction: column; align-items: center; gap: 1px; }
.bt-metric-main { /* 收益列稍大 */ }
.bt-m-val { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
.bt-m-lbl { font-size: 10px; color: var(--text-tertiary); }

.mini-bar { height: 3px; background: var(--border-default); border-radius: 2px; overflow: hidden; width: 100%; margin-top: 2px; }
.mini-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s ease; }

/* 操作 */
.bt-actions { display: flex; gap: 4px; flex-wrap: wrap; padding-top: 6px; border-top: 1px solid var(--border-light); }

/* ===== 表格视图 ===== */
.table-view { overflow-x: auto; padding: 0; }
.bt-table {
  width: 100%; border-collapse: collapse; font-size: 12px;
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border-default); white-space: nowrap; }
  th { background: var(--bg-elevated); font-weight: 600; color: var(--text-secondary); cursor: pointer; user-select: none;
    &:hover { color: var(--primary-500); }
    &.active { color: var(--primary-500); }
  }
  tr:hover td { background: var(--bg-muted); }
  tr.bt-selected td { background: var(--bg-active); }
  .td-date { color: var(--text-tertiary); }
  .td-mono { font-family: monospace; color: var(--text-secondary); }
  .td-strategies { white-space: normal; min-width: 120px; max-width: 220px; }
  .td-actions { white-space: nowrap; }
  .more-tag { font-size: 11px; color: var(--text-tertiary); margin-left: 2px; }
}

/* 对比 */
.compare-grid { overflow-x: auto; }
.cmp-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
  th, td { padding: 8px 14px; text-align: center; border: 1px solid var(--border-default); }
  th { background: var(--bg-elevated); font-weight: 600; }
  .cmp-label { text-align: left; font-weight: 600; color: var(--text-secondary); background: var(--bg-elevated); }
  .best-val { font-weight: 700; }
  .best-val::after { content: ' ★'; color: var(--warning); font-size: 11px; }
}

/* 多选删除 */
.delete-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(245, 108, 108, 0.08);
  border: 1px solid rgba(245, 108, 108, 0.2);
  border-radius: 6px;
  margin-bottom: 8px;
}
.db-count { font-size: 13px; color: var(--text-secondary); }
.delete-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 2px solid var(--border-default);
  border-radius: 4px;
  color: transparent;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
  user-select: none;
  &.checked {
    background: var(--el-color-danger);
    border-color: var(--el-color-danger);
    color: #fff;
  }
  &:hover { border-color: var(--el-color-danger); }
}
.bt-delete-selected {
  outline: 2px solid var(--el-color-danger);
  outline-offset: -2px;
  background: rgba(245, 108, 108, 0.04) !important;
}
.th-check, .td-check { width: 40px; text-align: center; }

</style>
