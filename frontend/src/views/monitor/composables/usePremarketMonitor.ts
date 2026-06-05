/**
 * usePremarketMonitor - 盘前竞价域
 * 
 * 从useScannerMonitor拆出的盘前竞价相关逻辑
 * 管理: premarketSignals/premarketStatus/premarketCandidates
 */

import { ref } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const scannerApi = '/scanner'

export function usePremarketMonitor() {
  // ==================== 盘前竞价状态 ====================
  const premarketSignals = ref<any[]>([])
  const premarketStatus = ref<'waiting' | 'active' | 'ended' | 'off' | 'debug'>('off')
  const premarketCandidates = ref<any[]>([])

  // 用户手动控制debug开关，不自动覆盖
  const premarketDebugMode = ref(false)
  // 追踪用户是否手动切换过debug，防止自动重开
  const premarketDebugUserToggled = ref(false)
  // 盘前日期选择(默认今天)
  const premarketDate = ref(new Date().toISOString().slice(0, 10))
  const premarketGroupMode = ref<'strategy' | 'industry' | 'list'>('strategy')
  const premarketGroupExpanded = ref<Record<string, boolean>>({})
  const premarketAnalysis = ref<any>(null)
  const premarketBlockedReasons = ref<any>({})
  const premarketFunnel = ref<any>(null)
  const premarketHitRate = ref<Record<string, any>>({})
  const premarketLimitPools = ref<any>(null)
  const premarketMarketSnapshot = ref<any>({})
  const premarketPositionGaps = ref<any[]>([])
  const premarketSentiment = ref<any>({})
  const premarketStrategyGroups = ref<any[]>([])
  const auctionTopGainers = ref<any[]>([])

  // ==================== API ====================
  async function fetchPremarketData() {
    try {
      // 选了非今天的日期时, 强制走debug/sim API(只有它支持历史日期)
      const today = new Date().toISOString().slice(0, 10)
      const isOtherDate = premarketDate.value && premarketDate.value !== today
      // 只有用户未手动关闭且在非交易时间才自动用debug模式
      const useDebug = premarketDebugMode.value || isOtherDate || (isNonTradingHours() && !premarketDebugUserToggled.value)
      const dateParam = premarketDate.value ? `&date=${premarketDate.value.replace(/-/g, '')}` : ''
      const url = useDebug ? `${scannerApi}/debug/premarket-sim?${dateParam.slice(1)}` : `${scannerApi}/premarket-status${dateParam ? '?' + dateParam.slice(1) : ''}`
      const r = await api.get(url)
      const p = parseResponse(r)
      // 捕获API错误消息(如无该日期数据)
      const errorMsg = (r as any)?.message || ''
      if (p.success && p.data) {
        premarketSignals.value = p.data.auction_signals || []
        premarketStatus.value = p.data.status || 'off'
        premarketCandidates.value = p.data.candidates || []
        auctionTopGainers.value = p.data.top_gainers || []
        premarketMarketSnapshot.value = p.data.market_snapshot || {}
        premarketSentiment.value = p.data.sentiment || {}
        premarketStrategyGroups.value = p.data.strategy_groups || []
        premarketHitRate.value = p.data.historical_hit_rate || {}
        premarketFunnel.value = p.data.funnel || null
        premarketBlockedReasons.value = p.data.blocked_reasons || {}
        premarketLimitPools.value = p.data.limit_pools || null
        premarketPositionGaps.value = p.data.position_gaps || []
        premarketAnalysis.value = p.data.analysis || null

        // 仅在初始加载(用户未手动切换)且非交易时间时自动开启debug
        // 用户手动关闭后不再自动重开
        if (!premarketDebugUserToggled.value && !premarketDebugMode.value && isNonTradingHours() && premarketStatus.value === 'off') {
          premarketDebugMode.value = true
        }
      } else if (!p.success) {
        // API返回失败(如无该日期数据), 清空并提示
        premarketCandidates.value = []
        premarketSignals.value = []
        premarketStatus.value = 'off'
        premarketMarketSnapshot.value = { data_date: premarketDate.value?.replace(/-/g, ''), error: errorMsg || '无数据' }
        premarketStrategyGroups.value = []
      }
    } catch { /* ignore */ }
  }

  /** 判断当前是否非交易时间(盘前9:00之前、盘后15:30之后、周末) */
  function isNonTradingHours(): boolean {
    const now = new Date()
    const day = now.getDay()
    const hhmm = now.getHours() * 100 + now.getMinutes()
    // 周末 或 9:00前 或 15:30后
    return day === 0 || day === 6 || hhmm < 900 || hhmm >= 1530
  }

  return {
    // 状态
    premarketSignals, premarketStatus, premarketCandidates,
    premarketDebugMode, premarketDebugUserToggled, premarketDate, premarketGroupMode, premarketGroupExpanded,
    premarketAnalysis, premarketBlockedReasons, premarketFunnel,
    premarketHitRate, premarketLimitPools, premarketMarketSnapshot,
    premarketPositionGaps, premarketSentiment, premarketStrategyGroups,
    auctionTopGainers,
    // 方法
    fetchPremarketData,
  }
}
