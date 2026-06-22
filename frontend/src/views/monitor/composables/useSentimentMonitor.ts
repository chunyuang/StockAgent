/**
 * useSentimentMonitor - 情绪数据管理
 * 
 * 从useScannerMonitor拆出的情绪功能域
 * 管理: 情绪时间线/矩阵/建议/阶段指南
 */

import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const scannerApi = '/scanner'

/** 获取中国时区的日期字符串 YYYY-MM-DD */
function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const y = china.getFullYear()
  const m = String(china.getMonth() + 1).padStart(2, '0')
  const d = String(china.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function useSentimentMonitor() {
  // 【v2.9.97h-v13】默认显示日内模式(用户更关心当下情绪而非历史日线)
  const sentimentMode = ref<'intraday' | 'daily' | 'weekly' | 'monthly'>('intraday')
  const sentimentDate = ref(getChinaDate())
  const hoveredPoint = ref<any>(null)
  // 每个模式独立缓存, 切换时不会清空
  const sentimentCache = ref<Record<string, any[]>>({})
  const sentimentTradesCache = ref<Record<string, any[]>>({})
  const sentimentTimeline = computed(() => sentimentCache.value[sentimentMode.value] || [])
  const sentimentTrades = computed(() => sentimentTradesCache.value[sentimentMode.value] || [])
  // displayTimeline: 日内无数据时fallback日线，标注清楚
  const displayTimeline = computed(() => {
    const data = sentimentTimeline.value
    if (sentimentMode.value === 'intraday' && !data.length) {
      const dailyData = sentimentCache.value['daily'] || []
      return dailyData.slice(-60)
    }
    return data
  })
  const isIntradayFallback = computed(() => sentimentMode.value === 'intraday' && !sentimentTimeline.value.length && (sentimentCache.value['daily'] || []).length > 0)
  // 日内模式candidates最大值(用于归一化Y轴)
  const intradayMaxCand = computed(() => {
    if (sentimentMode.value !== 'intraday') return 0
    const data = displayTimeline.value
    if (!data.length) return 0
    return Math.max(...data.map(p => p.candidates || 0), 1)
  })
  // X轴标签: 采样+可读格式
  const xAxisLabels = computed(() => {
    const data = displayTimeline.value
    if (!data.length) return []
    const maxLabels = sentimentMode.value === 'intraday' ? 6 : 8
    const step = Math.max(Math.ceil(data.length / maxLabels), 1)
    const sampled = data.filter((_, idx) => idx % step === 0)
    return sampled.map(p => {
      const d = p.date || ''
      if (sentimentMode.value === 'intraday') {
        return p.time?.substring(11, 16) || ''
      } else if (sentimentMode.value === 'weekly') {
        const wi = d.indexOf('-W')
        if (wi >= 0) {
          const yr = d.substring(2, 4)
          const wk = parseInt(d.substring(wi + 2)) || 1
          const mon = Math.min(Math.ceil(wk * 7 / 30), 12)
          return yr + '/' + String(mon).padStart(2, '0')
        }
        return d
      } else if (sentimentMode.value === 'monthly') {
        return d.length >= 6 ? d.substring(2, 4) + '/' + d.substring(4, 6) : d
      } else {
        return d.length >= 8 ? d.substring(4, 6) + '/' + d.substring(6, 8) : d
      }
    })
  })
  const sentimentMatrix = ref<any>(null)
  const sentimentRecommendations = ref<any[]>([])
  const sentimentLoading = ref(false)
  const sentimentLive = ref<any>(null)  // 实时情绪快照

  // 情绪阶段指南(固定数据)
  const phaseGuide = computed(() => {
    const cur = sentimentLive.value?.period_label || ''
    return [
      { name: '高潮', icon: '🔥', range: '≥70分', color: '#f56c6c', position: '100%', canOpen: '✅ 全部', strategy: '所有策略开放', advice: '满仓操作，可追涨打板、龙头低吸、跌停翘板', active: cur.includes('高潮') },
      { name: '分化', icon: '⚖️', range: '55-70分', color: '#409eff', position: '70%', canOpen: '✅ 精选', strategy: '仅龙头低吸+半路追涨', advice: '降仓位至70%，只做最强龙头，避免追风股', active: cur.includes('分化') },
      { name: '震荡', icon: '🌊', range: '40-55分', color: '#e6a23c', position: '50%', canOpen: '⚠️ 轻仓', strategy: '仅龙头低吸(半仓)', advice: '轻仓试错，严格止损3%，快进快出', active: cur.includes('震荡') },
      { name: '冰点', icon: '❄️', range: '<40分', color: '#67c23a', position: '30%', canOpen: '❌ 禁止', strategy: '禁止新开仓', advice: '极度弱势，禁止新开仓，持仓严格执行止损，亏损标的优先平仓', active: cur.includes('冰点') },
    ]
  })

  // 情绪降级调仓规则
  const downgradeRules = [
    { from: '分化', to: '冰点', action: '禁开仓', desc: '禁止新开仓，仓位≤30%' },
    { from: '高潮', to: '分化', action: '减仓50%', desc: '保留核心仓位' },
    { from: '高潮', to: '冰点', action: '清低利润', desc: '急转直下，保命优先' },
    { from: '震荡', to: '冰点', action: '禁开仓', desc: '禁止新开仓，仓位≤30%' },
    { from: '分化', to: '震荡', action: '减仓60%', desc: '仅保留最强持仓' },
    { from: '高潮', to: '震荡', action: '减仓50%', desc: '市场转弱，保留核心' },
  ]

  const phaseColors: Record<string, string> = { '高潮': '#f56c6c', '分化': '#409eff', '震荡': '#e6a23c', '冰点': '#67c23a' }

  // 基于当前情绪的智能建议
  const sentimentAdvice = computed(() => {
    const s = sentimentLive.value
    if (!s) return '选择日期后查看建议'
    const score = s.score || 0
    const lu = s.limit_up_count || 0
    const ld = s.limit_down_count || 0
    if (score >= 70) return `市场高潮，涨停${lu}只，赚钱效应强。可满仓操作，所有策略开放。注意高潮末端可能突然分化，设好止盈。`
    if (score >= 55) return `市场分化，涨停${lu}只跌停${ld}只。建议降仓位至50-70%，只做最强龙头，避免追高跟风股。`
    if (score >= 40) return `市场震荡，涨停${lu}只跌停${ld}只。建议轻仓25-40%试错，严格止损3%，快进快出，不恋战。`
    return `市场冰点，跌停${ld}只，极度弱势。禁止新开仓，持仓严格执行止损，亏损标的优先平仓。等待情绪回暖信号。`
  })

  async function fetchSentimentData() {
    sentimentLoading.value = true
    try {
      const opts = { timeout: 15000 }
      const dateParam = sentimentDate.value.replace(/-/g, '')
      const currentMode = sentimentMode.value
      const [tlRes, matRes, liveRes] = await Promise.allSettled([
        api.get(`${scannerApi}/sentiment-timeline?date=${dateParam}&mode=${currentMode}`, opts),
        api.get(`${scannerApi}/sentiment-strategy-matrix?date=${dateParam}`, opts),
        api.get(`${scannerApi}/market-sentiment?date=${dateParam}`, opts),
      ])
      if (tlRes.status === 'fulfilled') {
        const p = parseResponse(tlRes.value)
        if (p.success) { sentimentCache.value = { ...sentimentCache.value, [currentMode]: p.data?.points || [] }; sentimentTradesCache.value = { ...sentimentTradesCache.value, [currentMode]: p.data?.trades || [] } }
      }
      if (matRes.status === 'fulfilled') { const p = parseResponse(matRes.value); if (p.success) { sentimentMatrix.value = p.data?.matrix || {}; sentimentRecommendations.value = p.data?.recommendations || [] } }
      if (liveRes.status === 'fulfilled') { const p = parseResponse(liveRes.value); if (p.success) sentimentLive.value = p.data }
    } catch { /* ignore */ }
    finally { sentimentLoading.value = false }
  }

  return {
    sentimentMode, sentimentDate, hoveredPoint,
    sentimentCache, sentimentTradesCache,
    sentimentTimeline, sentimentTrades,
    displayTimeline, isIntradayFallback, intradayMaxCand,
    xAxisLabels, sentimentMatrix, sentimentRecommendations,
    sentimentLoading, sentimentLive,
    phaseGuide, downgradeRules, phaseColors, sentimentAdvice,
    fetchSentimentData,
  }
}
