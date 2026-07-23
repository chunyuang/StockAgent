<script setup lang="ts">
/**
 * PositionSystemPanel - 仓位管理系统设计面板
 * 纯CSS可视化: 仓位计算链路 + 参数表 + 实时计算器
 */
import { computed } from 'vue'

const props = defineProps<{
  sentiment: { score: number; period: string } | null
  circuitBreaker: { position_cap: number; cumulative_drawdown: number; buy_paused: boolean } | null
  account: { total_assets: number; available_cash: number; market_value: number } | null
  positionCount: number
  positionRatio: number
}>()

// ===== 策略参数 =====
const strategies = [
  { key: 'halfway_chase', name: '半路追涨', base: 0.35, color: '#f23645', desc: '主力策略', maxHold: 3, stopLoss: '3.5%', takeProfit: '12%', friday: '20%' },
  { key: 'first_limit_up', name: '首板打板', base: 0.25, color: '#e6a23c', desc: '涨停封板', maxHold: 3, stopLoss: '5%', takeProfit: '15%', friday: '-' },
  { key: 'limit_up_open', name: '涨停开板', base: 0.25, color: '#e6a23c', desc: '炸板回封', maxHold: 2, stopLoss: '5%', takeProfit: '10%', friday: '-' },
  { key: 'dragon_head', name: '龙头低吸', base: 0.15, color: '#409eff', desc: '连板回调', maxHold: 5, stopLoss: '5%', takeProfit: '15%', friday: '-' },
  { key: 'limit_down_qiao', name: '跌停翘板', base: 0.15, color: '#089981', desc: '撬板反弹', maxHold: 1, stopLoss: '5%', takeProfit: '8%', friday: '-' },
  { key: 'anomaly', name: '异动', base: 0.10, color: '#909399', desc: '异常放量', maxHold: 2, stopLoss: '3%', takeProfit: '8%', friday: '-' },
]

const sentimentMap = [
  { period: 'rising', cn: '高潮', score: '≥70', ratio: 1.0, maxPos: 10, color: '#f23645' },
  { period: 'differentiation', cn: '分化', score: '55-70', ratio: 0.7, maxPos: 8, color: '#e6a23c' },
  { period: 'chaos', cn: '震荡', score: '40-55', ratio: 0.5, maxPos: 6, color: '#409eff' },
  { period: 'bearish', cn: '冰点', score: '<40', ratio: 0.3, maxPos: 4, color: '#089981' },
]

const drawdownMap = [
  { range: '<5%', cap: 1.0, label: '正常', color: '#089981' },
  { range: '5-10%', cap: 0.5, label: '半仓', color: '#e6a23c' },
  { range: '10-15%', cap: 0.25, label: '1/4仓', color: '#f23645' },
  { range: '≥15%', cap: 0.0, label: '禁止', color: '#909399' },
]

const currentSentiment = computed(() => {
  const period = props.sentiment?.period || 'chaos'
  return sentimentMap.find(s => s.period === period) || sentimentMap[2]
})

const currentDrawdownCap = computed(() => {
  const cap = props.circuitBreaker?.position_cap ?? 1.0
  const dd = props.circuitBreaker?.cumulative_drawdown ?? 0
  return { cap, drawdown: dd, label: drawdownMap.find(d => d.cap === cap)?.label || '正常' }
})

const ma60Broken = computed(() => true)
const ma60Ratio = computed(() => ma60Broken.value ? 0.5 : 1.0)

const pipeline = computed(() => currentSentiment.value.ratio * ma60Ratio.value * currentDrawdownCap.value.cap)

// 链路步骤
const chainSteps = computed(() => {
  const sent = currentSentiment.value
  const cap = currentDrawdownCap.value
  const ma60 = ma60Ratio.value
  return [
    { label: '策略base', value: '', desc: '半路追涨35%', color: '#f23645' },
    { label: '情绪系数', value: `×${sent.ratio}`, desc: `${sent.cn} ${props.sentiment?.score || 0}分`, color: sent.color },
    { label: 'MA60', value: `×${ma60}`, desc: ma60 < 1 ? '大盘跌破MA60' : '大盘之上', color: ma60 < 1 ? '#f23645' : '#089981' },
    { label: '回撤cap', value: `×${cap.cap}`, desc: `回撤${(cap.drawdown * 100).toFixed(1)}% ${cap.label}`, color: cap.cap < 1 ? '#f23645' : '#089981' },
  ]
})

