<script setup lang="ts">
/**
 * PreMarketSignalList - 盘前信号列表
 * 展示当日/次日交易信号、情绪评分、竞价过滤结果
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ElTable,
  ElTableColumn,
  ElTag,
  ElProgress,
  ElBadge,
} from 'element-plus'
import { tradingApi } from '@/api'

interface SignalItem {
  signal_id: string
  ts_code: string
  stock_name: string
  strategy: string
  signal_type: string
  price: number
  suggest_quantity: number
  confidence: number
  reason: string
  generated_at: string
  expired_at: string
  status: string
}

const signals = ref<SignalItem[]>([])
const loading = ref(false)
const sentimentScore = ref(0)
const autoRefreshTimer = ref<ReturnType<typeof setInterval>>()

const strategyTagType: Record<string, string> = {
  halfway_chase: 'primary',
  first_limit_up: 'danger',
  limit_up_open: 'warning',
  leader_buy_dip: 'success',
  limit_down_qiao: 'info',
}

const strategyLabel: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  leader_buy_dip: '龙头低吸',
  limit_down_qiao: '跌停翘板',
}

function getConfidenceColor(c: number): string {
  if (c >= 0.8) return '#67c23a'
  if (c >= 0.6) return '#e6a23c'
  return '#f56c6c'
}

async function loadSignals() {
  loading.value = true
  try {
    const res = await tradingApi.getTradingSignals(50, 0, true)
    signals.value = (res.items || []).map((s: any) => ({
      signal_id: s.signal_id,
      ts_code: s.ts_code,
      stock_name: s.stock_name,
      strategy: s.strategy,
      signal_type: s.signal_type,
      price: s.price,
      suggest_quantity: s.suggest_quantity,
      confidence: s.confidence,
      reason: s.reason,
      generated_at: s.generated_at,
      expired_at: s.expired_at,
      status: s.status,
    }))
  } catch {
    // API不可用时显示空
  } finally {
    loading.value = false
  }
}

/** WebSocket推送新信号时调用 */
function onNewSignal(signal: SignalItem) {
  signals.value.unshift(signal)
  if (signals.value.length > 50) signals.value.pop()
  ElMessage.success(`新信号：${signal.stock_name} ${signal.reason}`)
}

defineExpose({ onNewSignal })

onMounted(() => {
  loadSignals()
  autoRefreshTimer.value = setInterval(loadSignals, 60000)
})

onUnmounted(() => {
  if (autoRefreshTimer.value) clearInterval(autoRefreshTimer.value)
})
</script>

<template>
  <div class="pre-market-signal-list">
    <!-- 情绪评分条 -->
    <div class="sentiment-bar" v-if="sentimentScore > 0">
      <span class="sentiment-label">📊 情绪评分</span>
      <ElProgress
        :percentage="sentimentScore"
        :color="sentimentScore >= 70 ? '#67c23a' : sentimentScore >= 40 ? '#e6a23c' : '#f56c6c'"
        :stroke-width="14"
        style="flex: 1; margin: 0 16px"
      />
      <ElTag :type="sentimentScore >= 70 ? 'success' : sentimentScore >= 40 ? 'warning' : 'danger'" size="small">
        {{ sentimentScore >= 70 ? '激进' : sentimentScore >= 40 ? '标准' : '保守' }}
      </ElTag>
    </div>

    <!-- 信号列表 -->
    <ElTable
      :data="signals"
      v-loading="loading"
      stripe
      size="small"
      max-height="400"
      empty-text="暂无盘前信号"
      style="width: 100%"
    >
      <ElTableColumn prop="ts_code" label="代码" width="100" />
      <ElTableColumn prop="stock_name" label="名称" width="90" />
      <ElTableColumn label="策略" width="90">
        <template #default="{ row }">
          <ElTag :type="(strategyTagType[row.strategy] || 'info') as any" size="small" effect="plain">
            {{ strategyLabel[row.strategy] || row.strategy }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="方向" width="60" align="center">
        <template #default="{ row }">
          <ElTag :type="row.signal_type === 'buy' ? 'danger' : 'success'" size="small">
            {{ row.signal_type === 'buy' ? '买' : '卖' }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="价格" width="80" align="right">
        <template #default="{ row }">{{ row.price?.toFixed(2) }}</template>
      </ElTableColumn>
      <ElTableColumn label="数量" width="70" align="right">
        <template #default="{ row }">{{ row.suggest_quantity }}</template>
      </ElTableColumn>
      <ElTableColumn label="信心" width="80" align="center">
        <template #default="{ row }">
          <span :style="{ color: getConfidenceColor(row.confidence), fontWeight: 600 }">
            {{ (row.confidence * 100).toFixed(0) }}%
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="reason" label="原因" min-width="160" show-overflow-tooltip />
      <ElTableColumn label="状态" width="80" align="center">
        <template #default="{ row }">
          <ElBadge :type="row.status === 'pending' ? 'warning' : row.status === 'executed' ? 'success' : 'info'" is-dot />
          <span style="margin-left: 4px; font-size: 12px">
            {{ row.status === 'pending' ? '待执行' : row.status === 'executed' ? '已执行' : '已过期' }}
          </span>
        </template>
      </ElTableColumn>
    </ElTable>
  </div>
</template>

<script lang="ts">
export default { name: 'PreMarketSignalList' }
</script>

<style scoped>
.pre-market-signal-list {
  padding: 4px 0;
}
.sentiment-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.sentiment-label {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
</style>
