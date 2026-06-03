<script setup lang="ts">
/**
 * UpdateLogDialog — 因子更新日志弹窗
 * 显示异常/失败记录，支持筛选和分页
 */
import { ref, watch } from 'vue'
import {
  ElDialog,
  ElTable,
  ElTableColumn,
  ElTag,
  ElPagination,
  ElSelect,
  ElOption,
  ElButton,
  ElEmpty,
} from 'element-plus'
import { factorApi, type FactorUpdateLog, type FactorUpdateLogsParams } from '@/api/modules/factor'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
}>()

const logs = ref<FactorUpdateLog[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref<string>('')

async function fetchLogs() {
  loading.value = true
  try {
    const params: FactorUpdateLogsParams = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (statusFilter.value) params.status = statusFilter.value as any
    const res = await factorApi.getFactorUpdateLogs(params)
    logs.value = res.items || []
    total.value = res.total || 0
  } catch {
    logs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

watch(() => props.visible, (v) => {
  if (v) {
    page.value = 1
    fetchLogs()
  }
})

function onPageChange(p: number) {
  page.value = p
  fetchLogs()
}

function statusType(s: string) {
  if (s === 'success') return 'success'
  if (s === 'error') return 'danger'
  return 'warning'
}

function formatDuration(ms?: number) {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// close is unused but kept for potential future use
// function close() { emit('update:visible', false) }
</script>

<template>
  <ElDialog
    :model-value="visible"
    title="📋 因子更新日志"
    width="800px"
    :close-on-click-modal="true"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="fv-log-toolbar">
      <ElSelect v-model="statusFilter" placeholder="状态筛选" size="small" clearable style="width:120px" @change="fetchLogs">
        <ElOption label="全部" value="" />
        <ElOption label="✅ 成功" value="success" />
        <ElOption label="🟠 警告" value="warning" />
        <ElOption label="❌ 失败" value="error" />
      </ElSelect>
      <ElButton size="small" @click="fetchLogs" :loading="loading">🔄 刷新</ElButton>
    </div>

    <ElTable :data="logs" size="small" max-height="450" v-loading="loading" stripe>
      <ElTableColumn prop="timestamp" label="时间" width="160" />
      <ElTableColumn prop="scope" label="范围" width="80">
        <template #default="{ row }">
          <span class="fv-code">{{ row.scope === 'single' ? '单只' : row.scope === 'watchlist' ? '自选' : '全市场' }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="code" label="代码" width="90">
        <template #default="{ row }">
          <span class="fv-code">{{ row.code || '-' }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="category" label="分类" width="70">
        <template #default="{ row }">
          <span>{{ row.category || '-' }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="status" label="状态" width="70">
        <template #default="{ row }">
          <ElTag size="small" :type="statusType(row.status)" style="font-size:10px">{{ row.status }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="message" label="信息" min-width="200" show-overflow-tooltip />
      <ElTableColumn prop="duration_ms" label="耗时" width="70">
        <template #default="{ row }">
          <span>{{ formatDuration(row.duration_ms) }}</span>
        </template>
      </ElTableColumn>
    </ElTable>

    <div class="fv-log-footer" v-if="total > 0">
      <ElPagination
        small
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPageChange"
      />
    </div>

    <ElEmpty v-if="!loading && logs.length === 0" description="暂无更新日志" :image-size="60" />
  </ElDialog>
</template>

<style scoped lang="scss">
.fv-log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.fv-log-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.fv-code {
  font-family: var(--font-mono);
  font-size: 10px;
}
</style>
