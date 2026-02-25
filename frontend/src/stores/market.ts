/**
 * Market Store - 市场数据状态管理
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { stockApi } from '@/api'
import type { MarketOverview, StockQuote, StockBasic } from '@/api/types'

export const useMarketStore = defineStore('market', () => {
  // ==================== 状态 ====================
  
  /** 大盘概览 */
  const overview = ref<MarketOverview | null>(null)
  
  /** 实时行情缓存 (ts_code -> StockQuote) */
  const quotesMap = ref<Map<string, StockQuote>>(new Map())
  
  /** 股票基本信息缓存 (ts_code -> StockBasic) */
  const stockBasicMap = ref<Map<string, StockBasic>>(new Map())
  
  /** 行业列表 */
  const industries = ref<string[]>([])
  
  /** 加载状态 */
  const loading = ref(false)
  
  /** 上次更新时间 */
  const lastUpdated = ref<Date | null>(null)
  
  // ==================== 计算属性 ====================
  
  /** 上证指数 */
  const shIndex = computed(() => overview.value?.sh_index || 0)
  
  /** 上证涨跌幅 */
  const shChange = computed(() => overview.value?.sh_change || 0)
  
  /** 深证指数 */
  const szIndex = computed(() => overview.value?.sz_index || 0)
  
  /** 深证涨跌幅 */
  const szChange = computed(() => overview.value?.sz_change || 0)
  
  /** 创业板指数 */
  const cybIndex = computed(() => overview.value?.cyb_index || 0)
  
  /** 创业板涨跌幅 */
  const cybChange = computed(() => overview.value?.cyb_change || 0)
  
  /** 涨跌统计 */
  const marketStats = computed(() => ({
    up: overview.value?.up_count || 0,
    down: overview.value?.down_count || 0,
    flat: overview.value?.flat_count || 0,
    limitUp: overview.value?.limit_up || 0,
    limitDown: overview.value?.limit_down || 0,
  }))
  
  /** 热门板块 */
  const hotSectors = computed(() => overview.value?.hot_sectors || [])
  
  // ==================== Actions ====================
  
  /** 获取大盘概览 */
  async function fetchOverview(): Promise<void> {
    loading.value = true
    try {
      const data = await stockApi.getMarketOverview()
      overview.value = data
      lastUpdated.value = new Date()
    } finally {
      loading.value = false
    }
  }
  
  /** 获取实时行情 */
  async function fetchQuotes(tsCodes: string[]): Promise<StockQuote[]> {
    // 过滤无效的股票代码
    const validCodes = tsCodes.filter(code => code && code !== 'undefined' && code !== 'null')
    if (validCodes.length === 0) return []
    
    try {
      const quotes = await stockApi.getRealtimeQuotes(validCodes)
      
      // 更新缓存
      for (const quote of quotes) {
        quotesMap.value.set(quote.ts_code, quote)
      }
      
      return quotes
    } catch {
      return []
    }
  }
  
  /** 获取单个行情 */
  function getQuote(tsCode: string): StockQuote | undefined {
    return quotesMap.value.get(tsCode)
  }
  
  /** 获取股票基本信息 */
  async function fetchStockBasic(tsCode: string): Promise<StockBasic | null> {
    // 校验参数
    if (!tsCode || tsCode === 'undefined' || tsCode === 'null') {
      return null
    }
    
    // 先检查缓存
    const cached = stockBasicMap.value.get(tsCode)
    if (cached) return cached
    
    try {
      const data = await stockApi.getStockBasic(tsCode)
      stockBasicMap.value.set(tsCode, data)
      return data
    } catch {
      return null
    }
  }
  
  /** 批量获取股票基本信息 */
  function getStockBasic(tsCode: string): StockBasic | undefined {
    return stockBasicMap.value.get(tsCode)
  }
  
  /** 获取行业列表 */
  async function fetchIndustries(): Promise<void> {
    try {
      industries.value = await stockApi.getIndustries()
    } catch {
      // ignore
    }
  }
  
  /** 搜索股票 */
  async function searchStocks(keyword: string): Promise<StockBasic[]> {
    try {
      const results = await stockApi.searchStocks(keyword)
      
      // 缓存搜索结果
      for (const stock of results) {
        stockBasicMap.value.set(stock.ts_code, stock)
      }
      
      return results
    } catch {
      return []
    }
  }
  
  /** 清除缓存 */
  function clearCache(): void {
    quotesMap.value.clear()
    stockBasicMap.value.clear()
    overview.value = null
    lastUpdated.value = null
  }
  
  return {
    // 状态
    overview,
    quotesMap,
    industries,
    loading,
    lastUpdated,
    
    // 计算属性
    shIndex,
    shChange,
    szIndex,
    szChange,
    cybIndex,
    cybChange,
    marketStats,
    hotSectors,
    
    // Actions
    fetchOverview,
    fetchQuotes,
    getQuote,
    fetchStockBasic,
    getStockBasic,
    fetchIndustries,
    searchStocks,
    clearCache,
  }
})
