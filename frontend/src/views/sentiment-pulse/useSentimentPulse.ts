/**
 * useSentimentPulse — 情绪脉搏页面数据 (独立composable, 不依赖scanner实例)
 *
 * 纯只读, 从后端API获取数据, 不修改任何策略/仓位/信号
 */

import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import { getChinaDate } from '@/utils/chinaDate'

const scannerApi = '/scanner'

export function useSentimentPulse() {
  const date = ref(getChinaDate())
  const loading = ref(false)

  // ── ① 实时心电: 盘中live-log + 盘后scores ──
  const liveLog = ref<any[]>([])
  const dailyScores = ref<any[]>([])
  const weeklyScores = ref<any[]>([])
  const monthlyScores = ref<any[]>([])

  // ── ② 周期地图: 日历热力图 ──
  const calendarData = ref<any[]>([])

  // ── ③ 维度解剖: market-sentiment详情 ──
  const marketSentiment = ref<any>(null)

  // ── ④ 策略共振: 矩阵 ──
  const strategyMatrix = ref<any>(null)
  const recommendations = ref<any[]>([])
  // ── ⑤ 每日复盘: forward_advice + discipline_check ──
  const dailyReview = ref<any>(null)
  // ── ⑥ 周期分析: 阶段转换 + 周期统计 ──
  const cycleAnalysis = ref<any>(null)

  // ── 参数配置 ──
  const thresholds = ref({ rising: 70, differentiation: 55, chaos: 40 })
  const positionMap = ref({ rising: 1.0, differentiation: 0.7, chaos: 0.5, bearish: 0.3 })

  // ── 当前快照 ──
  const currentScore = computed(() => marketSentiment.value?.score ?? 0)
  const currentPeriod = computed(() => {
    const s = currentScore.value
    if (s >= thresholds.value.rising) return 'rising'
    if (s >= thresholds.value.differentiation) return 'differentiation'
    if (s >= thresholds.value.chaos) return 'chaos'
    return 'bearish'
  })
  const currentPeriodCN = computed(() => {
    const map: Record<string, string> = { rising: '高潮', differentiation: '分化', chaos: '震荡', bearish: '冰点' }
    return map[currentPeriod.value] || '冰点'
  })
  const currentPositionRatio = computed(() => positionMap.value[currentPeriod.value as keyof typeof positionMap.value] ?? 0.3)

  // phase颜色
  const phaseColors: Record<string, string> = {
    'rising': '#f56c6c', 'differentiation': '#e6a23c', 'chaos': '#409eff', 'bearish': '#67c23a',
    '高潮': '#f56c6c', '分化': '#e6a23c', '震荡': '#409eff', '冰点': '#67c23a',
  }
  function scoreColor(s: number): string { return s >= 70 ? '#f56c6c' : s >= 55 ? '#e6a23c' : s >= 40 ? '#409eff' : '#67c23a' }

  async function fetchAll() {
    loading.value = true
    const dateStr = date.value.replace(/-/g, '')
    try {
      await Promise.allSettled([
        fetchLiveLog(dateStr),
        fetchDailyScores(dateStr),
        fetchCalendarData(),
        fetchMarketSentiment(dateStr),
        fetchStrategyMatrix(dateStr),
        fetchParams(),
        fetchDailyReview(dateStr),
        fetchCycleAnalysis(),
      ])
    } finally {
      loading.value = false
    }
  }

  async function fetchLiveLog(dateStr?: string) {
    try {
      const d = dateStr || date.value.replace(/-/g, '')
      const r = await api.get(`${scannerApi}/sentiment-live-log?limit=200&date=${d}`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) liveLog.value = p.data?.logs || []
    } catch (e) { console.error('[useSentimentPulse] liveLog', e) }
  }

  async function fetchDailyScores(dateStr?: string) {
    try {
      const d = dateStr || date.value.replace(/-/g, '')
      const r = await api.get(`${scannerApi}/sentiment-timeline?date=${d}&mode=daily`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) dailyScores.value = p.data?.points || []
    } catch (e) { console.error('[useSentimentPulse] daily', e) }
  }

  async function fetchCalendarData() {
    try {
      // 取最近120个交易日的盘后情绪
      const r = await api.get(`${scannerApi}/sentiment-timeline?mode=daily`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) calendarData.value = p.data?.points || []
    } catch (e) { console.error('[useSentimentPulse] calendar', e) }
  }

  async function fetchMarketSentiment(dateStr?: string) {
    try {
      const d = dateStr || date.value.replace(/-/g, '')
      const r = await api.get(`${scannerApi}/market-sentiment?date=${d}`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) marketSentiment.value = p.data
    } catch (e) { console.error('[useSentimentPulse] marketSentiment', e) }
  }

  async function fetchStrategyMatrix(dateStr?: string) {
    try {
      const d = dateStr || date.value.replace(/-/g, '')
      const r = await api.get(`${scannerApi}/sentiment-strategy-matrix?date=${d}`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) {
        strategyMatrix.value = p.data?.matrix || null
        recommendations.value = p.data?.recommendations || []
      }
    } catch (e) { console.error('[useSentimentPulse] matrix', e) }
  }

  async function fetchParams() {
    try {
      const r = await api.get('/strategy-config/global-risk', { timeout: 5000 })
      const p = parseResponse(r)
      if (p.success && p.data) {
        const gr = p.data || {}
        if (gr.sentiment_thresholds) thresholds.value = { ...thresholds.value, ...gr.sentiment_thresholds }
        if (gr.sentiment_position_map) positionMap.value = { ...positionMap.value, ...gr.sentiment_position_map }
      }
    } catch (e) { /* non-critical */ }
  }

  async function fetchDailyReview(dateStr?: string) {
    try {
      const d = dateStr || date.value.replace(/-/g, '')
      const r = await api.get(`${scannerApi}/historical-review?date=${d}`, { timeout: 15000 })
      const p = parseResponse(r)
      if (p.success) dailyReview.value = p.data
    } catch (e) { console.error('[useSentimentPulse] dailyReview', e) }
  }

  async function fetchCycleAnalysis() {
    try {
      // 取最近80天的sentiment_scores, 前端做阶段转换分析
      const r = await api.get(`${scannerApi}/sentiment-timeline?mode=daily`, { timeout: 10000 })
      const p = parseResponse(r)
      if (!p.success || !p.data?.points?.length) return
      const points = p.data.points
      // 阶段转换
      const transitions: any[] = []
      for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1], curr = points[i]
        const prevP = prev.score >= 70 ? 'rising' : prev.score >= 55 ? 'differentiation' : prev.score >= 40 ? 'chaos' : 'bearish'
        const currP = curr.score >= 70 ? 'rising' : curr.score >= 55 ? 'differentiation' : curr.score >= 40 ? 'chaos' : 'bearish'
        if (prevP !== currP) {
          transitions.push({
            from_date: prev.date, from_period: prevP, from_score: prev.score,
            to_date: curr.date, to_period: currP, to_score: curr.score,
            direction: curr.score > prev.score ? 'up' : 'down',
          })
        }
      }
      // 阶段持续统计
      const phaseStreaks: any[] = []
      let streak: any = null
      for (const p of points) {
        const phase = p.score >= 70 ? 'rising' : p.score >= 55 ? 'differentiation' : p.score >= 40 ? 'chaos' : 'bearish'
        if (!streak || streak.phase !== phase) {
          if (streak) phaseStreaks.push(streak)
          streak = { phase, start: p.date, end: p.date, count: 1, scores: [p.score] }
        } else {
          streak.end = p.date
          streak.count++
          streak.scores.push(p.score)
        }
      }
      if (streak) phaseStreaks.push(streak)
      // 计算每个streak的均值
      for (const s of phaseStreaks) {
        s.avgScore = (s.scores.reduce((a: number, b: number) => a + b, 0) / s.scores.length).toFixed(1)
      }
      // 阶段分布统计
      const dist: Record<string, number> = { rising: 0, differentiation: 0, chaos: 0, bearish: 0 }
      for (const p of points) {
        const phase = p.score >= 70 ? 'rising' : p.score >= 55 ? 'differentiation' : p.score >= 40 ? 'chaos' : 'bearish'
        dist[phase]++
      }
      cycleAnalysis.value = { transitions, phaseStreaks, dist, totalDays: points.length }
    } catch (e) { console.error('[useSentimentPulse] cycleAnalysis', e) }
  }

  return {
    date, loading,
    liveLog, dailyScores, weeklyScores, monthlyScores,
    calendarData, marketSentiment, strategyMatrix, recommendations,
    dailyReview, cycleAnalysis,
    thresholds, positionMap,
    currentScore, currentPeriod, currentPeriodCN, currentPositionRatio,
    phaseColors, scoreColor,
    fetchAll, fetchLiveLog, fetchDailyScores, fetchCalendarData, fetchMarketSentiment, fetchStrategyMatrix,
  }
}
