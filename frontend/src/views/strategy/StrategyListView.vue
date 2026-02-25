<script setup lang="ts">
/**
 * 策略订阅列表
 * 
 * 简化架构：
 * - 每种策略类型只有一条策略数据
 * - 普通用户只能添加/移除个股
 * - 管理员可修改策略参数和激活状态
 */

import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Edit } from '@element-plus/icons-vue'
import { subscriptionApi, stockApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { StrategySubscription, StockBasic, StrategyTypeInfo, StockInfoBrief } from '@/api/types'

// ==================== 状态 ====================

const userStore = useUserStore()

const subscriptions = ref<StrategySubscription[]>([])
const loading = ref(true)

// 可用策略类型（从服务端加载）
const availableStrategyTypes = ref<StrategyTypeInfo[]>([])

// 添加个股弹窗
const addStockDialogVisible = ref(false)
const currentStrategyType = ref<string>('')
const selectedStock = ref<string>('')
const stockOptions = ref<StockBasic[]>([])
const stockSearchLoading = ref(false)
const addingStock = ref(false)

// 展开的监听列表
const expandedLists = ref<Set<string>>(new Set())

// 编辑参数弹窗
const editParamsDialogVisible = ref(false)
const editingStrategyType = ref<string>('')
const editingParams = ref<Record<string, number | boolean>>({})
const savingParams = ref(false)

// ==================== 方法 ====================

/** 加载可用策略类型 */
async function loadStrategyTypes(): Promise<void> {
  try {
    availableStrategyTypes.value = await subscriptionApi.getStrategyTypes()
  } catch (error) {
    console.error('加载策略类型失败:', error)
  }
}

/** 加载订阅列表 */
async function loadSubscriptions(): Promise<void> {
  loading.value = true
  try {
    subscriptions.value = await subscriptionApi.getSubscriptions()
  } catch (error) {
    ElMessage.error('加载订阅列表失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

/** 获取显示的股票列表（包含名称） */
function getDisplayStockInfos(sub: StrategySubscription): StockInfoBrief[] {
  const stocks = sub.watch_list_info || []
  if (expandedLists.value.has(sub.strategy_type)) {
    return stocks
  }
  return stocks.slice(0, 5)
}

/** 获取策略显示名称 */
function getStrategyName(strategyType: string): string {
  const st = availableStrategyTypes.value.find(s => s.type === strategyType)
  return st?.name || strategyType
}

/** 获取策略订阅数据 */
function getSubscription(strategyType: string): StrategySubscription | undefined {
  return subscriptions.value.find(s => s.strategy_type === strategyType)
}

/** 打开添加个股弹窗 */
function openAddStockDialog(strategyType: string): void {
  currentStrategyType.value = strategyType
  selectedStock.value = ''
  stockOptions.value = []
  addStockDialogVisible.value = true
}

/** 搜索股票 (远程) */
async function searchStocks(query: string): Promise<void> {
  if (!query || query.length < 1) {
    stockOptions.value = []
    return
  }
  
  stockSearchLoading.value = true
  try {
    stockOptions.value = await stockApi.searchStocks(query, 10)
  } catch (error) {
    console.error('搜索股票失败:', error)
    stockOptions.value = []
  } finally {
    stockSearchLoading.value = false
  }
}

/** 添加个股到策略 */
async function addStockToStrategy(): Promise<void> {
  if (!currentStrategyType.value || !selectedStock.value) {
    ElMessage.warning('请选择股票')
    return
  }
  
  addingStock.value = true
  try {
    const response = await subscriptionApi.addStockToStrategy(
      currentStrategyType.value,
      selectedStock.value
    )
    
    if (response.success) {
      // 重新加载订阅以获取最新的 watch_list_info
      await loadSubscriptions()
      ElMessage.success(response.message)
      addStockDialogVisible.value = false
    } else {
      ElMessage.warning(response.message)
    }
  } catch (error) {
    ElMessage.error('添加失败')
    console.error(error)
  } finally {
    addingStock.value = false
  }
}

/** 移除个股 */
async function removeStock(strategyType: string, stockName: string, tsCode: string): Promise<void> {
  try {
    const response = await subscriptionApi.removeStockFromStrategy(
      strategyType,
      tsCode
    )
    
    if (response.success) {
      // 重新加载订阅以获取最新的 watch_list_info
      await loadSubscriptions()
      ElMessage.success(`已移除 ${stockName}`)
    }
  } catch (error) {
    ElMessage.error('移除失败')
    console.error(error)
  }
}

/** 切换展开/收起列表 */
function toggleExpand(strategyType: string): void {
  if (expandedLists.value.has(strategyType)) {
    expandedLists.value.delete(strategyType)
  } else {
    expandedLists.value.add(strategyType)
  }
}

// ==================== 管理员功能 ====================

/** 打开编辑参数弹窗（管理员） */
function openEditParamsDialog(strategyType: string): void {
  const sub = getSubscription(strategyType)
  if (!sub) return
  
  editingStrategyType.value = strategyType
  // 复制当前参数
  editingParams.value = { ...sub.params } as Record<string, number | boolean>
  editParamsDialogVisible.value = true
}

/** 保存策略参数（管理员） */
async function saveParams(): Promise<void> {
  if (!userStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return
  }
  
  savingParams.value = true
  try {
    await subscriptionApi.updateStrategyParams(
      editingStrategyType.value,
      editingParams.value
    )
    
    // 更新本地状态
    const sub = getSubscription(editingStrategyType.value)
    if (sub) {
      sub.params = { ...editingParams.value }
    }
    
    ElMessage.success('参数已保存')
    editParamsDialogVisible.value = false
  } catch (error) {
    ElMessage.error('保存失败，请检查管理员权限')
    console.error(error)
  } finally {
    savingParams.value = false
  }
}

/** 切换策略激活状态（管理员） */
async function toggleSubscription(strategyType: string): Promise<void> {
  if (!userStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return
  }
  
  try {
    const response = await subscriptionApi.toggleSubscription(strategyType)
    // 更新本地状态
    const sub = getSubscription(strategyType)
    if (sub) {
      sub.is_active = response.is_active
    }
    ElMessage.success(response.message)
  } catch (error) {
    ElMessage.error('操作失败')
    console.error(error)
  }
}

// ==================== 生命周期 ====================

onMounted(async () => {
  await loadStrategyTypes()
  await loadSubscriptions()
})
</script>

<template>
  <div class="strategy-list-view">
    <!-- 页面标题 -->
    <header class="page-header">
      <div class="header-content">
        <h1 class="page-title">策略监听</h1>
        <p class="page-subtitle">选择策略，添加想要监听的股票</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadSubscriptions" :loading="loading">
          刷新
        </el-button>
        <el-tag v-if="userStore.isAdmin" type="warning" effect="dark">
          管理员
        </el-tag>
      </div>
    </header>
    
    <!-- 策略列表 -->
    <div v-if="!loading" class="strategies-grid">
      <article
        v-for="st in availableStrategyTypes"
        :key="st.type"
        class="strategy-card"
        :class="{ 'is-inactive': getSubscription(st.type)?.is_active === false }"
      >
        <!-- 卡片头部 -->
        <div class="card-header">
          <div class="header-left">
            <h3 class="strategy-name">{{ st.name }}</h3>
          </div>
          <div class="header-right">
            <!-- 状态指示器 -->
            <div 
              class="status-indicator" 
              :class="getSubscription(st.type)?.is_active !== false ? 'active' : 'inactive'"
            >
              <span class="status-dot"></span>
              <span class="status-text">
                {{ getSubscription(st.type)?.is_active !== false ? '运行中' : '已停用' }}
              </span>
            </div>
            <!-- 管理员操作 -->
            <el-button 
              v-if="userStore.isAdmin"
              size="small"
              :type="getSubscription(st.type)?.is_active !== false ? 'warning' : 'success'"
              @click="toggleSubscription(st.type)"
            >
              {{ getSubscription(st.type)?.is_active !== false ? '停用' : '启用' }}
            </el-button>
          </div>
        </div>
        
        <!-- 策略描述 -->
        <p class="strategy-description">{{ st.description }}</p>
        
        <!-- 卡片主体 -->
        <div class="card-body">
          <!-- 策略参数 -->
          <div class="params-section">
            <div class="section-header">
              <h4 class="section-title">策略参数</h4>
              <el-button
                v-if="userStore.isAdmin"
                type="primary"
                size="small"
                :icon="Edit"
                plain
                @click="openEditParamsDialog(st.type)"
              >
                编辑
              </el-button>
            </div>
            <div class="params-grid">
              <div 
                v-for="param in st.param_schema" 
                :key="param.key"
                class="param-item"
              >
                <span class="param-label">{{ param.label }}</span>
                <span class="param-value">
                  {{ getSubscription(st.type)?.params[param.key] ?? param.default }}
                </span>
              </div>
            </div>
          </div>
          
          <!-- 监听股票 -->
          <div class="stocks-section">
            <div class="section-header">
              <h4 class="section-title">
                监听股票
                <el-badge 
                  :value="getSubscription(st.type)?.watch_list_info?.length || 0" 
                  :max="99"
                  class="stock-count-badge"
                />
              </h4>
              <el-button 
                type="primary" 
                size="small" 
                :icon="Plus"
                @click="openAddStockDialog(st.type)"
              >
                添加
              </el-button>
            </div>
            
            <!-- 股票列表 -->
            <div 
              v-if="getSubscription(st.type)?.watch_list_info?.length" 
              class="stock-tags"
            >
              <el-tag
                v-for="stock in getDisplayStockInfos(getSubscription(st.type)!)"
                :key="stock.ts_code"
                closable
                size="small"
                class="stock-tag"
                @close="removeStock(st.type, stock.name, stock.ts_code)"
              >
                {{ stock.name }}
              </el-tag>
              
              <!-- 展开/收起 -->
              <el-button
                v-if="(getSubscription(st.type)?.watch_list_info?.length || 0) > 5"
                link
                type="primary"
                size="small"
                @click="toggleExpand(st.type)"
              >
                {{ expandedLists.has(st.type) ? '收起' : `展开全部 (${getSubscription(st.type)?.watch_list_info?.length})` }}
              </el-button>
            </div>
            
            <!-- 空状态 -->
            <div v-else class="empty-stocks">
              <span class="empty-text">暂无监听股票</span>
              <span class="empty-hint">点击"添加"按钮开始监听</span>
            </div>
          </div>
        </div>
      </article>
    </div>
    
    <!-- 加载状态 -->
    <div v-else class="loading-state">
      <el-skeleton :rows="3" animated />
    </div>
    
    <!-- 添加个股弹窗 -->
    <el-dialog
      v-model="addStockDialogVisible"
      title="添加监听股票"
      width="400px"
      :close-on-click-modal="false"
    >
      <div class="add-stock-form">
        <p class="form-hint">
          搜索并选择要添加到 
          <strong>{{ getStrategyName(currentStrategyType) }}</strong> 
          策略的股票
        </p>
        
        <el-select
          v-model="selectedStock"
          filterable
          remote
          reserve-keyword
          placeholder="输入股票代码或名称搜索"
          :remote-method="searchStocks"
          :loading="stockSearchLoading"
          class="stock-select"
          size="large"
        >
          <el-option
            v-for="stock in stockOptions"
            :key="stock.ts_code"
            :label="`${stock.name} (${stock.ts_code})`"
            :value="stock.ts_code"
          >
            <div class="stock-option">
              <span class="stock-name">{{ stock.name }}</span>
              <span class="stock-code">{{ stock.ts_code }}</span>
            </div>
          </el-option>
        </el-select>
      </div>
      
      <template #footer>
        <el-button @click="addStockDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          :loading="addingStock"
          :disabled="!selectedStock"
          @click="addStockToStrategy"
        >
          确认添加
        </el-button>
      </template>
    </el-dialog>
    
    <!-- 编辑参数弹窗（管理员） -->
    <el-dialog
      v-model="editParamsDialogVisible"
      title="编辑策略参数"
      width="450px"
      :close-on-click-modal="false"
    >
      <div class="edit-params-form">
        <p class="form-hint mb-4">
          修改 <strong>{{ getStrategyName(editingStrategyType) }}</strong> 的策略参数
        </p>
        
        <!-- 动态参数表单 -->
        <div class="params-form-grid">
          <div 
            v-for="param in availableStrategyTypes.find(s => s.type === editingStrategyType)?.param_schema || []"
            :key="param.key"
            class="param-form-item"
          >
            <label class="param-form-label">{{ param.label }}</label>
            
            <!-- 布尔类型 -->
            <el-switch
              v-if="param.type === 'boolean'"
              v-model="editingParams[param.key]"
              :active-text="'是'"
              :inactive-text="'否'"
            />
            
            <!-- 数字类型 -->
            <el-input-number
              v-else
              v-model="editingParams[param.key]"
              :step="param.type === 'float' ? 0.01 : 1"
              :precision="param.type === 'float' ? 2 : 0"
              :min="0"
              size="default"
              controls-position="right"
            />
          </div>
        </div>
      </div>
      
      <template #footer>
        <el-button @click="editParamsDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          :loading="savingParams"
          @click="saveParams"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.strategy-list-view {
  @apply min-h-screen p-6;
  background: var(--bg-base);
  transition: background-color var(--transition-normal);
}

/* 页面头部 */
.page-header {
  @apply flex items-center justify-between mb-8;
}

.page-title {
  @apply text-2xl font-bold mb-1;
  color: var(--text-primary);
}

.page-subtitle {
  @apply text-sm;
  color: var(--text-tertiary);
}

.header-actions {
  @apply flex items-center gap-3;
}

/* 策略网格 */
.strategies-grid {
  @apply grid gap-6;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  grid-auto-rows: 1fr;
}

/* 策略卡片 */
.strategy-card {
  @apply rounded-xl p-5 transition-all duration-300 flex flex-col;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  height: 100%;
}

.strategy-card:hover {
  border-color: var(--border-muted);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.strategy-card.is-inactive {
  opacity: 0.6;
}

/* 卡片头部 */
.card-header {
  @apply flex items-start justify-between mb-3;
}

.header-left {
  @apply flex items-center gap-3;
}

.strategy-name {
  @apply text-lg font-semibold;
  color: var(--text-primary);
}

.header-right {
  @apply flex items-center gap-3;
}

/* 状态指示器 */
.status-indicator {
  @apply flex items-center gap-1.5 text-xs;
}

.status-dot {
  @apply w-2 h-2 rounded-full;
}

.status-indicator.active .status-dot {
  @apply bg-green-500;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
}

.status-indicator.active .status-text {
  @apply text-green-400;
}

.status-indicator.inactive .status-dot {
  @apply bg-gray-500;
}

.status-indicator.inactive .status-text {
  @apply text-gray-400;
}

/* 策略描述 */
.strategy-description {
  @apply text-sm text-gray-400 mb-4;
}

/* 卡片主体 */
.card-body {
  @apply flex-1 flex flex-col;
}

/* 参数区域 */
.params-section {
  @apply mb-4;
}

.section-title {
  @apply text-sm font-medium flex items-center;
  color: var(--text-secondary);
}

.params-grid {
  @apply grid grid-cols-2 gap-2;
}

.param-item {
  @apply flex justify-between items-center px-3 py-2 rounded-lg;
  background: var(--bg-muted);
}

.param-label {
  @apply text-xs;
  color: var(--text-tertiary);
}

.param-value {
  @apply text-sm font-medium;
  color: var(--text-primary);
}

/* 股票区域 */
.stocks-section {
  @apply pt-3 mt-auto;
  border-top: 1px solid var(--border-light);
}

.section-header {
  @apply flex items-center justify-between mb-3;
}

.stock-count-badge {
  @apply ml-2;
}

.stock-tags {
  @apply flex flex-wrap gap-2;
}

.stock-tag {
  @apply font-mono;
}

/* 空状态 */
.empty-stocks {
  @apply flex flex-col items-center py-6 text-center;
}

.empty-text {
  @apply text-sm;
  color: var(--text-tertiary);
}

.empty-hint {
  @apply text-xs mt-1;
  color: var(--text-muted);
}

/* 加载状态 */
.loading-state {
  @apply p-8;
}

/* 添加股票表单 */
.add-stock-form {
  @apply py-2;
}

.form-hint {
  @apply text-sm mb-4;
  color: var(--text-muted);
}

.stock-select {
  @apply w-full;
}

.stock-option {
  @apply flex items-center justify-between w-full;
}

.stock-name {
  @apply font-medium;
  color: var(--text-primary);
}

.stock-code {
  @apply text-sm font-mono;
  color: var(--text-tertiary);
}

/* 编辑参数表单 */
.edit-params-form {
  @apply space-y-4;
}

.params-form-grid {
  @apply space-y-4;
}

.param-form-item {
  @apply flex items-center justify-between gap-4;
}

.param-form-label {
  @apply text-sm flex-shrink-0;
  color: var(--text-secondary);
}
</style>
