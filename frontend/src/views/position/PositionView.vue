<script setup lang="ts">
/**
 * PositionView - 今日持仓页面
 * 展示持仓概览、持仓明细、支持多账户切换
 */
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight } from '@element-plus/icons-vue'
import { tradingApi, type SimAccount, type Position } from '@/api'

// 拆分子组件
import PositionSummaryCards from '@/components/position/PositionSummaryCards.vue'
import PositionDetailTable from '@/components/position/PositionDetailTable.vue'

const accounts = ref<SimAccount[]>([])
const positions = ref<Position[]>([])
const selectedAccountId = ref('')
const loading = ref(false)

const selectedAccount = ref<SimAccount | null>(null)

async function loadAccounts() {
  try {
    loading.value = true
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0 && !selectedAccountId.value) {
      selectedAccountId.value = accounts.value[0].account_id
      selectedAccount.value = accounts.value[0]
    }
    if (selectedAccountId.value) {
      await loadPositions()
    }
  } catch (e: any) {
    ElMessage.error(`加载账户失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

async function loadPositions() {
  if (!selectedAccountId.value) return
  try {
    positions.value = await tradingApi.getPositions(selectedAccountId.value)
    selectedAccount.value = accounts.value.find(a => a.account_id === selectedAccountId.value) || null
  } catch (e: any) {
    ElMessage.error(`加载持仓失败: ${e.message || '未知错误'}`)
  }
}

function onAccountChange(accountId: string) {
  selectedAccountId.value = accountId
  selectedAccount.value = accounts.value.find(a => a.account_id === accountId) || null
  loadPositions()
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <div class="position-view">
    <div class="page-header">
      <h2>📦 今日持仓</h2>
      <el-button size="small" :icon="RefreshRight" @click="loadAccounts" :loading="loading">刷新</el-button>
    </div>

    <!-- 账户切换 -->
    <div class="account-bar" v-if="accounts.length > 1">
      <div
        v-for="acc in accounts"
        :key="acc.account_id"
        class="account-chip"
        :class="{ active: acc.account_id === selectedAccountId }"
        @click="onAccountChange(acc.account_id)"
      >
        <span class="chip-name">{{ acc.name }}</span>
        <span class="chip-assets">¥{{ (acc.total_assets || 0).toLocaleString() }}</span>
      </div>
    </div>

    <!-- 概览统计 -->
    <PositionSummaryCards :account="selectedAccount" :positions="positions" />

    <!-- 持仓明细 -->
    <div style="margin-top: 16px">
      <PositionDetailTable :positions="positions" />
    </div>

    <!-- 底部 -->
    <div class="position-footer">
      <span v-if="positions.length">数据更新时间: {{ new Date().toLocaleTimeString() }}</span>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'PositionView' }
</script>

<style scoped>
.position-view {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.account-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.account-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
}
.account-chip:hover { border-color: var(--el-color-primary); }
.account-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.chip-name { font-weight: 600; }
.chip-assets { color: var(--el-text-color-secondary); }
.position-footer {
  text-align: center;
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
</style>
