<script setup lang="ts">
/**
 * BacktestHistoryPanel - 回测历史列表
 *
 * 展示所有历史回测记录，支持：
 * - 收益率/胜率/夏普等指标排序
 * - 查看结果、查看日志、复用参数
 * - 状态/日期筛选
 */
import { ref, onMounted, computed } from 'vue'
import { getUltraShortHistory, type BacktestHistoryItem } from '@/api/modules/backtest'

const emit = defineEmits<{
  (e: 'view-result', task: BacktestHistoryItem): void
  (e: 'view-logs', taskId: string): void
  (e: 'reuse-params', task: BacktestHistoryItem): void
}>()

const loading = ref(false)
const items = ref<BacktestHistoryItem[]>([])
const total = ref(0)

// 策略ID→中文名
const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  leader_buy_dip: '龙头低吸',
  limit_down_qiao: '跌停翘板',
}

// 排序
const sortKey = ref<'created_at' | 'total_return' | 'win_rate' | 'sharpe_ratio' | 'max_drawdown'>('created_at')
const sortDesc = ref(true)

function toggleSort(key: typeof sortKey.value) {
  if (sortKey.value === key) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = key
    sortDesc.value = key === 'created_at' ? true : false // 收益率默认降序
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
    console.error('Failed to load history:', e)
  } finally {
    loading.value = false
  }
}

function formatReturn(val: number | null): string {
  if (val === null || val === undefined) return '-'
  const pct = val * 100
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function formatRate(val: number | null): string {
  if (val === null || val === undefined) return '-'
  return `${(val * 100).toFixed(1)}%`
}

function formatSharpe(val: number | null): string {
  if (val === null || val === undefined) return '-'
  return val.toFixed(2)
}

function formatDrawdown(val: number | null): string {
  if (val === null || val === undefined) return '-'
  return `${(val * 100).toFixed(2)}%`
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return iso.slice(0, 10)
}

function strategyNames(strategies: string[]): string {
  if (!strategies || strategies.length === 0) return '-'
  return strategies.map(s => strategyNameMap[s] || s).join('、')
}

function returnClass(val: number | null): string {
  if (val === null || val === undefined) return ''
  return val >= 0 ? 'text-green-400' : 'text-red-400'
}

onMounted(loadHistory)
</script>

<template>
  <div class="history-panel">
    <div class="history-header">
      <h3>📊 回测历史 ({{ total }}条)</h3>
      <button class="refresh-btn" :disabled="loading" @click="loadHistory">
        {{ loading ? '⏳ 加载中...' : '🔄 刷新' }}
      </button>
    </div>

    <div v-if="sortedItems.length === 0 && !loading" class="empty-state">
      <p>暂无回测记录</p>
      <p class="hint">提交一次回测后，历史记录将出现在这里</p>
    </div>

    <div v-else class="history-table-wrap">
      <table class="history-table">
        <thead>
          <tr>
            <th @click="toggleSort('created_at')" :class="{ active: sortKey === 'created_at' }">
              时间 {{ sortKey === 'created_at' ? (sortDesc ? '↓' : '↑') : '' }}
            </th>
            <th>日期范围</th>
            <th>策略</th>
            <th @click="toggleSort('total_return')" :class="{ active: sortKey === 'total_return' }">
              收益率 {{ sortKey === 'total_return' ? (sortDesc ? '↓' : '↑') : '' }}
            </th>
            <th @click="toggleSort('win_rate')" :class="{ active: sortKey === 'win_rate' }">
              胜率 {{ sortKey === 'win_rate' ? (sortDesc ? '↓' : '↑') : '' }}
            </th>
            <th @click="toggleSort('sharpe_ratio')" :class="{ active: sortKey === 'sharpe_ratio' }">
              夏普 {{ sortKey === 'sharpe_ratio' ? (sortDesc ? '↓' : '↑') : '' }}
            </th>
            <th @click="toggleSort('max_drawdown')" :class="{ active: sortKey === 'max_drawdown' }">
              回撤 {{ sortKey === 'max_drawdown' ? (sortDesc ? '↓' : '↑') : '' }}
            </th>
            <th>信号</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sortedItems" :key="item.task_id">
            <td class="date-cell">{{ formatDate(item.created_at) }}</td>
            <td class="range-cell">{{ item.start_date || '?' }} ~ {{ item.end_date || '?' }}</td>
            <td class="strat-cell" :title="strategyNames(item.strategies)">
              {{ strategyNames(item.strategies?.slice(0, 2)) }}{{ (item.strategies?.length || 0) > 2 ? '...' : '' }}
            </td>
            <td :class="['num-cell', returnClass(item.total_return)]">
              {{ formatReturn(item.total_return) }}
            </td>
            <td class="num-cell">{{ formatRate(item.win_rate) }}</td>
            <td class="num-cell">{{ formatSharpe(item.sharpe_ratio) }}</td>
            <td class="num-cell">{{ formatDrawdown(item.max_drawdown) }}</td>
            <td class="num-cell">{{ item.total_signals ?? '-' }}</td>
            <td class="action-cell">
              <button class="action-btn" @click="emit('view-result', item)" title="查看结果">📊</button>
              <button class="action-btn" @click="emit('view-logs', item.task_id)" title="查看日志">📋</button>
              <button class="action-btn reuse-btn" @click="emit('reuse-params', item)" title="复用参数重跑">🔄</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped lang="scss">
.history-panel {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #161b22;
  border-bottom: 1px solid #30363d;

  h3 {
    margin: 0;
    font-size: 15px;
    color: #c9d1d9;
    font-weight: 600;
  }

  .refresh-btn {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    cursor: pointer;
    padding: 4px 12px;
    font-size: 12px;

    &:hover:not(:disabled) { background: #30363d; }
    &:disabled { opacity: 0.5; cursor: not-allowed; }
  }
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: #484f58;

  .hint {
    font-size: 13px;
    margin-top: 8px;
  }
}

.history-table-wrap {
  overflow-x: auto;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;

  th {
    padding: 10px 12px;
    text-align: left;
    color: #8b949e;
    font-weight: 600;
    font-size: 12px;
    border-bottom: 1px solid #30363d;
    cursor: pointer;
    white-space: nowrap;
    user-select: none;

    &:hover { color: #c9d1d9; }
    &.active { color: #58a6ff; }
  }

  td {
    padding: 8px 12px;
    color: #c9d1d9;
    border-bottom: 1px solid #21262d;
    white-space: nowrap;
  }

  tr:hover td {
    background: rgba(56, 139, 253, 0.04);
  }

  .date-cell { color: #8b949e; font-size: 12px; }
  .range-cell { font-family: monospace; font-size: 12px; }
  .strat-cell { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
  .num-cell { font-family: monospace; font-size: 12px; }

  .text-green-400 { color: #3fb950; }
  .text-red-400 { color: #f85149; }

  .action-cell {
    display: flex;
    gap: 4px;

    .action-btn {
      background: #21262d;
      border: 1px solid #30363d;
      border-radius: 4px;
      cursor: pointer;
      padding: 2px 6px;
      font-size: 13px;

      &:hover { background: #30363d; }

      &.reuse-btn {
        border-color: #238636;
        &:hover { background: #23863620; }
      }
    }
  }
}
</style>