// 每个策略的最终计算
const calcResults = computed(() => {
  const p = pipeline.value
  const assets = props.account?.total_assets || 934177
  const maxPos = currentSentiment.value.maxPos
  return strategies.slice(0, 4).map(s => {
    const ratio = s.base * p
    const maxAmount = assets * ratio
    const totalIfFull = maxPos * maxAmount
    const totalRatio = Math.min(totalIfFull / assets, 0.7)
    return {
      ...s,
      ratio,
      maxAmount,
      totalIfFull,
      totalRatio,
      barWidth: Math.min(totalRatio / 0.7 * 100, 100),
    }
  })
})

function fmtMoney(v: number): string {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return v.toFixed(0)
}
</script>

<template>
  <div class="psp-panel">
    <div class="psp-title">🎯 仓位管理系统设计</div>

    <!-- 1. 仓位计算链路 - 纯CSS流程图 -->
    <div class="psp-section">
      <div class="psp-section-title">📊 仓位计算链路</div>
      <div class="psp-chain">
        <div v-for="(step, i) in chainSteps" :key="i" class="psp-chain-group">
          <div class="psp-chain-node" :style="{ borderColor: step.color }">
            <div class="psp-chain-label">{{ step.label }}</div>
            <div class="psp-chain-value" :style="{ color: step.color }">{{ step.value }}</div>
            <div class="psp-chain-desc">{{ step.desc }}</div>
          </div>
          <div v-if="i < chainSteps.length - 1" class="psp-chain-arrow">→</div>
        </div>
        <div class="psp-chain-arrow">=</div>
        <div class="psp-chain-result">
          <div class="psp-chain-label">最终比例</div>
          <div class="psp-chain-value big">{{ (pipeline * 35).toFixed(2) }}%</div>
          <div class="psp-chain-desc">半路追涨</div>
        </div>
      </div>
      <div class="psp-formula-hint">
        基数 = 总资产 ¥{{ fmtMoney(account?.total_assets || 0) }} · pipeline = {{ pipeline.toFixed(4) }}
      </div>
    </div>

    <!-- 2. 三张参数表 -->
    <div class="psp-tables">
      <div class="psp-table-card">
        <div class="psp-table-title">策略仓位参数</div>
        <table class="psp-table">
          <thead><tr><th>策略</th><th>base</th><th>止损</th><th>止盈</th><th>持天</th><th>周五</th></tr></thead>
          <tbody>
            <tr v-for="s in strategies" :key="s.key">
              <td><span class="psp-dot" :style="{ background: s.color }"></span>{{ s.name }}</td>
              <td class="psp-num">{{ (s.base * 100).toFixed(0) }}%</td>
              <td class="psp-num">{{ s.stopLoss }}</td>
              <td class="psp-num">{{ s.takeProfit }}</td>
              <td class="psp-num">{{ s.maxHold }}</td>
              <td class="psp-num">{{ s.friday }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="psp-table-card">
        <div class="psp-table-title">情绪周期映射</div>
        <table class="psp-table">
          <thead><tr><th>周期</th><th>分数</th><th>系数</th><th>上限</th></tr></thead>
          <tbody>
            <tr v-for="s in sentimentMap" :key="s.period" :class="{ 'psp-row-active': s.period === currentSentiment.period }">
              <td><span class="psp-dot" :style="{ background: s.color }"></span>{{ s.cn }}</td>
              <td class="psp-num">{{ s.score }}</td>
              <td class="psp-num">×{{ s.ratio }}</td>
              <td class="psp-num">{{ s.maxPos }}只</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="psp-table-card">
        <div class="psp-table-title">回撤熔断cap</div>
        <table class="psp-table">
          <thead><tr><th>回撤</th><th>cap</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="d in drawdownMap" :key="d.range" :class="{ 'psp-row-active': d.cap === currentDrawdownCap.cap }">
              <td class="psp-num">{{ d.range }}</td>
              <td class="psp-num">×{{ d.cap }}</td>
              <td><span :style="{ color: d.color }">{{ d.label }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 3. 实时仓位计算器 -->
    <div class="psp-section">
      <div class="psp-section-title">🔢 实时仓位计算器（当前条件: {{ currentSentiment.cn }} + MA60{{ ma60Broken ? '破' : '上' }} + {{ currentDrawdownCap.label }}）</div>
      <div class="psp-calc-grid">
        <div v-for="c in calcResults" :key="c.key" class="psp-calc-card">
          <div class="psp-calc-header">
            <span class="psp-dot" :style="{ background: c.color }"></span>
            <span class="psp-calc-name">{{ c.name }}</span>
            <span class="psp-calc-base">base {{ (c.base * 100).toFixed(0) }}%</span>
          </div>
          <div class="psp-calc-ratio" :style="{ color: c.color }">{{ (c.ratio * 100).toFixed(2) }}%</div>
          <div class="psp-calc-detail">
            <span>单只 ¥{{ fmtMoney(c.maxAmount) }}</span>
            <span>满仓 {{ (c.totalRatio * 100).toFixed(1) }}%</span>
          </div>
          <div class="psp-calc-bar">
            <div class="psp-calc-bar-fill" :style="{ width: c.barWidth + '%', background: c.color }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. 风控层级 -->
    <div class="psp-section">
      <div class="psp-section-title">🛡️ 风控层级 (L1→L9 逐级过滤)</div>
      <div class="psp-layers">
        <div class="psp-layer"><span class="psp-layer-num">L1</span> 强制空仓: 跌停≥80 / 涨停≤10 / 大盘跌≥3%</div>
        <div class="psp-layer"><span class="psp-layer-num">L2</span> 特殊时期: 月末/季末/节前 ×系数</div>
        <div class="psp-layer psp-layer-active"><span class="psp-layer-num">L3</span> 情绪周期: 7维公式 → 仓位系数</div>
        <div class="psp-layer"><span class="psp-layer-num">L4</span> 盘前过滤: ST/退市/次新/低流动</div>
        <div class="psp-layer"><span class="psp-layer-num">L5</span> 竞价过滤: 高开>7% / 低开<-5%</div>
        <div class="psp-layer"><span class="psp-layer-num">L6</span> 策略筛选: 量能/涨幅/连板条件</div>
        <div class="psp-layer"><span class="psp-layer-num">L7</span> 排序去重: 优先级 / 最多10候选</div>
        <div class="psp-layer psp-layer-active"><span class="psp-layer-num">L8</span> 仓位控制: 情绪×MA60×cap → pipeline</div>
        <div class="psp-layer"><span class="psp-layer-num">L9</span> 执行: 计算股数 / 质量检查 / 下单</div>
      </div>
    </div>

    <!-- 5. 情绪自适应止盈 -->
    <div class="psp-section">
      <div class="psp-section-title">🎯 情绪自适应止盈 (v2.9.128)</div>
      <div class="psp-tables" style="grid-template-columns: 1fr;">
        <div class="psp-table-card">
          <table class="psp-table">
            <thead><tr><th>情绪周期</th><th>分批止盈</th><th>追踪止损回撤</th><th>冲高回落</th><th>策略思路</th></tr></thead>
            <tbody>
              <tr>
                <td><span class="psp-dot" style="background:#f23645"></span>高潮</td>
                <td class="psp-num" style="color:#f23645">禁用</td>
                <td class="psp-num">放宽5%</td>
                <td class="psp-num" style="color:#f23645">跳过</td>
                <td style="font-size:10px;color:var(--text-tertiary,#888)">让利润奔跑</td>
              </tr>
              <tr>
                <td><span class="psp-dot" style="background:#e6a23c"></span>分化</td>
                <td class="psp-num">8%触发</td>
                <td class="psp-num">原始计算</td>
                <td class="psp-num">正常</td>
                <td style="font-size:10px;color:var(--text-tertiary,#888)">落袋+追踪</td>
              </tr>
              <tr>
                <td><span class="psp-dot" style="background:#409eff"></span>震荡</td>
                <td class="psp-num">6%触发</td>
                <td class="psp-num">收紧2%</td>
                <td class="psp-num">正常</td>
                <td style="font-size:10px;color:var(--text-tertiary,#888)">有赚就跑</td>
              </tr>
              <tr>
                <td><span class="psp-dot" style="background:#089981"></span>冰点</td>
                <td class="psp-num">5%触发</td>
                <td class="psp-num">收紧1.5%</td>
                <td class="psp-num">正常</td>
                <td style="font-size:10px;color:var(--text-tertiary,#888)">快进快出</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.psp-panel { background: var(--bg-elevated, #1a1a2e); border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1px solid var(--border-default, #333); }
.psp-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; }

.psp-section { margin-bottom: 16px; }
.psp-section-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--text-secondary, #aaa); }

/* 链路流程图 */
.psp-chain { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.psp-chain-group { display: flex; align-items: center; gap: 4px; }
.psp-chain-node { border: 2px solid; border-radius: 8px; padding: 8px 12px; min-width: 80px; text-align: center; background: var(--bg-card, #16213e); }
.psp-chain-label { font-size: 10px; color: var(--text-tertiary, #888); }
.psp-chain-value { font-size: 16px; font-weight: 700; margin: 2px 0; }
.psp-chain-value.big { font-size: 20px; }
.psp-chain-desc { font-size: 9px; color: var(--text-quaternary, #666); }
.psp-chain-arrow { font-size: 18px; color: var(--text-tertiary, #555); font-weight: 700; }
.psp-chain-result { border: 2px solid #f23645; border-radius: 8px; padding: 8px 14px; text-align: center; background: rgba(242, 54, 69, 0.08); }
.psp-formula-hint { font-size: 11px; color: var(--text-quaternary, #666); margin-top: 6px; }

/* 表格 */
.psp-tables { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 14px; }
.psp-table-card { background: var(--bg-card, #16213e); border-radius: 8px; padding: 10px; border: 1px solid var(--border-default, #333); }
.psp-table-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.psp-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.psp-table th { text-align: left; padding: 4px 6px; color: var(--text-tertiary, #888); font-weight: 400; border-bottom: 1px solid var(--border-default, #333); }
.psp-table td { padding: 4px 6px; border-bottom: 1px solid var(--border-default, #222); }
.psp-num { text-align: right; font-variant-numeric: tabular-nums; }
.psp-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
.psp-row-active { background: rgba(64, 158, 255, 0.1); }

/* 计算器 */
.psp-calc-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.psp-calc-card { background: var(--bg-card, #16213e); border-radius: 8px; padding: 10px; border: 1px solid var(--border-default, #333); }
.psp-calc-header { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.psp-calc-name { font-size: 12px; font-weight: 600; }
.psp-calc-base { font-size: 10px; color: var(--text-tertiary, #888); margin-left: auto; }
.psp-calc-ratio { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.psp-calc-detail { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-tertiary, #888); margin-bottom: 6px; }
.psp-calc-bar { height: 4px; background: var(--bg-default, #222); border-radius: 2px; overflow: hidden; }
.psp-calc-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }

/* 风控层级 */
.psp-layers { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
.psp-layer { font-size: 11px; padding: 6px 10px; border-radius: 6px; background: var(--bg-card, #16213e); border: 1px solid var(--border-default, #333); display: flex; align-items: center; gap: 6px; }
.psp-layer-active { border-color: #409eff; background: rgba(64, 158, 255, 0.08); }
.psp-layer-num { font-size: 10px; font-weight: 700; color: #409eff; min-width: 20px; }

@media (max-width: 1200px) {
  .psp-tables { grid-template-columns: 1fr; }
  .psp-calc-grid { grid-template-columns: repeat(2, 1fr); }
  .psp-layers { grid-template-columns: 1fr; }
}
</style>
