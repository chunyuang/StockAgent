<script setup lang="ts">
/**
 * 持仓风控矩阵
 * P0-3: 风险热力矩阵 + 全局风险仪表 + 行业集中度
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import VChart from 'vue-echarts'

interface RiskPosition {
  ts_code: string; stock_name: string; strategy_name: string; industry: string
  current_price: number; cost_price: number; profit_pct: number; profit_amount: number
  market_value: number; position_pct: number; dist_stop_loss: number; dist_take_profit: number
  stop_loss_price: number; take_profit_price: number; volatility: number; turnover_rate: number
  risk_score: number; risk_level: string; trailing_stop: any; total_qty: number
}

interface GlobalRisk {
  total_assets: number; cash_ratio: number; position_ratio: number; max_single_pct: number
  top_industry_concentration: number; industry_exposure: Record<string, number>
  position_count: number; risk_summary: { normal: number; warning: number; critical: number }
}

const positions = ref<RiskPosition[]>([])
const globalRisk = ref<GlobalRisk | null>(null)
const loading = ref(false)

async function fetchData() {
  loading.value = true
  try {
    const r: any = await api.get('/scanner/position-risk-matrix')
    if (r?.success) {
      positions.value = r.data?.positions || []
      globalRisk.value = r.data?.global || null
    }
  } catch { } finally { loading.value = false }
}

function riskColor(score: number): string {
  if (score < 30) return '#67c23a'
  if (score < 50) return '#e6a23c'
  if (score < 70) return '#f56c6c'
  return '#c45656'
}

function riskBg(score: number): string {
  return riskColor(score) + '18'
}

function slColor(dist: number): string {
  if (dist > 5) return '#67c23a'
  if (dist > 2) return '#e6a23c'
  return '#f56c6c'
}

// 行业饼图
const industryOption = computed(() => {
  if (!globalRisk.value?.industry_exposure) return {}
  const entries = Object.entries(globalRisk.value.industry_exposure)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
    series: [{
      type: 'pie', radius: ['40%', '70%'], center: ['50%', '50%'],
      label: { show: true, fontSize: 10, formatter: '{b}\n{d}%' },
      data: entries.map(([k, v]) => ({ name: k, value: v })),
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } },
    }],
    animation: false,
  }
})

// 风险仪表盘
const gaugeOption = computed(() => {
  const g = globalRisk.value || {}
  if (!g) return {}
  const critical = (g.risk_summary?.critical || 0)
  const warning = (g.risk_summary?.warning || 0)
  const total = (g.position_count || 0)
  const score = total > 0 ? Math.round((critical * 100 + warning * 50) / total) : 0
  return {
    series: [{
      type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100,
      pointer: { show: true, length: '60%', width: 4, itemStyle: { color: 'auto' } },
      axisLine: { lineStyle: { width: 8, color: [[0.3, '#67c23a'], [0.7, '#e6a23c'], [1, '#f56c6c']] } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      detail: { formatter: '{value}', fontSize: 14, offsetCenter: [0, '70%'], color: 'auto' },
      data: [{ value: score, name: '风险分' }],
    }],
    animation: false,
  }
})

let timer: number
onMounted(() => { fetchData(); timer = window.setInterval(fetchData, 15000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="risk-matrix">
    <div class="rm-header">
      <span class="rm-title">🛡️ 风控矩阵</span>
      <span class="rm-refresh cp" @click="fetchData">🔄</span>
    </div>

    <!-- 全局仪表 -->
    <div v-if="globalRisk" class="rm-global">
      <div class="rm-gauge">
        <VChart :option="gaugeOption" autoresize style="height:100px;width:100%" />
      </div>
      <div class="rm-stats">
        <div class="rm-stat">
          <span class="rm-label">仓位</span>
          <span class="rm-val">{{ (globalRisk?.position_ratio || 0) }}%</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">现金</span>
          <span class="rm-val">{{ (globalRisk?.cash_ratio || 0) }}%</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">集中度</span>
          <span class="rm-val" :class="globalRisk.max_single_pct > 30 ? 'warn' : ''">{{ globalRisk.max_single_pct }}%</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">行业集中</span>
          <span class="rm-val">{{ (globalRisk?.top_industry_concentration || 0) }}%</span>
        </div>
        <div class="rm-risk-counts">
          <span class="rm-rc ok">🟢 {{ (globalRisk?.risk_summary?.normal || 0) }}</span>
          <span class="rm-rc warn">🟡 {{ (globalRisk?.risk_summary?.warning || 0) }}</span>
          <span class="rm-rc crit">🔴 {{ (globalRisk?.risk_summary?.critical || 0) }}</span>
        </div>
      </div>
      <div class="rm-industry" v-if="Object.keys(globalRisk.industry_exposure || {}).length > 1">
        <VChart :option="industryOption" autoresize style="height:80px;width:100%" />
      </div>
    </div>

    <!-- 风控矩阵表 -->
    <div class="rm-matrix" v-if="positions.length">
      <div class="rm-matrix-header">
        <span>股票</span><span>盈亏%</span><span>距止损</span><span>距止盈</span><span>仓位</span><span>风险分</span>
      </div>
      <div v-for="p in positions" :key="p.ts_code" class="rm-row" :style="{ borderLeftColor: riskColor(p.risk_score) }">
        <div class="rm-cell rm-cell-name">
          <span class="rm-code">{{ (p.ts_code || "").slice(0, 6) }}</span>
          <span class="rm-sname">{{ p.stock_name }}</span>
          <span class="rm-ind-tag">{{ p.industry }}</span>
        </div>
        <div class="rm-cell" :class="p.profit_pct >= 0 ? 'up' : 'down'">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct.toFixed(1) }}%</div>
        <div class="rm-cell">
          <span class="rm-bar-wrap">
            <span class="rm-bar" :style="{ width: Math.max(0, Math.min(p.dist_stop_loss / 10 * 100, 100)) + '%', background: slColor(p.dist_stop_loss) }"></span>
          </span>
          <span class="rm-bar-val" :style="{ color: slColor(p.dist_stop_loss) }">{{ p.dist_stop_loss.toFixed(1) }}%</span>
        </div>
        <div class="rm-cell">{{ p.dist_take_profit.toFixed(1) }}%</div>
        <div class="rm-cell">{{ p.position_pct.toFixed(1) }}%</div>
        <div class="rm-cell">
          <span class="rm-score" :style="{ background: riskBg(p.risk_score), color: riskColor(p.risk_score) }">{{ p.risk_score }}</span>
        </div>
      </div>
    </div>
    <div v-else-if="!loading" class="rm-empty">暂无持仓</div>
  </div>
</template>

<style scoped>
.risk-matrix { background: var(--el-bg-color); border-radius: 8px; padding: 12px; }
.rm-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.rm-title { font-weight: 600; font-size: 13px; }
.rm-refresh { font-size: 12px; }

.rm-global { display: flex; gap: 12px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter); flex-wrap: wrap; }
.rm-gauge { width: 120px; flex-shrink: 0; }
.rm-stats { flex: 1; display: flex; flex-wrap: wrap; gap: 6px 12px; align-content: flex-start; }
.rm-stat { display: flex; flex-direction: column; min-width: 50px; }
.rm-label { font-size: 10px; color: var(--el-text-color-secondary); }
.rm-val { font-size: 13px; font-weight: 600; }
.rm-val.warn { color: #f56c6c; }
.rm-risk-counts { display: flex; gap: 8px; width: 100%; margin-top: 4px; font-size: 11px; }
.rm-rc.ok { color: #67c23a; } .rm-rc.warn { color: #e6a23c; } .rm-rc.crit { color: #f56c6c; }
.rm-industry { width: 140px; flex-shrink: 0; }

.rm-matrix { font-size: 11px; }
.rm-matrix-header { display: grid; grid-template-columns: 2fr 1fr 1.5fr 1fr 0.8fr 0.8fr; gap: 4px; padding: 4px 6px; color: var(--el-text-color-secondary); font-size: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.rm-row { display: grid; grid-template-columns: 2fr 1fr 1.5fr 1fr 0.8fr 0.8fr; gap: 4px; padding: 4px 6px; border-left: 3px solid; align-items: center; }
.rm-row:hover { background: var(--el-fill-color-lighter); }
.rm-cell { white-space: nowrap; }
.rm-cell-name { display: flex; align-items: center; gap: 4px; }
.rm-code { font-family: monospace; font-size: 10px; color: var(--el-text-color-secondary); }
.rm-sname { font-size: 11px; }
.rm-ind-tag { font-size: 9px; padding: 0 3px; background: var(--el-fill-color); border-radius: 2px; color: var(--el-text-color-secondary); }
.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }

.rm-bar-wrap { display: inline-block; width: 30px; height: 6px; background: var(--el-fill-color); border-radius: 3px; vertical-align: middle; }
.rm-bar { display: block; height: 100%; border-radius: 3px; transition: width 0.3s; }
.rm-bar-val { font-size: 10px; margin-left: 2px; }

.rm-score { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.rm-empty { text-align: center; padding: 16px; color: var(--el-text-color-secondary); font-size: 12px; }
</style>
