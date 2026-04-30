<script setup lang="ts">
/**
 * PostMarketReport - 盘后报告查看
 * 展示当日交易总结、绩效报告、策略复盘
 */
import { ref, onMounted } from 'vue'
import {
  ElTag,
  ElEmpty,
  ElDescriptions,
  ElDescriptionsItem,
} from 'element-plus'
import { tradingApi, type PerformanceReport } from '@/api'

const reports = ref<PerformanceReport[]>([])
const selectedReport = ref<PerformanceReport | null>(null)
const loading = ref(false)

async function loadReports() {
  loading.value = true
  try {
    const accounts = await tradingApi.getSimAccounts()
    if (accounts.length > 0) {
      const res = await tradingApi.getPerformanceReports(accounts[0].account_id, 10, 0)
      reports.value = res.items || []
      if (reports.value.length > 0) {
        selectedReport.value = reports.value[0]
      }
    }
  } catch { /* ignore */ } finally {
    loading.value = false
  }
}

function selectReport(report: PerformanceReport) {
  selectedReport.value = report
}

// 后端返回的百分比字段已经是百分比数值(如50.0=50%)，不需要再×100
function fmtPct(v: number | undefined): string {
  if (v == null) return '-'
  const val = v.toFixed(2)
  return v >= 0 ? `+${val}%` : `${val}%`
}

onMounted(() => { loadReports() })
</script>

<template>
  <div class="post-market-report">
    <!-- 报告列表 -->
    <div class="report-list" v-loading="loading">
      <div v-if="reports.length === 0 && !loading" class="empty-state">
        <ElEmpty description="暂无盘后报告" :image-size="60" />
      </div>
      <div v-else class="report-items">
        <div
          v-for="r in reports"
          :key="r.report_id"
          class="report-card"
          :class="{ active: selectedReport?.report_id === r.report_id }"
          @click="selectReport(r)"
        >
          <div class="report-period">{{ r.period }}</div>
          <div class="report-range">{{ r.start_date }} ~ {{ r.end_date }}</div>
          <div class="report-return" :style="{ color: (r.total_return_pct || 0) >= 0 ? '#f56c6c' : '#67c23a' }">
            {{ fmtPct(r.total_return_pct) }}
          </div>
        </div>
      </div>
    </div>

    <!-- 选中报告详情 -->
    <div v-if="selectedReport" class="report-detail">
      <ElDescriptions :column="3" border size="small" title="📊 绩效概览">
        <ElDescriptionsItem label="累计收益">
          <span :style="{ color: (selectedReport.total_return_pct || 0) >= 0 ? '#f56c6c' : '#67c23a', fontWeight: 700 }">
            {{ fmtPct(selectedReport.total_return_pct) }}
          </span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="年化收益">
          <span :style="{ color: (selectedReport.annual_return_pct || 0) >= 0 ? '#f56c6c' : '#67c23a' }">
            {{ fmtPct(selectedReport.annual_return_pct) }}
          </span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="最大回撤">
          <span style="color: #f56c6c; font-weight: 700">{{ fmtPct(selectedReport.max_drawdown_pct) }}</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="夏普比率">
          <span style="color: #409eff">{{ (selectedReport.sharpe_ratio || 0).toFixed(2) }}</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="索提诺比率">
          <span style="color: #e6a23c">{{ (selectedReport.sortino_ratio || 0).toFixed(2) }}</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="胜率">
          <span :style="{ color: (selectedReport.win_rate_pct || 0) >= 50 ? '#67c23a' : '#f56c6c' }">
            {{ ((selectedReport.win_rate_pct || 0)).toFixed(1) }}%
          </span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="盈亏比">
          {{ (selectedReport.profit_factor || 0).toFixed(2) }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="总交易">
          {{ selectedReport.total_trades }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="盈利/亏损">
          <ElTag type="success" size="small">{{ selectedReport.winning_trades }}</ElTag>
          <span style="margin: 0 4px">/</span>
          <ElTag type="danger" size="small">{{ selectedReport.losing_trades }}</ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="最大连胜">
          {{ selectedReport.max_consecutive_wins }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="最大连亏">
          {{ selectedReport.max_consecutive_losses }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="平均盈利">
          <span style="color: #67c23a">{{ (selectedReport.avg_profit_per_trade || 0).toFixed(2) }}</span>
        </ElDescriptionsItem>
      </ElDescriptions>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'PostMarketReport' }
</script>

<style scoped>
.post-market-report { padding: 4px 0; }
.report-list { margin-bottom: 16px; }
.empty-state { padding: 30px 0; }
.report-items { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.report-card {
  min-width: 140px; padding: 10px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--el-border-color); transition: all 0.2s; text-align: center;
}
.report-card:hover { border-color: var(--el-color-primary); }
.report-card.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.report-period { font-size: 13px; font-weight: 600; }
.report-range { font-size: 11px; color: var(--el-text-color-secondary); margin: 4px 0; }
.report-return { font-size: 18px; font-weight: 700; }
.report-detail { margin-top: 8px; }
</style>
