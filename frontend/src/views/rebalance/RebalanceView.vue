<script setup lang="ts">
/**
 * RebalanceView - 调仓操作页面
 * 买入/卖出交易操作，持仓快捷操作，交易记录
 */
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tradingApi, type SimAccount, type Position, type TradeRecord } from '@/api'
import { RefreshRight } from '@element-plus/icons-vue'

// 拆分子组件
import TradeForm from '@/components/rebalance/TradeForm.vue'
import QuickPositionTable from '@/components/rebalance/QuickPositionTable.vue'

const accounts = ref<SimAccount[]>([])
const positions = ref<Position[]>([])
const trades = ref<TradeRecord[]>([])
const selectedAccountId = ref('')
const loading = ref(false)

async function loadAccounts() {
  try {
    loading.value = true
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0 && !selectedAccountId.value) {
      selectedAccountId.value = accounts.value[0].account_id
    }
    if (selectedAccountId.value) {
      await Promise.all([loadPositions(), loadTrades()])
    }
  } catch (e: any) {
    ElMessage.error(`加载数据失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

async function loadPositions() {
  if (!selectedAccountId.value) return
  try {
    positions.value = await tradingApi.getPositions(selectedAccountId.value)
  } catch { /* ignore */ }
}

async function loadTrades() {
  if (!selectedAccountId.value) return
  try {
    const res = await tradingApi.getTradeRecords(selectedAccountId.value, 50, 0)
    trades.value = res.items || []
  } catch { /* ignore */ }
}

/** 执行交易 */
async function handleTrade(payload: {
  account_id: string; ts_code: string; stock_name: string;
  direction: 'buy' | 'sell'; quantity: number; price: number;
  strategy: string; reason: string
}) {
  const actionText = payload.direction === 'buy' ? '买入' : '卖出'
  try {
    await ElMessageBox.confirm(
      `确认${actionText}：${payload.stock_name}(${payload.ts_code}) ${payload.quantity}股，价格 ¥${payload.price.toFixed(2)}？`,
      '确认交易',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )

    // 调用交易API
    await tradingApi.executeSignal(
      `manual_${Date.now()}`,
      payload.account_id,
      payload.quantity
    )
    ElMessage.success(`${actionText}委托已提交`)
    await loadPositions()
    await loadTrades()
  } catch {
    // 取消不提示
  }
}

/** 从持仓快捷卖出 */
function handleQuickSell(position: Position) {
  // 触发TradeForm切换到卖出模式，预填信息
  // 这里通过事件传递给TradeForm处理
  ElMessage.info(`卖出 ${position.stock_name}：请在交易表单中确认`)
}

/** 账户切换 */
function onAccountChange(accountId: string) {
  selectedAccountId.value = accountId
  loadPositions()
  loadTrades()
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <div class="rebalance-view">
    <div class="page-header">
      <h2>🔄 调仓操作</h2>
      <el-button size="small" :icon="RefreshRight" @click="loadAccounts" :loading="loading">刷新</el-button>
    </div>

    <!-- 账户选择栏 -->
    <div class="account-bar" v-if="accounts.length">
      <div
        v-for="acc in accounts"
        :key="acc.account_id"
        class="account-chip"
        :class="{ active: acc.account_id === selectedAccountId }"
        @click="onAccountChange(acc.account_id)"
      >
        <span class="chip-name">{{ acc.name }}</span>
        <span class="chip-cash">可用 ¥{{ (acc.available_cash || 0).toLocaleString() }}</span>
        <span class="chip-assets">总资产 ¥{{ (acc.total_assets || 0).toLocaleString() }}</span>
      </div>
    </div>

    <div class="content-grid">
      <!-- 左侧：交易表单 -->
      <div class="left-panel">
        <el-card shadow="hover">
          <template #header><span>📝 交易下单</span></template>
          <TradeForm :accounts="accounts" :positions="positions" @trade="handleTrade" />
        </el-card>
      </div>

      <!-- 右侧：持仓 + 交易记录 -->
      <div class="right-panel">
        <el-card shadow="hover" style="margin-bottom: 16px">
          <template #header><span>📦 持仓列表</span></template>
          <QuickPositionTable :positions="positions" @sell="handleQuickSell" />
        </el-card>

        <el-card shadow="hover">
          <template #header><span>📜 最近交易记录</span></template>
          <div class="trade-history" v-if="trades.length">
            <div v-for="trade in trades.slice(0, 10)" :key="trade.trade_id" class="trade-item">
              <div class="trade-left">
                <span class="trade-direction" :class="trade.direction">
                  {{ trade.direction === 'buy' ? '买入' : '卖出' }}
                </span>
                <span class="trade-stock">{{ trade.stock_name }}</span>
                <span class="trade-code">{{ trade.ts_code }}</span>
              </div>
              <div class="trade-right">
                <span>{{ trade.quantity }}股 × ¥{{ trade.price?.toFixed(2) }}</span>
                <span class="trade-amount">¥{{ (trade.amount || 0).toLocaleString() }}</span>
              </div>
            </div>
          </div>
          <div v-else class="empty-text">暂无交易记录</div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'RebalanceView' }
</script>

<style scoped>
.rebalance-view {
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
.account-chip:hover {
  border-color: var(--el-color-primary);
}
.account-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.chip-name { font-weight: 600; }
.chip-cash { color: var(--el-color-success); }
.chip-assets { color: var(--el-text-color-secondary); }
.content-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
}
.left-panel { min-width: 0; }
.right-panel { min-width: 0; }
.trade-history { max-height: 300px; overflow-y: auto; }
.trade-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.trade-item:last-child { border-bottom: none; }
.trade-left { display: flex; align-items: center; gap: 6px; }
.trade-direction {
  font-weight: 600;
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 3px;
}
.trade-direction.buy { color: #fff; background: #67c23a; }
.trade-direction.sell { color: #fff; background: #f56c6c; }
.trade-stock { font-weight: 500; }
.trade-code { color: var(--el-text-color-secondary); font-size: 12px; }
.trade-right {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
}
.trade-amount { font-weight: 600; color: var(--el-text-color-primary); }
.empty-text {
  text-align: center;
  padding: 20px;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}
@media (max-width: 900px) {
  .content-grid { grid-template-columns: 1fr; }
}
</style>
