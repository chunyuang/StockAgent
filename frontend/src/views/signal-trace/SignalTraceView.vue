<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useSignalTrace, PIPELINE_LAYERS } from './useSignalTrace'
import {
  ElCard, ElSelect, ElOption, ElButton, ElEmpty, ElTooltip,
} from 'element-plus'
import { Refresh, CaretRight, CaretBottom, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import UnifiedDateBar from '@/components/UnifiedDateBar.vue'

const trace = useSignalTrace()
const dateValue = ref('')
function onDateChange(dateStr: string) { trace.fetchSignalTrace(dateStr) }
onMounted(() => { trace.fetchSignalTrace() })

// 完整9层管道 + 执行结果
const FLOW_LAYERS = [
  { key: 'L1_force_empty', short: 'L1', label: '强制空仓', desc: '极端行情下禁止开仓(千股跌停/涨停≥80)' },
  { key: 'L2_special_period', short: 'L2', label: '特殊时期', desc: '特殊时段限制(午间/尾盘/竞价防守期)' },
  { key: 'L3_sentiment', short: 'L3', label: '情绪周期', desc: '市场情绪阶段(冰点/复苏/高潮/分化/恐慌)' },
  { key: 'L4_premarket', short: 'L4', label: '盘前预选', desc: '开盘前基本面/技术面/异动初筛' },
  { key: 'L5_auction', short: 'L5', label: '竞价过滤', desc: '竞价异常排除(高开>7%/低开<-5%/ST/停牌)' },
  { key: 'L6_strategy', short: 'L6', label: '策略量能', desc: '策略专属过滤(量比/换手/振幅/市值)' },
  { key: 'L7_ranking', short: 'L7', label: '综合排序', desc: '因子加权打分排序,截断取前N名' },
  { key: 'L8_position', short: 'L8', label: '仓位控制', desc: '风控拦截(MA5弱势/冷却期/持仓满/重复信号)' },
  { key: 'L9_execute', short: 'L9', label: '执行队列', desc: '管道筛选通过,进入执行队列' },
  { key: 'execution', short: '下单', label: '执行结果', desc: '最终执行结果: 成交/拦截/观察' },
]

function strategyCN(s: string): string {
  const m: Record<string, string> = {
    halfway_chase: '半路追涨', first_limit_up: '首板打板',
    limit_up_open: '涨停开板', dragon_head: '龙头低吸',
    limit_down_qiao: '跌停翘板', anomaly_strong: '强势涨停', anomaly_surge: '放量异动',
  }
  return m[s] || s
}
function strategyColor(s: string): string {
  const m: Record<string, string> = {
    halfway_chase: '#e6a23c', first_limit_up: '#f56c6c',
    limit_up_open: '#f56c6c', dragon_head: '#409eff',
    limit_down_qiao: '#909399', anomaly_strong: '#67c23a', anomaly_surge: '#67c23a',
  }
  return m[s] || '#909399'
}

// 展开详情: 因子明细
function getFactorDetails(stock: any): { label: string; value: string; cls?: string; desc?: string }[] {
  const f = stock.factors || {}
  const mv = (f.circ_mv || 0) / 10000
  const pb = (f.pullback_pct || 0) * 100
  const opPct = f.opening_pct_chg || 0
  const items = [
    { label: '涨幅', value: `${f.pct_chg?.toFixed(1) || '-'}%`, cls: (f.pct_chg || 0) > 0 ? 'up' : 'down' },
    { label: '量比', value: `${f.volume_ratio?.toFixed(1) || '-'}x`, cls: (f.volume_ratio || 0) > 5 ? 'warn' : '' },
    { label: '换手率', value: `${f.turnover_rate?.toFixed(1) || '-'}%`, cls: (f.turnover_rate || 0) > 5 ? 'warn' : '' },
    { label: '流通市值', value: `${mv.toFixed(0)}亿` },
    { label: 'MA5偏离', value: `${pb.toFixed(1)}%`, cls: pb < -3 ? 'down' : '' },
    { label: 'RSI6', value: `${f.rsi_6?.toFixed(0) || '-'}`, cls: (f.rsi_6 || 50) > 80 ? 'warn' : '' },
    { label: '开盘涨幅', value: `${opPct.toFixed(1)}%`, cls: opPct > 2 ? 'warn' : opPct < 0 ? 'up' : '', desc: opPct > 2 ? '高开追高风险' : opPct < -1 ? '低开冲高较优' : '' },
    { label: '恐贪指数', value: f.fear_greed_index != null ? f.fear_greed_index.toFixed(1) : '-', cls: (f.fear_greed_index || 5) < 3 ? 'up' : '', desc: f.fear_greed_index != null ? ((f.fear_greed_index < 3 ? '冰点反弹' : f.fear_greed_index < 5 ? '恐惧区间' : f.fear_greed_index < 7 ? '正常' : '贪婪')) : '' },
    { label: '开盘价', value: `¥${f.open?.toFixed(2) || '-'}` },
    { label: '最高价', value: `¥${f.high?.toFixed(2) || '-'}` },
    { label: '最低价', value: `¥${f.low?.toFixed(2) || '-'}` },
    { label: '收盘价', value: `¥${f.close?.toFixed(2) || '-'}` },
    { label: '昨收价', value: `¥${f.pre_close?.toFixed(2) || '-'}` },
    { label: 'MA5', value: `¥${f.ma5?.toFixed(2) || '-'}` },
    { label: 'ATR', value: f.atr?.toFixed(2) || '-' },
    { label: 'MACD', value: f.macd?.toFixed(3) || '-' },
    { label: '连板数', value: `${f.limit_up_count || 0}` },
    { label: '是否涨停', value: f.is_limit_up ? '是' : '否' },
  ]
  return items.filter(i => i.value && i.value !== '¥-' && i.value !== '-')
}

// 展开详情: 管道通过状态
function getPipeStatus(stock: any, layerKey: string): string {
  const lr = stock.layerResults || {}
  const layer = lr[layerKey]
  if (!layer) return 'skip'
  return layer.passed ? 'pass' : 'reject'
}

function clickFilterLayer(layer: string) {
  trace.filterLayer.value = trace.filterLayer.value === layer ? 'all' : layer
}
function clickFilterResult(result: string) {
  trace.filterResult.value = trace.filterResult.value === result ? 'all' : result
}

// 综合描述 computed
const boughtStocks = computed(() => trace.filteredStockTraces.value.filter(s => s.finalStatus === 'bought'))
const boughtAvgPrice = computed(() => {
  const b = boughtStocks.value
  if (!b.length) return '0.00'
  return (b.reduce((sum, s) => sum + (s.boughtPrice || 0), 0) / b.length).toFixed(2)
})
const boughtAvgPct = computed(() => {
  const b = boughtStocks.value
  if (!b.length) return '0.0'
  return (b.reduce((sum, s) => sum + (s.pctChg || 0), 0) / b.length).toFixed(1)
})
const boughtAvgVR = computed(() => {
  const b = boughtStocks.value
  if (!b.length) return '0.0'
  return (b.reduce((sum, s) => sum + (s.factors?.volume_ratio || 0), 0) / b.length).toFixed(1)
})
const topRejectReasons = computed(() => {
  const counts: Record<string, number> = {}
  trace.filteredStockTraces.value.forEach(s => {
    if (s.rejectionReason) {
      // 简化原因：取前15字
      const r = s.rejectionReason.substring(0, 15)
      counts[r] = (counts[r] || 0) + 1
    }
  })
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([r, c]) => `${r}(${c}只)`)
})
const topFactors = computed(() => {
  const all = trace.filteredStockTraces.value
  if (!all.length) return []
  const avg = (key: string) => {
    const vals = all.map(s => s.factors?.[key]).filter(v => v != null && v !== 0)
    return vals.length ? (vals.reduce((a: number, b: number) => a + b, 0) / vals.length).toFixed(1) : '-'
  }
  return [
    { label: '涨幅', value: avg('pct_chg') + '%' },
    { label: '量比', value: avg('volume_ratio') + '倍' },
    { label: '换手', value: avg('turnover_rate') + '%' },
    { label: '流通市值', value: avg('circ_mv') !== '-' ? (parseFloat(avg('circ_mv')) / 10000).toFixed(0) + '亿' : '-' },
  ]
})

