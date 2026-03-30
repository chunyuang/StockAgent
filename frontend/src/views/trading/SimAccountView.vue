<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElCard, ElTable, ElTableColumn, ElButton, ElMessage, ElTag, ElSpace } from 'element-plus'
import { CreditCard, Sell } from '@element-plus/icons-vue'
import { tradingApi, type SimAccount, type Position, type TradeRecord } from '@/api'

// 状态
const accounts = ref<SimAccount[]>([])
const positions = ref<Position[]>([])
const trades = ref<TradeRecord[]>([])
const selectedAccountId = ref<string>('')
const loading = ref(false)

// 加载模拟账户列表
async function loadAccounts() {
  try {
    loading.value = true
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0) {
      selectedAccountId.value = accounts.value[0].account_id
      loadPositions(selectedAccountId.value)
      loadTrades(selectedAccountId.value)
    }
  } catch (e: any) {
    ElMessage.error(`加载账户失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// 加载持仓
async function loadPositions(account_id: string) {
  try {
    positions.value = await tradingApi.getPositions(account_id)
  } catch (e: any) {
    ElMessage.error(`加载持仓失败: ${e.message || '未知错误'}`)
  }
}

// 加载交易记录
async function loadTrades(account_id: string) {
  try {
    const res = await tradingApi.getTradeRecords(account_id, 20, 0)
    trades.value = res.items
  } catch (e: any) {
    ElMessage.error(`加载交易记录失败: ${e.message || '未知错误'}`)
  }
}

// 格式化收益
function formatProfit(pct: number): string {
  const val = (pct * 100).toFixed(2)
  return pct >= 0 ? `+${val}%` : `${val}%`
}

// 收益颜色
function getProfitColor(pct: number): string {
  return pct >= 0 ? 'color: var(--stock-up)' : 'color: var(--stock-down)'
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <div class="sim-account-page p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">模拟交易账户</h1>
      <ElButton type="primary" :icon="CreditCard">创建模拟账户</ElButton>
    </div>

    <!-- 账户卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <ElCard 
        v-for="account in accounts" 
        :key="account.account_id"
        :class="{ 'border-primary': account.account_id === selectedAccountId }"
        class="cursor-pointer hover:shadow-md transition-shadow"
        @click="selectedAccountId = account.account_id; loadPositions(account.account_id); loadTrades(account.account_id)"
      >
        <template #header>
          <div class="flex items-center justify-between">
            <span class="font-bold">{{ account.name }}</span>
            <ElTag type="success">模拟盘</ElTag>
          </div>
        </template>
        <div class="space-y-3">
          <div class="grid grid-cols-2 gap-2">
            <div>
              <div class="text-sm text-gray-500">总资产</div>
              <div class="text-xl font-bold">{{ account.total_assets.toLocaleString() }} 元</div>
            </div>
            <div>
              <div class="text-sm text-gray-500">总收益</div>
              <div class="text-xl font-bold" :style="getProfitColor(account.total_profit_pct)">
                {{ formatProfit(account.total_profit_pct) }}
              </div>
            </div>
            <div>
              <div class="text-sm text-gray-500">可用资金</div>
              <div class="text-lg">{{ account.available_cash.toLocaleString() }} 元</div>
            </div>
            <div>
              <div class="text-sm text-gray-500">仓位占比</div>
              <div class="text-lg">{{ (account.position_ratio * 100).toFixed(1) }}%</div>
            </div>
          </div>
        </div>
      </ElCard>
    </div>

    <!-- 持仓列表 -->
    <ElCard title="当前持仓" v-loading="loading">
      <ElTable :data="positions" border stripe>
        <ElTableColumn prop="stock_name" label="股票名称" width="120" />
        <ElTableColumn prop="ts_code" label="股票代码" width="120" />
        <ElTableColumn prop="quantity" label="持仓数量" width="100" />
        <ElTableColumn prop="available_quantity" label="可用数量" width="100" />
        <ElTableColumn prop="avg_cost" label="持仓成本" width="100" />
        <ElTableColumn prop="current_price" label="当前价格" width="100" />
        <ElTableColumn label="收益" width="120">
          <template #default="{ row }">
            <span :style="getProfitColor(row.profit_pct)">
              {{ formatProfit(row.profit_pct) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="hold_days" label="持仓天数" width="100" />
        <ElTableColumn prop="strategy" label="策略来源" width="120" />
        <ElTableColumn label="操作" width="120" fixed="right">
          <template #default>
            <ElSpace>
              <ElButton type="danger" size="small" :icon="Sell">卖出</ElButton>
            </ElSpace>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- 交易记录 -->
    <ElCard title="最近交易记录" v-loading="loading">
      <ElTable :data="trades" border stripe>
        <ElTableColumn prop="trade_time" label="交易时间" width="160" />
        <ElTableColumn prop="stock_name" label="股票名称" width="120" />
        <ElTableColumn prop="ts_code" label="股票代码" width="120" />
        <ElTableColumn label="方向" width="80">
          <template #default="{ row }">
            <ElTag :type="row.direction === 'buy' ? 'success' : 'danger'">
              {{ row.direction === 'buy' ? '买入' : '卖出' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="quantity" label="数量" width="80" />
        <ElTableColumn prop="price" label="成交价格" width="100" />
        <ElTableColumn prop="amount" label="成交金额" width="120" />
        <ElTableColumn prop="strategy" label="策略" width="120" />
        <ElTableColumn prop="reason" label="交易原因" min-width="200" />
      </ElTable>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.sim-account-page {
  .border-primary {
    border: 2px solid var(--el-color-primary);
  }
}
</style>
