<script setup lang="ts">
/**
 * PoolOverviewCards - 今日预选池概览统计卡片
 * 显示今日选股总数、买入信号数、策略分布等核心指标
 */
import { computed } from 'vue'
import type { TradingSignal } from '@/api'

const props = defineProps<{
  signals: TradingSignal[]
  tradeDate: string
}>()

/** 买入信号数 */
const buyCount = computed(() => props.signals.filter(s => s.signal_type === 'buy').length)

/** 卖出信号数 */
const sellCount = computed(() => props.signals.filter(s => s.signal_type === 'sell').length)

/** 待执行信号数 */
const pendingCount = computed(() => props.signals.filter(s => !s.executed).length)

/** 已执行信号数 */
const executedCount = computed(() => props.signals.filter(s => s.executed).length)

/** 平均置信度 */
const avgConfidence = computed(() => {
  if (!props.signals.length) return 0
  return props.signals.reduce((sum, s) => sum + s.confidence, 0) / props.signals.length
})

/** 策略分布 */
const strategyDistribution = computed(() => {
  const map = new Map<string, { name: string; count: number }>()
  for (const s of props.signals) {
    const key = s.strategy
    const name = getStrategyName(s.strategy)
    if (!map.has(key)) {
      map.set(key, { name, count: 0 })
    }
    map.get(key)!.count++
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count)
})

function getStrategyName(strategyId: string): string {
  const map: Record<string, string> = {
    halfway_chase: '半路追涨',
    first_limit_up: '首板打板',
    limit_up_open: '涨停开板',
    leader_buy_dip: '龙头低吸',
    limit_down_qiao: '跌停翘板',
  }
  return map[strategyId] || strategyId
}

function getConfidenceLevel(confidence: number): { text: string; color: string } {
  if (confidence >= 0.8) return { text: '高', color: '#67c23a' }
  if (confidence >= 0.6) return { text: '中', color: '#e6a23c' }
  return { text: '低', color: '#f56c6c' }
}
</script>

<template>
  <div class="pool-overview">
    <div class="overview-header">
      <span class="title">📊 今日预选池概览</span>
      <span class="trade-date">交易日期：{{ tradeDate }}</span>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card total">
        <div class="kpi-value">{{ signals.length }}</div>
        <div class="kpi-label">选股总数</div>
      </div>
      <div class="kpi-card buy">
        <div class="kpi-value">{{ buyCount }}</div>
        <div class="kpi-label">买入信号</div>
      </div>
      <div class="kpi-card sell">
        <div class="kpi-value">{{ sellCount }}</div>
        <div class="kpi-label">卖出信号</div>
      </div>
      <div class="kpi-card pending">
        <div class="kpi-value">{{ pendingCount }}</div>
        <div class="kpi-label">待执行</div>
      </div>
      <div class="kpi-card executed">
        <div class="kpi-value">{{ executedCount }}</div>
        <div class="kpi-label">已执行</div>
      </div>
      <div class="kpi-card confidence">
        <div class="kpi-value" :style="{ color: getConfidenceLevel(avgConfidence).color }">
          {{ (avgConfidence * 100).toFixed(1) }}%
        </div>
        <div class="kpi-label">平均置信度</div>
      </div>
    </div>

    <!-- 策略分布条 -->
    <div class="strategy-bar" v-if="strategyDistribution.length">
      <div class="strategy-bar-label">策略分布</div>
      <div class="strategy-bar-track">
        <div
          v-for="(s, i) in strategyDistribution"
          :key="i"
          class="strategy-bar-segment"
          :style="{
            width: signals.length ? (s.count / signals.length * 100) + '%' : '0%',
            backgroundColor: getBarColor(i),
          }"
          :title="`${s.name}: ${s.count}只`"
        >
          <span class="bar-label" v-if="s.count >= 2">{{ s.name }} {{ s.count }}</span>
        </div>
      </div>
      <div class="strategy-legend">
        <span v-for="(s, i) in strategyDistribution" :key="i" class="legend-item">
          <span class="legend-dot" :style="{ backgroundColor: getBarColor(i) }"></span>
          {{ s.name }} ({{ s.count }})
        </span>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
const BAR_COLORS = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399']
function getBarColor(index: number): string {
  return BAR_COLORS[index % BAR_COLORS.length]
}
export default { name: 'PoolOverviewCards' }
</script>

<style scoped>
.pool-overview {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
}
.overview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.overview-header .title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.overview-header .trade-date {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.kpi-card {
  text-align: center;
  padding: 12px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.kpi-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.3;
}
.kpi-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.kpi-card.total .kpi-value { color: #409eff; }
.kpi-card.buy .kpi-value { color: #67c23a; }
.kpi-card.sell .kpi-value { color: #f56c6c; }
.kpi-card.pending .kpi-value { color: #e6a23c; }
.kpi-card.executed .kpi-value { color: #909399; }

.strategy-bar { margin-top: 4px; }
.strategy-bar-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.strategy-bar-track {
  display: flex;
  height: 24px;
  border-radius: 4px;
  overflow: hidden;
}
.strategy-bar-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 2px;
  transition: width 0.3s ease;
}
.bar-label {
  font-size: 11px;
  color: #fff;
  white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0,0,0,0.3);
}
.strategy-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
}
.legend-item {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
@media (max-width: 768px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
