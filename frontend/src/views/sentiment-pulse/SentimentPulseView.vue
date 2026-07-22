<script setup lang="ts">
/**
 * SentimentPulseView — 情绪脉搏
 *
 * 4大板块:
 * ① 实时心电 — 盘中7维折线+盘后5维对比
 * ② 周期地图 — 情绪阶段日历热力图
 * ③ 维度解剖 — 雷达图+分数条
 * ④ 策略共振 — 策略×情绪矩阵
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSentimentPulse } from './useSentimentPulse'
import { ElButton } from 'element-plus'
import UnifiedDateBar from '@/views/monitor/components/UnifiedDateBar.vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, RadarChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  MarkLineComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
use([CanvasRenderer, LineChart, BarChart, RadarChart,
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  MarkLineComponent])

const {
  date, loading,
  liveLog, dailyScores, calendarData, marketSentiment,
  strategyMatrix, recommendations,
  dailyReview, cycleAnalysis,
  thresholds, positionMap,
  currentScore, currentPeriod, currentPeriodCN, currentPositionRatio,
  phaseColors, scoreColor,
  fetchAll, fetchLiveLog,
} = useSentimentPulse()

// ===== 工具函数 =====
function phaseEmoji(p: string): string {
  const map: Record<string, string> = { rising: '🔥', differentiation: '⚡', chaos: '🌀', bearish: '🥶',
    '高潮': '🔥', '分化': '⚡', '震荡': '🌀', '冰点': '🥶' }
  return map[p] || '🌀'
}
function phaseCN(p: string): string {
  const map: Record<string, string> = { rising: '高潮', differentiation: '分化', chaos: '震荡', bearish: '冰点',
    RISING: '高潮', DIFFERENTIATION: '分化', CHAOS: '震荡', BEARISH: '冰点' }
  return map[p] || p
}
function heroClass(s: number): string { return s >= 70 ? 'hot' : s >= 55 ? 'warm' : s >= 40 ? 'neutral' : 'cold' }

// ===== ① 实时心电 ECharts =====
const ecgChartOption = computed(() => {
  const logs = liveLog.value
  if (!logs.length) return {}
  // 按时间正序
  const sorted = [...logs].sort((a, b) => (a.time || '').localeCompare(b.time || ''))
  const labels = sorted.map(p => p.time || '')
  const scores = sorted.map(p => p.score ?? null)
  const limitUps = sorted.map(p => p.limit_up || 0)
  const limitDowns = sorted.map(p => -(p.limit_down || 0))
  const brokenRates = sorted.map(p => p.broken_rate != null ? (p.broken_rate * 100) : null)
  const momentums = sorted.map(p => p.momentum != null ? (p.momentum * 100) : null)
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(30,30,30,0.92)', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 },
      formatter: (params: any[]) => {
        const idx = params[0]?.dataIndex ?? 0
        const p = sorted[idx]
        if (!p) return ''
        return `<div style="font-weight:600">${p.time}</div>情绪<b style="color:${scoreColor(p.score||0)}">${(p.score||0).toFixed(1)}</b> ${phaseEmoji(p.phase||'')}${phaseCN(p.phase||'')}<br/>涨停<b style="color:#f56c6c">${p.limit_up||0}</b> 跌停<b style="color:#409eff">${p.limit_down||0}</b> 炸板<b style="color:#e6a23c">${p.broken||0}</b><br/>动量${(p.momentum||0)>=0?'+':''}${((p.momentum||0)*100).toFixed(1)}% 炸板率${((p.broken_rate||0)*100).toFixed(0)}%`
      }
    },
    legend: { data: ['涨停', '跌停', '情绪分', '炸板率%'], top: 4, right: 8, textStyle: { fontSize: 10 }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 42, right: 42, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 9, interval: Math.max(0, Math.floor(labels.length / 10) - 1), color: '#999' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '数量', nameTextStyle: { fontSize: 9, color: '#999' }, axisLabel: { fontSize: 9, color: '#999', formatter: (v: number) => Math.abs(v) }, splitLine: { lineStyle: { color: '#333', type: 'dashed' } } },
      { type: 'value', name: 'Score/%', min: 0, max: 100, nameTextStyle: { fontSize: 9, color: '#999' }, axisLabel: { fontSize: 9, color: '#999' }, splitLine: { show: false } },
    ],
    series: [
      { name: '涨停', type: 'bar', data: limitUps, itemStyle: { color: 'rgba(245,108,108,0.7)', borderRadius: [2, 2, 0, 0] }, barMaxWidth: 14 },
      { name: '跌停', type: 'bar', data: limitDowns, itemStyle: { color: 'rgba(64,158,255,0.6)', borderRadius: [0, 0, 2, 2] }, barMaxWidth: 14 },
      { name: '情绪分', type: 'line', data: scores, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 2.5, color: '#a855f7' }, itemStyle: { color: '#a855f7' }, symbol: 'circle', symbolSize: 3,
        markLine: { silent: true, lineStyle: { color: '#666', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#888' }, data: [
          { yAxis: 70, label: { formatter: '70🔥' } }, { yAxis: 55, label: { formatter: '55⚡' } }, { yAxis: 40, label: { formatter: '40🌀' } },
        ] } },
      { name: '炸板率%', type: 'line', data: brokenRates, yAxisIndex: 1, smooth: 0.2, lineStyle: { width: 1, color: '#e6a23c', type: 'dashed' }, itemStyle: { color: '#e6a23c' }, symbol: 'none', connectNulls: true },
    ],
    animation: true, animationDuration: 600,
  }
})

// ===== ② 周期地图: 横向情绪时间线 =====
const timelineData = computed(() => {
  const data = calendarData.value
  if (!data.length) return []
  return data.map(p => {
    const d = String(p.date || '')
    const s = p.score ?? 0
    const period = p.period || ''
    const emoji = s >= 70 ? '🔥' : s >= 55 ? '⚡' : s >= 40 ? '🌀' : '🥶'
    const periodCN = s >= 70 ? '高潮' : s >= 55 ? '分化' : s >= 40 ? '震荡' : '冰点'
    const dateLabel = d.length === 8 ? `${d.slice(4, 6)}/${d.slice(6, 8)}` : d
    return { date: d, score: s, period, emoji, periodCN, dateLabel,
      limitUp: p.limit_up || 0, limitDown: p.limit_down || 0 }
  })
})
// 月度统计
const monthStats = computed(() => {
  const data = timelineData.value
  if (!data.length) return []
  const map: Record<string, { count: number, avg: number, hot: number, cold: number, dates: string[] }> = {}
  for (const d of data) {
    const mk = d.date.slice(0, 6)
    if (!map[mk]) map[mk] = { count: 0, avg: 0, hot: 0, cold: 0, dates: [] }
    map[mk].count++
    map[mk].avg += d.score
    if (d.score >= 70) map[mk].hot++
    if (d.score < 40) map[mk].cold++
    map[mk].dates.push(d.dateLabel)
  }
  return Object.entries(map)
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([k, v]) => ({
      label: `${k.slice(0, 4)}/${k.slice(4, 6)}`,
      count: v.count,
      avg: v.count > 0 ? (v.avg / v.count).toFixed(1) : '0.0',
      hot: v.hot,
      cold: v.cold,
    }))
})

// ===== ③ 维度解剖: 雷达图 =====
const radarChartOption = computed(() => {
  const ms = marketSentiment.value
  if (!ms) return {}
  const dims = ms.dimensions || {}
  // 8维(盘中) or 5维(盘后)
  const is7dim = dims.d1_limit_up != null
  if (is7dim) {
    const indicators = [
      { name: 'D1涨停', max: 20 }, { name: 'D2跌停', max: 15 },
      { name: 'D3涨跌比', max: 15 }, { name: 'D4动量', max: 10 },
      { name: 'D5炸板率', max: 10 }, { name: 'D6连板', max: 10 },
      { name: 'D7昨溢价', max: 5 }, { name: 'D8今溢价', max: 5 },
    ]
    const values = [
      dims.d1_limit_up || 0, dims.d2_limit_down || 0,
      dims.d3_up_down || 0, Math.max(0, dims.d4_momentum || 0),
      dims.d5_broken_rate || 0, dims.d6_max_continue || 0,
      dims.d7_zt_premium || 0, dims.d8_today_premium || 0,
    ]
    return {
      radar: { indicator: indicators, radius: '68%', axisName: { fontSize: 10, color: '#aaa' }, splitArea: { areaStyle: { color: ['rgba(64,158,255,0.02)', 'rgba(64,158,255,0.04)'] } } },
      series: [{ type: 'radar', data: [{ value: values, name: '8维得分', areaStyle: { color: 'rgba(168,85,247,0.15)' }, lineStyle: { color: '#a855f7', width: 2 }, itemStyle: { color: '#a855f7' } }] }],
    }
  }
  // 5维盘后fallback
  const lu = ms.limit_up_count || 0, ld = ms.limit_down_count || 0
  const mc = ms.max_continue || 0, udr = ms.up_down_ratio || 0, ztp = ms.zt_premium || 0
  const indicators = [
    { name: '涨停', max: 30 }, { name: '跌停', max: 20 },
    { name: '连板', max: 20 }, { name: '涨跌比', max: 15 }, { name: '溢价', max: 15 },
  ]
  const values = [
    Math.min(30, lu), Math.max(0, 20 - ld * 2),
    Math.min(20, mc * 2), Math.min(15, Math.round(udr * 15)),
    Math.min(15, Math.max(0, Math.round(ztp))),
  ]
  return {
    radar: { indicator: indicators, radius: '68%', axisName: { fontSize: 10, color: '#aaa' }, splitArea: { areaStyle: { color: ['rgba(64,158,255,0.02)', 'rgba(64,158,255,0.04)'] } } },
    series: [{ type: 'radar', data: [{ value: values, name: '5维得分', areaStyle: { color: 'rgba(64,158,255,0.15)' }, lineStyle: { color: '#409eff', width: 2 }, itemStyle: { color: '#409eff' } }] }],
  }
})

// 维度分数条(与雷达图配合)
const dimBars = computed(() => {
  const ms = marketSentiment.value
  if (!ms) return []
  const dims = ms.dimensions || {}
  const is7dim = dims.d1_limit_up != null
  if (is7dim) {
    return [
      { label: 'D1 涨停数量', value: dims.d1_limit_up || 0, max: 20, color: '#f56c6c' },
      { label: 'D2 跌停惩罚', value: dims.d2_limit_down || 0, max: 15, color: '#409eff' },
      { label: 'D3 涨跌家数比', value: dims.d3_up_down || 0, max: 15, color: '#36cfc9' },
      { label: 'D4 涨跌加速度', value: Math.max(0, dims.d4_momentum || 0), max: 10, color: '#a855f7' },
      { label: 'D5 涨停开板率', value: dims.d5_broken_rate || 0, max: 10, color: '#e6a23c' },
      { label: 'D6 最高连板', value: dims.d6_max_continue || 0, max: 10, color: '#f56c6c' },
      { label: 'D7 昨日涨停溢价', value: dims.d7_zt_premium || 0, max: 5, color: '#409eff' },
      { label: 'D8 今日涨停溢价', value: dims.d8_today_premium || 0, max: 5, color: '#36cfc9' },
    ]
  }
  const lu = ms.limit_up_count || 0, ld = ms.limit_down_count || 0
  const mc = ms.max_continue || 0, udr = ms.up_down_ratio || 0, ztp = ms.zt_premium || 0
  return [
    { label: '涨停数量', value: Math.min(30, lu), max: 30, color: '#f56c6c' },
    { label: '跌停惩罚', value: Math.max(0, 20 - ld * 2), max: 20, color: '#409eff' },
    { label: '连板高度', value: Math.min(20, mc * 2), max: 20, color: '#a855f7' },
    { label: '涨跌家数比', value: Math.min(15, Math.round(udr * 15)), max: 15, color: '#36cfc9' },
    { label: '涨停溢价', value: Math.min(15, Math.max(0, Math.round(ztp))), max: 15, color: '#e6a23c' },
  ]
})

// ===== ④ 策略共振 =====
const strategyCN: Record<string, string> = {
  first_limit_up: '首板', limit_up_chase: '打板', low_buy_dragon: '龙头低吸',
  broken_limit_up: '翘板', halfway_chase: '半路追涨', dragon_head: '龙头',
  anomaly_surge: '异动急拉', premarket_auction: '竞价', rebound_bottom: '底部反弹',
}
function stratName(id: string): string { return strategyCN[id] || id }

// ===== 日线趋势图 =====
const dailyChartOption = computed(() => {
  const data = dailyScores.value
  if (!data.length) return {}
  const labels = data.map(p => {
    const d = String(p.date || '')
    return d.length === 8 ? `${d.slice(4, 6)}/${d.slice(6, 8)}` : d
  })
  const scores = data.map(p => p.score ?? null)
  const limitUps = data.map(p => p.limit_up || 0)
  const limitDowns = data.map(p => -(p.limit_down || 0))
  return {
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(30,30,30,0.92)', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 } },
    legend: { data: ['涨停', '跌停', '情绪分'], top: 4, right: 8, textStyle: { fontSize: 10 } },
    grid: { left: 42, right: 20, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 9, interval: Math.max(0, Math.floor(labels.length / 12) - 1), color: '#999' }, axisLine: { lineStyle: { color: '#444' } } },
    yAxis: [
      { type: 'value', name: '数量', axisLabel: { fontSize: 9, color: '#999', formatter: (v: number) => Math.abs(v) }, splitLine: { lineStyle: { color: '#333', type: 'dashed' } } },
      { type: 'value', name: 'Score', min: 0, max: 100, axisLabel: { fontSize: 9, color: '#999' }, splitLine: { show: false } },
    ],
    series: [
      { name: '涨停', type: 'bar', data: limitUps, itemStyle: { color: 'rgba(245,108,108,0.6)' }, barMaxWidth: 12 },
      { name: '跌停', type: 'bar', data: limitDowns, itemStyle: { color: 'rgba(64,158,255,0.5)' }, barMaxWidth: 12 },
      { name: '情绪分', type: 'line', data: scores, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 2, color: '#a855f7' }, itemStyle: { color: '#a855f7' }, symbol: 'circle', symbolSize: 3,
        markLine: { silent: true, lineStyle: { color: '#666', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#888' }, data: [
          { yAxis: 70, label: { formatter: '70🔥' } }, { yAxis: 55, label: { formatter: '55⚡' } }, { yAxis: 40, label: { formatter: '40🌀' } },
        ] } },
    ],
  }
})

// ===== 盘中情绪分析 =====
const intradayScores = computed(() => liveLog.value.map(l => l.score ?? 0))
const intradayAvg = computed(() => intradayScores.value.length ? intradayScores.value.reduce((a: number, b: number) => a + b, 0) / intradayScores.value.length : currentScore.value)
const intradayMin = computed(() => intradayScores.value.length ? Math.min(...intradayScores.value) : currentScore.value)
const intradayMax = computed(() => intradayScores.value.length ? Math.max(...intradayScores.value) : currentScore.value)
const intradayPhaseCN = computed(() => {
  const a = intradayAvg.value
  return a >= 70 ? '高潮' : a >= 55 ? '分化' : a >= 40 ? '震荡偏弱' : '冰点'
})
const intradayTransitions = computed(() => {
  const logs = liveLog.value
  if (logs.length < 2) return 0
  let cnt = 0
  for (let i = 1; i < logs.length; i++) {
    const prev = logs[i-1].phase || ''
    const curr = logs[i].phase || ''
    if (prev !== curr) cnt++
  }
  return cnt
})
const intradayPhaseDist = computed(() => {
  const logs = liveLog.value
  if (!logs.length) return []
  const cnt: Record<string, number> = { bearish: 0, chaos: 0, differentiation: 0, rising: 0 }
  for (const l of logs) { cnt[l.phase || 'chaos'] = (cnt[l.phase || 'chaos'] || 0) + 1 }
  const total = logs.length
  const cnMap: Record<string, string> = { bearish: '🥶冰点', chaos: '🌀震荡', differentiation: '⚡分化', rising: '🔥高潮' }
  return Object.entries(cnt).filter(([_, c]) => c > 0).map(([p, c]) => ({ phase: p, cn: cnMap[p] || p, pct: Math.round(c / total * 100) }))
})
const intradayTrendDesc = computed(() => {
  const logs = liveLog.value
  if (logs.length < 4) return '数据不足'
  // 比较前半段和后半段均值
  const mid = Math.floor(logs.length / 2)
  const first = logs.slice(0, mid).reduce((s: number, l: any) => s + (l.score || 0), 0) / mid
  const second = logs.slice(mid).reduce((s: number, l: any) => s + (l.score || 0), 0) / (logs.length - mid)
  const diff = second - first
  if (diff > 10) return `盘中持续走强(+${diff.toFixed(0)}分)，午后情绪明显回暖`
  if (diff < -10) return `盘中持续走弱(${diff.toFixed(0)}分)，午后情绪恶化`
  // 阶段转换多
  if (intradayTransitions.value > 20) return `盘中反复摇摆(${intradayTransitions.value}次转换)，冰点↔震荡频繁切换`
  return '盘中情绪波动不大，整体稳定'
})

// ===== 综合评分(盘中均值×0.6 + 盘后×0.4) =====
const todayOverallScore = computed(() => {
  if (!liveLog.value.length) return currentScore.value
  return intradayAvg.value * 0.6 + currentScore.value * 0.4
})
const todayOverallCN = computed(() => {
  const s = todayOverallScore.value
  return s >= 70 ? '高潮' : s >= 55 ? '分化偏强' : s >= 40 ? '震荡偏弱' : '冰点'
})
const todayOverallEmoji = computed(() => {
  const s = todayOverallScore.value
  return s >= 70 ? '🔥' : s >= 55 ? '⚡' : s >= 40 ? '🌀' : '🥶'
})
const todayOneLineSummary = computed(() => {
  const s = todayOverallScore.value
  const trans = intradayTransitions.value
  if (s >= 70) return '市场普涨，涨停潮，积极做多。'
  if (s >= 55) return '市场有主线但分化，精选强势股参与。'
  if (s >= 40) {
    if (trans > 20) return '市场偏弱且情绪极不稳定，冰点↔震荡频繁切换，轻仓防守为主。'
    return '市场偏弱，涨少跌多，轻仓防守为主。'
  }
  if (trans > 20) return '市场冰冻且盘中反复摇摆，风险极高，应空仓观望。'
  return '市场冰冻，涨跌比极低，应空仓观望。'
})

// ===== 明日综合评分 =====
const tomorrowCompositeScore = computed(() => {
  // 盘后定调权重50%，盘中趋势30%，多日走势20%
  const postWeight = currentScore.value * 0.5
  const intradayWeight = intradayAvg.value * 0.3
  // 多日走势: 最近5天均值
  const recentScores = dailyScores.value.slice(-5).map(p => p.score ?? 0)
  const recentAvg = recentScores.length ? recentScores.reduce((a: number, b: number) => a + b, 0) / recentScores.length : currentScore.value
  const multiWeight = recentAvg * 0.2
  return postWeight + intradayWeight + multiWeight
})
const tomorrowPositionPct = computed(() => {
  const s = tomorrowCompositeScore.value
  return s >= 70 ? 1.0 : s >= 55 ? 0.7 : s >= 40 ? 0.5 : 0.3
})
const tomorrowEmoji = computed(() => {
  const s = tomorrowCompositeScore.value
  return s >= 70 ? '🔥' : s >= 55 ? '⚡' : s >= 40 ? '🌀' : '🥶'
})
const tomorrowActionCN = computed(() => {
  const s = tomorrowCompositeScore.value
  return s >= 70 ? '积极做多' : s >= 55 ? '精选参与' : s >= 40 ? '轻仓防守' : '空仓观望'
})
const tomorrowAnalysis = computed(() => {
  const cs = tomorrowCompositeScore.value
  const trans = intradayTransitions.value
  const diff = intradayAvg.value - currentScore.value
  let base = ''
  if (cs >= 70) base = '盘后高潮+盘中强势，明日可积极做多，所有策略开放。'
  else if (cs >= 55) base = '盘后分化+盘中偏强，精选龙头参与，仓位70%。'
  else if (cs >= 40) base = '盘后偏弱+盘中震荡，轻仓防守，仅龙头低吸可尝试。'
  else base = '盘后冰点+盘中弱势，禁止新开仓，现有持仓只做止损。'
  // 补充盘中特征
  if (trans > 20) base += ` 盘中情绪极不稳定(${trans}次转换)，注意盘中可能有短暂回暖但不改弱势。`
  if (diff > 15) base += ` 盘中均值(${intradayAvg.value.toFixed(0)}分)显著高于盘后(${currentScore.value.toFixed(0)}分)，收盘走弱，明日开盘可能延续弱势。`
  else if (diff < -5) base += ` 盘中均值低于盘后，尾盘加速下跌。`
  return base
})
const recentDaysTrendDesc = computed(() => {
  const scores = dailyScores.value.slice(-5).map(p => p.score ?? 0)
  if (scores.length < 3) return '数据不足'
  const latest = scores[scores.length - 1]
  const prev = scores[scores.length - 2]
  const prev2 = scores.length >= 3 ? scores[scores.length - 3] : prev
  if (latest < prev && prev < prev2) return `${prev2.toFixed(0)}→${prev.toFixed(0)}→${latest.toFixed(0)} 三连跌`
  if (latest > prev && prev > prev2) return `${prev2.toFixed(0)}→${prev.toFixed(0)}→${latest.toFixed(0)} 三连涨`
  return `${prev2.toFixed(0)}→${prev.toFixed(0)}→${latest.toFixed(0)} 震荡`
})

// ===== 降级规则 =====
const downgradeRules = [
  { from: '高潮', to: '分化', action: '减仓50%', desc: '保留核心仓位' },
  { from: '高潮', to: '震荡', action: '减仓50%', desc: '市场转弱，保留核心' },
  { from: '高潮', to: '冰点', action: '清低利润', desc: '急转直下，保命优先' },
  { from: '分化', to: '震荡', action: '减仓60%', desc: '仅保留最强持仓' },
  { from: '分化', to: '冰点', action: '禁开仓', desc: '禁止新开仓，仓位≤30%' },
  { from: '震荡', to: '冰点', action: '禁开仓', desc: '禁止新开仓，仓位≤30%' },
]

// ===== 今日总结: 总盈亏 =====
const totalPnl = computed(() => {
  const ss = dailyReview.value?.strategy_summary
  if (!ss) return 0
  return Object.values(ss).reduce((sum: number, info: any) => sum + (info.total_pnl || 0), 0)
})

// ===== 明日展望: 策略开关 =====
const tomorrowSwitches = computed(() => {
  // 所有策略
  const allStrats = [
    { id: 'first_limit_up', name: '首板', openDefault: true },
    { id: 'halfway_chase', name: '半路追涨', openDefault: true },
    { id: 'limit_up_chase', name: '打板', openDefault: true },
    { id: 'low_buy_dragon', name: '龙头低吸', openDefault: true },
    { id: 'broken_limit_up', name: '翘板', openDefault: true },
    { id: 'dragon_head', name: '龙头', openDefault: true },
  ]
  const fa = dailyReview.value?.forward_advice
  const switches = fa?.strategy_switches || []
  const period = currentPeriod.value
  // 根据情绪阶段决定默认开关
  return allStrats.map(s => {
    const sw = switches.find((x: any) => x.strategy === s.id)
    let open = s.openDefault
    let reason = ''
    if (period === 'bearish') {
      open = false
      reason = '冰点期禁止'
    } else if (period === 'chaos') {
      open = ['low_buy_dragon', 'dragon_head'].includes(s.id)
      reason = open ? '震荡期允许' : '震荡期禁止'
    } else if (period === 'differentiation') {
      open = !['limit_up_chase', 'broken_limit_up'].includes(s.id)
      reason = open ? '分化期允许' : '分化期风险高'
    } else {
      reason = '高潮期全部开放'
    }
    // forward_advice覆盖
    if (sw) {
      open = sw.action !== 'close'
      if (!reason) reason = sw.reason
    }
    return { ...s, open, reason }
  })
})

// ===== 明日展望: 近期趋势 =====
const recentTrend = computed(() => {
  const ts = cycleAnalysis.value?.transitions
  if (!ts || ts.length < 2) return 'flat'
  const last3 = ts.slice(-3)
  const ups = last3.filter((t: any) => t.direction === 'up').length
  const downs = last3.filter((t: any) => t.direction === 'down').length
  if (downs >= 2) return 'falling'
  if (ups >= 2) return 'rising'
  return 'flat'
})

// ===== 动态持仓上限映射 =====
const dynamicPositions: Record<string, number> = { rising: 10, differentiation: 8, chaos: 6, bearish: 4 }

// ===== 阶段说明 =====
const phaseGuide = [
  { name: '高潮', icon: '🔥', range: '≥70分', position: '100%', canOpen: '✅ 全部', strategy: '所有策略开放', color: '#f56c6c' },
  { name: '分化', icon: '⚡', range: '55-70分', position: '70%', canOpen: '✅ 精选', strategy: '仅龙头低吸+半路追涨', color: '#e6a23c' },
  { name: '震荡', icon: '🌀', range: '40-55分', position: '50%', canOpen: '⚠️ 轻仓', strategy: '仅龙头低吸(半仓)', color: '#409eff' },
  { name: '冰点', icon: '🥶', range: '<40分', position: '30%', canOpen: '❌ 禁止', strategy: '禁止新开仓', color: '#67c23a' },
]

// ===== 自动刷新 =====
let refreshTimer: number | undefined
onMounted(() => { fetchAll(); refreshTimer = window.setInterval(() => fetchLiveLog(), 30000) })
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<template>
  <div class="sp-page">
    <!-- ========== 顶栏 ========== -->
    <div class="sp-header">
      <h2 class="sp-title">💓 情绪脉搏</h2>
      <UnifiedDateBar @change="(_d: string) => { date = _d; fetchAll() }" />
      <ElButton size="small" @click="fetchAll" :loading="loading">🔄 刷新</ElButton>
    </div>

    <!-- ========== Hero: 当前情绪快照 ========== -->
    <div class="sp-hero" :class="heroClass(currentScore)">
      <div class="sp-hero-left">
        <div class="sp-hero-emoji">{{ phaseEmoji(currentPeriod) }}</div>
        <div class="sp-hero-score" :style="{ color: scoreColor(currentScore) }">{{ currentScore.toFixed(0) }}<span class="sp-hero-unit">分</span></div>
      </div>
      <div class="sp-hero-center">
        <div class="sp-hero-period">{{ currentPeriodCN }}期</div>
        <div class="sp-hero-desc">{{ currentScore >= 70 ? '市场高潮，积极做多' : currentScore >= 55 ? '市场分化，精选龙头' : currentScore >= 40 ? '市场震荡，轻仓操作' : '市场冰点，空仓观望' }}</div>
      </div>
      <div class="sp-hero-right">
        <div class="sp-hero-stat">
          <span class="sp-stat-label">仓位系数</span>
          <span class="sp-stat-val" :style="{ color: scoreColor(currentScore) }">{{ (currentPositionRatio * 100).toFixed(0) }}%</span>
        </div>
        <div class="sp-hero-stat">
          <span class="sp-stat-label">最大持仓</span>
          <span class="sp-stat-val">{{ dynamicPositions[currentPeriod] || 6 }}只</span>
        </div>
        <div class="sp-hero-stat">
          <span class="sp-stat-label">允许开仓</span>
          <span class="sp-stat-val" :style="{ color: currentPeriod !== 'bearish' ? '#67c23a' : '#f56c6c' }">{{ currentPeriod !== 'bearish' ? '✅' : '❌' }}</span>
        </div>
      </div>
    </div>

    <!-- ========== ① 实时心电 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">📈</span>
        <span class="sp-section-title">实时心电</span>
        <span class="sp-section-sub">盘中7维实时采样，每5分钟跳动一次</span>
      </div>
      <div v-if="liveLog.length" class="sp-chart">
        <VChart :option="ecgChartOption" autoresize style="height: 260px; width: 100%" />
      </div>
      <div v-else class="sp-empty">📡 今日无盘中数据（非交易时段或Scanner未运行）</div>
    </div>

    <!-- ========== ② 日线趋势 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">📊</span>
        <span class="sp-section-title">日线趋势</span>
        <span class="sp-section-sub">盘后5维情绪得分，每日1点</span>
      </div>
      <div v-if="dailyScores.length" class="sp-chart">
        <VChart :option="dailyChartOption" autoresize style="height: 240px; width: 100%" />
      </div>
      <div v-else class="sp-empty">暂无日线数据</div>
    </div>

    <!-- ========== ② 周期地图 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">🗓️</span>
        <span class="sp-section-title">周期地图</span>
        <span class="sp-section-sub">每日情绪阶段一览，从左到右看趋势走向</span>
      </div>
      <div v-if="timelineData.length" class="sp-timeline-wrap">
        <!-- 图例 -->
        <div class="sp-tl-legend">
          <span class="sp-tl-leg"><span class="sp-tl-dot" style="background:#f56c6c"></span>🔥 高潮 ≥70</span>
          <span class="sp-tl-leg"><span class="sp-tl-dot" style="background:#e6a23c"></span>⚡ 分化 55-70</span>
          <span class="sp-tl-leg"><span class="sp-tl-dot" style="background:#409eff"></span>🌀 震荡 40-55</span>
          <span class="sp-tl-leg"><span class="sp-tl-dot" style="background:#67c23a"></span>🥶 冰点 <40</span>
        </div>
        <!-- 时间线格子 -->
        <div class="sp-tl-grid">
          <div v-for="d in timelineData" :key="d.date" class="sp-tl-cell" :class="'sp-tl-' + (d.score >= 70 ? 'hot' : d.score >= 55 ? 'warm' : d.score >= 40 ? 'neutral' : 'cold')">
            <div class="sp-tl-date">{{ d.dateLabel }}</div>
            <div class="sp-tl-emoji">{{ d.emoji }}</div>
            <div class="sp-tl-score">{{ d.score }}</div>
            <div class="sp-tl-detail">涨{{ d.limitUp }} 跌{{ d.limitDown }}</div>
          </div>
        </div>
        <!-- 月度摘要 -->
        <div v-if="monthStats.length" class="sp-tl-months">
          <div v-for="m in monthStats" :key="m.label" class="sp-tl-month">
            <span class="sp-tl-m-label">{{ m.label }}</span>
            <span class="sp-tl-m-avg">均值<b :style="{ color: scoreColor(+m.avg) }">{{ m.avg }}</b></span>
            <span class="sp-tl-m-hot">🔥{{ m.hot }}天</span>
            <span class="sp-tl-m-cold">🥶{{ m.cold }}天</span>
            <span class="sp-tl-m-count">共{{ m.count }}日</span>
          </div>
        </div>
      </div>
      <div v-else class="sp-empty">暂无日历数据</div>
    </div>

    <!-- ========== ③ 维度解剖 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">🔬</span>
        <span class="sp-section-title">维度解剖</span>
        <span class="sp-section-sub">{{ marketSentiment?.dimensions?.d1_limit_up != null ? '8维盘中实时' : '5维盘后' }}雷达图 + 分数条</span>
      </div>
      <div v-if="marketSentiment" class="sp-dims">
        <div class="sp-radar">
          <VChart :option="radarChartOption" autoresize style="height: 260px; width: 100%" />
        </div>
        <div class="sp-bars">
          <div v-for="d in dimBars" :key="d.label" class="sp-dim-row">
            <span class="sp-dim-label">{{ d.label }}</span>
            <div class="sp-dim-bar-wrap">
              <div class="sp-dim-bar" :style="{ width: (d.value / d.max * 100).toFixed(1) + '%', background: d.color }"></div>
            </div>
            <span class="sp-dim-val" :style="{ color: d.color }">{{ d.value.toFixed(1) }}<span class="sp-dim-max">/{{ d.max }}</span></span>
          </div>
          <!-- 总分 -->
          <div class="sp-dim-row sp-dim-total">
            <span class="sp-dim-label">总分</span>
            <div class="sp-dim-bar-wrap">
              <div class="sp-dim-bar" :style="{ width: (currentScore) + '%', background: scoreColor(currentScore) }"></div>
            </div>
            <span class="sp-dim-val" :style="{ color: scoreColor(currentScore), fontWeight: 700 }">{{ currentScore.toFixed(0) }}<span class="sp-dim-max">/100</span></span>
          </div>
        </div>
      </div>
      <div v-else class="sp-empty">选择日期后查看维度拆解</div>
    </div>

    <!-- ========== ④ 策略共振 ========== -->
    <div class="sp-section" v-if="strategyMatrix && Object.keys(strategyMatrix).length">
      <div class="sp-section-header">
        <span class="sp-section-icon">📋</span>
        <span class="sp-section-title">策略共振</span>
        <span class="sp-section-sub">策略×情绪阶段表现矩阵，哪类策略在哪个阶段最强</span>
      </div>
      <div class="sp-matrix-wrap">
        <table class="sp-matrix">
          <thead><tr><th>策略</th><th>🥶 冰点</th><th>🌀 震荡</th><th>⚡ 分化</th><th>🔥 高潮</th><th>合计</th></tr></thead>
          <tbody>
            <tr v-for="(periods, strat) in strategyMatrix" :key="strat">
              <td class="sp-m-strat">{{ stratName(strat as string) }}</td>
              <td v-for="col in ['冰点','震荡','分化','高潮']" :key="col" class="sp-m-cell">
                <template v-if="(periods as any)[col]">
                  <div class="sp-m-count" :class="(periods as any)[col].total_pnl >= 0 ? 'up' : 'down'">{{ (periods as any)[col].count }}笔</div>
                  <div class="sp-m-wr" :class="(periods as any)[col].win_rate >= 50 ? 'up' : 'down'">WR{{ (periods as any)[col].win_rate }}%</div>
                  <div class="sp-m-pnl" :class="(periods as any)[col].total_pnl >= 0 ? 'up' : 'down'">¥{{ (periods as any)[col].total_pnl }}</div>
                </template>
                <span v-else class="sp-m-empty">-</span>
              </td>
              <td class="sp-m-total">{{ Object.values(periods).reduce((s: number, v: any) => s + (v.count || 0), 0) }}笔</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ========== 阶段说明 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">📖</span>
        <span class="sp-section-title">四阶段说明</span>
      </div>
      <div class="sp-phase-grid">
        <div v-for="p in phaseGuide" :key="p.name" class="sp-phase-card" :class="{ active: currentPeriodCN === p.name }" :style="{ borderColor: p.color }">
          <div class="sp-phase-head" :style="{ background: p.color + '15' }">
            <span class="sp-phase-icon">{{ p.icon }}</span>
            <span class="sp-phase-name" :style="{ color: p.color }">{{ p.name }}</span>
            <span class="sp-phase-range">{{ p.range }}</span>
          </div>
          <div class="sp-phase-body">
            <div class="sp-phase-row"><span>仓位</span><span>{{ p.position }}</span></div>
            <div class="sp-phase-row"><span>开仓</span><span>{{ p.canOpen }}</span></div>
            <div class="sp-phase-row"><span>策略</span><span>{{ p.strategy }}</span></div>
            <div class="sp-phase-row"><span>持仓上限</span><span>{{ dynamicPositions[{ '高潮': 'rising', '分化': 'differentiation', '震荡': 'chaos', '冰点': 'bearish' }[p.name] as string] || 6 }}只</span></div>
            <div class="sp-phase-row"><span>仓位系数</span><span>{{ ((positionMap[{ '高潮': 'rising', '分化': 'differentiation', '震荡': 'chaos', '冰点': 'bearish' }[p.name] as string] || 0.3) * 100).toFixed(0) }}%</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 降级调仓规则 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">⚠️</span>
        <span class="sp-section-title">降级调仓</span>
        <span class="sp-section-sub">情绪阶段下降时自动执行的调仓动作</span>
      </div>
      <div class="sp-dg-list">
        <div v-for="r in downgradeRules" :key="r.from + r.to" class="sp-dg-row">
          <span class="sp-dg-from" :style="{ color: phaseColors[r.from] }">{{ r.from }}</span>
          <span class="sp-dg-arrow">→</span>
          <span class="sp-dg-to" :style="{ color: phaseColors[r.to] }">{{ r.to }}</span>
          <span class="sp-dg-action">{{ r.action }}</span>
          <span class="sp-dg-desc">{{ r.desc }}</span>
        </div>
      </div>
    </div>

    <!-- ========== ⑤ 今日总结 ========== -->
    <div class="sp-section" v-if="dailyReview || liveLog.length">
      <div class="sp-section-header">
        <span class="sp-section-icon">📋</span>
        <span class="sp-section-title">今日总结</span>
      </div>

      <!-- 一句话综合判断 -->
      <div class="sp-sum-sentence">
        <span class="sp-sum-emoji">{{ todayOverallEmoji }}</span>
        <span>今日情绪<b :style="{color: scoreColor(todayOverallScore)}">{{ todayOverallScore.toFixed(0) }}分</b>，<b>{{ todayOverallCN }}</b>。</span>
        <span>{{ todayOneLineSummary }}</span>
      </div>

      <!-- 盘中vs盘后对比 -->
      <div class="sp-sum-compare" v-if="liveLog.length">
        <div class="sp-sc-card">
          <div class="sp-sc-label">📈 盘中7维</div>
          <div class="sp-sc-score" :style="{color: scoreColor(intradayAvg)}">{{ intradayAvg.toFixed(0) }}</div>
          <div class="sp-sc-range">{{ intradayMin.toFixed(0) }} ~ {{ intradayMax.toFixed(0) }}</div>
          <div class="sp-sc-desc">{{ intradayPhaseCN }} · {{ liveLog.length }}次采样</div>
        </div>
        <div class="sp-sc-vs">vs</div>
        <div class="sp-sc-card">
          <div class="sp-sc-label">📊 盘后5维</div>
          <div class="sp-sc-score" :style="{color: scoreColor(currentScore)}">{{ currentScore.toFixed(0) }}</div>
          <div class="sp-sc-range">收盘后一次计算</div>
          <div class="sp-sc-desc">{{ currentPeriodCN }}</div>
        </div>
        <div class="sp-sc-card">
          <div class="sp-sc-label">🔄 阶段转换</div>
          <div class="sp-sc-score" style="color:#e6a23c">{{ intradayTransitions }}</div>
          <div class="sp-sc-range">次</div>
          <div class="sp-sc-desc">{{ intradayTransitions > 20 ? '极不稳定' : intradayTransitions > 10 ? '波动较大' : '相对稳定' }}</div>
        </div>
      </div>

      <!-- 盘中阶段分布条 -->
      <div class="sp-sum-phases" v-if="liveLog.length">
        <span class="sp-sp-label">盘中阶段分布</span>
        <div class="sp-sp-bar">
          <div class="sp-sp-seg" v-for="p in intradayPhaseDist" :key="p.phase" :style="{flex: p.pct, background: phaseColors[p.phase] || '#999'}">
            <span class="sp-sp-text" v-if="p.pct >= 10">{{ p.cn }}{{ p.pct }}%</span>
          </div>
        </div>
      </div>

      <!-- 纪律 -->
      <div v-if="dailyReview?.discipline_check" class="sp-sum-row">
        <span class="sp-sum-label">执行纪律</span>
        <template v-if="dailyReview.discipline_check.violation_count === 0">
          <span class="sp-sum-good">✅ 全部遵守，执行率{{ dailyReview.discipline_check.execution_rate }}%</span>
        </template>
        <template v-else>
          <span class="sp-sum-bad">⚠️ 违纪{{ dailyReview.discipline_check.violation_count }}次，执行率{{ dailyReview.discipline_check.execution_rate }}%</span>
          <div class="sp-sum-violations">
            <span v-for="v in dailyReview.discipline_check.violations.slice(0, 3)" :key="v.ts_code" class="sp-sum-vio">
              {{ v.severity === 'high' ? '🔴' : '🟡' }}{{ v.ts_code }} {{ v.side === 'buy' ? '买入' : '卖出' }}违反「{{ v.violation }}」
            </span>
          </div>
        </template>
      </div>
      <!-- 盈亏 -->
      <div v-if="dailyReview?.strategy_summary && Object.keys(dailyReview.strategy_summary).length" class="sp-sum-row">
        <span class="sp-sum-label">今日盈亏</span>
        <span :class="totalPnl >= 0 ? 'sp-sum-good' : 'sp-sum-bad'">{{ totalPnl >= 0 ? '💰' : '💸' }}{{ totalPnl >= 0 ? '+' : '' }}¥{{ totalPnl.toLocaleString() }}</span>
        <span class="sp-sum-detail">
          （<span v-for="(info, strat, idx) in dailyReview.strategy_summary" :key="strat">
            {{ idx > 0 ? ' · ' : '' }}{{ stratName(strat as string) }}{{ (info.total_pnl || 0) >= 0 ? '+' : '' }}¥{{ info.total_pnl || 0 }}
          </span>）
        </span>
      </div>
    </div>

    <!-- ========== ⑥ 明日展望 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">🔮</span>
        <span class="sp-section-title">明日展望</span>
      </div>

      <!-- 综合评分 -->
      <div class="sp-tomorrow-advice">
        <div class="sp-ta-head" :class="heroClass(tomorrowCompositeScore)">
          {{ tomorrowEmoji }} 明日建议: {{ tomorrowActionCN }}
        </div>
        <div class="sp-ta-body">{{ tomorrowAnalysis }}</div>
      </div>

      <!-- 三维分析 -->
      <div class="sp-ta-dims">
        <div class="sp-ta-dim">
          <div class="sp-ta-dim-head"><span class="sp-ta-dim-icon">📊</span><span>盘后定调</span></div>
          <div class="sp-ta-dim-val" :style="{color: scoreColor(currentScore)}">{{ currentScore.toFixed(0) }}分 · {{ currentPeriodCN }}</div>
          <div class="sp-ta-dim-desc">收盘后5维最终结论，决定明日基础仓位</div>
        </div>
        <div class="sp-ta-dim">
          <div class="sp-ta-dim-head"><span class="sp-ta-dim-icon">📈</span><span>盘中趋势</span></div>
          <div class="sp-ta-dim-val" :style="{color: scoreColor(intradayAvg)}">{{ intradayAvg.toFixed(0) }}分 · {{ intradayPhaseCN }}</div>
          <div class="sp-ta-dim-desc">{{ intradayTrendDesc }}</div>
        </div>
        <div class="sp-ta-dim">
          <div class="sp-ta-dim-head"><span class="sp-ta-dim-icon">📉</span><span>多日走势</span></div>
          <div class="sp-ta-dim-val" :style="{color: recentTrend === 'falling' ? '#f56c6c' : recentTrend === 'rising' ? '#67c23a' : '#e6a23c'}">
            {{ recentDaysTrendDesc }}
          </div>
          <div class="sp-ta-dim-desc">{{ recentTrend === 'falling' ? '连续走低，不宜抄底' : recentTrend === 'rising' ? '正在回暖，可逐步加仓' : '震荡反复，保持灵活' }}</div>
        </div>
      </div>

      <!-- 仓位建议 -->
      <div class="sp-ta-position">
        <span class="sp-ta-pos-label">建议仓位</span>
        <div class="sp-ta-pos-bar"><div class="sp-ta-pos-fill" :style="{width: (tomorrowPositionPct * 100) + '%', background: scoreColor(tomorrowCompositeScore)}"></div></div>
        <span class="sp-ta-pos-val" :style="{color: scoreColor(tomorrowCompositeScore)}">{{ (tomorrowPositionPct * 100).toFixed(0) }}%</span>
        <span class="sp-ta-pos-hint">持仓上限{{ dynamicPositions[currentPeriod] || 6 }}只</span>
      </div>

      <!-- 策略开关 -->
      <div class="sp-ta-switches">
        <div class="sp-ta-sw-label">策略开关</div>
        <div class="sp-ta-sw-grid">
          <div v-for="s in tomorrowSwitches" :key="s.name" class="sp-ta-sw" :class="s.open ? 'sp-ta-open' : 'sp-ta-closed'">
            <span class="sp-ta-sw-icon">{{ s.open ? '✅' : '🚫' }}</span>
            <span class="sp-ta-sw-name">{{ s.name }}</span>
            <span class="sp-ta-sw-reason">{{ s.reason }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 情绪数据流转 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">🔗</span>
        <span class="sp-section-title">情绪数据流转</span>
        <span class="sp-section-sub">从行情到决策，情绪如何影响每一笔交易</span>
      </div>

      <!-- 主流程: 3步 -->
      <div class="fp-main">
        <!-- Step 1 -->
        <div class="fp-step">
          <div class="fp-step-head fp-blue">
            <div class="fp-step-num">1</div>
            <div class="fp-step-title">行情输入</div>
          </div>
          <div class="fp-step-body">
            <div class="fp-tag fp-blue">涨停池</div>
            <div class="fp-tag fp-blue">跌停池</div>
            <div class="fp-tag fp-blue">涨跌分布</div>
            <div class="fp-tag fp-blue">连板高度</div>
            <div class="fp-tag fp-blue">盘中实时价</div>
          </div>
        </div>
        <!-- Arrow -->
        <div class="fp-arrow">
          <svg width="40" height="24" viewBox="0 0 40 24"><path d="M0,12 L30,12" stroke="var(--text-quaternary)" stroke-width="1.5" stroke-dasharray="4 3"/><path d="M26,6 L34,12 L26,18" fill="none" stroke="var(--text-quaternary)" stroke-width="1.5"/></svg>
        </div>
        <!-- Step 2 -->
        <div class="fp-step">
          <div class="fp-step-head fp-purple">
            <div class="fp-step-num">2</div>
            <div class="fp-step-title">情绪计算</div>
          </div>
          <div class="fp-step-body">
            <div class="fp-formula">
              <div class="fp-fm-row">
                <span class="fp-fm-dot fp-purple"></span>
                <span class="fp-fm-name">盘中7维</span>
                <span class="fp-fm-desc">每次scan(~5min)实时算</span>
              </div>
              <div class="fp-fm-row fp-fm-sub">
                <span>涨停·跌停·涨跌比·动量·炸板率·连板·溢价</span>
              </div>
              <div class="fp-fm-divider"></div>
              <div class="fp-fm-row">
                <span class="fp-fm-dot fp-purple-light"></span>
                <span class="fp-fm-name">盘后5维</span>
                <span class="fp-fm-desc">收盘后一次性算</span>
              </div>
              <div class="fp-fm-row fp-fm-sub">
                <span>涨停·跌停·连板·涨跌比·溢价</span>
              </div>
            </div>
            <div class="fp-mapping">
              <span class="fp-mapping-label">得分 → 阶段 → 仓位系数</span>
              <div class="fp-mapping-bar">
                <div class="fp-mb-seg" style="flex:30;background:#67c23a"><span>🥶&lt;40 冰点 30%</span></div>
                <div class="fp-mb-seg" style="flex:15;background:#409eff"><span>🌀40-55 震荡 50%</span></div>
                <div class="fp-mb-seg" style="flex:15;background:#e6a23c"><span>⚡55-70 分化 70%</span></div>
                <div class="fp-mb-seg" style="flex:30;background:#f56c6c"><span>🔥≥70 高潮 100%</span></div>
              </div>
            </div>
          </div>
        </div>
        <!-- Arrow -->
        <div class="fp-arrow">
          <svg width="40" height="24" viewBox="0 0 40 24"><path d="M0,12 L30,12" stroke="var(--text-quaternary)" stroke-width="1.5" stroke-dasharray="4 3"/><path d="M26,6 L34,12 L26,18" fill="none" stroke="var(--text-quaternary)" stroke-width="1.5"/></svg>
        </div>
        <!-- Step 3 -->
        <div class="fp-step">
          <div class="fp-step-head fp-red">
            <div class="fp-step-num">3</div>
            <div class="fp-step-title">影响决策</div>
          </div>
          <div class="fp-step-body">
            <div class="fp-impact-grid">
              <div class="fp-impact-item">
                <span class="fp-impact-icon">🎚️</span>
                <div>
                  <div class="fp-impact-name">仓位系数</div>
                  <div class="fp-impact-desc">L3层 · 冰点25%~高潮100%</div>
                </div>
              </div>
              <div class="fp-impact-item">
                <span class="fp-impact-icon">🛑</span>
                <div>
                  <div class="fp-impact-name">冰点过滤</div>
                  <div class="fp-impact-desc">L3层 · 半路追涨禁止开仓</div>
                </div>
              </div>
              <div class="fp-impact-item">
                <span class="fp-impact-icon">📦</span>
                <div>
                  <div class="fp-impact-name">持仓上限</div>
                  <div class="fp-impact-desc">冰点4只 ~ 高潮10只</div>
                </div>
              </div>
              <div class="fp-impact-item">
                <span class="fp-impact-icon">📉</span>
                <div>
                  <div class="fp-impact-name">降级调仓</div>
                  <div class="fp-impact-desc">阶段下降时减仓/清仓</div>
                </div>
              </div>
              <div class="fp-impact-item">
                <span class="fp-impact-icon">⚖️</span>
                <div>
                  <div class="fp-impact-name">L8最终仓位</div>
                  <div class="fp-impact-desc">情绪×特殊期×硬上限</div>
                </div>
              </div>
              <div class="fp-impact-item">
                <span class="fp-impact-icon">🎯</span>
                <div>
                  <div class="fp-impact-name">竞价风险</div>
                  <div class="fp-impact-desc">情绪&lt;35时风险评分+10</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 存储层(底部注释) -->
      <div class="fp-storage">
        <div class="fp-storage-item">
          <span class="fp-storage-icon">💾</span>
          <span class="fp-storage-name">sentiment_scores</span>
          <span class="fp-storage-desc">盘后5维 · 每日1条 · 复盘/回测用</span>
        </div>
        <div class="fp-storage-sep">|</div>
        <div class="fp-storage-item">
          <span class="fp-storage-icon">⚡</span>
          <span class="fp-storage-name">sentiment_live_log</span>
          <span class="fp-storage-desc">盘中7维 · 每次scan1条 · TTL 30天</span>
        </div>
        <div class="fp-storage-sep">|</div>
        <div class="fp-storage-item">
          <span class="fp-storage-icon">🧠</span>
          <span class="fp-storage-name">scanner内存</span>
          <span class="fp-storage-desc">_current_sentiment · 实时读取</span>
        </div>
      </div>
    </div>

    <!-- ========== 算法说明 ========== -->
    <div class="sp-section">
      <div class="sp-section-header">
        <span class="sp-section-icon">📐</span>
        <span class="sp-section-title">算法说明</span>
      </div>
      <div class="sp-algo-cards">
        <div class="sp-algo-card">
          <div class="sp-algo-title" style="color: #a855f7">📈 盘中7维公式</div>
          <div class="sp-algo-desc">每次scan(约5分钟)重新计算8个维度的加权得分。动态维度(涨停/跌停/涨跌比/动量/炸板率/今日溢价)占60分，静态维度(连板/昨溢价)占40分。</div>
          <table class="sp-algo-tbl">
            <thead><tr><th>维度</th><th>分值</th><th>来源</th></tr></thead>
            <tbody>
              <tr><td>D1 涨停数量</td><td>0~20</td><td>realtime ≥9.5%</td></tr>
              <tr><td>D2 跌停数量</td><td>0~15</td><td>realtime ≤-9.5%</td></tr>
              <tr><td>D3 涨跌家数比</td><td>0~15</td><td>pct_chg分布</td></tr>
              <tr><td>D4 涨跌加速度</td><td>-5~10</td><td>涨跌比变化率</td></tr>
              <tr><td>D5 涨停开板率</td><td>0~10</td><td>炸板/曾涨停</td></tr>
              <tr><td>D6 最高连板</td><td>0~10</td><td>limit_list缓存</td></tr>
              <tr><td>D7 昨日涨停溢价</td><td>0~5</td><td>zt_premium缓存</td></tr>
              <tr><td>D8 今日涨停溢价</td><td>0~5</td><td>涨停股当前涨幅</td></tr>
            </tbody>
          </table>
        </div>
        <div class="sp-algo-card">
          <div class="sp-algo-title" style="color: #409eff">📊 盘后5维公式</div>
          <div class="sp-algo-desc">收盘后从MongoDB(limit_list + stock_daily_ak_full)计算5个维度。每日1条，存入sentiment_scores集合。四级数据源降级链保证数据完整性。</div>
          <table class="sp-algo-tbl">
            <thead><tr><th>维度</th><th>分值</th><th>来源</th></tr></thead>
            <tbody>
              <tr><td>涨停数量</td><td>0~30</td><td>limit_list→daily→估算</td></tr>
              <tr><td>跌停数量</td><td>0~20</td><td>同上四级降级</td></tr>
              <tr><td>最高连板高度</td><td>0~20</td><td>limit_times反推</td></tr>
              <tr><td>涨跌家数比</td><td>0~15</td><td>pct_chg统计</td></tr>
              <tr><td>昨日涨停溢价</td><td>0~15</td><td>批量查询</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.sp-page { padding: 16px; }

.sp-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.sp-title { font-size: 18px; font-weight: 800; margin: 0; }

/* ===== Hero ===== */
.sp-hero { display: flex; align-items: center; gap: 16px; padding: 12px 16px; border-radius: 8px; margin-bottom: 12px; }
.sp-hero.hot { background: linear-gradient(135deg, rgba(245,108,108,0.12), rgba(245,108,108,0.03)); border: 1px solid rgba(245,108,108,0.25); }
.sp-hero.warm { background: linear-gradient(135deg, rgba(230,162,60,0.10), rgba(230,162,60,0.03)); border: 1px solid rgba(230,162,60,0.2); }
.sp-hero.neutral { background: linear-gradient(135deg, rgba(64,158,255,0.10), rgba(64,158,255,0.03)); border: 1px solid rgba(64,158,255,0.18); }
.sp-hero.cold { background: linear-gradient(135deg, rgba(103,194,58,0.10), rgba(103,194,58,0.03)); border: 1px solid rgba(103,194,58,0.18); }
.sp-hero-left { display: flex; align-items: baseline; gap: 8px; }
.sp-hero-emoji { font-size: 28px; }
.sp-hero-score { font-size: 32px; font-weight: 800; letter-spacing: -1px; }
.sp-hero-unit { font-size: 12px; font-weight: 400; margin-left: 2px; }
.sp-hero-center { flex: 1; }
.sp-hero-period { font-size: 16px; font-weight: 700; }
.sp-hero-desc { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.sp-hero-right { display: flex; gap: 16px; }
.sp-hero-stat { text-align: center; }
.sp-stat-label { display: block; font-size: 10px; color: var(--text-tertiary); }
.sp-stat-val { font-size: 14px; font-weight: 700; }

/* ===== Section ===== */
.sp-section { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 12px; margin-bottom: 10px; }
.sp-section-header { display: flex; align-items: baseline; gap: 6px; margin-bottom: 8px; }
.sp-section-icon { font-size: 14px; }
.sp-section-title { font-size: 14px; font-weight: 800; }
.sp-section-sub { font-size: 11px; color: var(--text-tertiary); }
.sp-chart { border-radius: 6px; overflow: hidden; }
.sp-empty { padding: 20px; text-align: center; color: var(--text-tertiary); font-size: 12px; }

/* ===== 周期地图时间线 ===== */
.sp-timeline-wrap { }
.sp-tl-legend { display: flex; gap: 16px; margin-bottom: 8px; padding: 4px 8px; background: var(--bg-secondary); border-radius: 4px; }
.sp-tl-leg { font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; gap: 4px; }
.sp-tl-dot { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.sp-tl-grid { display: flex; flex-wrap: wrap; gap: 4px; }
.sp-tl-cell { width: 64px; text-align: center; border-radius: 6px; padding: 6px 2px 4px; cursor: default; transition: transform 0.15s, box-shadow 0.15s; border: 1px solid transparent; }
.sp-tl-cell:hover { transform: translateY(-2px); box-shadow: 0 3px 8px rgba(0,0,0,0.15); z-index: 1; }
.sp-tl-date { font-size: 10px; color: var(--text-tertiary); font-weight: 500; }
.sp-tl-emoji { font-size: 18px; line-height: 1.2; }
.sp-tl-score { font-size: 14px; font-weight: 800; line-height: 1.1; }
.sp-tl-detail { font-size: 9px; color: var(--text-quaternary); margin-top: 1px; }
.sp-tl-hot { background: rgba(245,108,108,0.12); border-color: rgba(245,108,108,0.3); }
.sp-tl-hot .sp-tl-score { color: #f56c6c; }
.sp-tl-warm { background: rgba(230,162,60,0.10); border-color: rgba(230,162,60,0.25); }
.sp-tl-warm .sp-tl-score { color: #e6a23c; }
.sp-tl-neutral { background: rgba(64,158,255,0.10); border-color: rgba(64,158,255,0.2); }
.sp-tl-neutral .sp-tl-score { color: #409eff; }
.sp-tl-cold { background: rgba(103,194,58,0.10); border-color: rgba(103,194,58,0.2); }
.sp-tl-cold .sp-tl-score { color: #67c23a; }
/* 月度摘要 */
.sp-tl-months { display: flex; gap: 12px; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-default); flex-wrap: wrap; }
.sp-tl-month { display: flex; align-items: center; gap: 8px; padding: 4px 10px; background: var(--bg-secondary); border-radius: 4px; font-size: 11px; }
.sp-tl-m-label { font-weight: 700; color: var(--text-secondary); }
.sp-tl-m-avg b { font-weight: 800; }
.sp-tl-m-hot { color: #f56c6c; }
.sp-tl-m-cold { color: #67c23a; }
.sp-tl-m-count { color: var(--text-quaternary); }

/* ===== 维度解剖 ===== */
.sp-dims { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sp-radar { }
.sp-bars { display: flex; flex-direction: column; gap: 6px; justify-content: center; }
.sp-dim-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.sp-dim-label { width: 80px; text-align: right; color: var(--text-secondary); flex-shrink: 0; }
.sp-dim-bar-wrap { flex: 1; height: 10px; background: var(--bg-secondary); border-radius: 3px; overflow: hidden; }
.sp-dim-bar { height: 100%; border-radius: 3px; transition: width 0.4s; }
.sp-dim-val { font-weight: 600; min-width: 40px; font-family: 'Menlo', 'Monaco', monospace; font-size: 12px; }
.sp-dim-max { font-weight: 400; color: var(--text-tertiary); font-size: 10px; }
.sp-dim-total { margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--border-default); }

/* ===== 策略共振 ===== */
.sp-matrix-wrap { overflow-x: auto; }
.sp-matrix { width: 100%; border-collapse: collapse; font-size: 11px; }
.sp-matrix th { padding: 6px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); }
.sp-matrix td { padding: 6px 8px; text-align: center; border-bottom: 1px solid var(--border-default); }
.sp-m-strat { font-weight: 600; text-align: left !important; }
.sp-m-cell { min-width: 80px; }
.sp-m-count { font-weight: 600; }
.sp-m-wr { font-size: 10px; }
.sp-m-pnl { font-size: 10px; font-weight: 600; }
.sp-m-empty { color: var(--text-quaternary); }
.sp-m-total { font-weight: 600; color: var(--text-secondary); }

/* ===== 阶段说明 ===== */
.sp-phase-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sp-phase-card { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; opacity: 0.55; transition: all 0.2s; }
.sp-phase-card.active { opacity: 1; box-shadow: 0 0 0 2px var(--el-color-primary); }
.sp-phase-head { display: flex; align-items: center; gap: 4px; padding: 6px 8px; font-size: 12px; }
.sp-phase-icon { font-size: 16px; }
.sp-phase-name { font-weight: 700; }
.sp-phase-range { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.sp-phase-body { padding: 4px 8px; }
.sp-phase-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.sp-phase-row span:first-child { color: var(--text-tertiary); }

/* ===== 降级规则 ===== */
.sp-dg-list { display: flex; flex-direction: column; gap: 4px; }
.sp-dg-row { display: flex; align-items: center; gap: 8px; padding: 4px 10px; font-size: 11px; background: var(--bg-secondary); border-radius: 4px; }
.sp-dg-from, .sp-dg-to { font-weight: 700; min-width: 28px; }
.sp-dg-arrow { color: var(--text-quaternary); }
.sp-dg-action { color: var(--el-color-warning); font-weight: 600; min-width: 60px; }
.sp-dg-desc { color: var(--text-tertiary); }

/* ===== 算法说明 ===== */
.sp-algo-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.sp-algo-card { padding: 8px 10px; background: var(--bg-secondary); border-radius: 6px; }
.sp-algo-title { font-weight: 700; font-size: 12px; margin-bottom: 4px; }
.sp-algo-desc { font-size: 10px; color: var(--text-tertiary); line-height: 1.5; margin-bottom: 6px; }
.sp-algo-tbl { width: 100%; border-collapse: collapse; font-size: 10px; }
.sp-algo-tbl th { padding: 3px 4px; font-weight: 600; color: var(--text-tertiary); text-align: left; border-bottom: 1px solid var(--border-default); }
.sp-algo-tbl td { padding: 2px 4px; border-bottom: 1px solid var(--border-subtle); }

.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

/* ===== 今日总结 ===== */
.sp-summary-sentence { font-size: 13px; line-height: 1.8; padding: 8px 12px; background: var(--bg-secondary); border-radius: 6px; margin-bottom: 8px; }
.sp-sum-emoji { font-size: 20px; margin-right: 4px; vertical-align: middle; }
.sp-sum-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; padding: 4px 0; flex-wrap: wrap; }
.sp-sum-label { font-weight: 700; color: var(--text-secondary); min-width: 56px; }
.sp-sum-good { color: var(--stock-up); font-weight: 600; }
.sp-sum-bad { color: var(--stock-down); font-weight: 600; }
.sp-sum-detail { color: var(--text-tertiary); }
.sp-sum-violations { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; padding-left: 64px; width: 100%; }
.sp-sum-vio { font-size: 11px; color: var(--text-tertiary); }
/* 盘中vs盘后对比 */
.sp-sum-compare { display: flex; align-items: stretch; gap: 8px; margin-bottom: 8px; }
.sp-sc-card { flex: 1; text-align: center; padding: 8px; background: var(--bg-secondary); border-radius: 6px; }
.sp-sc-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 2px; }
.sp-sc-score { font-size: 28px; font-weight: 800; line-height: 1.1; }
.sp-sc-range { font-size: 10px; color: var(--text-quaternary); }
.sp-sc-desc { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }
.sp-sc-vs { font-size: 12px; color: var(--text-quaternary); align-self: center; font-weight: 700; }
/* 盘中阶段分布条 */
.sp-sum-phases { margin-bottom: 8px; }
.sp-sp-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 3px; display: block; }
.sp-sp-bar { display: flex; height: 18px; border-radius: 4px; overflow: hidden; }
.sp-sp-seg { display: flex; align-items: center; justify-content: center; }
.sp-sp-text { font-size: 9px; font-weight: 700; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.4); }

/* ===== 明日展望 ===== */
.sp-tomorrow-advice { margin-bottom: 10px; }
.sp-ta-head { font-size: 16px; font-weight: 800; padding: 6px 12px; border-radius: 6px; margin-bottom: 6px; }
.sp-ta-head.hot { background: rgba(245,108,108,0.12); color: #f56c6c; }
.sp-ta-head.warm { background: rgba(230,162,60,0.10); color: #e6a23c; }
.sp-ta-head.neutral { background: rgba(64,158,255,0.10); color: #409eff; }
.sp-ta-head.cold { background: rgba(103,194,58,0.10); color: #67c23a; }
.sp-ta-body { font-size: 13px; line-height: 1.7; color: var(--text-secondary); padding: 0 4px; }
.sp-ta-body b { color: var(--text-primary); }
/* 三维分析 */
.sp-ta-dims { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.sp-ta-dim { padding: 8px; background: var(--bg-secondary); border-radius: 6px; }
.sp-ta-dim-head { display: flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; color: var(--text-secondary); margin-bottom: 4px; }
.sp-ta-dim-icon { font-size: 14px; }
.sp-ta-dim-val { font-size: 14px; font-weight: 800; margin-bottom: 2px; }
.sp-ta-dim-desc { font-size: 10px; color: var(--text-tertiary); line-height: 1.4; }
/* 仓位建议 */
.sp-ta-position { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; }
.sp-ta-pos-label { font-weight: 700; color: var(--text-secondary); }
.sp-ta-pos-bar { flex: 1; height: 12px; background: var(--bg-secondary); border-radius: 4px; overflow: hidden; }
.sp-ta-pos-fill { height: 100%; border-radius: 4px; transition: width 0.4s; }
.sp-ta-pos-val { font-size: 18px; font-weight: 800; min-width: 40px; }
.sp-ta-pos-hint { color: var(--text-tertiary); font-size: 11px; }
.sp-ta-switches { margin-bottom: 8px; }
.sp-ta-sw-label { font-size: 12px; font-weight: 700; color: var(--text-secondary); margin-bottom: 4px; }
.sp-ta-sw-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.sp-ta-sw { display: flex; align-items: center; gap: 4px; padding: 5px 8px; border-radius: 5px; font-size: 12px; }
.sp-ta-open { background: rgba(103,194,58,0.06); border: 1px solid rgba(103,194,58,0.15); }
.sp-ta-closed { background: rgba(245,108,108,0.06); border: 1px solid rgba(245,108,108,0.15); }
.sp-ta-sw-icon { font-size: 14px; }
.sp-ta-sw-name { font-weight: 700; }
.sp-ta-sw-reason { color: var(--text-tertiary); font-size: 10px; }
.sp-ta-trend { }
.sp-ta-trend-text { font-size: 12px; color: var(--text-secondary); line-height: 1.6; }

/* ===== 情绪流转(三步卡片) ===== */
.fp-main { display: flex; align-items: flex-start; gap: 0; }
.fp-step { flex: 1; min-width: 0; }
.fp-step-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px 8px 0 0; }
.fp-step-head.fp-blue { background: rgba(64,158,255,0.08); border-bottom: 2px solid #409eff; }
.fp-step-head.fp-purple { background: rgba(168,85,247,0.08); border-bottom: 2px solid #a855f7; }
.fp-step-head.fp-red { background: rgba(245,108,108,0.08); border-bottom: 2px solid #f56c6c; }
.fp-step-num { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; color: #fff; }
.fp-blue .fp-step-num { background: #409eff; }
.fp-purple .fp-step-num { background: #a855f7; }
.fp-red .fp-step-num { background: #f56c6c; }
.fp-step-title { font-size: 13px; font-weight: 700; }
.fp-blue .fp-step-title { color: #409eff; }
.fp-purple .fp-step-title { color: #a855f7; }
.fp-red .fp-step-title { color: #f56c6c; }
.fp-step-body { padding: 10px; }
/* tags */
.fp-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }
.fp-tag.fp-blue { background: rgba(64,158,255,0.08); color: #409eff; border: 1px solid rgba(64,158,255,0.15); }
/* formula */
.fp-formula { margin-bottom: 8px; }
.fp-fm-row { display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 2px 0; }
.fp-fm-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.fp-fm-dot.fp-purple { background: #a855f7; }
.fp-fm-dot.fp-purple-light { background: #a855f7; opacity: 0.5; }
.fp-fm-name { font-weight: 700; color: var(--text-primary); }
.fp-fm-desc { color: var(--text-tertiary); font-size: 10px; }
.fp-fm-sub { padding-left: 14px; color: var(--text-quaternary); font-size: 10px; }
.fp-fm-divider { height: 1px; background: var(--border-default); margin: 4px 0; }
/* mapping bar */
.fp-mapping { }
.fp-mapping-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 3px; display: block; }
.fp-mapping-bar { display: flex; border-radius: 4px; overflow: hidden; height: 22px; }
.fp-mb-seg { display: flex; align-items: center; justify-content: center; font-size: 8px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.4); padding: 0 4px; white-space: nowrap; }
/* arrow */
.fp-arrow { display: flex; align-items: center; padding: 30px 0 0; flex-shrink: 0; }
/* impact grid */
.fp-impact-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.fp-impact-item { display: flex; align-items: flex-start; gap: 6px; padding: 4px 6px; background: var(--bg-secondary); border-radius: 4px; }
.fp-impact-icon { font-size: 14px; line-height: 1; flex-shrink: 0; margin-top: 1px; }
.fp-impact-name { font-size: 11px; font-weight: 700; color: var(--text-primary); }
.fp-impact-desc { font-size: 9px; color: var(--text-tertiary); line-height: 1.3; }
/* storage */
.fp-storage { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border-default); font-size: 11px; }
.fp-storage-item { display: flex; align-items: center; gap: 4px; }
.fp-storage-icon { font-size: 14px; }
.fp-storage-name { font-weight: 700; color: var(--text-secondary); font-family: 'Menlo', monospace; font-size: 11px; }
.fp-storage-desc { color: var(--text-quaternary); font-size: 10px; }
.fp-storage-sep { color: var(--text-quaternary); }
</style>
