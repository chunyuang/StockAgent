<script setup lang="ts">
/**
 * PositionSummaryCards - 持仓概览统计卡片
 * 显示总市值、总收益、仓位占比等核心持仓指标
 */
import { computed } from 'vue'
import type { SimAccount, Position } from '@/api'

const props = defineProps<{
  account: SimAccount | null
  positions: Position[]
}>()

/** 持仓总市值 */
const totalPositionValue = computed(() => {
  return props.positions.reduce((sum, p) => sum + (p.quantity * (p.current_price || p.avg_cost)), 0)
})

/** 总收益 */
const totalProfit = computed(() => {
  return props.positions.reduce((sum, p) => sum + (p.profit || 0), 0)
})

/** 总收益率 */
const totalProfitPct = computed(() => {
  const cost = props.positions.reduce((sum, p) => sum + p.quantity * p.avg_cost, 0)
  return cost > 0 ? totalProfit.value / cost : 0
})

/** 盈利股票数 */
const profitCount = computed(() => props.positions.filter(p => (p.profit_pct || 0) > 0).length)

/** 亏损股票数 */
const lossCount = computed(() => props.positions.filter(p => (p.profit_pct || 0) < 0).length)

/** 平均持仓天数 */
const avgHoldDays = computed(() => {
  if (!props.positions.length) return 0
  return (props.positions.reduce((sum, p) => sum + (p.hold_days || 0), 0) / props.positions.length).toFixed(1)
})

function formatMoney(val: number): string {
  if (Math.abs(val) >= 10000) return (val / 10000).toFixed(2) + '万'
  return val.toLocaleString()
}
</script>

<template>
  <div class="position-summary">
    <div class="summary-header">
      <span class="title">📊 持仓概览</span>
      <span class="account-name" v-if="account">{{ account.name }}</span>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value" style="color: #409eff">{{ positions.length }}</div>
        <div class="kpi-label">持仓股票数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color: #409eff">¥{{ formatMoney(totalPositionValue) }}</div>
        <div class="kpi-label">持仓总市值</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" :style="{ color: totalProfit >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ totalProfit >= 0 ? '+' : '' }}¥{{ formatMoney(totalProfit) }}
        </div>
        <div class="kpi-label">总收益</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" :style="{ color: totalProfitPct >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ totalProfitPct >= 0 ? '+' : '' }}{{ (totalProfitPct * 100).toFixed(2) }}%
        </div>
        <div class="kpi-label">总收益率</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">
          <span style="color: #67c23a">{{ profitCount }}</span>
          <span style="color: var(--el-text-color-placeholder); margin: 0 4px">/</span>
          <span style="color: #f56c6c">{{ lossCount }}</span>
        </div>
        <div class="kpi-label">盈/亏股票数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value" style="color: #e6a23c">{{ avgHoldDays }}</div>
        <div class="kpi-label">平均持仓天数</div>
      </div>
    </div>

    <!-- 仓位占比条 -->
    <div class="position-ratio" v-if="account">
      <span class="ratio-label">仓位占比</span>
      <div class="ratio-track">
        <div
          class="ratio-fill"
          :style="{ width: ((account.position_ratio || 0) * 100) + '%' }"
          :class="{ high: (account.position_ratio || 0) > 0.8, medium: (account.position_ratio || 0) > 0.5 && (account.position_ratio || 0) <= 0.8 }"
        ></div>
      </div>
      <span class="ratio-text">{{ ((account.position_ratio || 0) * 100).toFixed(1) }}%</span>
      <span class="cash-text">可用: ¥{{ (account.available_cash || 0).toLocaleString() }}</span>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'PositionSummaryCards' }
</script>

<style scoped>
.position-summary {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
}
.summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.summary-header .title {
  font-size: 16px;
  font-weight: 600;
}
.summary-header .account-name {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.kpi-card {
  text-align: center;
  padding: 10px 6px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.kpi-value {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.3;
}
.kpi-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 3px;
}
.position-ratio {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}
.ratio-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.ratio-track {
  flex: 1;
  height: 16px;
  background: var(--el-fill-color);
  border-radius: 4px;
  overflow: hidden;
}
.ratio-fill {
  height: 100%;
  border-radius: 4px;
  background: #67c23a;
  transition: width 0.3s;
}
.ratio-fill.high { background: #f56c6c; }
.ratio-fill.medium { background: #e6a23c; }
.ratio-text {
  font-size: 13px;
  font-weight: 600;
  min-width: 50px;
}
.cash-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
@media (max-width: 768px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
