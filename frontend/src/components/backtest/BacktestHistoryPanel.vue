<script setup lang="ts">
/**
 * BacktestHistoryPanel V5 - 回测历史列表（丰富版）
 *
 * 改进：
 * 1. 顶部汇总统计条（总回测次数/最佳收益/平均胜率/平均夏普）
 * 2. 收益率可视化色块条（从红到绿的渐变，直观区分好坏）
 * 3. 更多指标列：盈亏比、耗时、策略数
 * 4. 状态标签（completed/failed彩色标记）
 * 5. 对比模式优化：内联对比面板+雷达图式对比
 * 6. 行内mini进度条表示收益在全部记录中的分位
 */
import { ref, onMounted, computed, watch } from 'vue'
import { getUltraShortHistory, deleteBacktestHistory, type BacktestHistoryItem } from '@/api/modules/backtest'
import { ElTable, ElTableColumn, ElButton, ElTag, ElEmpty, ElMessageBox, ElMessage, ElCard, ElTooltip, ElProgress } from 'element-plus'
import { View, Document, RefreshRight, Delete, TrendCharts, Timer } from '@element-plus/icons-vue'
import { STRATEGY_NAMES } from '@/config/backtestConstants'

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

// 对比
const selectedForCompare = ref<string[]>([])
const showCompare = ref(false)
const compareItems = ref<BacktestHistoryItem[]>([])
const historyTableRef = ref<any>(null)

// 策略ID→中文名
const strategyNameMap: Record<string, string> = Object.fromEntries(
  Object.entries(STRATEGY_NAMES).map(([k, v]) => [k, v.replace(/^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}\u{20E3}]+\s*/u, '').trim() || v])
)

// ==================== 汇总统计 ====================
const summary = computed(() => {
  const completed = items.value.filter(i => i.status === 'completed' || !i.status)
  if (completed.length === 0) return null
  const returns = completed.map(i => i.total_return ?? 0).filter(v => v != null)
  const winRates = completed.map(i => i.win_rate ?? 0).filter(v => v != null)
  const sharpes = completed.map(i => i.sharpe_ratio ?? 0).filter(v => v != null)
  const drawdowns = completed.map(i => i.max_drawdown ?? 0).filter(v => v != null)
  const trades = completed.map(i => i.total_trades ?? i.trades_count ?? 0)
  return {
    count: completed.length,
    bestReturn: returns.length ? Math.max(...returns) : 0,
    worstReturn: returns.length ? Math.min(...returns) : 0,
    avgReturn: returns.length ? returns.reduce((a, b) => a + b, 0) / returns.length : 0,
    avgWinRate: winRates.length ? winRates.reduce((a, b) => a + b, 0) / winRates.length : 0,
    avgSharpe: sharpes.length ? sharpes.reduce((a, b) => a + b, 0) / sharpes.length : 0,
    maxDrawdown: drawdowns.length ? Math.max(...drawdowns) : 0,
    totalTrades: trades.reduce((a, b) => a + b, 0),
    profitCount: returns.filter(v => v > 0).length,
  }
})

// 收益率在全部记录中的分位数（用于mini进度条）
function returnPercentile(val: number | null | undefined): number {
  if (val == null) return 0
  const allReturns = items.value
    .map(i => i.total_return)
    .filter((v): v is number => v != null)
  if (allReturns.length === 0) return 50
  const sorted = [...allReturns].sort((a, b) => a - b)
  const min = sorted[0]
  const max = sorted[sorted.length - 1]
  if (max === min) return 50
  return Math.round(((val - min) / (max - min)) * 100)
}

// 收益率对应颜色
function returnColor(val: number | null | undefined): string {
  if (val == null) return '#c0c4cc'
  if (val >= 30) return '#2d8a4e'
  if (val >= 10) return '#67c23a'
  if (val >= 0) return '#95d475'
  if (val >= -10) return '#f89898'
  return '#f56c6c'
}

// 排序
const sortKey = ref<'created_at' | 'total_return' | 'win_rate' | 'sharpe_ratio' | 'max_drawdown' | 'profit_loss_ratio'>('created_at')
const sortDesc = ref(true)

