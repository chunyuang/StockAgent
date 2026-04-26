<script setup lang="ts">
/**
 * PositionDetailTable - 持仓详情表格
 * 支持搜索、排序、策略筛选，展示每只股票的持仓详情
 */
import { ref, computed } from 'vue'
import type { Position } from '@/api'
import {
  ElTable,
  ElTableColumn,
  ElTag,
  ElInput,
  ElSelect,
  ElOption,
  ElEmpty,
} from 'element-plus'

const props = defineProps<{
  positions: Position[]
}>()

const searchKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')

const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨',
  first_limit_up: '首板打板',
  limit_up_open: '涨停开板',
  leader_buy_dip: '龙头低吸',
  limit_down_qiao: '跌停翘板',
  manual: '手动交易',
}

const strategyOptions = computed(() => {
  const set = new Set(props.positions.map(p => p.strategy).filter(Boolean))
  return Array.from(set).map(id => ({
    value: id,
    label: strategyNameMap[id] || id,
  }))
})

const filteredPositions = computed(() => {
  return props.positions.filter(p => {
    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      if (!p.ts_code.toLowerCase().includes(kw) && !p.stock_name.toLowerCase().includes(kw)) return false
    }
    if (filterStrategy.value && p.strategy !== filterStrategy.value) return false
    if (filterProfit.value) {
      const pct = p.profit_pct || 0
      if (filterProfit.value === 'profit' && pct <= 0) return false
      if (filterProfit.value === 'loss' && pct >= 0) return false
    }
    return true
  })
})

/** 合计行数据 */
const summaryRow = computed(() => {
  const list = filteredPositions.value
  const totalQty = list.reduce((s, p) => s + p.quantity, 0)
  const totalValue = list.reduce((s, p) => s + p.quantity * (p.current_price || p.avg_cost), 0)
  const totalCost = list.reduce((s, p) => s + p.quantity * p.avg_cost, 0)
  const totalProfitVal = list.reduce((s, p) => s + (p.profit || 0), 0)
  const totalProfitPct = totalCost > 0 ? totalProfitVal / totalCost : 0
  return { totalQty, totalValue, totalCost, totalProfitVal, totalProfitPct }
})

function formatProfit(pct: number): string {
  const val = ((pct || 0) * 100).toFixed(2)
  return pct >= 0 ? `+${val}%` : `${val}%`
}

function getProfitColor(pct: number): string {
  return pct >= 0 ? '#67c23a' : '#f56c6c'
}
</script>

<template>
  <div class="position-detail-table">
    <div class="section-header">
      <span class="section-title">📋 持仓明细</span>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <ElInput v-model="searchKeyword" placeholder="搜索代码/名称" clearable size="small" style="width: 200px" />
      <ElSelect v-model="filterStrategy" placeholder="策略" clearable size="small" style="width: 130px">
        <ElOption v-for="opt in strategyOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </ElSelect>
      <ElSelect v-model="filterProfit" placeholder="盈亏" clearable size="small" style="width: 110px">
        <ElOption label="盈利" value="profit" />
        <ElOption label="亏损" value="loss" />
      </ElSelect>
      <span class="result-count">共 {{ filteredPositions.length }} 只</span>
    </div>

    <ElTable
      :data="filteredPositions"
      stripe
      size="small"
      :default-sort="{ prop: 'profit_pct', order: 'descending' }"
      show-summary
      :summary-method="() => ['', '合计', '', summaryRow.totalQty.toLocaleString(), '', '', '', `¥${summaryRow.totalValue.toLocaleString()}`, formatProfit(summaryRow.totalProfitPct), '']"
      style="width: 100%"
      max-height="600"
    >
      <ElTableColumn type="index" label="#" width="45" />
      <ElTableColumn prop="ts_code" label="代码" width="110" sortable />
      <ElTableColumn prop="stock_name" label="名称" width="90" show-overflow-tooltip />
      <ElTableColumn label="策略" width="90" show-overflow-tooltip>
        <template #default="{ row }">
          <ElTag size="small" type="info">{{ strategyNameMap[row.strategy] || row.strategy || '-' }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="quantity" label="持仓量" width="90" align="right" sortable />
      <ElTableColumn prop="available_quantity" label="可卖量" width="80" align="right" />
      <ElTableColumn label="成本价" width="90" align="right" sortable :sort-method="(a: any, b: any) => a.avg_cost - b.avg_cost">
        <template #default="{ row }">¥{{ row.avg_cost?.toFixed(2) }}</template>
      </ElTableColumn>
      <ElTableColumn label="现价" width="90" align="right">
        <template #default="{ row }">¥{{ (row.current_price || row.avg_cost)?.toFixed(2) }}</template>
      </ElTableColumn>
      <ElTableColumn label="收益额" width="110" align="right" sortable :sort-method="(a: any, b: any) => (a.profit || 0) - (b.profit || 0)">
        <template #default="{ row }">
          <span :style="{ color: getProfitColor(row.profit_pct), fontWeight: 600 }">
            {{ (row.profit || 0) >= 0 ? '+' : '' }}¥{{ (row.profit || 0).toLocaleString() }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="收益率" width="110" align="right" sortable :sort-method="(a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)">
        <template #default="{ row }">
          <span :style="{ color: getProfitColor(row.profit_pct), fontWeight: 600 }">
            {{ formatProfit(row.profit_pct) }}
          </span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="hold_days" label="持仓天数" width="90" align="center" sortable />
      <ElTableColumn label="买入日期" width="100" align="center">
        <template #default="{ row }">
          {{ row.first_buy_date ? new Date(row.first_buy_date).toLocaleDateString() : '-' }}
        </template>
      </ElTableColumn>
    </ElTable>

    <ElEmpty v-if="!filteredPositions.length" description="暂无持仓" :image-size="60" />
  </div>
</template>

<script lang="ts">
export default { name: 'PositionDetailTable' }
</script>

<style scoped>
.position-detail-table {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.result-count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}
</style>
