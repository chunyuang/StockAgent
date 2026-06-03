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

  const premarketDebugMode = ref(false)
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
      const url = premarketDebugMode.value ? `${scannerApi}/debug/premarket-sim` : `${scannerApi}/premarket-status`
      const r = await api.get(url)
      const p = parseResponse(r)
      if (p.success && p.data) {
        premarketSignals.value = p.data.auction_signals || []
        premarketStatus.value = premarketDebugMode.value ? 'debug' : (p.data.status || 'off')
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
      }
    } catch { /* ignore */ }
  }

  return {
    // 状态
    premarketSignals, premarketStatus, premarketCandidates,
    premarketDebugMode, premarketGroupMode, premarketGroupExpanded,
    premarketAnalysis, premarketBlockedReasons, premarketFunnel,
    premarketHitRate, premarketLimitPools, premarketMarketSnapshot,
    premarketPositionGaps, premarketSentiment, premarketStrategyGroups,
    auctionTopGainers,
    // 方法
    fetchPremarketData,
  }
}
