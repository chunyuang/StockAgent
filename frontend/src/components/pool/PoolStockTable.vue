<script setup lang="ts">
/**
 * PoolStockTable - 今日预选池选股列表表格
 * 支持搜索、策略筛选、置信度筛选、排序
 */
import { ref, computed } from 'vue'
import type { TradingSignal } from '@/api'
import {
  ElTable,
  ElTableColumn,
  ElTag,
  ElInput,
  ElSelect,
  ElOption,
  ElProgress,
  ElEmpty,
  ElTooltip,
} from 'element-plus'

const props = defineProps<{
  signals: TradingSignal[]
}>()

// 筛选
const searchKeyword = ref('')
const filterStrategy = ref('')
const filterSignalType = ref('')
const filterConfidence = ref('')

/** 策略名称映射 */
const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  leader_buy_dip: '龙头低吸',
  limit_down_qiao: '跌停翘板',
}

/** 策略选项列表 */
const strategyOptions = computed(() => {
  const set = new Set(props.signals.map(s => s.strategy))
  return Array.from(set).map(id => ({
    value: id,
    label: strategyNameMap[id] || id,
  }))
})

/** 筛选后的信号列表 */
const filteredSignals = computed(() => {
  return props.signals.filter(s => {
    // 搜索
    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      const match = s.ts_code.toLowerCase().includes(kw) ||
        s.stock_name.toLowerCase().includes(kw) ||
        (strategyNameMap[s.strategy] || s.strategy).includes(kw)
      if (!match) return false
    }
    // 策略
    if (filterStrategy.value && s.strategy !== filterStrategy.value) return false
    // 信号类型
    if (filterSignalType.value && s.signal_type !== filterSignalType.value) return false
    // 置信度
    if (filterConfidence.value) {
      const c = s.confidence
      if (filterConfidence.value === 'high' && c < 0.8) return false
      if (filterConfidence.value === 'medium' && (c < 0.6 || c >= 0.8)) return false
      if (filterConfidence.value === 'low' && c >= 0.6) return false
    }
    return true
  })
})

function getSignalTypeTag(type: string): 'success' | 'danger' | 'info' {
  if (type === 'buy') return 'success'
  if (type === 'sell') return 'danger'
  return 'info'
}

function getSignalTypeText(type: string): string {
  if (type === 'buy') return '买入'
  if (type === 'sell') return '卖出'
  return '持有'
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.8) return '#67c23a'
  if (confidence >= 0.6) return '#e6a23c'
  return '#f56c6c'
}

function formatTime(dateStr: string): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="pool-stock-table">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <ElInput
        v-model="searchKeyword"
        placeholder="搜索股票代码/名称/策略"
        clearable
        size="small"
        style="width: 240px"
      />
      <ElSelect v-model="filterStrategy" placeholder="策略筛选" clearable size="small" style="width: 140px">
        <ElOption
          v-for="opt in strategyOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </ElSelect>
      <ElSelect v-model="filterSignalType" placeholder="信号类型" clearable size="small" style="width: 120px">
        <ElOption label="买入" value="buy" />
        <ElOption label="卖出" value="sell" />
        <ElOption label="持有" value="hold" />
      </ElSelect>
      <ElSelect v-model="filterConfidence" placeholder="置信度" clearable size="small" style="width: 120px">
        <ElOption label="高 (≥80%)" value="high" />
        <ElOption label="中 (60-80%)" value="medium" />
        <ElOption label="低 (<60%)" value="low" />
      </ElSelect>
      <span class="result-count">共 {{ filteredSignals.length }} 条</span>
    </div>

    <!-- 表格 -->
    <ElTable
      :data="filteredSignals"
      stripe
      size="small"
      :default-sort="{ prop: 'confidence', order: 'descending' }"
      style="width: 100%"
      max-height="600"
    >
      <ElTableColumn type="index" label="#" width="50" />
      <ElTableColumn prop="ts_code" label="股票代码" width="110" sortable />
      <ElTableColumn prop="stock_name" label="股票名称" width="100" show-overflow-tooltip />
      <ElTableColumn label="策略" width="100" show-overflow-tooltip>
        <template #default="{ row }">
          {{ strategyNameMap[row.strategy] || row.strategy }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="信号" width="80" align="center" sortable sort-by="signal_type">
        <template #default="{ row }">
          <ElTag :type="getSignalTypeTag(row.signal_type)" size="small" effect="dark">
            {{ getSignalTypeText(row.signal_type) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="price" label="价格" width="90" align="right" sortable>
        <template #default="{ row }">
          ¥{{ row.price?.toFixed(2) || '-' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="置信度" width="150" sortable :sort-method="(a: any, b: any) => a.confidence - b.confidence">
        <template #default="{ row }">
          <div class="confidence-cell">
            <ElProgress
              :percentage="Math.round(row.confidence * 100)"
              :stroke-width="14"
              :color="getConfidenceColor(row.confidence)"
              :show-text="false"
              style="flex: 1"
            />
            <span class="confidence-text" :style="{ color: getConfidenceColor(row.confidence) }">
              {{ (row.confidence * 100).toFixed(0) }}%
            </span>
          </div>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="suggest_quantity" label="建议数量" width="90" align="right" />
      <ElTableColumn label="生成时间" width="80" align="center">
        <template #default="{ row }">
          {{ formatTime(row.generated_at) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="80" align="center">
        <template #default="{ row }">
          <ElTag :type="row.executed ? 'info' : 'warning'" size="small">
            {{ row.executed ? '已执行' : '待执行' }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="推荐理由" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <ElTooltip :content="row.reason" placement="top" :show-after="300">
            <span class="reason-text">{{ row.reason || '-' }}</span>
          </ElTooltip>
        </template>
      </ElTableColumn>
    </ElTable>

    <ElEmpty v-if="!filteredSignals.length" description="暂无预选数据" />
  </div>
</template>

<script lang="ts">
export default { name: 'PoolStockTable' }
</script>

<style scoped>
.pool-stock-table {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.result-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
.confidence-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.confidence-text {
  font-size: 12px;
  font-weight: 600;
  min-width: 36px;
  text-align: right;
}
.reason-text {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
</style>
