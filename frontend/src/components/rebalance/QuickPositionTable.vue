<script setup lang="ts">
/**
 * QuickPositionTable - 快捷持仓表格组件
 * 显示当前持仓，支持一键卖出
 */
import type { Position } from '@/api'
import {
  ElTable,
  ElTableColumn,
  ElButton,
  ElEmpty,
} from 'element-plus'

defineProps<{
  positions: Position[]
}>()

const emit = defineEmits<{
  (e: 'sell', position: Position): void
}>()

const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  leader_buy_dip: '龙头低吸',
  limit_down_qiao: '跌停翘板',
  manual: '手动交易',
}

function formatProfit(pct: number): string {
  const val = ((pct || 0) * 100).toFixed(2)
  return pct >= 0 ? `+${val}%` : `${val}%`
}

function getProfitColor(pct: number): string {
  return pct >= 0 ? '#67c23a' : '#f56c6c'
}
</script>

<template>
  <div class="quick-position-table">
    <div class="section-title">📋 当前持仓</div>
    <ElTable :data="positions" stripe size="small" max-height="400" v-if="positions.length">
      <ElTableColumn prop="ts_code" label="代码" width="110" />
      <ElTableColumn prop="stock_name" label="名称" width="90" show-overflow-tooltip />
      <ElTableColumn prop="quantity" label="持仓" width="80" align="right" />
      <ElTableColumn prop="available_quantity" label="可卖" width="80" align="right" />
      <ElTableColumn label="成本" width="90" align="right">
        <template #default="{ row }">¥{{ row.avg_cost?.toFixed(2) }}</template>
      </ElTableColumn>
      <ElTableColumn label="现价" width="90" align="right">
        <template #default="{ row }">¥{{ (row.current_price || row.avg_cost)?.toFixed(2) }}</template>
      </ElTableColumn>
      <ElTableColumn label="收益" width="100" align="right" sortable :sort-method="(a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)">
        <template #default="{ row }">
          <span :style="{ color: getProfitColor(row.profit_pct), fontWeight: 600 }">
            {{ formatProfit(row.profit_pct) }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="hold_days" label="天数" width="60" align="center" />
      <ElTableColumn label="策略" width="90" show-overflow-tooltip>
        <template #default="{ row }">
          {{ strategyNameMap[row.strategy] || row.strategy || '-' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="80" align="center" fixed="right">
        <template #default="{ row }">
          <ElButton
            type="danger"
            size="small"
            plain
            :disabled="row.available_quantity <= 0"
            @click="emit('sell', row)"
          >
            卖出
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    <ElEmpty v-else description="暂无持仓" :image-size="60" />
  </div>
</template>

<script lang="ts">
export default { name: 'QuickPositionTable' }
</script>

<style scoped>
.quick-position-table { padding: 12px 0; }
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 10px;
}
</style>
