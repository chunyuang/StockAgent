<script setup lang="ts">
/**
 * 持仓风控矩阵
 * P0-3: 风险热力矩阵 + 全局风险仪表 + 行业集中度
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { getChinaDate } from '@/utils/chinaDate'


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
  stop_loss_exec_rate?: number  // 止损执行率(0-100): 亏损中走止损的占比
}

const positions = ref<RiskPosition[]>([])
const globalRisk = ref<GlobalRisk | null>(null)
const loading = ref(false)
const isFallback = ref(false)

const selectedDate = ref(getChinaDate())

async function fetchData() {
  loading.value = true
  try {
    const params: any = {}
    if (selectedDate.value) params.date = selectedDate.value
    const r: any = await api.get('/scanner/position-risk-matrix', { params })
    if (r?.success) {
      positions.value = Array.isArray(r.data?.positions) ? r.data.positions : []
      globalRisk.value = r.data?.global || null
      isFallback.value = !!r.data?._fallback
    }
  } catch (e) { console.error('[PositionRiskMatrix] fetch error:', e) } finally { loading.value = false }
}

function safeNum(v: any, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
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



const riskScore = computed(() => {
  if (!globalRisk.value) return 0
  const c = globalRisk.value?.risk_summary?.critical ?? 0
  const w = globalRisk.value?.risk_summary?.warning ?? 0
  const n = globalRisk.value?.risk_summary?.normal ?? 0
  const t = c + w + n
  if (t === 0) return 0
  // 【v2.9.112】全局风险评分: 基于持仓15维度评分(risk_score)汇总, 归一化到0-100
  // 后端每只持仓已有D1-D15的risk_score, 此处用3级汇总做全局仪表
  // 15维度: D1止损距离(0-25) D2仓位集中(0-15) D3浮亏(0-15) D4换手(0-10) D5波动(0-10)
  //   D6追踪止损(0-5) D7行业集中(0-5) D8新仓(0-5) D9连亏(0-5) D10持仓天数(0-3)
  //   D11溢价(0-2) D12大盘(0-2) D13流动性(0-2) D14盈亏偏离(0-2) D15策略胜率(0-2)
  const raw = (c * 80 + w * 45 + n * 10) / t
  return safeNum(Math.min(Math.round(raw / 80 * 100), 100))
})

let timer: number
onMounted(() => { fetchData(); timer = window.setInterval(fetchData, 15000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="risk-matrix">
    <div class="rm-header">
      <span class="rm-title">🛡️ 风控矩阵</span>
      <UnifiedDateBar :modelValue="selectedDate" @change="(d: string) => { selectedDate = d; fetchData() }" />
      <span v-if="isFallback" style="font-size:10px;color:var(--el-color-warning);margin-right:6px">📜历史数据(Scanner未运行,从MongoDB回退)</span>
      <span class="rm-refresh cp" @click="fetchData">🔄</span>
    </div>

    <!-- 全局仪表 -->
    <div v-if="globalRisk" class="rm-global">
      <div class="rm-gauge">
        <div class="css-gauge">
          <div class="css-gauge-bg">
            <div class="css-gauge-fill" :style="{ width: riskScore + '%' }"></div>
          </div>
          <div class="css-gauge-val" :style="{ color: riskColor(riskScore) }">{{ riskScore }}</div>
        </div>
      </div>
      <div class="rm-stats">
        <div class="rm-stat">
          <span class="rm-label">仓位</span>
          <span class="rm-val">{{ globalRisk?.position_ratio != null && Number.isFinite(Number(globalRisk?.position_ratio)) ? Number(globalRisk?.position_ratio).toFixed(1) + '%' : '-' }}</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">现金</span>
          <span class="rm-val">{{ globalRisk?.cash_ratio != null && Number.isFinite(Number(globalRisk?.cash_ratio)) ? Number(globalRisk?.cash_ratio).toFixed(1) + '%' : '-' }}</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">集中度</span>
          <span class="rm-val" :class="(globalRisk?.max_single_pct || 0) > 30 ? 'warn' : ''">{{ globalRisk?.max_single_pct != null && Number.isFinite(Number(globalRisk?.max_single_pct)) ? Number(globalRisk?.max_single_pct).toFixed(1) + '%' : '-' }}</span>
        </div>
        <div class="rm-stat">
          <span class="rm-label">行业集中</span>
          <!-- 【v2.9.120】后端已返回0-100范围,不要再*100 -->
          <span class="rm-val">{{ globalRisk?.top_industry_concentration != null && Number.isFinite(Number(globalRisk?.top_industry_concentration)) ? Number(globalRisk?.top_industry_concentration).toFixed(1) + '%' : '-' }}</span>
        </div>
        <div class="rm-stat" v-if="globalRisk?.stop_loss_exec_rate != null">
          <span class="rm-label">止损执行</span>
          <!-- 止损执行率分母=亏损卖出笔数(不含止盈/手动止盈), 分子=其中走止损卖出的笔数 -->
          <span class="rm-val" :class="(globalRisk?.stop_loss_exec_rate ?? 0) < 50 ? 'warn' : ''">{{ Number(globalRisk?.stop_loss_exec_rate).toFixed(0) }}%</span>
        </div>
        <div class="rm-risk-counts">
          <span class="rm-rc ok">🟢 {{ globalRisk?.risk_summary?.normal ?? 0 }}</span>
          <span class="rm-rc warn">🟡 {{ globalRisk?.risk_summary?.warning ?? 0 }}</span>
          <span class="rm-rc crit">🔴 {{ globalRisk?.risk_summary?.critical ?? 0 }}</span>
        </div>
      </div>
      <div class="rm-industry" v-if="Object.keys(globalRisk?.industry_exposure || {}).length > 1">
        <div v-for="(pct, name) in globalRisk?.industry_exposure || {}" :key="name" class="ind-bar-row">
          <span class="ind-label">{{ name }}</span>
          <div class="ind-bar-track"><div class="ind-bar-fill" :style="{ width: Math.min(safeNum(pct, 0), 100).toFixed(0) + '%' }"></div></div>
          <span class="ind-pct">{{ safeNum(pct, 0).toFixed(1) }}%</span>
        </div>
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
        <div class="rm-cell" :class="p.profit_pct != null && p.profit_pct >= 0 ? 'up' : 'down'">{{ p.profit_pct != null ? ((p.profit_pct >= 0 ? '+' : '') + Number(p.profit_pct).toFixed(1) + '%') : '-' }}</div>
        <div class="rm-cell">
          <span class="rm-bar-wrap">
            <span class="rm-bar" :style="{ width: Math.max(0, Math.min((p.dist_stop_loss ?? 0) / 10 * 100, 100)) + '%', background: slColor(p.dist_stop_loss ?? 0) }"></span>
          </span>
          <span class="rm-bar-val" :style="{ color: slColor(p.dist_stop_loss ?? 0) }">{{ p.dist_stop_loss != null && Number.isFinite(Number(p.dist_stop_loss)) ? Number(p.dist_stop_loss).toFixed(1) + '%' : '-' }}</span>
        </div>
        <div class="rm-cell">{{ p.dist_take_profit != null && Number.isFinite(Number(p.dist_take_profit)) ? Number(p.dist_take_profit).toFixed(1) + '%' : '-' }}</div>
        <div class="rm-cell">{{ p.position_pct != null && Number.isFinite(Number(p.position_pct)) ? Number(p.position_pct).toFixed(1) + '%' : '-' }}</div>
        <div class="rm-cell">
          <span class="rm-score" :style="{ background: riskBg(p.risk_score || 0), color: riskColor(p.risk_score || 0) }">{{ p.risk_score ?? '-' }}</span>
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
.rm-industry { flex: 1; min-width: 120px; }
.css-gauge { text-align: center; }
.css-gauge-bg { width: 80px; height: 8px; background: var(--el-fill-color); border-radius: 4px; margin: 4px auto; overflow: hidden; }
.css-gauge-fill { height: 100%; border-radius: 4px; transition: width 0.3s; background: linear-gradient(90deg, #67c23a, #e6a23c, #f56c6c); }
.css-gauge-val { font-size: 18px; font-weight: 700; }
.ind-bar-row { display: flex; align-items: center; gap: 4px; font-size: 10px; margin: 2px 0; }
.ind-label { width: 40px; text-align: right; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ind-bar-track { flex: 1; height: 6px; background: var(--el-fill-color); border-radius: 3px; overflow: hidden; }
.ind-bar-fill { height: 100%; background: var(--el-color-primary); border-radius: 3px; transition: width 0.3s; }
.ind-pct { width: 28px; color: var(--el-text-color-secondary); }

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
