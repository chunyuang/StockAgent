<script setup lang="ts">
/**
 * BacktestHistoryPanel - 回测历史列表
 *
 * 展示所有历史回测记录，支持：
 * - 收益率/胜率/夏普等指标排序
 * - 查看结果、查看日志、复用参数
 * - 删除历史记录
 * - 状态/日期筛选
 * - 多条记录对比
 *
 * V4: 统一Element Plus浅色主题，与整体界面风格一致
 */
import { ref, onMounted, computed } from 'vue'
import { getUltraShortHistory, deleteBacktestHistory, type BacktestHistoryItem } from '@/api/modules/backtest'
import { ElTable, ElTableColumn, ElButton, ElTag, ElEmpty, ElMessageBox, ElMessage, ElCard } from 'element-plus'
import { View, Document, RefreshRight, Delete } from '@element-plus/icons-vue'
import { STRATEGY_NAMES } from '@/config/backtestConstants'

const emit = defineEmits<{
  (e: 'view-result', task: BacktestHistoryItem): void
  (e: 'view-logs', taskId: string): void
  (e: 'reuse-params', task: BacktestHistoryItem): void
}>()

const loading = ref(false)
const items = ref<BacktestHistoryItem[]>([])
const total = ref(0)

// 任务4: 历史对比
const selectedForCompare = ref<string[]>([])
const showCompare = ref(false)
const compareItems = ref<BacktestHistoryItem[]>([])

// 策略ID→中文名 - 使用共享配置，robust地去emoji
const strategyNameMap: Record<string, string> = Object.fromEntries(
  Object.entries(STRATEGY_NAMES).map(([k, v]) => [k, v.replace(/^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}\u{20E3}]+\s*/u, '').trim() || v])
)

// 排序
const sortKey = ref<'created_at' | 'total_return' | 'win_rate' | 'sharpe_ratio' | 'max_drawdown'>('created_at')
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

function strategyNames(strategies: string[] | undefined): string {
  if (!strategies || strategies.length === 0) return '-'
  const names = strategies.map(s => strategyNameMap[s] || s)
  if (names.length <= 3) return names.join('、')
  return names.slice(0, 3).join('、') + `等${names.length}个`
}

// 任务4: 对比功能
function openCompare() {
  compareItems.value = sortedItems.value.filter(i => selectedForCompare.value.includes(i.task_id))
  showCompare.value = true
}

// 判断是否被选中用于对比
function isCompareSelected(taskId: string): boolean {
  return selectedForCompare.value.includes(taskId)
}

function toggleCompareSelect(taskId: string) {
  if (selectedForCompare.value.includes(taskId)) {
    selectedForCompare.value = selectedForCompare.value.filter(id => id !== taskId)
  } else if (selectedForCompare.value.length < 3) {
    selectedForCompare.value.push(taskId)
  }
}

// 对比表指标
const compareMetrics = [
  { key: 'date_range', label: '日期范围', format: (item: BacktestHistoryItem) => `${item.start_date || '?'}~${item.end_date || '?'}` },
  { key: 'total_return', label: '收益率', format: (item: BacktestHistoryItem) => formatReturn(item.total_return), classFn: (item: BacktestHistoryItem) => item.total_return != null && item.total_return >= 0 ? 'text-green' : 'text-red' },
  { key: 'win_rate', label: '胜率', format: (item: BacktestHistoryItem) => formatRate(item.win_rate) },
  { key: 'sharpe_ratio', label: '夏普比率', format: (item: BacktestHistoryItem) => formatSharpe(item.sharpe_ratio) },
  { key: 'max_drawdown', label: '最大回撤', format: (item: BacktestHistoryItem) => formatDrawdown(item.max_drawdown), classFn: () => 'text-red' },
  { key: 'trades_count', label: '交易笔数', format: (item: BacktestHistoryItem) => String(item.total_trades ?? item.trades_count ?? '-') },
  { key: 'profit_loss_ratio', label: '盈亏比', format: (item: BacktestHistoryItem) => item.profit_loss_ratio?.toFixed(2) ?? '-' },
  { key: 'total_signals', label: '信号数', format: (item: BacktestHistoryItem) => String(item.total_signals ?? '-') },
]

// 对比表中最优值高亮
function isBestInCompare(metricKey: string, item: BacktestHistoryItem): boolean {
  if (compareItems.value.length < 2) return false
  const metric = compareMetrics.find(m => m.key === metricKey)
  if (!metric) return false
  const val = item[metricKey as keyof BacktestHistoryItem] as number | null | undefined
  if (val == null) return false
  const allVals = compareItems.value.map(i => i[metricKey as keyof BacktestHistoryItem] as number | null | undefined).filter(v => v != null) as number[]
  if (allVals.length === 0) return false
  if (metricKey === 'max_drawdown') return val === Math.min(...allVals) // 回撤越小越好
  return val === Math.max(...allVals) // 其他指标越大越好
}

onMounted(loadHistory)
</script>

<template>
  <div class="history-panel">
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
      :data="sortedItems"
      v-loading="loading"
      size="small"
      border
      stripe
      style="width: 100%"
      @row-click="(row: any) => toggleCompareSelect(row.task_id)"
      :row-class-name="({ row }: any) => isCompareSelected(row.task_id) ? 'compare-selected-row' : ''"
    >
      <ElTableColumn type="selection" width="40" :selectable="() => selectedForCompare.length < 3 || true" />
      <ElTableColumn label="时间" width="110" sortable sort-by="created_at">
        <template #default="{ row }">
          <span style="color: #909399; font-size: 12px">{{ formatDate(row.created_at) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="日期范围" width="160">
        <template #default="{ row }">
          <span style="font-family: monospace; font-size: 12px">{{ row.start_date || '?' }} ~ {{ row.end_date || '?' }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="策略" min-width="120" show-overflow-tooltip>
        <template #default="{ row }">
          {{ strategyNames(row.strategies) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="收益率" width="100" sortable sort-by="total_return">
        <template #default="{ row }">
          <span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c', fontWeight: 600 }">
            {{ formatReturn(row.total_return) }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="胜率" width="80" sortable sort-by="win_rate">
        <template #default="{ row }">{{ formatRate(row.win_rate) }}</template>
      </ElTableColumn>
      <ElTableColumn label="夏普" width="80" sortable sort-by="sharpe_ratio">
        <template #default="{ row }">{{ formatSharpe(row.sharpe_ratio) }}</template>
      </ElTableColumn>
      <ElTableColumn label="回撤" width="90" sortable sort-by="max_drawdown">
        <template #default="{ row }">
          <span style="color: #f56c6c">{{ formatDrawdown(row.max_drawdown) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="信号" width="60" align="center">
        <template #default="{ row }">{{ row.total_signals ?? '-' }}</template>
      </ElTableColumn>
      <ElTableColumn label="交易" width="60" align="center">
        <template #default="{ row }">{{ row.trades_count ?? row.total_trades ?? '-' }}</template>
      </ElTableColumn>
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
          <ElButton size="small" @click="showCompare = false; selectedForCompare = []">关闭</ElButton>
        </div>
      </template>
      <ElTable :data="compareMetrics" size="small" border>
        <ElTableColumn prop="label" label="指标" width="100" />
        <ElTableColumn v-for="item in compareItems" :key="item.task_id" :label="strategyNames(item.strategies)">
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
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;

  h3 {
    margin: 0;
    font-size: 15px;
    color: #303133;
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

:deep(.compare-selected-row) {
  background-color: #ecf5ff !important;
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
