<script setup lang="ts">
/**
 * FactorTable — 因子数据表格
 * 动态列(按选中分类分组)，支持排序+分页
 */
import { computed } from 'vue'
import {
  ElTable,
  ElTableColumn,
  ElPagination,
  ElTooltip,
  ElEmpty,
  ElTag,
} from 'element-plus'
import type { FactorRow, FactorMeta, FactorCategory, FactorDataStatus as _FD } from '@/api/modules/factor'
import FactorStatusTag from './FactorStatusTag.vue'

const props = defineProps<{
  rows: FactorRow[]
  factors: FactorMeta[]
  activeCategories: FactorCategory[]
  loading: boolean
  total: number
  page: number
  pageSize: number
  /** 市场阶段: 交易中/盘后/非交易日 */
  marketPhase: 'trading' | 'after_close' | 'non_trading'
}>()

const emit = defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'size-change', size: number): void
  (e: 'sort-change', prop: string, order: 'ascending' | 'descending' | null): void
  (e: 'row-click', row: FactorRow): void
}>()

/** 按选中分类过滤因子元数据 */
const visibleFactors = computed(() => {
  if (props.activeCategories.length === 0) return props.factors
  return props.factors.filter(f => props.activeCategories.includes(f.category))
})

/** 按分类分组 */
const groupedFactors = computed(() => {
  const groups: Record<string, FactorMeta[]> = {}
  for (const f of visibleFactors.value) {
    if (!groups[f.category]) groups[f.category] = []
    groups[f.category].push(f)
  }
  return groups
})

const categoryNameMap: Record<FactorCategory, string> = {
  intraday: '盘中实时',
  daily: '日线盘后',
  fundamental: '基本面',
  composite: '复合打分',
}

const categoryOrder: FactorCategory[] = ['intraday', 'daily', 'fundamental', 'composite']

const sortedGroups = computed(() => {
  return categoryOrder
    .filter(c => groupedFactors.value[c])
    .map(c => ({ key: c, name: categoryNameMap[c], factors: groupedFactors.value[c] }))
})

/** 格式化因子值 */
function formatFactorValue(val: number | null | undefined, meta: FactorMeta): string {
  if (val === null || val === undefined) return '-'
  const prec = meta.precision ?? 2
  return val.toFixed(prec)
}

/** 因子列排序 */
function factorSortMethod(a: FactorRow, b: FactorRow, factorKey: string): number {
  const va = a.factors[factorKey]?.value
  const vb = b.factors[factorKey]?.value
  if (va == null && vb == null) return 0
  if (va == null) return -1
  if (vb == null) return 1
  return va - vb
}

function handleSortChange({ prop, order }: { prop: string; order: string | null }) {
  emit('sort-change', prop, order as 'ascending' | 'descending' | null)
}

function handlePageChange(p: number) {
  emit('page-change', p)
}

function handleSizeChange(s: number) {
  emit('size-change', s)
}

/** 行状态类 */
function rowStatusClass(row: FactorRow): string {
  return `fv-row-${row.data_status}`
}

/** 行点击跳转股票详情 */
function onRowClick(row: FactorRow) {
  emit('row-click', row)
}
</script>

