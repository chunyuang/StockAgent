<script setup lang="ts">
/**
 * PerformanceView - 业绩曲线页面
 * 展示净值曲线、月度收益、核心绩效指标
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight } from '@element-plus/icons-vue'
import { tradingApi, type SimAccount, type PerformanceReport } from '@/api'

// 拆分子组件
import NetValueChart from '@/components/performance/NetValueChart.vue'
import MonthlyReturnChart from '@/components/performance/MonthlyReturnChart.vue'

const accounts = ref<SimAccount[]>([])
const reports = ref<PerformanceReport[]>([])
const selectedAccountId = ref('')
const loading = ref(false)

const selectedAccount = computed(() =>
  accounts.value.find(a => a.account_id === selectedAccountId.value) || null
)

async function loadAccounts() {
  try {
    loading.value = true
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0 && !selectedAccountId.value) {
      selectedAccountId.value = accounts.value[0].account_id
    }
    if (selectedAccountId.value) {
      await loadReports()
    }
  } catch (e: any) {
    ElMessage.error(`加载账户失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

async function loadReports() {
  if (!selectedAccountId.value) return
  try {
    const res = await tradingApi.getPerformanceReports(selectedAccountId.value, 100, 0)
    reports.value = res.items || []
  } catch (e: any) {
    ElMessage.error(`加载报告失败: ${e.message || '未知错误'}`)
  }
}

function onAccountChange(accountId: string) {
  selectedAccountId.value = accountId
  loadReports()
}

/** 最新报告的核心指标 */
const latestReport = computed(() => reports.value.length ? reports.value[0] : null)

// 后端返回的百分比字段已经是百分比数值(如50.0=50%)，不需要再×100
function fmtPct(v: number | undefined): string {
  if (v == null) return '-'
  const val = v.toFixed(2)
  return v >= 0 ? `+${val}%` : `${val}%`
}

onMounted(() => {
  loadAccounts()
})
</script>

<template>
  <div class="performance-view">
    <div class="page-header">
      <h2>📈 业绩曲线</h2>
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
        <span class="chip-assets" :style="{ color: (acc.total_profit_pct || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(acc.total_profit_pct) }}
        </span>
      </div>
    </div>

    <!-- 核心绩效指标卡片 -->
    <div class="kpi-strip" v-if="latestReport">
      <div class="kpi-chip">
        <span class="kpi-label">累计收益</span>
        <span class="kpi-value" :style="{ color: (latestReport.total_return_pct || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(latestReport.total_return_pct) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">年化收益</span>
        <span class="kpi-value" :style="{ color: (latestReport.annual_return_pct || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(latestReport.annual_return_pct) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">最大回撤</span>
        <span class="kpi-value" style="color: #f56c6c">{{ fmtPct(latestReport.max_drawdown_pct) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">夏普比率</span>
        <span class="kpi-value" style="color: #409eff">{{ (latestReport.sharpe_ratio || 0).toFixed(2) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">索提诺比率</span>
        <span class="kpi-value" style="color: #e6a23c">{{ (latestReport.sortino_ratio || 0).toFixed(2) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">胜率</span>
        <span class="kpi-value" :style="{ color: (latestReport.win_rate_pct || 0) >= 50 ? '#67c23a' : '#f56c6c' }">
          {{ ((latestReport.win_rate_pct || 0)).toFixed(1) }}%
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">盈亏比</span>
        <span class="kpi-value" style="color: #909399">{{ (latestReport.profit_factor || 0).toFixed(2) }}</span>
      </div>
    </div>

    <!-- 净值曲线 -->
    <NetValueChart :reports="reports" :account-id="selectedAccountId" />

    <!-- 月度收益 -->
    <div style="margin-top: 16px">
      <MonthlyReturnChart :reports="reports" />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'PerformanceView' }
</script>

<style scoped>
.performance-view {
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
.chip-assets { font-weight: 600; }
.kpi-strip {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.kpi-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 18px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  min-width: 100px;
}
.kpi-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.kpi-value {
  font-size: 18px;
  font-weight: 700;
  margin-top: 2px;
}
</style>
