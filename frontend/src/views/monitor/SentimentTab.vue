<script setup lang="ts">
/**
 * SentimentTab — 情绪分析Tab
 * v2.9.92: 日内改为多指标展示(涨跌停柱状图+涨跌比+情绪score)
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const m = useScannerMonitorInject()
const {
  sentimentMode, sentimentDate, hoveredPoint, sentimentTimeline,
  sentimentTrades, displayTimeline, isIntradayFallback,
  xAxisLabels, sentimentMatrix, sentimentRecommendations, sentimentLoading,
  sentimentLive, phaseGuide, downgradeRules, phaseColors, sentimentAdvice,
  fetchSentimentData, strategyCN,
} = m

// ===== 日内涨跌停柱状图 =====
const intradayBarData = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  if (!tl.length) return { bars: [], maxVal: 10, svgWidth: 100 }
  const maxVal = Math.max(...tl.map((p: Record<string, any>) => Math.max(p.limit_up || 0, p.limit_down || 0)), 10)
  const barW = Math.max(8, Math.min(24, 800 / tl.length))
  const gap = Math.max(2, barW * 0.2)
  const svgWidth = tl.length * (barW + gap)
  const bars = tl.map((p: Record<string, any>, i: number) => ({
    x: i * (barW + gap) + gap / 2,
    limitUpH: ((p.limit_up || 0) / maxVal) * 90,
    limitDownH: ((p.limit_down || 0) / maxVal) * 90,
    score: p.score,
    barW,
  }))
  return { bars, maxVal, svgWidth }
})

// ===== 日内涨跌比+score =====
const intradayRatioData = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  if (!tl.length) return { points: '', fillPoints: '', svgWidth: 100, scorePoints: '' }
  const barW = Math.max(8, Math.min(24, 800 / tl.length))
  const gap = Math.max(2, barW * 0.2)
  const svgWidth = tl.length * (barW + gap)
  let cumX = 0
  const pts: string[] = []
  const sPts: string[] = []
  tl.forEach((p: Record<string, any>, i: number) => {
    const x = i * (barW + gap) + gap / 2 + barW / 2
    cumX = x
    const ratio = p.limit_ratio ?? 0.5
    pts.push(`${x},${100 - ratio * 100}`)
    sPts.push(`${x},${100 - (p.score || 0)}`)
  })
  const first = `${gap / 2 + barW / 2},100`
  const last = `${cumX},100`
  return { points: pts.join(' '), fillPoints: [first, ...pts, last].join(' '), svgWidth, scorePoints: sPts.join(' ') }
})

// ===== 日线 =====
const dailyScorePoints = computed(() => {
  const tl = (displayTimeline.value as Array<Record<string, any>>).filter((p: Record<string, any>) => p.score != null)
  return tl.map((p: Record<string, any>, i: number) => `${i * 20},${100 - (p.score || 0)}`).join(' ')
})
const scoredTimeline = computed(() => (displayTimeline.value as Array<Record<string, any>>).filter((p: Record<string, any>) => p.score != null))
const dailyTradeMarkers = computed(() =>
  (sentimentTrades.value as Array<Record<string, any>>).map((t: Record<string, any>) => ({ ...t, leftPct: (() => { const tl = displayTimeline.value as Array<Record<string, any>>; const idx = tl.findIndex((p: Record<string, any>) => (p.date as string) >= (t.date as string)); return tl.length ? idx / Math.max(tl.length - 1, 1) * 100 : 50 })() }))
)
function matrixTotal(periods: Record<string, any>): number { return Object.values(periods).reduce((s: number, v: any) => s + ((v as Record<string, any>).count as number || 0), 0) }
function dailyDotBottom(p: Record<string, any>): number { return (p.score || 0) as number }

// 【v2.9.96h】盘中计算日志
const liveLogs = ref<Array<Record<string, any>>>([])
const liveLogsLoading = ref(false)
async function fetchLiveLogs() {
  liveLogsLoading.value = true
  try {
    const r = await api.get('/scanner/sentiment-live-log?limit=50', { timeout: 5000 })
    const p = parseResponse(r)
    if (p.success) liveLogs.value = (p.data?.logs || []) as Array<Record<string, any>>
  } catch { /* ignore */ }
  finally { liveLogsLoading.value = false }
}
function scoreColor(s: number): string {
  if (s >= 70) return '#f56c6c'
  if (s >= 55) return '#409eff'
  if (s >= 40) return '#e6a23c'
  return '#67c23a'
}
let liveLogTimer: number | undefined
onMounted(() => { fetchLiveLogs(); liveLogTimer = window.setInterval(fetchLiveLogs, 15000) })
onUnmounted(() => { if (liveLogTimer) clearInterval(liveLogTimer) })
function dailyHoverLeft(): number { const tl = displayTimeline.value as Array<Record<string, any>>; const hp = hoveredPoint.value as Record<string, any> | null; if (!hp) return 0; const idx = tl.findIndex((p: Record<string, any>) => p === hp); return Math.min(idx / Math.max(tl.length - 1, 1) * 100, 75) }
function dailyHoverBottom(): number { const hp = hoveredPoint.value as Record<string, any> | null; return Math.min(((hp?.score || 30) as number) + 8, 85) }
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <div class="review-header">
        <button :class="['review-tab', sentimentMode === 'intraday' ? 'active' : '']" @click="sentimentMode = 'intraday'; fetchSentimentData()">📈 日内</button>
        <button :class="['review-tab', sentimentMode === 'daily' ? 'active' : '']" @click="sentimentMode = 'daily'; fetchSentimentData()">📊 日线</button>
        <button :class="['review-tab', sentimentMode === 'weekly' ? 'active' : '']" @click="sentimentMode = 'weekly'; fetchSentimentData()">📅 周线</button>
        <button :class="['review-tab', sentimentMode === 'monthly' ? 'active' : '']" @click="sentimentMode = 'monthly'; fetchSentimentData()">📆 月线</button>
        <UnifiedDateBar @change="(_d: string) => { sentimentDate = _d; fetchSentimentData() }" />
        <ElButton size="small" @click="fetchSentimentData" :loading="sentimentLoading">🔄</ElButton>
      </div>

      <div class="st">📈 情绪时间线
        <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary);margin-left:8px">
          {{ isIntradayFallback ? '（无日内数据，显示日线参考）' : `（${displayTimeline.length}个数据点）` }}
        </span>
      </div>
      <div v-if="sentimentMode === 'intraday' && !sentimentTimeline.length && isIntradayFallback" class="empty" style="padding:10px 0;text-align:center;font-size:12px;color:var(--text-tertiary)">
        📡 当前日期无日内扫描数据（非交易日或Scanner未运行），上方显示日线数据供参考。
      </div>
      <div v-else-if="!displayTimeline.length" class="empty" style="padding:12px 0">暂无情绪数据</div>

      <!-- ====== 日内: 多指标分区 ====== -->
      <template v-else-if="sentimentMode === 'intraday' && !isIntradayFallback">
        <!-- 涨停/跌停柱状图 -->
        <div class="intraday-panel">
          <div class="ip-title">🔴 涨停 / 🔵 跌停 <span class="ip-sub">(5min采样)</span></div>
          <div class="ip-chart" style="height:170px">
            <div class="sc-y-axis"><span>{{ intradayBarData.maxVal }}</span><span>{{ Math.round(intradayBarData.maxVal / 2) }}</span><span>0</span></div>
            <div class="sc-chart-body">
              <svg class="sc-svg" :viewBox="`0 0 ${intradayBarData.svgWidth} 100`" preserveAspectRatio="none">
                <line x1="0" y1="50" :x2="intradayBarData.svgWidth" y2="50" stroke="var(--border-default)" stroke-width="0.3" stroke-dasharray="2,2" />
                <g v-for="(bar, i) in intradayBarData.bars" :key="'u'+i"><rect :x="bar.x" :y="100 - bar.limitUpH" :width="bar.barW" :height="bar.limitUpH" fill="rgba(245,108,108,0.65)" rx="1" /></g>
                <g v-for="(bar, i) in intradayBarData.bars" :key="'d'+i"><rect :x="bar.x + bar.barW * 0.35" :y="100 - bar.limitDownH" :width="bar.barW * 0.55" :height="bar.limitDownH" fill="rgba(64,158,255,0.55)" rx="1" /></g>
              </svg>
              <div style="position:absolute;top:4px;right:8px;font-size:10px;z-index:5"><span style="color:#f56c6c">■ 涨停</span> <span style="color:#409eff;margin-left:6px">■ 跌停</span></div>
            </div>
          </div>
          <div class="sc-x-labels"><span v-for="(lbl, i) in xAxisLabels" :key="i">{{ lbl }}</span></div>
        </div>

        <!-- 涨跌比 + Score -->
        <div class="intraday-panel" style="margin-top:8px">
          <div class="ip-title">📊 涨跌停比 <span style="color:var(--el-color-primary);margin-left:6px">--- Score</span> <span class="ip-sub">(&gt;50%偏强)</span></div>
          <div class="ip-chart" style="height:110px">
            <div class="sc-y-axis"><span>100%</span><span>50%</span><span>0%</span></div>
            <div class="sc-chart-body">
              <div style="position:absolute;top:50%;left:0;right:0;height:1px;background:var(--border-default);z-index:2"></div>
              <div style="position:absolute;top:0;height:50%;width:100%;background:rgba(245,108,108,0.04);z-index:1"></div>
              <div style="position:absolute;top:50%;height:50%;width:100%;background:rgba(103,194,58,0.04);z-index:1"></div>
              <svg class="sc-svg" :viewBox="`0 0 ${intradayRatioData.svgWidth} 100`" preserveAspectRatio="none">
                <polygon :points="intradayRatioData.fillPoints" fill="rgba(64,158,255,0.12)" />
                <polyline :points="intradayRatioData.points" fill="none" stroke="#409eff" stroke-width="1.5" />
                <polyline :points="intradayRatioData.scorePoints" fill="none" stroke="var(--el-color-primary)" stroke-width="1" stroke-dasharray="3,3" opacity="0.5" />
              </svg>
              <div style="position:absolute;top:4px;right:8px;font-size:10px;z-index:5"><span style="color:#409eff">— 涨跌比</span> <span style="color:var(--el-color-primary);margin-left:6px">--- Score</span></div>
            </div>
          </div>
          <div class="sc-x-labels"><span v-for="(lbl, i) in xAxisLabels" :key="i">{{ lbl }}</span></div>
        </div>
      </template>

      <!-- ====== 日线/周线/月线 ====== -->
      <div v-else class="sentiment-chart">
        <div class="sc-chart-row">
          <div class="sc-y-axis"><span>100</span><span>70</span><span>55</span><span>40</span><span>0</span></div>
          <div class="sc-chart-body">
            <div class="sc-band" style="height:30%;background:rgba(245,108,108,0.08)"></div>
            <div class="sc-band" style="height:15%;background:rgba(64,158,255,0.08)"></div>
            <div class="sc-band" style="height:15%;background:rgba(230,162,60,0.08)"></div>
            <div class="sc-band" style="height:40%;background:rgba(103,194,58,0.08)"></div>
            <svg class="sc-svg" :viewBox="`0 0 ${Math.max(scoredTimeline.length - 1, 1) * 20} 100`" preserveAspectRatio="none">
              <polyline :points="dailyScorePoints" fill="none" stroke="var(--el-color-primary)" stroke-width="1.5" />
            </svg>
            <template v-for="(p, i) in (displayTimeline as any[])" :key="i">
              <div v-if="p.score != null" class="sc-dot" :style="{ left: `${i / Math.max((displayTimeline as any[]).length - 1, 1) * 100}%`, bottom: `${dailyDotBottom(p)}%` }" :class="p.period === '高潮' ? 'hot' : p.period === '冰点' ? 'cold' : p.missing_data ? 'missing' : ''" @mouseenter="hoveredPoint = p" @mouseleave="hoveredPoint = null"></div>
            </template>
            <div v-if="hoveredPoint" class="sc-hover-card" :style="{ left: `${dailyHoverLeft()}%`, bottom: `${dailyHoverBottom()}%` }">
              <div class="sc-hover-date">{{ hoveredPoint.date }}</div>
              <div class="sc-hover-score" :class="hoveredPoint.period === '高潮' ? 'hot' : hoveredPoint.period === '冰点' ? 'cold' : ''">{{ hoveredPoint.score?.toFixed(1) }} {{ hoveredPoint.period }}</div>
              <div class="sc-hover-detail">涨停{{ hoveredPoint.limit_up || 0 }} 跌停{{ hoveredPoint.limit_down || 0 }}</div>
            </div>
          </div>
        </div>
        <div class="sc-x-labels"><span v-for="(lbl, i) in xAxisLabels" :key="i">{{ lbl }}</span></div>
      </div>

      <!-- 当前状态+市场全景+得分拆解 -->
      <div class="sentiment-3col" style="margin-top:12px">
        <div class="sentiment-panel"><div class="st">🔄 当前状态</div>
          <div v-if="sentimentLive" class="sl-content">
            <div class="sl-gauge"><div class="sl-gauge-bar"><div class="sl-gauge-fill" :style="{ width: (sentimentLive?.score || 0) + '%', background: (sentimentLive?.score || 0) >= 70 ? '#f56c6c' : (sentimentLive?.score || 0) >= 55 ? '#409eff' : (sentimentLive?.score || 0) >= 40 ? '#e6a23c' : '#67c23a' }"></div></div><div class="sl-score-labels"><span>0 冰点</span><span>40 震荡</span><span>55 分化</span><span>70 高潮</span><span>100</span></div></div>
            <div class="sl-row"><span>情绪分</span><span class="sl-val" :style="{ color: (sentimentLive?.score || 0) >= 70 ? '#f56c6c' : (sentimentLive?.score || 0) >= 55 ? '#409eff' : (sentimentLive?.score || 0) >= 40 ? '#e6a23c' : '#67c23a' }">{{ (sentimentLive?.score || 0)?.toFixed(0) }}</span></div>
            <div class="sl-row"><span>周期</span><span class="sl-val">{{ (sentimentLive?.period_label || "") }}</span></div>
            <div class="sl-row"><span>仓位系数</span><span class="sl-val">{{ ((sentimentLive?.position_ratio || 0) * 100).toFixed(0) }}%</span></div>
            <div class="sl-row"><span>允许开仓</span><span class="sl-val" :style="{ color: sentimentLive?.can_open !== false ? '#67c23a' : '#f56c6c' }">{{ sentimentLive?.can_open !== false ? '✅ 是' : '❌ 否' }}</span></div>
          </div><div v-else class="empty" style="padding:8px 0">无数据</div></div>
        <div class="sentiment-panel"><div class="st">📊 市场全景</div>
          <div v-if="sentimentLive" class="sl-content">
            <div class="sl-row"><span>涨停</span><span class="sl-val up">{{ (sentimentLive?.limit_up_count || 0) }}</span></div>
            <div class="sl-row"><span>跌停</span><span class="sl-val down">{{ (sentimentLive?.limit_down_count || 0) }}</span></div>
            <div class="sl-row"><span>炸板率</span><span class="sl-val" :style="{ color: (sentimentLive?.broken_rate || 0) > 30 ? '#f56c6c' : 'var(--text-primary)' }">{{ (sentimentLive?.broken_rate || 0).toFixed(1) }}%</span></div>
            <div class="sl-row"><span>炸板数</span><span class="sl-val">{{ (sentimentLive?.broken_count || 0) }}</span></div>
          </div><div v-else class="empty" style="padding:8px 0">无数据</div></div>
        <div class="sentiment-panel"><div class="st">🧮 得分拆解</div>
          <div v-if="sentimentLive" class="sl-content">
            <div class="sl-row"><span>涨停贡献</span><span class="sl-val">{{ Math.min(30, (sentimentLive?.limit_up_count || 0)) }}/30</span></div>
            <div class="sl-row"><span>跌停扣分</span><span class="sl-val">{{ Math.max(0, 20 - (sentimentLive?.limit_down_count || 0) * 2) }}/20</span></div>
            <div class="sl-row"><span>连板高度</span><span class="sl-val">{{ Math.min(20, (sentimentLive?.max_continue || 0) * 2) }}/20</span></div>
            <div class="sl-row"><span>涨跌比</span><span class="sl-val">{{ Math.min(15, Math.round((sentimentLive?.up_down_ratio || 0) * 15)) }}/15</span></div>
            <div class="sl-row"><span>涨停溢价</span><span class="sl-val">{{ Math.min(15, Math.max(0, Math.round(sentimentLive?.zt_premium || 0))) }}/15</span></div>
            <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-default)"><div style="font-size:10px;color:var(--text-quaternary);line-height:1.4">满分100 = 涨停30 + 跌停20 + 连板20 + 涨跌比15 + 溢价15<br>≥70高潮 | 55-70分化 | 40-55震荡 | &lt;40冰点</div></div>
          </div><div v-else class="empty" style="padding:8px 0">无数据</div></div>
      </div>

      <!-- 【v2.9.96h】盘中实时计算日志 -->
      <div class="st" style="margin-top:12px;display:flex;align-items:center;gap:8px">
        <span>📜 盘中计算日志</span>
        <span style="font-size:10px;color:var(--text-quaternary);font-weight:normal">(追踪每次情绪快照变化, 最近 {{ liveLogs.length }} 条)</span>
        <ElButton size="small" @click="fetchLiveLogs" :loading="liveLogsLoading" style="font-size:10px;padding:2px 6px;margin-left:auto">🔄</ElButton>
      </div>
      <div v-if="liveLogs.length" class="live-log-wrap">
        <table class="live-log-tbl">
          <thead><tr><th>时间</th><th>得分</th><th>周期</th><th>仓位</th><th>涨停</th><th>跌停</th><th>连板</th><th>涨跌比</th><th>溢价</th><th>动量</th><th>炸板</th><th>7维拆解</th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in liveLogs" :key="l.time + i" :class="i === 0 ? 'live-log-latest' : ''">
              <td class="ll-time">{{ l.time }}</td>
              <td class="ll-score" :style="{ color: scoreColor(l.score), fontWeight: 'bold' }">{{ Number(l.score).toFixed(1) }}</td>
              <td><span class="ll-phase" :style="{ color: phaseColors[l.phase_label] || '#888' }">{{ l.phase_label }}</span></td>
              <td>{{ ((l.position_ratio || 0) * 100).toFixed(0) }}%</td>
              <td class="up">{{ l.limit_up }}</td>
              <td class="down">{{ l.limit_down }}</td>
              <td>{{ l.max_continue }}</td>
              <td>{{ ((l.up_down_ratio || 0) * 100).toFixed(1) }}%</td>
              <td>{{ Number(l.zt_premium || 0).toFixed(2) }}</td>
              <td :style="{ color: (l.momentum || 0) >= 0 ? '#67c23a' : '#f56c6c' }">{{ ((l.momentum || 0) * 100).toFixed(2) }}%</td>
              <td :class="(l.broken_rate || 0) > 30 ? 'down' : ''">{{ l.broken }} ({{ (l.broken_rate || 0).toFixed(1) }}%)</td>
              <td class="ll-bd">
                <span class="ll-bd-item" title="涨停数">{{ l.breakdown?.limit_up_score }}</span>+<span class="ll-bd-item" title="跌停数">{{ l.breakdown?.limit_down_score }}</span>+<span class="ll-bd-item" title="涨跌比">{{ l.breakdown?.up_down_score }}</span>+<span class="ll-bd-item" title="动量">{{ l.breakdown?.momentum_score ?? '-' }}</span>+<span class="ll-bd-item" title="炸板率">{{ l.breakdown?.broken_score ?? '-' }}</span>+<span class="ll-bd-item" title="连板高度">{{ l.breakdown?.max_continue_score }}</span>+<span class="ll-bd-item" title="今日溢价">{{ l.breakdown?.zt_premium_score }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty" style="padding:8px 0">暂无盘中计算日志 (非交易时段或 scanner 未运行)</div>

      <!-- 阶段说明 -->
      <div class="st" style="margin-top:12px">📖 阶段说明与建议</div>
      <div class="phase-guide">
        <div v-for="p in phaseGuide" :key="p.name" class="phase-card" :class="p.active ? 'active' : ''" :style="{ borderColor: p.color }">
          <div class="phase-header" :style="{ background: p.color + '18' }"><span class="phase-icon">{{ p.icon }}</span><span class="phase-name" :style="{ color: p.color }">{{ p.name }}</span><span class="phase-range">{{ p.range }}</span></div>
          <div class="phase-body"><div class="phase-row"><span class="phase-label">仓位</span><span class="phase-val">{{ p.position }}</span></div><div class="phase-row"><span class="phase-label">开仓</span><span class="phase-val">{{ p.canOpen }}</span></div><div class="phase-row"><span class="phase-label">策略</span><span class="phase-val">{{ p.strategy }}</span></div><div class="phase-row"><span class="phase-label">建议</span><span class="phase-val">{{ p.advice }}</span></div></div>
        </div>
      </div>

      <!-- 降级规则 -->
      <div class="st" style="margin-top:12px">⚠️ 情绪降级调仓规则</div>
      <div class="downgrade-rules"><div v-for="r in downgradeRules" :key="r.from+r.to" class="dg-rule"><span class="dg-from" :style="{ color: phaseColors[r.from] }">{{ r.from }}</span><span class="dg-arrow">→</span><span class="dg-to" :style="{ color: phaseColors[r.to] }">{{ r.to }}</span><span class="dg-action">{{ r.action }}</span><span class="dg-desc">{{ r.desc }}</span></div></div>

      <!-- 策略矩阵 -->
      <div class="st" style="margin-top:12px">📋 策略×情绪 效果矩阵</div>
      <div v-if="sentimentMatrix && Object.keys(sentimentMatrix).length" class="matrix-table-wrap"><table class="matrix-table"><thead><tr><th>策略</th><th>冰点</th><th>震荡</th><th>分化</th><th>高潮</th><th>合计</th></tr></thead><tbody><tr v-for="(periods, strat) in sentimentMatrix" :key="strat"><td class="mt-strat">{{ strategyCN(strat) }}</td><td v-for="col in ['冰点','震荡','分化','高潮']" :key="col" class="mt-cell"><template v-if="periods[col]"><div class="mt-count" :class="periods[col].total_pnl >= 0 ? 'up' : 'down'">{{ periods[col].count }}笔</div><div class="mt-wr" :class="periods[col].win_rate >= 50 ? 'up' : 'down'">WR{{ periods[col].win_rate }}%</div><div class="mt-pnl" :class="periods[col].total_pnl >= 0 ? 'up' : 'down'">¥{{ periods[col].total_pnl }}</div></template><span v-else class="mt-empty">-</span></td><td class="mt-total">{{ matrixTotal(periods) }}笔</td></tr></tbody></table></div>
      <div v-else class="empty" style="padding:8px 0">暂无策略×情绪数据</div>

      <!-- 推荐 -->
      <div class="st" style="margin-top:12px">💡 推荐与警告</div>
      <div v-if="sentimentLive" class="rec-warn-section">
        <div class="rw-card rw-rec"><div class="rw-title">📌 当前建议</div><div class="rw-content">{{ sentimentAdvice }}</div></div>
        <div v-if="(sentimentLive?.score || 0) < 40" class="rw-card rw-warn"><div class="rw-title">⚠️ 风险警告</div><div class="rw-content">当前情绪冰点，市场极度弱势。建议空仓观望，禁止新开仓。</div></div>
        <div v-else-if="(sentimentLive?.score || 0) < 55" class="rw-card rw-caution"><div class="rw-title">⚡ 震荡提醒</div><div class="rw-content">市场情绪震荡，建议轻仓操作，仅做龙头股低吸，严格止损3%。</div></div>
      </div><div v-else class="empty" style="padding:8px 0">选择日期后查看推荐</div>

      <!-- 算法说明 -->
      <div class="st" style="margin-top:12px">🔬 算法与数据源</div>
      <div class="algo-info">
        <div class="algo-section"><div class="algo-title">📐 情绪得分算法</div><div class="algo-body">综合得分满分100，5维度加权：<strong>涨停数量(0-30分)</strong> — 每只+1分，50只以上满分<br><strong>跌停数量(0-20分)</strong> — 0跌停满分20，每只-2分<br><strong>最高连板(0-20分)</strong> — 每层+2分，10板满分<br><strong>涨跌家数比(0-15分)</strong> — 上涨占比×15<br><strong>昨日涨停溢价(0-15分)</strong> — 每1%+1分</div></div>
        <div class="algo-section"><div class="algo-title">📊 数据来源</div><div class="algo-body"><strong>实时</strong>：Scanner内存缓存，盘中最快5秒更新<br><strong>历史</strong>：MongoDB sentiment_scores集合<br><strong>涨跌停</strong>：limit_list集合或daily_basic<br><strong>日内图表</strong>：5分钟采样聚合，涨停/跌停取时段峰值，涨跌比=涨停/(涨停+跌停)</div></div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.intraday-panel { border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; background: var(--bg-elevated); }
.ip-title { padding: 6px 10px; font-size: 12px; font-weight: 700; background: var(--bg-secondary); border-bottom: 1px solid var(--border-default); }
.ip-sub { font-weight: normal; color: var(--text-tertiary); font-size: 10px; }
.ip-chart { display: flex; padding: 0; }

.sentiment-chart { display: flex; flex-direction: column; height: 260px; border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; background: var(--bg-elevated); }
.sc-y-axis { display: flex; flex-direction: column-reverse; justify-content: space-between; padding: 4px 6px; font-size: 10px; color: var(--text-tertiary); min-width: 36px; text-align: right; }
.sc-chart-row { display: flex; flex: 1; min-height: 0; }
.sc-chart-body { flex: 1; position: relative; display: flex; flex-direction: column-reverse; }
.sc-band { width: 100%; position: relative; z-index: 1; }
.sc-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; }
.sc-dot { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: var(--el-color-primary); transform: translate(-50%, 50%); z-index: 4; cursor: pointer; transition: transform 0.15s; }
.sc-dot:hover { transform: translate(-50%, 50%) scale(2); }
.sc-dot.hot { background: #f56c6c; }
.sc-dot.cold { background: #67c23a; }
.sc-dot.missing { background: var(--el-color-warning); opacity: 0.6; }
.sc-hover-card { position: absolute; z-index: 10; background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 6px 10px; font-size: 12px; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,0.15); white-space: nowrap; }
.sc-hover-date { color: var(--text-secondary); margin-bottom: 2px; }
.sc-hover-score { font-weight: 600; font-size: 14px; }
.sc-hover-score.hot { color: #f56c6c; }
.sc-hover-score.cold { color: #67c23a; }
.sc-hover-detail { color: var(--text-tertiary); margin-top: 2px; }
.sc-x-labels { display: flex; justify-content: space-between; padding: 4px 8px 4px 40px; font-size: 11px; color: var(--text-tertiary); border-top: 1px solid var(--border-default); min-height: 22px; }

.sentiment-3col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.sentiment-panel { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.sl-content { margin-top: 6px; }
.sl-gauge { margin-bottom: 8px; }
.sl-gauge-bar { height: 16px; background: var(--bg-secondary); border-radius: 8px; overflow: hidden; }
.sl-gauge-fill { height: 100%; border-radius: 8px; transition: width 0.5s; }
.sl-score-labels { display: flex; justify-content: space-between; font-size: 9px; color: var(--text-tertiary); margin-top: 2px; }
.sl-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
.sl-row span:first-child { color: var(--text-tertiary); }
.sl-val { font-weight: 600; }

.phase-guide { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.phase-card { border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; opacity: 0.65; }
.phase-card.active { opacity: 1; box-shadow: 0 0 0 2px var(--el-color-primary); }
.phase-header { display: flex; align-items: center; gap: 4px; padding: 6px 8px; font-size: 12px; }
.phase-icon { font-size: 16px; }
.phase-name { font-weight: 700; font-size: 13px; }
.phase-range { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.phase-body { padding: 6px 8px; }
.phase-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.phase-label { color: var(--text-tertiary); }
.phase-val { font-weight: 500; }

.downgrade-rules { display: flex; flex-direction: column; gap: 4px; }
.dg-rule { display: flex; align-items: center; gap: 6px; padding: 4px 10px; font-size: 11px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); }
.dg-from, .dg-to { font-weight: 700; min-width: 28px; }
.dg-arrow { color: var(--text-quaternary); }
.dg-action { color: var(--el-color-warning); font-weight: 600; min-width: 60px; }
.dg-desc { color: var(--text-tertiary); }

.matrix-table-wrap { overflow-x: auto; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.matrix-table th { padding: 6px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); }
.matrix-table td { padding: 6px 8px; text-align: center; border-bottom: 1px solid var(--border-default); }
.mt-strat { font-weight: 600; text-align: left !important; }
.mt-cell { min-width: 80px; }
.mt-count { font-weight: 600; }
.mt-wr { font-size: 10px; }
.mt-pnl { font-size: 10px; font-weight: 600; }
.mt-empty { color: var(--text-quaternary); }
.mt-total { font-weight: 600; color: var(--text-secondary); }

.rec-warn-section { display: flex; flex-direction: column; gap: 8px; }
.rw-card { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border-default); }
.rw-card.rw-rec { background: rgba(64,158,255,0.06); border-color: rgba(64,158,255,0.2); }
.rw-card.rw-warn { background: rgba(245,108,108,0.06); border-color: rgba(245,108,108,0.2); }
.rw-card.rw-caution { background: rgba(230,162,60,0.06); border-color: rgba(230,162,60,0.2); }
.rw-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.rw-content { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }

.algo-info { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.algo-section { border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.algo-title { font-weight: 700; font-size: 12px; padding: 6px 10px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); }
.algo-body { padding: 8px 10px; font-size: 11px; color: var(--text-secondary); line-height: 1.6; }

/* 【v2.9.96h】盘中计算日志表格 */
.live-log-wrap { overflow-x: auto; max-height: 360px; overflow-y: auto; border: 1px solid var(--border-default); border-radius: 6px; }
.live-log-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.live-log-tbl th { position: sticky; top: 0; z-index: 1; padding: 6px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.live-log-tbl td { padding: 4px 8px; text-align: center; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
.live-log-latest { background: rgba(64, 158, 255, 0.08); }
.live-log-latest td { font-weight: 500; }
.ll-time { font-family: 'Menlo', 'Monaco', monospace; color: var(--text-tertiary); }
.ll-score { font-family: 'Menlo', 'Monaco', monospace; min-width: 38px; }
.ll-phase { padding: 1px 6px; border-radius: 3px; font-size: 10px; background: rgba(128,128,128,0.08); }
.ll-bd { font-family: 'Menlo', 'Monaco', monospace; font-size: 10px; color: var(--text-tertiary); }
.ll-bd-item { display: inline-block; padding: 0 2px; color: var(--text-secondary); }
</style>
