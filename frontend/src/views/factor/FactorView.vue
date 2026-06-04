<script setup lang="ts">
/**
 * FactorView — 因子查看主页面
 * 
 * 布局: 顶部操作区 + 筛选维度区 + 主体数据表格 + 底部状态栏
 * 
 * 数据流:
 * 1. onMounted: 加载因子元数据(getFactorMetadata) + 更新状态(getFactorUpdateStatus)
 * 2. 搜索/筛选变化: 调用getFactorBatchView获取表格数据
 * 3. 手动更新: triggerFactorUpdate → 轮询getFactorUpdateStatus直到完成 → 刷新表格
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElSelect,
  ElOption,
  ElTabs,
  ElTabPane,
  ElMessageBox,
  ElMessage,
  ElTooltip,
} from 'element-plus'
import { Refresh, Document } from '@element-plus/icons-vue'
import {
  factorApi,
  type FactorRow,
  type FactorMeta,
  type FactorCategory,
  type FactorDataStatus,
  type FactorUpdateStatus,
  type FactorMetadataResponse as _FMR,
} from '@/api/modules/factor'
import { stockApi } from '@/api/modules/stock'
import { useThemeStore } from '@/stores'
import FactorTable from './FactorTable.vue'
import UpdateLogDialog from './UpdateLogDialog.vue'

const router = useRouter()
const themeStore = useThemeStore()

// ==================== 状态 ====================

// 元数据
const factorMeta = ref<FactorMeta[]>([])
const categoryList = ref<{ key: FactorCategory; name: string }[]>([])

// 表格数据
const rows = ref<FactorRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)

// 更新状态
const updateStatus = ref<FactorUpdateStatus | null>(null)
const isPollingUpdate = ref(false)
let updatePollTimer: ReturnType<typeof setInterval> | null = null

// 筛选
const searchQuery = ref('')
const searchOptions = ref<{ code: string; name: string }[]>([])
const searchLoading = ref(false)
const activeCategory = ref<FactorCategory | 'all'>('all')
const statusFilter = ref<FactorDataStatus | 'all'>('all')
const marketPhase = ref<'trading' | 'after_close' | 'non_trading'>('non_trading')

// 排序
const sortBy = ref('')
const sortOrder = ref<'asc' | 'desc'>('desc')

// 弹窗
const logDialogVisible = ref(false)

// ==================== 计算属性 ====================

const activeCategories = computed<FactorCategory[]>(() => {
  if (activeCategory.value === 'all') return []
  return [activeCategory.value]
})

/** 系统状态文字+颜色 */
const systemStatusText = computed(() => {
  if (!updateStatus.value) return { text: '未知', class: '' }
  const phase = updateStatus.value.market_phase
  if (updateStatus.value.is_updating) return { text: '更新中', class: 'fv-status-updating' }
  if (phase === 'trading') return { text: '盘中自动更新', class: 'fv-status-trading' }
  if (phase === 'after_close') return { text: '盘后更新完成', class: 'fv-status-after-close' }
  return { text: '非交易日暂停', class: 'fv-status-non-trading' }
})

const systemStatusEmoji = computed(() => {
  if (!updateStatus.value) return '⚪'
  if (updateStatus.value.is_updating) return '🔄'
  const phase = updateStatus.value.market_phase
  if (phase === 'trading') return '🔴'
  if (phase === 'after_close') return '🟢'
  return '⏸️'
})

const lastUpdateTime = computed(() => {
  return updateStatus.value?.last_update_time?.slice(11, 19) || '--:--:--'
})

/** 数据源状态圆点 */
const dsStatus = computed(() => {
  const ds = updateStatus.value?.data_source_status
  return {
    eastmoney: ds?.eastmoney || 'offline',
    liangmai: ds?.liangmai || 'offline',
    akshare: ds?.akshare || 'offline',
  }
})

// ==================== 方法 ====================