// 流程图折叠状态(默认折叠)
const flowCollapsed = ref(true)
const flowShowAll = ref(false)
const flowExpandedRow = ref<string>('')
const flowFilterLayer = ref('all')  // 流程图本地筛选, 不影响全局

// 评分排行数据(独立于流程图)
const rankShowAll = ref(false)
const rankExpandedRow = ref<string>('')  // 展开的行key
const rankedListFull = computed(() => {
  return [...trace.filteredStockTraces.value]
    .filter(s => s.score > 0)
    .sort((a, b) => (b.score || 0) - (a.score || 0))
})
const rankedList = computed(() => {
  return rankShowAll.value ? rankedListFull.value : rankedListFull.value.slice(0, 10)
})

const funnelRows = computed(() => {
  const s = trace.summary.value
  const lc = s.layerCounts || {}
  const maxVal = Math.max(s.total, 1)
  const rows: { layer: string; icon: string; label: string; val: number; cls?: string; tip?: string; barPct: number; pct?: string }[] = [
    { layer: '', icon: '🎯', label: '策略筛选', val: s.total, cls: 'total', barPct: 100 },
    ...PIPELINE_LAYERS.filter(l => l.key !== 'L9_execute').map(l => {
      const v = lc[l.key] || 0
      return { layer: l.key, icon: l.icon, label: l.label, val: v, barPct: Math.round(v / maxVal * 100), pct: v > 0 ? `${Math.round(v / maxVal * 100)}%` : '' }
    }),
    { layer: '', icon: '✅', label: '通过管道', val: s.bought + s.passedNotBought, cls: 'passed', barPct: Math.round((s.bought + s.passedNotBought) / maxVal * 100), pct: s.total > 0 ? `${Math.round((s.bought + s.passedNotBought) / s.total * 100)}%` : '' },
    { layer: 'execution', icon: '📋', label: '未成交', val: s.passedNotBought, tip: '通过管道但未成交: 持仓满/冷却期/时间限制/异动仅观察等', barPct: Math.round(s.passedNotBought / maxVal * 100) },
    { layer: '', icon: '💵', label: '成交', val: s.bought, cls: 'final', barPct: Math.round(s.bought / maxVal * 100), pct: s.total > 0 ? `${Math.round(s.bought / s.total * 100)}%` : '' },
  ]
  return rows.filter(r => r.val > 0 || r.cls === 'total' || r.cls === 'passed' || r.cls === 'final' || r.layer === 'execution')
})

// ====== 流程图数据 ======
interface FlowCell {
  status: 'pass' | 'reject' | 'skip' | 'none'
  reason: string
  layerKey: string
  layerLabel: string
}

// 时间线按交易时段分组
const timelineSlots = computed(() => {
  const nodes = trace.timelineNodes.value
  if (!nodes.length) return []
  
  // 时段定义: key, label, type, 时间范围
  const slotDefs = [
    { key: 'premarket', label: '盘前竞价', type: 'premarket', start: '09:00', end: '09:30' },
    { key: 'early', label: '早盘', type: 'early', start: '09:30', end: '11:30' },
    { key: 'lunch', label: '午休', type: 'lunch', start: '11:30', end: '13:00' },
    { key: 'afternoon', label: '下午盘', type: 'afternoon', start: '13:00', end: '15:00' },
  ]
  
  const result = slotDefs.map(sd => {
    const slotNodes = nodes.filter(n => {
      const t = n.time || ''
      return t >= sd.start && t < sd.end
    })
    return {
      ...sd,
      nodes: slotNodes,
      range: slotNodes.length ? `${slotNodes[0].time}-${slotNodes[slotNodes.length-1].time}` : '',
      totalCand: slotNodes.reduce((s, n) => s + (n.candidates || 0), 0),
      totalPassed: slotNodes.reduce((s, n) => s + (n.passed || 0), 0),
      totalBuys: slotNodes.reduce((s, n) => s + (n.buys || 0), 0),
      maxCand: Math.max(...slotNodes.map(n => n.candidates || 0), 1),
    }
  }).filter(s => s.nodes.length > 0)
  
  return result
})

function barHeight(val: number, maxVal: number): number {
  if (!maxVal || !val) return 2
  return Math.max(2, Math.round(val / maxVal * 48))
}

const flowRows = computed(() => {
  // 流程图: 先用全局筛选结果, 再叠加本地flowFilterLayer筛选
  const base = trace.filteredStockTraces.value
  const source = flowFilterLayer.value === 'all'
    ? base
    : base.filter(s => {
        if (flowFilterLayer.value === 'execution') return s.rejectionType === 'execution'
        return s.rejectionLayer === flowFilterLayer.value
      })
  return source.slice(0, 80).map(stock => {
    const cells: FlowCell[] = []
    const lr = stock.layerResults || {}
    let stopped = false

    for (const layer of FLOW_LAYERS) {
      if (stopped) {
        cells.push({ status: 'none', reason: '', layerKey: layer.key, layerLabel: layer.label })
        continue
      }

      if (layer.key === 'execution') {
        if (stock.finalStatus === 'bought') {
          cells.push({ status: 'pass', reason: stock.executionDesc || '成交', layerKey: 'execution', layerLabel: '执行结果' })
        } else if (stock.rejectionType === 'execution') {
          cells.push({ status: 'reject', reason: stock.rejectionReason || stock.executionDesc || '', layerKey: 'execution', layerLabel: '执行结果' })
          stopped = true
        } else if (stock.executionStatus === 'pending') {
          cells.push({ status: 'skip', reason: stock.executionDesc || '待执行', layerKey: 'execution', layerLabel: '执行结果' })
          stopped = true
        } else {
          cells.push({ status: 'none', reason: '', layerKey: 'execution', layerLabel: '执行结果' })
        }
        continue
      }

      const result = lr[layer.key]
      if (!result) {
        cells.push({ status: 'skip', reason: '', layerKey: layer.key, layerLabel: layer.label })
        continue
      }

      if (result.passed === false) {
        cells.push({ status: 'reject', reason: result.reason || '', layerKey: layer.key, layerLabel: layer.label })
        stopped = true
      } else {
        cells.push({ status: 'pass', reason: result.reason || '', layerKey: layer.key, layerLabel: layer.label })
      }
    }
    return { stock, cells }
  })
})

