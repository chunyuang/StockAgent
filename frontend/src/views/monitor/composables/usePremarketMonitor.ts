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

  // 盘前分析辅助(后续逐步实现)
  const premarketDebugMode = ref(false)
  const premarketGroupMode = ref<'strategy' | 'industry' | 'list'>('strategy')
  const premarketGroupExpanded = ref<Record<string, boolean>>({})
  const premarketAnalysis = ref<any>(null)
  const premarketBlockedReasons = ref<string[]>([])
  const premarketFunnel = ref<any>(null)
  const premarketHitRate = ref<any>(null)
  const premarketLimitPools = ref<any>(null)
  const premarketMarketSnapshot = ref<any>(null)
  const premarketPositionGaps = ref<any[]>([])
  const premarketSentiment = ref<any>(null)
  const premarketStrategyGroups = ref<any[]>([])
  const auctionTopGainers = ref<any[]>([])

  // ==================== API ====================
  async function fetchPremarketData() {
    try {
      const r = await api.get(`${scannerApi}/premarket-status`)
      const p = parseResponse(r)
      if (p.success && p.data) {
        premarketSignals.value = p.data.auction_signals || []
        premarketStatus.value = p.data.status || 'off'
        premarketCandidates.value = p.data.candidates || []
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