/** 加载因子元数据 */
async function loadMetadata() {
  try {
    const res = await factorApi.getFactorMetadata()
    // 从categories中提取所有因子, 映射category名, name→key
    const cats = res.categories || res.data?.categories || []
    const catMap: Record<string, string> = { realtime: 'intraday', daily: 'daily', basic: 'fundamental', composite: 'composite', static: 'fundamental' }
    const allFactors: any[] = []
    for (const cat of cats) {
      for (const f of (cat.factors || [])) {
        allFactors.push({
          ...f,
          key: f.name,  // 用name作为key
          category: catMap[f.category] || f.category || 'daily',
        })
      }
    }
    factorMeta.value = allFactors
    // 分类tabs用前端统一的4分组
    categoryList.value = [
      { key: 'intraday', name: '盘中实时' },
      { key: 'daily', name: '日线盘后' },
      { key: 'fundamental', name: '基本面' },
      { key: 'composite', name: '复合打分' },
    ]
  } catch {
    factorMeta.value = []
    categoryList.value = []
  }
}

/** 加载更新状态 */
async function loadUpdateStatus() {
  try {
    updateStatus.value = await factorApi.getFactorUpdateStatus()
  } catch {
    // 静默失败
  }
}

/** 加载表格数据 */
async function loadTableData() {
  loading.value = true
  try {
    const params: any = {
      page: page.value,
      limit: pageSize.value,
    }
    if (searchQuery.value) params.codes = searchQuery.value
    if (activeCategories.value.length > 0) params.categories = activeCategories.value
    if (statusFilter.value !== 'all') params.status_filter = statusFilter.value
    if (sortBy.value) {
      params.sort_by = sortBy.value
      params.sort_order = sortOrder.value
    }
    const res = await factorApi.getFactorBatchView(params)
    const data = res.data || res
    // 将factors数组转为嵌套对象格式(前端FactorTable需要)
    const rawItems = data.items || []
    rows.value = rawItems.map((item: any) => {
      const factorMap: Record<string, any> = {}
      if (Array.isArray(item.factors)) {
        for (const f of item.factors) {
          factorMap[f.name] = { value: f.value, status: f.status, display_name: f.display_name, category: f.category }
        }
      }
      return {
        code: item.ts_code,
        name: item.stock_name,
        updated_at: item.trade_date,
        data_status: item.fresh_count > 0 ? 'fresh' : 'stale',
        factors: factorMap,
        fresh_count: item.fresh_count,
        stale_count: item.stale_count,
      }
    })
    total.value = data.total || 0
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 远程搜索股票 */
async function remoteSearch(query: string) {
  if (!query || query.length < 2) {
    searchOptions.value = []
    return
  }
  searchLoading.value = true
  try {
    const results = await stockApi.searchStocks(query) as any[]
    searchOptions.value = (results || []).map((s: any) => ({
      code: s.ts_code,
      name: s.name,
    }))
  } catch {
    searchOptions.value = []
  } finally {
    searchLoading.value = false
  }
}

/** 手动更新 */
async function triggerUpdate(scope: 'single' | 'watchlist' | 'market') {
  const scopeText = scope === 'single' ? '单只股票' : scope === 'watchlist' ? '自选池' : '全市场'
  const scopeEmoji = scope === 'single' ? '🎯' : scope === 'watchlist' ? '📋' : '🌍'

  try {
    await ElMessageBox.confirm(
      `确定要执行${scopeEmoji} ${scopeText} 粒度的因子更新吗？`,
      '确认更新',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return // 用户取消
  }

  try {
    const params: any = { scope }
    if (scope === 'single' && searchQuery.value) params.codes = [searchQuery.value]
    await factorApi.triggerFactorUpdate(params)
    ElMessage.success(`${scopeEmoji} ${scopeText}因子更新已触发`)
    startUpdatePolling()
  } catch (e: any) {
    ElMessage.error(e?.message || '触发更新失败')
  }
}

/** 轮询更新状态 */
function startUpdatePolling() {
  if (isPollingUpdate.value) return
  isPollingUpdate.value = true
  updatePollTimer = setInterval(async () => {
    await loadUpdateStatus()
    if (updateStatus.value && !updateStatus.value.is_updating) {
      stopUpdatePolling()
      loadTableData() // 更新完成，刷新表格
    }
  }, 3000)
}

function stopUpdatePolling() {
  isPollingUpdate.value = false
  if (updatePollTimer) {
    clearInterval(updatePollTimer)
    updatePollTimer = null
  }
}

/** 刷新(仅前端拉取最新数据) */
function refreshData() {
  loadUpdateStatus()
  loadTableData()
}

/** 表格排序变化 */
function handleSortChange(prop: string, order: string | null) {
  if (!order) {
    sortBy.value = ''
    sortOrder.value = 'desc'
  } else {
    sortBy.value = prop
    sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  }
  loadTableData()
}

/** 行点击跳转股票详情 */
function onRowClick(row: FactorRow) {
  router.push(`/stock/${row.code}`)
}

/** 数据源状态圆点类 */
function dsDotClass(status: string) {
  return status === 'ok' ? 'fv-ds-ok' : status === 'error' ? 'fv-ds-err' : 'fv-ds-off'
}

// ==================== 筛选变化监听 ====================

watch([searchQuery, activeCategory, statusFilter], () => {
  page.value = 1
  loadTableData()
})

// ==================== 生命周期 ====================

onMounted(async () => {
  await Promise.all([loadMetadata(), loadUpdateStatus()])
  loadTableData()
})

onUnmounted(() => {
  stopUpdatePolling()
})
</script>

<template>
  <div class="fv" :class="{ dark: themeStore.isDark }">
    <!-- 顶部操作区 -->
    <div class="fv-header">
      <div class="fv-header-left">
        <!-- 系统状态 -->
        <div class="fv-sys-status" :class="systemStatusText.class">
          <span class="fv-sys-dot" />
          <span class="fv-sys-text">{{ systemStatusEmoji }} {{ systemStatusText.text }}</span>
        </div>

        <!-- 手动更新按钮组 -->
        <ElTooltip content="单只股票更新" placement="bottom">
          <ElButton size="small" @click="triggerUpdate('single')" :loading="isPollingUpdate" :disabled="isPollingUpdate">
            🎯 单只
          </ElButton>
        </ElTooltip>
        <ElTooltip content="自选池更新" placement="bottom">
          <ElButton size="small" @click="triggerUpdate('watchlist')" :loading="isPollingUpdate" :disabled="isPollingUpdate">
            📋 自选
          </ElButton>
        </ElTooltip>
        <ElTooltip content="全市场更新" placement="bottom">
          <ElButton size="small" type="primary" @click="triggerUpdate('market')" :loading="isPollingUpdate" :disabled="isPollingUpdate">
            🌍 全市场
          </ElButton>
        </ElTooltip>

        <!-- 刷新 -->
        <ElButton size="small" :icon="Refresh" @click="refreshData" :loading="loading">🔄</ElButton>

        <!-- 更新日志 -->
        <ElButton size="small" :icon="Document" @click="logDialogVisible = true">📋 日志</ElButton>

        <!-- 最后更新时间 -->
        <span class="fv-last-update">最后更新: {{ lastUpdateTime }}</span>
      </div>
    </div>

    <!-- 筛选维度区 -->
    <div class="fv-filter-bar">
      <!-- 标的搜索 -->
      <ElSelect
        v-model="searchQuery"
        filterable
        remote
        reserve-keyword
        clearable
        placeholder="搜索股票代码/名称"
        remote-show-suffix
        :remote-method="remoteSearch"
        :loading="searchLoading"
        size="small"
        style="width: 220px"
      >
        <ElOption
          v-for="item in searchOptions"
          :key="item.code"
          :label="`${item.code} ${item.name}`"
          :value="item.code"
        />
      </ElSelect>

      <!-- 因子分类Tab -->
      <ElTabs v-model="activeCategory" type="card" class="fv-category-tabs" @tab-change="page = 1">
        <ElTabPane label="全部" name="all" />
        <ElTabPane
          v-for="cat in categoryList"
          :key="cat.key"
          :label="cat.name"
          :name="cat.key"
        />
      </ElTabs>

      <!-- 数据状态过滤 -->
      <ElSelect v-model="statusFilter" size="small" style="width: 110px" @change="page = 1">
        <ElOption label="全部" value="all" />
        <ElOption label="✅ 正常" value="fresh" />
        <ElOption label="⬜ 沿用" value="stale" />
        <ElOption label="🟠 异常" value="error" />
        <ElOption label="❌ 缺失" value="missing" />
      </ElSelect>
    </div>

    <!-- 主体数据表格 -->
    <div class="fv-table-area">
      <FactorTable
        :rows="rows"
        :factors="factorMeta"
        :active-categories="activeCategories"
        :loading="loading"
        :market-phase="marketPhase"
        :total="total"
        :page="page"
        :page-size="pageSize"
        @page-change="page = $event; loadTableData()"
        @size-change="pageSize = $event; page = 1; loadTableData()"
        @sort-change="handleSortChange"
        @row-click="onRowClick"
      />
    </div>

    <!-- 底部状态栏 -->
    <div class="fv-footer">
      <div class="fv-footer-left">
        <!-- 今日更新批次 -->
        <span v-if="updateStatus" class="fv-footer-item">
          更新: <b>{{ updateStatus.success_count }}</b>/<b>{{ updateStatus.total }}</b>
          <span v-if="updateStatus.fail_count" class="fv-fail-count">失败{{ updateStatus.fail_count }}</span>
        </span>

        <!-- 数据源状态 -->
        <span class="fv-footer-item">
          数据源:
          <span class="fv-ds-dot" :class="dsDotClass(dsStatus.eastmoney)" title="东方财富">东财</span>
          <span class="fv-ds-dot" :class="dsDotClass(dsStatus.liangmai)" title="量脉">量脉</span>
          <span class="fv-ds-dot" :class="dsDotClass(dsStatus.akshare)" title="AKShare">AK</span>
        </span>
      </div>
      <div class="fv-footer-right">
        <span class="fv-footer-time">{{ updateStatus?.last_update_time || '-' }}</span>
      </div>
    </div>

    <!-- 更新日志弹窗 -->
    <UpdateLogDialog v-model:visible="logDialogVisible" />
  </div>
</template>

<style scoped lang="scss">
// ==================== 变量 ====================
$fv-header-h: 44px;
$fv-filter-h: 40px;
$fv-footer-h: 32px;

// ==================== 主容器 ====================
.fv {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-base);
  overflow: hidden;
}

// ==================== 顶部操作区 ====================
.fv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $fv-header-h;
  padding: 0 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.fv-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

// 系统状态指示
.fv-sys-status {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.fv-sys-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.fv-sys-text {
  white-space: nowrap;
}

.fv-status-trading {
  .fv-sys-dot { background: #ef4444; animation: pulse 2s infinite; }
  .fv-sys-text { color: #ef4444; }
  background: rgba(239, 68, 68, 0.06);
}

.fv-status-after-close {
  .fv-sys-dot { background: #10b981; }
  .fv-sys-text { color: #10b981; }
  background: rgba(16, 185, 129, 0.06);
}

.fv-status-non-trading {
  .fv-sys-dot { background: #94a3b8; }
  .fv-sys-text { color: var(--text-tertiary); }
  background: var(--bg-muted);
}

.fv-status-updating {
  .fv-sys-dot { background: #3b82f6; animation: pulse 1s infinite; }
  .fv-sys-text { color: #3b82f6; }
  background: rgba(59, 130, 246, 0.06);
}

.fv-last-update {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  margin-left: 4px;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

// ==================== 筛选维度区 ====================
.fv-filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.fv-category-tabs {
  flex: 1;

  :deep(.el-tabs__header) {
    margin-bottom: 0;
  }

  :deep(.el-tabs__item) {
    font-size: 12px;
    height: 28px;
    line-height: 28px;
    padding: 0 12px;
  }

  :deep(.el-tabs__nav) {
    border: none;
  }

  :deep(.el-tabs__item.is-active) {
    font-weight: 600;
  }
}

// ==================== 主体数据表格 ====================
.fv-table-area {
  flex: 1;
  overflow: hidden;
  padding: 8px 16px;
}

// ==================== 底部状态栏 ====================
.fv-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $fv-footer-h;
  padding: 0 16px;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-default);
  flex-shrink: 0;
}

.fv-footer-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.fv-footer-item {
  font-size: 11px;
  color: var(--text-tertiary);

  b {
    color: var(--text-secondary);
    font-family: var(--font-mono);
    font-weight: 600;
  }
}

.fv-fail-count {
  color: var(--error, #ef4444);
  margin-left: 4px;
  font-weight: 600;
}

.fv-footer-right {
  font-size: 11px;
  color: var(--text-tertiary);
}

.fv-footer-time {
  font-family: var(--font-mono);
}

// 数据源状态圆点
.fv-ds-dot {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  margin: 0 2px;
}

.fv-ds-ok {
  color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}

.fv-ds-err {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
}

.fv-ds-off {
  color: #94a3b8;
  background: rgba(148, 163, 184, 0.08);
}

// ==================== 暗色模式 ====================
.fv.dark {
  .fv-header, .fv-filter-bar, .fv-footer {
    background: var(--bg-elevated);
  }
}
</style>
