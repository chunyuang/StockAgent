<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElCard, ElTable, ElTableColumn, ElButton, ElMessage, ElSelect, ElOption } from 'element-plus'
import { Document, Download } from '@element-plus/icons-vue'
import { tradingApi, type PerformanceReport, type SimAccount } from '@/api'

// 状态
const reports = ref<PerformanceReport[]>([])
const accounts = ref<SimAccount[]>([])
const selectedAccountId = ref<string>('')
const loading = ref(false)

// 加载账户列表
async function loadAccounts() {
  try {
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0) {
      selectedAccountId.value = accounts.value[0].account_id
      loadReports()
    }
  } catch (e: any) {
    ElMessage.error(`加载账户失败: ${e.message || '未知错误'}`)
  }
}

// 加载绩效报告
async function loadReports() {
  try {
    loading.value = true
    const res = await tradingApi.getPerformanceReports(selectedAccountId.value, 20, 0)
    reports.value = res.items
  } catch (e: any) {
    ElMessage.error(`加载报告失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// 格式化百分比
function formatPct(value: number | undefined): string {
  if (value === undefined) return '-'
  const val = (value * 100).toFixed(2)
  return value >= 0 ? `+${val}%` : `${val}%`
}

// 收益颜色
function getProfitColor(pct: number | undefined): string {
  if (pct === undefined) return ''
  return pct >= 0 ? 'color: var(--stock-up)' : 'color: var(--stock-down)'
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <div class="performance-report-page p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">绩效报告</h1>
      <div class="flex items-center gap-4">
        <ElSelect
          v-model="selectedAccountId"
          placeholder="选择账户"
          style="width: 200px"
          @change="loadReports"
        >
          <ElOption
            v-for="account in accounts"
            :key="account.account_id"
            :label="account.name"
            :value="account.account_id"
          />
        </ElSelect>
        <ElButton :icon="Download">导出报告</ElButton>
      </div>
    </div>

    <!-- 绩效卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4" v-if="reports.length > 0">
      <ElCard>
        <div class="text-sm text-gray-500 mb-1">累计收益率</div>
        <div class="text-2xl font-bold" :style="getProfitColor(reports[0].total_return_pct)">
          {{ formatPct(reports[0].total_return_pct) }}
        </div>
      </ElCard>
      <ElCard>
        <div class="text-sm text-gray-500 mb-1">年化收益率</div>
        <div class="text-2xl font-bold" :style="getProfitColor(reports[0].annual_return_pct)">
          {{ formatPct(reports[0].annual_return_pct) }}
        </div>
      </ElCard>
      <ElCard>
        <div class="text-sm text-gray-500 mb-1">最大回撤</div>
        <div class="text-2xl font-bold text-orange-500">
          {{ formatPct(reports[0].max_drawdown_pct) }}
        </div>
      </ElCard>
      <ElCard>
        <div class="text-sm text-gray-500 mb-1">夏普比率</div>
        <div class="text-2xl font-bold text-purple-500">
          {{ reports[0].sharpe_ratio.toFixed(2) }}
        </div>
      </ElCard>
    </div>

    <!-- 报告列表 -->
    <ElCard title="历史报告" v-loading="loading">
      <ElTable :data="reports" border stripe>
        <ElTableColumn prop="period" label="报告周期" width="120" />
        <ElTableColumn prop="start_date" label="开始日期" width="120" />
        <ElTableColumn prop="end_date" label="结束日期" width="120" />
        <ElTableColumn label="累计收益" width="120">
          <template #default="{ row }">
            <span :style="getProfitColor(row.total_return_pct)">
              {{ formatPct(row.total_return_pct) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="年化收益" width="120">
          <template #default="{ row }">
            <span :style="getProfitColor(row.annual_return_pct)">
              {{ formatPct(row.annual_return_pct) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="最大回撤" width="120">
          <template #default="{ row }">
            <span class="text-orange-500">
              {{ formatPct(row.max_drawdown_pct) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="sharpe_ratio" label="夏普比率" width="100" :formatter="(row) => row.sharpe_ratio.toFixed(2)" />
        <ElTableColumn prop="sortino_ratio" label="索提诺比率" width="120" :formatter="(row) => row.sortino_ratio.toFixed(2)" />
        <ElTableColumn label="胜率" width="100">
          <template #default="{ row }">
            {{ (row.win_rate_pct * 100).toFixed(1) }}%
          </template>
        </ElTableColumn>
        <ElTableColumn prop="profit_factor" label="盈亏比" width="100" :formatter="(row) => row.profit_factor.toFixed(2)" />
        <ElTableColumn prop="total_trades" label="交易次数" width="100" />
        <ElTableColumn prop="created_at" label="生成时间" width="160" />
        <ElTableColumn label="操作" width="120" fixed="right">
          <template #default>
            <ElButton type="primary" size="small" :icon="Document">查看详情</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
</style>