// 找到被拦截的层(用于行高亮)
// (unused, removed getRejectCell)
</script>

<template>
  <div class="signal-trace-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <UnifiedDateBar v-model="dateValue" @change="onDateChange" />
        <ElButton :icon="Refresh" size="small" @click="trace.fetchSignalTrace()" :loading="trace.loading.value">刷新</ElButton>
        <span class="toolbar-hint" v-if="trace.filteredStockTraces.value.length !== trace.stockTraces.value.length">
          筛选: {{ trace.filteredStockTraces.value.length }}/{{ trace.stockTraces.value.length }}
          <ElButton size="small" link type="primary" @click="trace.filterLayer.value='all'; trace.filterResult.value='all'; trace.filterStrategy.value='all'; trace.filterScore.value='all'; trace.filterCap.value='all'">清除</ElButton>
        </span>
      </div>
      <div class="toolbar-right">
        <ElSelect v-model="trace.filterStrategy.value" size="small" style="width:130px" clearable placeholder="全部策略">
          <ElOption value="all" label="全部策略" />
          <ElOption v-for="s in trace.strategyList.value" :key="s" :value="s" :label="strategyCN(s)" />
        </ElSelect>
        <ElSelect v-model="trace.filterResult.value" size="small" style="width:110px">
          <ElOption value="all" label="全部状态" />
          <ElOption value="bought" label="💰 成交" />
          <ElOption value="passed" label="📋 未成交" />
          <ElOption value="rejected" label="❌ 被拦" />
        </ElSelect>
        <ElSelect v-model="trace.filterScore.value" size="small" style="width:130px" clearable placeholder="评分区间">
          <ElOption value="all" label="全部评分" />
          <ElOption value="high" label="🟢 ≥70 建议" />
          <ElOption value="mid" label="🟡 50-69 观察" />
          <ElOption value="low" label="🔴 <50 不建议" />
        </ElSelect>
        <ElSelect v-model="trace.filterCap.value" size="small" style="width:120px" clearable placeholder="市值">
          <ElOption value="all" label="全部市值" />
          <ElOption value="small" label="<30亿 小盘" />
          <ElOption value="mid" label="30-100亿 中盘" />
          <ElOption value="large" label="100-300亿 大盘" />
          <ElOption value="mega" label="≥300亿 超大" />
        </ElSelect>
        <ElSelect v-model="trace.filterLayer.value" size="small" style="width:140px" clearable placeholder="全部层级">
          <ElOption v-for="l in trace.layerList" :key="l.key" :value="l.key" :label="l.label" />
        </ElSelect>
      </div>
    </div>

    <!-- 统计摘要 -->
    <div class="summary-bar">
      <div class="summary-item clickable" @click="clickFilterResult('all')" :class="{ active: !trace.filterResult.value || trace.filterResult.value === 'all' }">
        <span class="summary-label">候选</span><span class="summary-value">{{ trace.summary.value.total }}</span>
      </div>
      <div class="summary-item clickable bought" @click="clickFilterResult('bought')" :class="{ active: trace.filterResult.value === 'bought' }">
        <span class="summary-label">💰成交</span><span class="summary-value">{{ trace.summary.value.bought }}</span>
      </div>
      <div class="summary-item clickable passed" @click="clickFilterResult('passed')" :class="{ active: trace.filterResult.value === 'passed' }">
        <span class="summary-label">📋未成交</span><span class="summary-value">{{ trace.summary.value.passedNotBought }}</span>
      </div>
      <div class="summary-item clickable rejected" @click="clickFilterResult('rejected')" :class="{ active: trace.filterResult.value === 'rejected' }">
        <span class="summary-label">❌被拦</span><span class="summary-value">{{ trace.summary.value.rejected }}</span>
      </div>
      <div class="summary-item" v-if="trace.summary.value.maxLayer !== '-'">
        <span class="summary-label">最大拦截</span>
        <span class="summary-value clickable-tag" @click="clickFilterLayer(trace.summary.value.maxLayerKey || 'all')">{{ trace.summary.value.maxLayer }}</span>
      </div>
    </div>

    <!-- 综合描述 -->
    <div class="overview-card" v-if="trace.stockTraces.value.length > 0">
      <div class="ov-left">
        <div class="ov-stat">
          <span class="ov-num bought">{{ trace.summary.value.bought }}</span>
          <span class="ov-label">笔成交</span>
        </div>
        <div class="ov-stat">
          <span class="ov-num rejected">{{ trace.summary.value.rejected }}</span>
          <span class="ov-label">只被拦截</span>
        </div>
        <div class="ov-stat">
          <span class="ov-num passed">{{ trace.summary.value.passedNotBought }}</span>
          <span class="ov-label">只观察/未成交</span>
        </div>
      </div>
      <div class="ov-right">
        <div class="ov-text">
          <template v-if="trace.summary.value.bought > 0">
            今日成交<strong>{{ trace.summary.value.bought }}</strong>笔，买入均价¥{{ boughtAvgPrice }}，
            平均涨幅<strong>{{ boughtAvgPct }}%</strong>，量比{{ boughtAvgVR }}倍。
          </template>
          <template v-else-if="trace.summary.value.pipelineRejected > 0">
            今日<strong>{{ trace.summary.value.total }}</strong>只候选，全部被拦截。
            主要拦截层：<strong>{{ trace.summary.value.maxLayer }}</strong>，
            <template v-if="topRejectReasons.length > 0">
              拦截原因：{{ topRejectReasons.join('、') }}。
            </template>
          </template>
          <template v-else>
            今日暂无候选数据。
          </template>
          <template v-if="trace.summary.value.passedNotBought > 0">
            {{ trace.summary.value.passedNotBought }}只通过管道但未成交（观察信号/持仓满/时间限制）。
          </template>
        </div>
        <div class="ov-factors" v-if="topFactors.length > 0">
          <span class="ov-fact-label">候选因子均值：</span>
          <span v-for="f in topFactors" :key="f.label" class="ov-fact">
            {{ f.label }}<strong>{{ f.value }}</strong>
          </span>
        </div>
      </div>
    </div>

    <!-- 🔗 管道流程图 -->
    <ElCard shadow="never" class="flow-card">
      <template #header>
        <div class="card-header">
          <span>🔗 信号管道流程图</span>
          <div class="header-right">
            <div v-if="!flowCollapsed" class="header-legend">
              <span class="legend-item"><span class="lg pass">✓</span> 通过</span>
              <span class="legend-item"><span class="lg reject">✗</span> 拦截</span>
              <span class="legend-item"><span class="lg skip">·</span> 未到达</span>
              <span class="legend-sep">|</span>
              <span class="legend-hint">点击红格筛选 · hover看原因 · 点击行展开详情</span>
            </div>
            <template v-if="!flowCollapsed">
              <ElButton size="small" @click="flowShowAll = !flowShowAll">
                {{ flowShowAll ? '显示前10' : '显示全部' }}
                <span v-if="!flowShowAll" class="rank-count">({{ flowRows.length }}只)</span>
              </ElButton>
            </template>
            <ElButton size="small" :icon="flowCollapsed ? ArrowDown : ArrowUp" @click="flowCollapsed = !flowCollapsed" circle />
          </div>
        </div>
      </template>

      <div class="flow-table" v-if="flowRows.length > 0" v-show="!flowCollapsed">
        <!-- 表头 -->
        <div class="flow-header">
          <div class="fh-stock">股票</div>
          <div class="fh-score">评分</div>
          <div class="fh-strat">策略</div>
          <div class="fh-price">价格</div>
          <div class="fh-time">时间</div>
          <div class="fh-pipeline">
            <div v-for="layer in FLOW_LAYERS" :key="layer.key" class="fh-cell"
                 :class="{ active: flowFilterLayer === layer.key }"
                 @click="flowFilterLayer = flowFilterLayer === layer.key ? 'all' : layer.key">
              <ElTooltip :content="layer.key + ': ' + layer.desc" placement="top">
                <span class="fh-label">{{ layer.label }}</span>
              </ElTooltip>
            </div>
          </div>
          <div class="fh-result">结果</div>
          <div class="fh-reason">拦截原因</div>
        </div>

        <!-- 数据行 -->
        <template v-for="({ stock, cells }) in (flowShowAll ? flowRows : flowRows.slice(0, 10))" :key="stock.tsCode + '|' + stock.strategy">
          <div class="flow-row" :class="['row-' + stock.finalStatus, { expanded: flowExpandedRow === stock.tsCode + '|' + stock.strategy }]"
               @click="flowExpandedRow = flowExpandedRow === stock.tsCode + '|' + stock.strategy ? '' : stock.tsCode + '|' + stock.strategy">
            <div class="fr-main">
              <!-- 股票信息 -->
              <div class="fr-stock">
                <component :is="flowExpandedRow === stock.tsCode + '|' + stock.strategy ? CaretBottom : CaretRight" class="expand-icon" />
                <span class="fr-code">{{ stock.tsCode }}</span>
                <span class="fr-name">{{ stock.stockName }}</span>
              </div>
              <!-- 综合评分 -->
              <div class="fr-score">
                <ElTooltip :content="`综合评分${stock.score}分: 涨幅${stock.factors?.pct_chg?.toFixed(1)}% 量比${stock.factors?.volume_ratio?.toFixed(1)}倍 换手${stock.factors?.turnover_rate?.toFixed(1)}% 流通${((stock.factors?.circ_mv||0)/10000).toFixed(0)}亿 MA5偏离${((stock.factors?.pullback_pct||0)*100).toFixed(1)}%`" placement="top">
                  <span class="score-bar" :class="stock.score >= 70 ? 'high' : stock.score >= 50 ? 'mid' : 'low'">{{ stock.score }}</span>
                </ElTooltip>
              </div>
              <!-- 策略 -->
              <div class="fr-strat">
                <span class="strat-tag" :style="{ borderColor: strategyColor(stock.strategy), color: strategyColor(stock.strategy) }">{{ strategyCN(stock.strategyName || stock.strategy) }}</span>
              </div>
              <!-- 价格 -->
              <div class="fr-price">
                <span class="price-val">¥{{ stock.price?.toFixed(2) }}</span>
                <span class="pct-val" :class="stock.pctChg > 0 ? 'up' : 'down'">{{ stock.pctChg > 0 ? '+' : '' }}{{ stock.pctChg?.toFixed(1) }}%</span>
              </div>
              <!-- 时间 -->
              <div class="fr-time">{{ trace.fmtTime(stock.firstSeen) }}</div>
              <!-- 管道格子 -->
              <div class="fr-pipeline">
                <template v-for="(cell, ci) in cells" :key="ci">
                  <ElTooltip v-if="cell.status !== 'none'"
                    :content="cell.layerLabel + (cell.reason ? ': ' + cell.reason : (cell.status === 'pass' ? ' — 通过' : ''))"
                    placement="top" :show-after="200">
                    <div class="fr-cell" :class="cell.status"
                         @click.stop="cell.status === 'reject' && (flowFilterLayer = flowFilterLayer === cell.layerKey ? 'all' : cell.layerKey)">
                      <span v-if="cell.status === 'pass'">✓</span>
                      <span v-else-if="cell.status === 'reject'">✗</span>
                      <span v-else-if="cell.status === 'skip'">·</span>
                    </div>
                  </ElTooltip>
                  <div v-else class="fr-cell none"></div>
                </template>
              </div>
              <!-- 结果 -->
              <div class="fr-result">
                <span v-if="stock.finalStatus === 'bought'" class="result-badge bought">💰 成交</span>
                <span v-else-if="stock.executionStatus === 'pending'" class="result-badge pending">👁 观察</span>
                <span v-else-if="stock.rejectionType === 'execution'" class="result-badge exec-block">🛡 执行拦截</span>
                <span v-else class="result-badge rejected">✗ 被拦</span>
              </div>
              <!-- 拦截原因 -->
              <div class="fr-reason">
                <template v-if="stock.finalStatus === 'bought'">
                  <span class="reason-bought">¥{{ stock.boughtPrice?.toFixed(2) }} × {{ stock.boughtShares }}股 = ¥{{ (stock.boughtAmount / 10000).toFixed(2) }}万</span>
                  <span class="reason-time" v-if="stock.executionTime">{{ stock.executionTime }}</span>
                </template>
                <span v-else-if="stock.rejectionReason" class="reason-reject">{{ stock.rejectionReason }}</span>
                <span v-else-if="stock.executionDesc" class="reason-exec">{{ stock.executionDesc }}</span>
                <span v-else class="reason-dim">-</span>
              </div>
            </div>
          </div>

          <!-- 展开详情(复用排行详情面板) -->
          <div v-if="flowExpandedRow === stock.tsCode + '|' + stock.strategy" class="rank-detail">
            <div class="rd-section">
              <div class="rd-title">📊 因子详情</div>
              <div class="rd-factors">
                <div class="rd-fact" v-for="fact in getFactorDetails(stock)" :key="fact.label">
                  <span class="rd-fact-label">{{ fact.label }}</span>
                  <span class="rd-fact-value" :class="fact.cls || ''">{{ fact.value }}</span>
                  <span v-if="fact.desc" class="rd-fact-desc">{{ fact.desc }}</span>
                </div>
              </div>
            </div>
            <div class="rd-section">
              <div class="rd-title">🔗 逐层追踪</div>
              <div class="rd-pipeline">
                <div v-for="(cell, ci) in cells" :key="'p'+ci" class="rd-pipe-cell" v-if="cell.status !== 'none'">
                  <div class="rd-pipe-status" :class="cell.status">
                    {{ cell.status === 'pass' ? '✓' : cell.status === 'reject' ? '✗' : '·' }}
                  </div>
                  <div class="rd-pipe-label">{{ FLOW_LAYERS[ci]?.label || '' }}</div>
                  <div v-if="cell.reason" class="rd-pipe-reason">{{ cell.reason }}</div>
                </div>
              </div>
            </div>
            <div class="rd-section" v-if="stock.executionDesc">
              <div class="rd-title">📝 执行信息</div>
              <div class="rd-exec">{{ stock.executionDesc }}</div>
            </div>
            <div class="rd-section" v-if="stock.rejectionReason">
              <div class="rd-title">🚫 拦截原因</div>
              <div class="rd-reject">{{ stock.rejectionReason }}</div>
            </div>
            <div class="rd-section" v-if="stock.reason">
              <div class="rd-title">📋 信号描述</div>
              <div class="rd-signal">{{ stock.reason }}</div>
            </div>
          </div>
        </template>
      </div>
      <ElEmpty v-else description="暂无候选数据" :image-size="60" />
    </ElCard>

    <!-- 🏆 综合评分排行 -->
    <ElCard shadow="never" class="rank-card">
      <template #header>
        <div class="card-header">
          <span>🏆 综合评分排行</span>
          <div class="header-right">
            <span class="header-hint">🟢≥70建议关注(胜率54%) · 🟡50-69观察(胜率29-36%) · 🔴<50不建议(胜率10%)</span>
            <ElButton size="small" @click="rankShowAll = !rankShowAll">
              {{ rankShowAll ? '显示前10' : '显示全部' }}
              <span v-if="!rankShowAll" class="rank-count">({{ rankedListFull.length }}只)</span>
            </ElButton>
          </div>
        </div>
      </template>
      <div class="rank-table" v-if="rankedList.length > 0">
        <div class="rank-header">
          <div class="rh-rank">#</div>
          <div class="rh-score">评分</div>
          <div class="rh-stock">股票</div>
          <div class="rh-strat">策略</div>
          <div class="rh-pct">涨幅</div>
          <div class="rh-vr">量比</div>
          <div class="rh-tr">换手</div>
          <div class="rh-mv">流通市值</div>
          <div class="rh-ma5">MA5偏离</div>
          <div class="rh-result">状态</div>
          <div class="rh-reason">说明</div>
        </div>
        <template v-for="(stock, i) in rankedList" :key="stock.tsCode + stock.strategy">
          <div class="rank-row" :class="['row-' + stock.finalStatus, { expanded: rankExpandedRow === stock.tsCode + stock.strategy }]"
               @click="rankExpandedRow = rankExpandedRow === stock.tsCode + stock.strategy ? '' : stock.tsCode + stock.strategy">
            <div class="rr-rank" :class="i < 3 ? 'top3' : ''">{{ i + 1 }}</div>
            <div class="rr-score">
              <span class="score-bar" :class="stock.score >= 70 ? 'high' : stock.score >= 50 ? 'mid' : 'low'">{{ stock.score }}</span>
            </div>
            <div class="rr-stock">
              <span class="rr-code">{{ stock.tsCode }}</span>
              <span class="rr-name">{{ stock.stockName }}</span>
            </div>
            <div class="rr-strat">
              <span class="strat-tag" :style="{ borderColor: strategyColor(stock.strategy), color: strategyColor(stock.strategy) }">{{ strategyCN(stock.strategyName || stock.strategy) }}</span>
            </div>
            <div class="rr-pct" :class="stock.pctChg > 0 ? 'up' : 'down'">{{ stock.pctChg > 0 ? '+' : '' }}{{ stock.pctChg?.toFixed(1) }}%</div>
            <div class="rr-vr">{{ stock.factors?.volume_ratio?.toFixed(1) || '-' }}</div>
            <div class="rr-tr">{{ stock.factors?.turnover_rate?.toFixed(1) || '-' }}</div>
            <div class="rr-mv">{{ ((stock.factors?.circ_mv || 0) / 10000).toFixed(0) }}亿</div>
            <div class="rr-ma5" :class="(stock.factors?.pullback_pct || 0) < -0.03 ? 'down' : ''">{{ ((stock.factors?.pullback_pct || 0) * 100).toFixed(1) }}%</div>
            <div class="rr-result">
              <span v-if="stock.finalStatus === 'bought'" class="result-badge bought">💰 成交</span>
              <span v-else-if="stock.executionStatus === 'pending'" class="result-badge pending">👁 观察</span>
              <span v-else-if="stock.rejectionType === 'execution'" class="result-badge exec-block">🛡 拦截</span>
              <span v-else class="result-badge rejected">✗ 被拦</span>
            </div>
            <div class="rr-reason">{{ stock.rejectionReason || stock.executionDesc || stock.reason || '-' }}</div>
          </div>
          <!-- 展开详情 -->
          <div v-if="rankExpandedRow === stock.tsCode + stock.strategy" class="rank-detail">
            <div class="rd-section">
              <div class="rd-title">📊 因子详情</div>
              <div class="rd-factors">
                <div class="rd-fact" v-for="fact in getFactorDetails(stock)" :key="fact.label">
                  <span class="rd-fact-label">{{ fact.label }}</span>
                  <span class="rd-fact-value" :class="fact.cls || ''">{{ fact.value }}</span>
                  <span v-if="fact.desc" class="rd-fact-desc">{{ fact.desc }}</span>
                </div>
              </div>
            </div>
            <div class="rd-section" v-if="stock.layerResults && Object.keys(stock.layerResults).length">
              <div class="rd-title">🔗 管道通过情况</div>
              <div class="rd-pipeline">
                <div v-for="layer in PIPELINE_LAYERS" :key="layer.key" class="rd-pipe-cell">
                  <div class="rd-pipe-status" :class="getPipeStatus(stock, layer.key)">
                    {{ getPipeStatus(stock, layer.key) === 'pass' ? '✓' : getPipeStatus(stock, layer.key) === 'reject' ? '✗' : '·' }}
                  </div>
                  <div class="rd-pipe-label">{{ layer.short }}</div>
                </div>
              </div>
            </div>
            <div class="rd-section" v-if="stock.executionDesc">
              <div class="rd-title">📝 执行信息</div>
              <div class="rd-exec">{{ stock.executionDesc }}</div>
            </div>
            <div class="rd-section" v-if="stock.rejectionReason">
              <div class="rd-title">🚫 拦截原因</div>
              <div class="rd-reject">{{ stock.rejectionReason }}</div>
            </div>
            <div class="rd-section" v-if="stock.reason">
              <div class="rd-title">📋 信号描述</div>
              <div class="rd-signal">{{ stock.reason }}</div>
            </div>
          </div>
        </template>
      </div>
      <ElEmpty v-else description="暂无评分数据" :image-size="40" />
    </ElCard>

    <!-- 漏斗 + 时间线 -->
    <div class="bottom-row">
      <!-- 漏斗概览 -->
      <ElCard shadow="never" class="funnel-card">
        <template #header>
          <div class="card-header">
            <span>📊 漏斗概览</span>
            <span class="header-hint">点击筛选</span>
          </div>
        </template>
        <div class="funnel-body" v-if="trace.scanTraces.value.length > 0">
          <div v-for="row in funnelRows" :key="row.label"
               class="funnel-row" :class="[row.cls || '', { clickable: !!row.layer, active: trace.filterLayer.value === row.layer }]"
               @click="row.layer && clickFilterLayer(row.layer)">
            <div class="fn-left">
              <span class="fn-icon">{{ row.icon }}</span>
              <span class="fn-label">{{ row.label }}</span>
            </div>
            <div class="fn-right">
              <div class="fn-bar-wrap">
                <div class="fn-bar" :class="row.cls || ''" :style="{ width: row.barPct + '%' }" />
              </div>
              <span class="fn-count" :class="{ zero: row.val === 0 }">{{ row.val }}</span>
              <span class="fn-pct" v-if="row.pct">{{ row.pct }}</span>
            </div>
            <ElTooltip v-if="row.tip" :content="row.tip" placement="top">
              <span class="fn-tip">ⓘ</span>
            </ElTooltip>
          </div>
        </div>
        <ElEmpty v-else description="暂无数据" :image-size="40" />
      </ElCard>

      <!-- 时间线 -->
      <ElCard shadow="never" class="timeline-card">
        <template #header><span>🕐 时间线</span></template>
        <div class="timeline-body" v-if="timelineSlots.length > 0">
          <div v-for="slot in timelineSlots" :key="slot.label" class="tl-slot">
            <div class="tl-slot-header">
              <span class="tl-slot-tag" :class="slot.type">{{ slot.label }}</span>
              <span class="tl-slot-range">{{ slot.range }}</span>
              <span class="tl-slot-stats">
                <span class="tl-ss-cand">{{ slot.totalCand }}</span>→
                <span class="tl-ss-pass">{{ slot.totalPassed }}</span>
                <span v-if="slot.totalBuys > 0" class="tl-ss-buy">💰{{ slot.totalBuys }}</span>
              </span>
            </div>
            <div class="tl-bars">
              <div v-for="node in slot.nodes" :key="node.time" class="tl-bar-group">
                <ElTooltip :content="`${node.time} 候选${node.candidates||0} 通过${node.passed||0}${node.buys?' 成交'+node.buys:''}`" placement="top">
                  <div class="tl-bar-stack">
                    <div class="tl-bar-cand" :style="{ height: barHeight(node.candidates, slot.maxCand) + 'px' }" />
                    <div class="tl-bar-pass" :style="{ height: barHeight(node.passed, slot.maxCand) + 'px' }" />
                  </div>
                </ElTooltip>
                <span class="tl-bar-time">{{ node.time }}</span>
                <span v-if="node.buys > 0" class="tl-bar-buy">💰</span>
              </div>
            </div>
          </div>
        </div>
        <ElEmpty v-else description="暂无数据" :image-size="40" />
      </ElCard>
    </div>
  </div>
