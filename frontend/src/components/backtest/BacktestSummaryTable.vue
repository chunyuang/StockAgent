<script setup lang="ts">
/**
 * BacktestSummaryTable - 回测结果精简概要卡片
 *
 * 定位：紧凑的核心指标一览，不与BacktestResultPanel重复
 * - 核心KPI指标（与ResultPanel KPI Strip对齐但更紧凑）
 * - 策略对比速览表
 * - 运行元信息（耗时/交易日/基准对比）
 *
 * 不包含：交易记录、TOP5、风险指标明细、图表（这些全在ResultPanel中）
 */
import { computed } from 'vue'
import { ElCard, ElDescriptions, ElDescriptionsItem, ElTable, ElTableColumn, ElTag } from 'element-plus'
import { STRATEGY_NAMES } from '@/config/backtestConstants'

const props = defineProps<{
  result: any
}>()

/** 核心绩效指标 */
const coreMetrics = computed(() => {
  const r: any = props.result
  if (!r) return []
  const risk = r.metrics?.risk || {}
  const ret = r.metrics?.returns || {}
  const nvsLen = r.net_value_series?.length || 0
  const items = [
    { label: '累计收益', value: fmtPct(r.total_return), color: colorSign(r.total_return) },
    { label: '年化收益', value: fmtPct(r.annualized_return) + (nvsLen < 250 ? ' ⚠️' : ''), color: colorSign(r.annualized_return) },
    { label: '最大回撤', value: fmtPct(r.max_drawdown), color: '#f56c6c' },
    { label: '夏普比率', value: fmtNum(r.sharpe_ratio), color: r.sharpe_ratio >= 1 ? '#67c23a' : '#e6a23c' },
    { label: '胜率', value: fmtPct(r.win_rate), color: r.win_rate >= 50 ? '#67c23a' : '#f56c6c' },
    { label: '盈亏比', value: fmtNum(risk.profit_loss_ratio ?? r.profit_loss_ratio), color: (risk.profit_loss_ratio ?? r.profit_loss_ratio ?? 0) >= 2 ? '#67c23a' : '#e6a23c' },
    { label: '交易笔数', value: String(r.total_trades ?? 0), color: '#409eff' },
    { label: '信号数', value: String(r.total_signals ?? 0), color: '#909399' },
  ]
  if (ret.benchmark_return_pct != null) {
    items.push({ label: '基准收益', value: fmtPct(ret.benchmark_return_pct), color: colorSign(ret.benchmark_return_pct) })
  }
  if (ret.alpha_pct != null) {
    items.push({ label: '超额收益', value: fmtPct(ret.alpha_pct), color: colorSign(ret.alpha_pct) })
  }
  return items
})

/** 策略对比速览 */
const strategyData = computed(() => {
  const r = props.result
  if (!r?.strategy_results) return []
  return Object.entries(r.strategy_results).map(([key, s]: [string, any]) => ({
    key,
    strategy_name: s.strategy_name || STRATEGY_NAMES[key]?.replace(/^[\S]+\s/, '') || key,
    total_return: s.total_return,
    win_rate: s.win_rate,
    trades_count: s.trades_count,
    max_drawdown: s.max_drawdown,
  }))
})

/** 运行元信息 */
const metaInfo = computed(() => {
  const r: any = props.result
  if (!r) return null
  const nvsLen = r.net_value_series?.length || 0
  return {
    execution_time: r.execution_time_ms ? `${(r.execution_time_ms / 1000).toFixed(1)}秒` : '-',
    trading_days: nvsLen,
    initial_cash: r.initial_cash ? `¥${(r.initial_cash / 10000).toFixed(0)}万` : '-',
    final_value: r.final_value ? `¥${(r.final_value / 10000).toFixed(2)}万` : '-',
  }
})

function fmtPct(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(2) + '%'
}

function fmtNum(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(2)
}

function colorSign(val: number | null | undefined): string {
  if (val == null) return '#909399'
  return val >= 0 ? '#67c23a' : '#f56c6c'
}
</script>

<template>
  <div class="backtest-summary-compact" v-if="result">
    <!-- 核心指标 Descriptions -->
    <ElCard shadow="hover" class="summary-card">
      <template #header>
        <div class="card-header">
          <span>📊 回测概要</span>
          <div v-if="metaInfo" class="meta-tags">
            <ElTag size="small" type="info">⏱ {{ metaInfo.execution_time }}</ElTag>
            <ElTag size="small" type="info">📅 {{ metaInfo.trading_days }}交易日</ElTag>
            <ElTag size="small">{{ metaInfo.initial_cash }} → {{ metaInfo.final_value }}</ElTag>
          </div>
        </div>
      </template>
      <ElDescriptions :column="4" border size="small">
        <ElDescriptionsItem
          v-for="m in coreMetrics"
          :key="m.label"
          :label="m.label"
        >
          <span :style="{ color: m.color, fontWeight: 600 }">{{ m.value }}</span>
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <!-- 策略对比速览 -->
    <ElCard v-if="strategyData.length > 1" shadow="hover" class="summary-card" style="margin-top: 12px">
      <template #header><span>🎯 策略对比速览</span></template>
      <ElTable :data="strategyData" size="small" border stripe>
        <ElTableColumn prop="strategy_name" label="策略" min-width="100" />
        <ElTableColumn label="累计盈利" min-width="90">
          <template #default="{ row }">
            <span :style="{ color: colorSign(row.total_return), fontWeight: 600 }">{{ fmtPct(row.total_return) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="胜率" min-width="80">
          <template #default="{ row }">
            <span :style="{ color: row.win_rate >= 50 ? '#67c23a' : '#f56c6c' }">{{ fmtPct(row.win_rate) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="trades_count" label="交易" width="70" align="center" />
        <ElTableColumn label="最大回撤" min-width="90">
          <template #default="{ row }">
            <span style="color: #f56c6c">{{ fmtPct(row.max_drawdown) }}</span>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- 不足1年回测提示 -->
    <div v-if="(result?.net_value_series?.length || 0) < 250" class="disclaimer">
      ⚠️ 回测期不足1年，年化收益/卡玛比率等指标仅供参考，存在放大效应
    </div>
  </div>
</template>

<style scoped lang="scss">
.backtest-summary-compact {
  margin-bottom: 12px;
}
.summary-card {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 15px;
    .meta-tags {
      display: flex;
      gap: 6px;
    }
  }
}
.disclaimer {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 4px;
  font-size: 12px;
  color: #e6a23c;
}
</style>