<template>
  <div class="fv-table-wrap">
    <ElTable
      :data="rows"
      size="small"
      stripe
      border
      v-loading="loading"
      max-height="calc(100vh - 320px)"
      :row-class-name="rowStatusClass"
      @sort-change="handleSortChange"
      @row-click="onRowClick"
      class="fv-factor-table"
      :header-cell-style="{ fontSize: '11px', padding: '4px 0' }"
      :cell-style="{ fontSize: '12px', padding: '2px 4px' }"
    >
      <!-- 固定列: 代码 -->
      <ElTableColumn prop="code" label="代码" width="90" fixed="left" sortable>
        <template #default="{ row }">
          <span class="fv-code">{{ row.code }}</span>
        </template>
      </ElTableColumn>
      <!-- 固定列: 名称 -->
      <ElTableColumn prop="name" label="名称" width="70" fixed="left">
        <template #default="{ row }">
          <span class="fv-name">{{ row.name }}</span>
        </template>
      </ElTableColumn>
      <!-- 固定列: 更新时间 -->
      <ElTableColumn prop="updated_at" label="更新时间" width="130" fixed="left" sortable>
        <template #default="{ row }">
          <span class="fv-time">{{ row.updated_at?.slice(11, 19) || '-' }}</span>
        </template>
      </ElTableColumn>
      <!-- 固定列: 数据状态 -->
      <ElTableColumn prop="data_status" label="状态" width="50" fixed="left" align="center">
        <template #default="{ row }">
          <FactorStatusTag :status="row.data_status" size="small" />
        </template>
      </ElTableColumn>

      <!-- 因子动态列(按分类分组) -->
      <template v-for="group in sortedGroups" :key="group.key">
        <ElTableColumn :label="group.name" align="center">
          <!-- 分组表头非交易时段标注 -->
          <template #header>
            <span>{{ group.name }}</span>
            <ElTag
              v-if="group.key === 'intraday' && marketPhase !== 'trading'"
              size="small"
              type="info"
              class="fv-phase-tag"
            >
              非交易时段
            </ElTag>
            <ElTag
              v-if="group.key === 'daily' && marketPhase === 'trading'"
              size="small"
              type="info"
              class="fv-phase-tag"
            >
              盘中不变
            </ElTag>
          </template>

          <ElTableColumn
            v-for="factor in group.factors"
            :key="factor.key"
            :prop="`factors.${factor.key}.value`"
            :label="factor.display_name || factor.name"
            width="100"
            sortable
            :sort-method="(a: FactorRow, b: FactorRow) => factorSortMethod(a, b, factor.key)"
          >
            <template #header>
              <ElTooltip :content="factor.description" placement="top" :show-after="300">
                <span class="fv-factor-header">{{ factor.display_name || factor.name }}</span>
              </ElTooltip>
            </template>
            <template #default="{ row }">
              <div class="fv-factor-cell">
                <span class="fv-factor-val">{{ formatFactorValue(row.factors[factor.key]?.value, factor) }}</span>
                <FactorStatusTag
                  :status="row.factors[factor.key]?.status || 'missing'"
                  size="small"
                  class="fv-factor-dot"
                />
              </div>
            </template>
          </ElTableColumn>
        </ElTableColumn>
      </template>
    </ElTable>

    <!-- 分页 -->
    <div class="fv-pagination" v-if="total > 0">
      <ElPagination
        small
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[20, 50, 100]"
        :page-size="pageSize"
        :current-page="page"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <ElEmpty v-if="!loading && rows.length === 0" description="暂无因子数据" :image-size="60" />
  </div>
</template>

<style scoped lang="scss">
.fv-table-wrap {
  width: 100%;
  overflow: hidden;
}

.fv-factor-table {
  width: 100%;
  font-size: 12px;

  :deep(.el-table__header th) {
    background: var(--bg-muted);
    font-weight: 600;
    font-size: 11px;
  }

  :deep(.el-table__body td) {
    padding: 2px 4px;
  }
}

.fv-code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}

.fv-name {
  font-size: 11px;
  color: var(--text-primary);
}

.fv-time {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-tertiary);
}

.fv-phase-tag {
  margin-left: 4px;
  font-size: 9px !important;
  padding: 0 4px !important;
  height: 16px !important;
  line-height: 16px !important;
  vertical-align: middle;
}

.fv-factor-header {
  font-size: 11px;
  cursor: help;
  border-bottom: 1px dashed var(--text-muted);
}

.fv-factor-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2px;
  width: 100%;
}

.fv-factor-val {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
  flex: 1;
  text-align: right;
}

.fv-factor-dot {
  flex-shrink: 0;
}

// 行状态颜色
.fv-factor-table :deep(.fv-row-error) {
  background: rgba(245, 158, 11, 0.04) !important;
}
.fv-factor-table :deep(.fv-row-missing) {
  background: rgba(239, 68, 68, 0.04) !important;
}

.fv-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