</template>

<style scoped lang="scss">
.signal-trace-page {
  padding: 12px 16px; display: flex; flex-direction: column; gap: 10px;
  min-height: 100%; background: var(--bg-base);
}
.toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
  .toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 8px; }
  .toolbar-hint { font-size: 12px; color: var(--text-tertiary); }
}
.summary-bar {
  display: flex; gap: 16px; padding: 8px 16px;
  background: var(--bg-elevated); border-radius: 8px; border: 1px solid var(--border-default);
  .summary-item {
    display: flex; flex-direction: column; align-items: center; gap: 1px;
    .summary-label { font-size: 11px; color: var(--text-tertiary); }
    .summary-value { font-size: 20px; font-weight: 700; color: var(--text-primary); }
    &.bought .summary-value { color: var(--el-color-success); }
    &.passed .summary-value { color: var(--el-color-warning); }
    &.rejected .summary-value { color: var(--el-color-danger); }
    &.clickable { cursor: pointer; border-radius: 6px; padding: 2px 8px; transition: background 0.15s; &:hover { background: var(--bg-hover); } }
    &.clickable.active { background: var(--el-color-primary-light-9); outline: 2px solid var(--el-color-primary-light-7); }
  }
  .clickable-tag { cursor: pointer; &:hover { text-decoration: underline; } }
}
.card-header {
  display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600;
  .header-right { display: flex; align-items: center; gap: 10px; }
  .header-hint { font-size: 11px; color: var(--text-tertiary); font-weight: 400; }
  .header-legend { display: flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 400; color: var(--text-tertiary); }
  .legend-item { display: flex; align-items: center; gap: 3px; }
  .legend-sep { color: var(--border-default); }
  .legend-hint { color: var(--text-quaternary); }
  .lg {
    display: inline-flex; align-items: center; justify-content: center;
    width: 16px; height: 16px; border-radius: 3px; font-size: 10px; font-weight: 700;
    &.pass { background: rgba(103, 194, 58, 0.15); color: var(--el-color-success); }
    &.reject { background: rgba(245, 108, 108, 0.18); color: var(--el-color-danger); }
    &.skip { background: var(--bg-muted); color: var(--text-quaternary); }
  }
}