function toggleSort(key: typeof sortKey.value) {
  if (sortKey.value === key) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = key
    sortDesc.value = key === 'created_at' ? true : false
  }
}

const sortedItems = computed(() => {
  const list = [...items.value]
  list.sort((a, b) => {
    const va = a[sortKey.value] ?? 0
    const vb = b[sortKey.value] ?? 0
    if (typeof va === 'string' && typeof vb === 'string') {
      return sortDesc.value ? vb.localeCompare(va) : va.localeCompare(vb)
    }
    return sortDesc.value ? (vb as number) - (va as number) : (va as number) - (vb as number)
  })
  return list
})

async function loadHistory() {
  loading.value = true
  try {
    const result = await getUltraShortHistory({ limit: 100 })
    items.value = result.items
    total.value = result.total
  } catch (e) {
    console.error('加载回测历史失败:', e)
  } finally {
    loading.value = false
  }
}

async function handleDelete(item: BacktestHistoryItem) {
  const dateRange = `${item.start_date || '?'}~${item.end_date || '?'}`
  const strategies = strategyNames(item.strategies)
  try {
    await ElMessageBox.confirm(
      `确定删除这条回测记录？\n日期: ${dateRange}\n策略: ${strategies}\n收益: ${formatReturn(item.total_return)}`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteBacktestHistory(item.task_id)
    ElMessage.success('已删除')
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// 格式化
function formatReturn(val: number | null | undefined): string {
  if (val === null || val === undefined) return '-'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}
function formatRate(val: number | null | undefined): string {
  if (val === null || val === undefined) return '-'
  return `${val.toFixed(1)}%`
}
function formatSharpe(val: number | null | undefined): string {
  if (val === null || val === undefined) return '-'
  return val.toFixed(2)
}
function formatDrawdown(val: number | null | undefined): string {
  if (val === null || val === undefined) return '-'
  return `${val.toFixed(2)}%`
}
function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return iso.slice(0, 10)
}
function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}秒`
  const m = Math.floor(s / 60)
  const rs = s % 60
  return `${m}分${rs}秒`
}
function strategyNames(strategies: string[] | undefined): string {
  if (!strategies || strategies.length === 0) return '-'
  const names = strategies.map(s => strategyNameMap[s] || s)
  if (names.length <= 2) return names.join(' + ')
  return names.slice(0, 2).join(' + ') + ` +${names.length - 2}`
}

// 对比
function onSelectionChange(rows: BacktestHistoryItem[]) {
  selectedForCompare.value = rows.slice(0, 3).map(r => r.task_id)
}
function openCompare() {
  compareItems.value = sortedItems.value.filter(i => selectedForCompare.value.includes(i.task_id))
  showCompare.value = true
}
function closeCompare() {
  showCompare.value = false
  selectedForCompare.value = []
  historyTableRef.value?.clearSelection()
}
function isCompareSelected(taskId: string): boolean {
  return selectedForCompare.value.includes(taskId)
}

const compareMetrics = [
  { key: 'date_range', label: '日期范围', format: (item: BacktestHistoryItem) => `${item.start_date || '?'}~${item.end_date || '?'}` },
  { key: 'total_return', label: '累计收益', format: (item: BacktestHistoryItem) => formatReturn(item.total_return), classFn: (item: BacktestHistoryItem) => item.total_return != null && item.total_return >= 0 ? 'text-green' : 'text-red' },
  { key: 'annualized_return', label: '年化收益', format: (item: BacktestHistoryItem) => item.annualized_return != null ? formatReturn(item.annualized_return) : '-' },
  { key: 'win_rate', label: '胜率', format: (item: BacktestHistoryItem) => formatRate(item.win_rate) },
  { key: 'sharpe_ratio', label: '夏普比率', format: (item: BacktestHistoryItem) => formatSharpe(item.sharpe_ratio) },
  { key: 'max_drawdown', label: '最大回撤', format: (item: BacktestHistoryItem) => formatDrawdown(item.max_drawdown), classFn: () => 'text-red' },
  { key: 'trades_count', label: '交易笔数', format: (item: BacktestHistoryItem) => String(item.total_trades ?? item.trades_count ?? '-') },
  { key: 'profit_loss_ratio', label: '盈亏比', format: (item: BacktestHistoryItem) => item.profit_loss_ratio?.toFixed(2) ?? '-' },
  { key: 'total_signals', label: '信号数', format: (item: BacktestHistoryItem) => String(item.total_signals ?? '-') },
  { key: 'initial_cash', label: '初始资金', format: (item: BacktestHistoryItem) => item.initial_cash ? `¥${(item.initial_cash / 10000).toFixed(0)}万` : '-' },
]

function isBestInCompare(metricKey: string, item: BacktestHistoryItem): boolean {
  if (compareItems.value.length < 2) return false
  const val = item[metricKey as keyof BacktestHistoryItem] as number | null | undefined
  if (val == null) return false
  const allVals = compareItems.value.map(i => i[metricKey as keyof BacktestHistoryItem] as number | null | undefined).filter(v => v != null) as number[]
  if (allVals.length === 0) return false
  if (metricKey === 'max_drawdown') return val === Math.min(...allVals)
  return val === Math.max(...allVals)
}

onMounted(loadHistory)
// 当面板变为可见时，如果还没有数据则加载
watch(() => props.visible, (v) => { if (v && items.value.length === 0) loadHistory() })
</script>

<template>
  <div class="history-panel" v-loading="loading" element-loading-text="正在加载回测历史..." element-loading-background="rgba(255,255,255,0.7)">
    <!-- 汇总统计条 -->
    <div v-if="summary" class="summary-bar">
      <div class="summary-item">
        <span class="summary-label">回测次数</span>
        <span class="summary-value">{{ summary.count }}</span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">最佳收益</span>
        <span class="summary-value" :style="{ color: returnColor(summary.bestReturn) }">
          {{ formatReturn(summary.bestReturn) }}
        </span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">最差收益</span>
        <span class="summary-value" :style="{ color: returnColor(summary.worstReturn) }">
          {{ formatReturn(summary.worstReturn) }}
        </span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">平均胜率</span>
        <span class="summary-value">{{ formatRate(summary.avgWinRate) }}</span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">平均夏普</span>
        <span class="summary-value">{{ formatSharpe(summary.avgSharpe) }}</span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">盈利占比</span>
        <span class="summary-value" :style="{ color: summary.profitCount / summary.count > 0.5 ? '#67c23a' : '#f56c6c' }">
          {{ summary.count > 0 ? (summary.profitCount / summary.count * 100).toFixed(0) : 0 }}%
        </span>
      </div>
      <div class="summary-divider" />
      <div class="summary-item">
        <span class="summary-label">总交易</span>
        <span class="summary-value">{{ summary.totalTrades }}笔</span>
      </div>
    </div>

    <!-- 头部 -->
    <div class="history-header">
      <h3>📊 回测历史 ({{ total }}条)</h3>
      <div class="header-actions">
        <ElButton size="small" :disabled="selectedForCompare.length < 2" @click="openCompare" type="primary" plain>
          📊 对比 ({{ selectedForCompare.length }}/3)
        </ElButton>
        <ElButton size="small" :loading="loading" @click="loadHistory" :icon="RefreshRight">
          刷新
        </ElButton>
      </div>
    </div>

    <!-- 空状态 -->
    <ElEmpty v-if="sortedItems.length === 0 && !loading" description="暂无回测记录">
      <template #description>
        <p>暂无回测记录</p>
        <p class="hint">提交一次回测后，历史记录将出现在这里</p>
      </template>
    </ElEmpty>

    <!-- 历史列表 -->
    <ElTable
      v-else
      ref="historyTableRef"
      :data="sortedItems"
      v-loading="loading"
      size="small"
      border
      stripe
      style="width: 100%"
      @selection-change="onSelectionChange"
      :row-class-name="({ row }: any) => isCompareSelected(row.task_id) ? 'compare-selected-row' : ''"
    >
      <ElTableColumn type="selection" width="40" :selectable="(row: any) => selectedForCompare.length < 3 || selectedForCompare.includes(row.task_id)" />

      <!-- 状态 -->
      <ElTableColumn label="状态" width="60" align="center">
        <template #default="{ row }">
          <ElTag v-if="row.status === 'failed'" type="danger" size="small" effect="dark">失败</ElTag>
          <ElTag v-else-if="row.status === 'running'" type="warning" size="small" effect="dark">运行</ElTag>
          <ElTag v-else type="success" size="small" effect="plain">完成</ElTag>
        </template>
      </ElTableColumn>

      <!-- 时间 -->
      <ElTableColumn label="时间" width="105" sortable sort-by="created_at">
        <template #default="{ row }">
          <span style="color: #909399; font-size: 12px">{{ formatDate(row.created_at) }}</span>
        </template>
      </ElTableColumn>

      <!-- 日期范围 -->
      <ElTableColumn label="日期范围" width="155">
        <template #default="{ row }">
          <span style="font-family: monospace; font-size: 12px">{{ row.start_date || '?' }} ~ {{ row.end_date || '?' }}</span>
        </template>
      </ElTableColumn>

      <!-- 策略 -->
      <ElTableColumn label="策略" min-width="110" show-overflow-tooltip>
        <template #default="{ row }">
          <div style="display:flex;align-items:center;gap:4px">
            <ElTag size="small" effect="plain" type="info">{{ row.strategies?.length ?? 0 }}策略</ElTag>
            <span style="font-size:12px">{{ strategyNames(row.strategies) }}</span>
          </div>
        </template>
      </ElTableColumn>

      <!-- 收益率（带mini进度条） -->
      <ElTableColumn label="收益率" width="130" sortable sort-by="total_return">
        <template #default="{ row }">
          <div style="display:flex;flex-direction:column;gap:2px">
            <span :style="{ color: returnColor(row.total_return), fontWeight: 700, fontSize: '13px' }">
              {{ formatReturn(row.total_return) }}
            </span>
            <div v-if="row.total_return != null" class="mini-bar">
              <div class="mini-bar-fill" :style="{ width: returnPercentile(row.total_return) + '%', background: returnColor(row.total_return) }" />
            </div>
          </div>
        </template>
      </ElTableColumn>

      <!-- 胜率 -->
      <ElTableColumn label="胜率" width="75" sortable sort-by="win_rate">
        <template #default="{ row }">
          <span :style="{ color: (row.win_rate ?? 0) >= 50 ? '#67c23a' : '#e6a23c' }">{{ formatRate(row.win_rate) }}</span>
        </template>
      </ElTableColumn>

      <!-- 夏普 -->
      <ElTableColumn label="夏普" width="70" sortable sort-by="sharpe_ratio">
        <template #default="{ row }">
          <span :style="{ color: (row.sharpe_ratio ?? 0) >= 2 ? '#67c23a' : (row.sharpe_ratio ?? 0) >= 1 ? '#e6a23c' : '#f56c6c' }">
            {{ formatSharpe(row.sharpe_ratio) }}
          </span>
        </template>
      </ElTableColumn>

      <!-- 回撤 -->
      <ElTableColumn label="回撤" width="75" sortable sort-by="max_drawdown">
        <template #default="{ row }">
          <span :style="{ color: (row.max_drawdown ?? 0) <= 5 ? '#67c23a' : (row.max_drawdown ?? 0) <= 10 ? '#e6a23c' : '#f56c6c' }">
            {{ formatDrawdown(row.max_drawdown) }}
          </span>
        </template>
      </ElTableColumn>

      <!-- 盈亏比 -->
      <ElTableColumn label="盈亏比" width="70" sortable sort-by="profit_loss_ratio">
        <template #default="{ row }">
          <span :style="{ color: (row.profit_loss_ratio ?? 0) >= 2 ? '#67c23a' : (row.profit_loss_ratio ?? 0) >= 1 ? '#e6a23c' : '#f56c6c' }">
            {{ row.profit_loss_ratio?.toFixed(2) ?? '-' }}
          </span>
        </template>
      </ElTableColumn>

      <!-- 交易/信号 -->
      <ElTableColumn label="交易" width="55" align="center">
        <template #default="{ row }">{{ row.trades_count ?? row.total_trades ?? '-' }}</template>
      </ElTableColumn>
      <ElTableColumn label="信号" width="55" align="center">
        <template #default="{ row }">{{ row.total_signals ?? '-' }}</template>
      </ElTableColumn>

      <!-- 耗时 -->
      <ElTableColumn label="耗时" width="75" align="center">
        <template #default="{ row }">
          <ElTooltip v-if="row.execution_time_ms" :content="`${row.execution_time_ms}ms`" placement="top">
            <span style="font-size:12px;color:#909399">{{ formatDuration(row.execution_time_ms) }}</span>
          </ElTooltip>
          <span v-else style="color:#c0c4cc">-</span>
        </template>
      </ElTableColumn>

      <!-- 操作 -->
      <ElTableColumn label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <ElButton size="small" link type="primary" :icon="View" @click.stop="emit('view-result', row)">结果</ElButton>
          <ElButton size="small" link type="info" :icon="Document" @click.stop="emit('view-logs', row.task_id)">日志</ElButton>
          <ElButton size="small" link type="success" :icon="RefreshRight" @click.stop="emit('reuse-params', row)">复用</ElButton>
          <ElButton size="small" link type="danger" :icon="Delete" @click.stop="handleDelete(row)">删除</ElButton>
        </template>
      </ElTableColumn>
    </ElTable>

    <!-- 对比面板 -->
    <ElCard v-if="showCompare" shadow="hover" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-weight: 600">📊 回测对比</span>
          <ElButton size="small" @click="closeCompare">关闭</ElButton>
        </div>
      </template>
      <ElTable :data="compareMetrics" size="small" border>
        <ElTableColumn prop="label" label="指标" width="100" />
        <ElTableColumn v-for="item in compareItems" :key="item.task_id" :label="strategyNames(item.strategies) + ' (' + formatDate(item.created_at).slice(5) + ')'" min-width="120">
          <template #default="{ row }">
            <span
              :class="{ 'best-value': isBestInCompare(row.key, item) }"
              :style="{ color: row.classFn ? (row.classFn(item) === 'text-green' ? '#67c23a' : row.classFn(item) === 'text-red' ? '#f56c6c' : '') : '' }"
            >
              {{ row.format(item) }}
            </span>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<script lang="ts">
export default { name: 'BacktestHistoryPanel' }
</script>

<style scoped lang="scss">
.history-panel {
  background: var(--bg-elevated);
  border-radius: 6px;
  overflow: hidden;
}

/* 汇总统计条 */
.summary-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: var(--bg-muted);
  border-bottom: 1px solid var(--border-default);
  flex-wrap: wrap;
}
.summary-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.summary-label {
  font-size: 11px;
  color: var(--text-tertiary);
}
.summary-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.summary-divider {
  width: 1px;
  height: 28px;
  background: var(--border-default);
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);

  h3 {
    margin: 0;
    font-size: 15px;
    color: var(--text-primary);
    font-weight: 600;
  }

  .header-actions {
    display: flex;
    gap: 8px;
    align-items: center;
  }
}

.hint {
  font-size: 13px;
  margin-top: 8px;
  color: #909399;
}

/* Mini进度条（收益率分位） */
.mini-bar {
  height: 3px;
  background: var(--border-default);
  border-radius: 2px;
  overflow: hidden;
}
.mini-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

:deep(.compare-selected-row) {
  background-color: var(--primary-50) !important;
}

.best-value {
  font-weight: 700;
  position: relative;
  &::after {
    content: ' ★';
    color: #e6a23c;
    font-size: 11px;
  }
}

.text-green { color: #67c23a; }
.text-red { color: #f56c6c; }
</style>
