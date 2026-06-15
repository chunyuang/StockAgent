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
  // 默认空字符串, fetchPremarketData会自动选最近交易日
  // (避免周末/节假日默认选今天导致无数据)
  const premarketDate = ref('')
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
      const today = new Date()
      const todayStr = today.toISOString().slice(0, 10)
      const isOtherDate = premarketDate.value && premarketDate.value !== todayStr
      const isWeekend = today.getDay() === 0 || today.getDay() === 6
      
      // 决定是否用debug/sim API:
      // 1. 用户手动开了debug → 用
      // 2. 选了非今天的日期 → 用(只有sim支持date参数)
      // 3. 周末/节假日 → 用(没有实时数据)
      // 4. 交易日非竞价时段 → 也用! (scanner没运行时premarket-status返回空数据)
      //    竞价时段(9:00-9:25)且scanner运行中 → 用premarket-status
      const hhmm = today.getHours() * 100 + today.getMinutes()
      const isInAuctionWindow = !isWeekend && hhmm >= 900 && hhmm < 925
      const useDebug = premarketDebugMode.value || isOtherDate || isWeekend || !isInAuctionWindow
      
      const dateParam = premarketDate.value ? `date=${premarketDate.value.replace(/-/g, '')}` : ''
      let url = useDebug 
        ? `${scannerApi}/debug/premarket-sim${dateParam ? '?' + dateParam : ''}`
        : `${scannerApi}/premarket-status${dateParam ? '?' + dateParam : ''}`
      let r = await api.get(url)
      let p = parseResponse(r)
      // 【v2.9.83修复】premarket-status可能因scanner未运行返回空数据(candidates=[]且market_snapshot={})
      // 【v2.9.92s扩展】竞价时段scanner运行但行情缓存未就绪也返回candidates=[]
      // 自动回退到debug/premarket-sim获取完整MongoDB数据
      if (!useDebug && p.success && p.data && (!p.data.candidates?.length)) {
        url = `${scannerApi}/debug/premarket-sim${dateParam ? '?' + dateParam : ''}`
        r = await api.get(url)
        p = parseResponse(r)
      }
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

        // 从API响应回填实际数据日期(周末/节假日可能回退到上一交易日)
        const dataDate = p.data.market_snapshot?.data_date
        if (dataDate && !premarketDate.value) {
          // 首次加载: 设置日期为实际数据日期
          const ds = String(dataDate)
          premarketDate.value = ds.length === 8 ? `${ds.slice(0,4)}-${ds.slice(4,6)}-${ds.slice(6,8)}` : ds
        }

        // 修正status: debug API统一返回status='debug', 但根据实际时间应该显示更有意义的标签
        // 交易日9:30前 → waiting(等待竞价)
        // 交易日9:30后 → ended(竞价已结束,可查看当日预选)
        // 周末/节假日 → debug(调试模式)
        if (premarketStatus.value === 'debug') {
          const now2 = new Date()
          const day2 = now2.getDay()
          const hhmm2 = now2.getHours() * 100 + now2.getMinutes()
          if (day2 !== 0 && day2 !== 6) {
            // 交易日
            if (hhmm2 < 915) {
              premarketStatus.value = 'waiting'
            } else if (hhmm2 < 925) {
              premarketStatus.value = 'active'
            } else {
              premarketStatus.value = 'ended'
            }
          }
        }

        // 不再自动开启debug: 交易日始终用debug/sim API, 周末也用
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

  /** 判断当前是否非交易时间(盘前9:00之前、盘后15:30之后、周末) - 暴露给模板使用 */
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
    fetchPremarketData, isNonTradingHours,
  }
}