// ====== 综合描述 ======
.overview-card {
  display: flex; gap: 16px; padding: 12px 16px;
  background: var(--bg-elevated); border-radius: 8px; border: 1px solid var(--border-default);
  .ov-left {
    display: flex; gap: 12px; align-items: center;
    .ov-stat { display: flex; flex-direction: column; align-items: center; gap: 1px;
      .ov-num { font-size: 22px; font-weight: 700;
        &.bought { color: var(--el-color-success); }
        &.rejected { color: var(--el-color-danger); }
        &.passed { color: #e6a23c; }
      }
      .ov-label { font-size: 10px; color: var(--text-tertiary); }
    }
  }
  .ov-right {
    flex: 1; display: flex; flex-direction: column; gap: 6px;
    .ov-text { font-size: 12px; color: var(--text-secondary); line-height: 1.6;
      strong { color: var(--text-primary); font-weight: 600; }
    }
    .ov-factors {
      display: flex; gap: 12px; flex-wrap: wrap;
      .ov-fact-label { font-size: 11px; color: var(--text-tertiary); }
      .ov-fact {
        font-size: 11px; color: var(--text-secondary);
        strong { color: var(--text-primary); font-weight: 600; margin-left: 2px; }
      }
    }
  }
}

// ====== 流程图 ======
.flow-card { :deep(.el-card__body) { padding: 0; overflow: auto; max-height: 65vh; } }
.flow-table { width: 100%; font-size: 12px; }

.flow-header {
  display: flex; align-items: center; padding: 8px 12px;
  background: var(--bg-muted); border-bottom: 2px solid var(--border-default);
  position: sticky; top: 0; z-index: 2;
  .fh-stock { width: 120px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); }
  .fh-score { width: 36px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); text-align: center; }
  .fh-strat { width: 64px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); text-align: center; }
  .fh-price { width: 80px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); text-align: right; }
  .fh-time { width: 40px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); text-align: center; }
  .fh-pipeline { display: flex; gap: 0; flex: 1; }
  .fh-cell {
    flex: 1; min-width: 52px; text-align: center; padding: 4px 2px;
    border-radius: 4px; cursor: pointer; transition: background 0.15s;
    &:hover { background: var(--bg-hover); }
    &.active { background: var(--el-color-primary-light-9); outline: 1.5px solid var(--el-color-primary-light-5); }
    .fh-label { font-weight: 600; font-size: 10px; color: var(--text-secondary); letter-spacing: 0.3px; white-space: nowrap; }
  }
  .fh-result { width: 68px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); text-align: center; }
  .fh-reason { width: 200px; flex-shrink: 0; font-weight: 600; color: var(--text-secondary); }
}

.flow-row {
  border-bottom: 1px solid var(--border-lighter); transition: background 0.12s;
  &:hover { background: var(--bg-hover); }
  &.row-bought { border-left: 3px solid var(--el-color-success); background: rgba(103, 194, 58, 0.03); }
  &.row-passed { border-left: 3px solid var(--el-color-warning); }
  &.row-rejected { border-left: 3px solid var(--el-color-danger); }
}

.fr-main {
  display: flex; align-items: center; padding: 5px 12px; min-height: 38px; cursor: pointer;
}

.fr-stock {
  width: 120px; flex-shrink: 0; display: flex; align-items: center; gap: 3px;
  .expand-icon { width: 12px; height: 12px; color: var(--text-quaternary); flex-shrink: 0; }
  .fr-code { font-family: monospace; font-size: 11px; color: var(--text-primary); font-weight: 600; }
  .fr-name { font-size: 11px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}

.fr-score { width: 36px; flex-shrink: 0; text-align: center; }
.score-bar {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 28px; height: 20px; border-radius: 10px;
  font-size: 11px; font-weight: 700; padding: 0 5px;
  &.high { background: rgba(103, 194, 58, 0.18); color: var(--el-color-success); }
  &.mid { background: rgba(230, 162, 60, 0.15); color: #e6a23c; }
  &.low { background: rgba(245, 108, 108, 0.12); color: var(--el-color-danger); }
}

.fr-strat { width: 64px; flex-shrink: 0; text-align: center; }
.strat-tag {
  font-size: 10px; padding: 1px 4px; border-radius: 3px;
  border: 1px solid; font-weight: 500;
}

.fr-price {
  width: 80px; flex-shrink: 0; text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 0;
  .price-val { font-family: monospace; font-size: 11px; color: var(--text-primary); }
  .pct-val { font-family: monospace; font-size: 10px; font-weight: 600; &.up { color: #f56c6c; } &.down { color: #67c23a; } }
}

.fr-time { width: 40px; flex-shrink: 0; text-align: center; font-size: 11px; color: var(--text-tertiary); font-family: monospace; }

.fr-pipeline { display: flex; gap: 0; flex: 1; align-items: center; }

.fr-cell {
  flex: 1; min-width: 52px; height: 28px; display: flex; align-items: center; justify-content: center;
  border-radius: 4px; font-size: 14px; font-weight: 700; cursor: default; transition: all 0.12s;
  position: relative;
  // 管道连接线: 每个格子左侧画一条线连接前一个格子
  &::before {
    content: ''; position: absolute; left: -2px; top: 50%;
    width: 4px; height: 2px; background: var(--border-lighter);
  }
  &:first-child::before { display: none; }
  &.pass {
    background: rgba(103, 194, 58, 0.15); color: var(--el-color-success);
    border: 1px solid rgba(103, 194, 58, 0.25);
    &::before { background: rgba(103, 194, 58, 0.3); }
  }
  &.reject {
    background: rgba(245, 108, 108, 0.18); color: var(--el-color-danger); cursor: pointer;
    border: 1px solid rgba(245, 108, 108, 0.35);
    &::before { background: var(--border-lighter); }
    &:hover { background: rgba(245, 108, 108, 0.35); transform: scale(1.1); box-shadow: 0 0 8px rgba(245,108,108,0.3); }
  }
  &.skip {
    background: var(--bg-muted); color: var(--text-quaternary);
    border: 1px dashed var(--border-lighter);
    &::before { background: var(--border-lighter); }
  }
  &.none {
    background: transparent; color: transparent; border: none;
    &::before { display: none; }
  }
}

.fr-result { width: 68px; flex-shrink: 0; text-align: center; }
.result-badge {
  font-size: 10px; padding: 2px 5px; border-radius: 4px; font-weight: 600; white-space: nowrap;
  &.bought { background: rgba(103, 194, 58, 0.12); color: var(--el-color-success); }
  &.pending { background: rgba(144, 147, 153, 0.12); color: #909399; }
  &.exec-block { background: rgba(230, 162, 60, 0.12); color: #e6a23c; }
  &.rejected { background: rgba(245, 108, 108, 0.12); color: var(--el-color-danger); }
}

.fr-reason {
  width: 200px; flex-shrink: 0; padding: 0 6px; display: flex; flex-direction: column; gap: 1px;
  .reason-bought { font-size: 11px; color: var(--el-color-success); font-weight: 600; }
  .reason-time { font-size: 10px; color: var(--text-quaternary); }
  .reason-reject { font-size: 11px; color: var(--el-color-danger); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .reason-exec { font-size: 11px; color: var(--el-color-warning); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .reason-dim { font-size: 11px; color: var(--text-quaternary); }
}

// ====== 评分排行 ======
.rank-card {
  :deep(.el-card__body) { padding: 0; overflow: auto; max-height: 40vh; }
}
.rank-table { width: 100%; font-size: 12px; }
.rank-header {
  display: flex; align-items: center; padding: 6px 12px;
  background: var(--bg-muted); border-bottom: 2px solid var(--border-default);
  position: sticky; top: 0; z-index: 2;
  font-weight: 600; color: var(--text-secondary); font-size: 11px;
  .rh-rank { width: 28px; flex-shrink: 0; text-align: center; }
  .rh-score { width: 42px; flex-shrink: 0; text-align: center; }
  .rh-stock { width: 130px; flex-shrink: 0; }
  .rh-strat { width: 64px; flex-shrink: 0; text-align: center; }
  .rh-pct { width: 55px; flex-shrink: 0; text-align: right; }
  .rh-vr { width: 42px; flex-shrink: 0; text-align: right; }
  .rh-tr { width: 42px; flex-shrink: 0; text-align: right; }
  .rh-mv { width: 55px; flex-shrink: 0; text-align: right; }
  .rh-ma5 { width: 55px; flex-shrink: 0; text-align: right; }
  .rh-result { width: 60px; flex-shrink: 0; text-align: center; }
  .rh-reason { flex: 1; min-width: 120px; }
}
.rank-row {
  display: flex; align-items: center; padding: 5px 12px;
  border-bottom: 1px solid var(--border-lighter); transition: background 0.12s;
  &:hover { background: var(--bg-hover); }
  &.row-bought { border-left: 3px solid var(--el-color-success); background: rgba(103, 194, 58, 0.03); }
  &.row-passed { border-left: 3px solid #e6a23c; }
  &.row-rejected { border-left: 3px solid var(--el-color-danger); }
}
.rr-rank {
  width: 28px; flex-shrink: 0; text-align: center; font-size: 12px; font-weight: 700;
  color: var(--text-tertiary);
  &.top3 { color: #e6a23c; font-size: 14px; }
}
.rr-score { width: 42px; flex-shrink: 0; text-align: center; }
.rr-stock {
  width: 130px; flex-shrink: 0; display: flex; align-items: center; gap: 3px;
  .rr-code { font-family: monospace; font-size: 11px; color: var(--text-primary); font-weight: 600; }
  .rr-name { font-size: 11px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.rr-strat { width: 64px; flex-shrink: 0; text-align: center; }
.rr-pct {
  width: 55px; flex-shrink: 0; text-align: right; font-family: monospace; font-size: 11px; font-weight: 600;
  &.up { color: #f56c6c; } &.down { color: #67c23a; }
}
.rr-vr, .rr-tr, .rr-mv {
  font-family: monospace; font-size: 11px; text-align: right; color: var(--text-secondary);
}
.rr-vr { width: 42px; flex-shrink: 0; }
.rr-tr { width: 42px; flex-shrink: 0; }
.rr-mv { width: 55px; flex-shrink: 0; }
.rr-ma5 {
  width: 55px; flex-shrink: 0; text-align: right; font-family: monospace; font-size: 11px;
  color: var(--text-secondary);
  &.down { color: var(--el-color-danger); }
}
.rr-result { width: 60px; flex-shrink: 0; text-align: center; }
.rr-reason {
  flex: 1; min-width: 120px; font-size: 11px; color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

// 展开详情
.rank-row {
  cursor: pointer;
  &.expanded { background: var(--bg-hover); border-bottom-color: transparent; }
}
.rank-detail {
  background: var(--bg-elevated); border-bottom: 1px solid var(--border-default);
  padding: 12px 16px; display: flex; flex-direction: column; gap: 12px;
}
.rd-section {
  .rd-title { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
}
.rd-factors {
  display: flex; flex-wrap: wrap; gap: 8px 16px;
}
.rd-fact {
  display: flex; align-items: center; gap: 4px; font-size: 11px;
  .rd-fact-label { color: var(--text-tertiary); min-width: 48px; }
  .rd-fact-value {
    font-family: monospace; font-weight: 600; color: var(--text-primary);
    &.up { color: #f56c6c; }
    &.down { color: #67c23a; }
    &.warn { color: #e6a23c; }
  }
  .rd-fact-desc { color: #e6a23c; font-size: 10px; }
}
.rd-pipeline {
  display: flex; gap: 4px;
}
.rd-pipe-cell {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  .rd-pipe-status {
    width: 22px; height: 22px; border-radius: 4px; display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700;
    &.pass { background: rgba(103, 194, 58, 0.15); color: var(--el-color-success); }
    &.reject { background: rgba(245, 108, 108, 0.18); color: var(--el-color-danger); }
    &.skip { background: var(--bg-muted); color: var(--text-quaternary); }
  }
  .rd-pipe-label { font-size: 10px; color: var(--text-tertiary); }
  .rd-pipe-reason { font-size: 10px; color: var(--text-quaternary); max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.rd-exec { font-size: 12px; color: var(--el-color-success); font-weight: 600; }
.rd-reject { font-size: 12px; color: var(--el-color-danger); }
.rd-signal { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.rank-count { font-weight: 400; color: var(--text-tertiary); margin-left: 2px; }

// ====== 底部: 漏斗 + 时间线 ======
.bottom-row { display: flex; gap: 10px; align-items: stretch; }

// --- 漏斗 ---
.funnel-card {
  width: 260px; min-width: 260px;
  :deep(.el-card__body) { padding: 8px 12px; }
}
.funnel-body { display: flex; flex-direction: column; gap: 4px; }
.funnel-row {
  display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 6px;
  font-size: 12px; background: var(--bg-muted); transition: all 0.15s;
  &.clickable { cursor: pointer; &:hover { background: var(--bg-hover); transform: translateX(2px); } }
  &.clickable.active { background: var(--el-color-primary-light-9); outline: 1.5px solid var(--el-color-primary-light-5); }
  &.total { background: rgba(64, 158, 255, 0.06); }
  &.passed { background: rgba(103, 194, 58, 0.05); }
  &.final { background: rgba(103, 194, 58, 0.10); }
  .fn-left {
    display: flex; align-items: center; gap: 4px; width: 80px; flex-shrink: 0;
    .fn-icon { font-size: 13px; }
    .fn-label { font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  }
  .fn-right {
    flex: 1; display: flex; align-items: center; gap: 6px;
    .fn-bar-wrap {
      flex: 1; height: 6px; border-radius: 3px; background: var(--border-lighter); overflow: hidden;
    }
    .fn-bar {
      height: 100%; border-radius: 3px; transition: width 0.3s ease;
      &.total { background: linear-gradient(90deg, #409eff, #79bbff); }
      &.passed, &.final { background: linear-gradient(90deg, #67c23a, #95d475); }
      background: linear-gradient(90deg, #f56c6c, #fab6b6);
    }
    .fn-count {
      font-weight: 700; font-size: 12px; color: var(--text-primary); min-width: 24px; text-align: right;
      &.zero { color: var(--text-quaternary); font-weight: 400; }
    }
    .fn-pct { font-size: 10px; color: var(--text-tertiary); min-width: 28px; }
  }
  .fn-tip {
    font-size: 10px; color: var(--text-quaternary); cursor: help;
    width: 14px; height: 14px; display: inline-flex; align-items: center; justify-content: center;
    border-radius: 50%; border: 1px solid var(--border-default);
  }
}

// --- 时间线 ---
.timeline-card {
  flex: 1; min-width: 0;
  :deep(.el-card__body) { padding: 10px 16px; }
}
.timeline-body { display: flex; flex-direction: column; gap: 12px; }
.tl-slot {
  .tl-slot-header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
    .tl-slot-tag {
      font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
      &.premarket { background: rgba(230, 162, 60, 0.12); color: #e6a23c; }
      &.early { background: rgba(64, 158, 255, 0.12); color: #409eff; }
      &.lunch { background: rgba(144, 147, 153, 0.10); color: #909399; }
      &.afternoon { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
    }
    .tl-slot-range { font-size: 10px; color: var(--text-quaternary); font-family: monospace; }
    .tl-slot-stats { font-size: 11px; margin-left: auto;
      .tl-ss-cand { color: var(--text-secondary); }
      .tl-ss-pass { color: var(--el-color-success); font-weight: 600; }
      .tl-ss-buy { color: var(--el-color-success); font-weight: 700; margin-left: 4px; }
    }
  }
  .tl-bars {
    display: flex; gap: 3px; align-items: flex-end; padding-left: 4px;
    border-left: 2px solid var(--border-lighter); padding-bottom: 2px;
  }
  .tl-bar-group {
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    min-width: 32px;
  }
  .tl-bar-stack {
    display: flex; flex-direction: column-reverse; gap: 0;
    cursor: default;
  }
  .tl-bar-cand {
    width: 20px; border-radius: 3px 3px 0 0;
    background: linear-gradient(180deg, rgba(64, 158, 255, 0.25), rgba(64, 158, 255, 0.10));
    border: 1px solid rgba(64, 158, 255, 0.20); border-bottom: none;
    min-height: 2px; transition: height 0.2s;
  }
  .tl-bar-pass {
    width: 20px; border-radius: 0 0 3px 3px;
    background: linear-gradient(180deg, rgba(103, 194, 58, 0.35), rgba(103, 194, 58, 0.15));
    border: 1px solid rgba(103, 194, 58, 0.25); border-top: none;
    min-height: 2px; transition: height 0.2s;
  }
  .tl-bar-time { font-size: 9px; color: var(--text-quaternary); font-family: monospace; }
  .tl-bar-buy { font-size: 8px; }
}
</style>
