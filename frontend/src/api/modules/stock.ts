/**
 * 股票数据 API
 */

import { api } from '../client'
import type { StockBasic, StockDaily, StockQuote, MarketOverview } from '../types'

export const stockApi = {
  /** 搜索股票 */
  searchStocks(keyword: string, limit = 20): Promise<StockBasic[]> {
    return api.get('/stocks/search', { params: { keyword, limit } })
  },
  
  /** 获取股票基本信息 */
  getStockBasic(tsCode: string): Promise<StockBasic> {
    return api.get(`/stocks/${tsCode}/basic`)
  },
  
  /** 获取日线数据 */
  getStockDaily(tsCode: string, params?: { start_date?: string; end_date?: string; limit?: number }): Promise<StockDaily[]> {
    return api.get(`/stocks/${tsCode}/daily`, { params })
  },
  
  /** 获取实时行情 */
  getRealtimeQuotes(tsCodes: string[]): Promise<StockQuote[]> {
    return api.post('/stocks/realtime', { ts_codes: tsCodes })
  },
  
  /** 获取大盘概览 */
  getMarketOverview(tradeDate?: string): Promise<MarketOverview> {
    return api.get('/market/overview', { params: { trade_date: tradeDate } })
  },
  
  /** 获取行业列表 */
  getIndustries(): Promise<string[]> {
    return api.get('/stocks/industries')
  },
  
  /** 按行业获取股票 */
  getStocksByIndustry(industry: string, limit = 50): Promise<StockBasic[]> {
    return api.get(`/stocks/by-industry/${industry}`, { params: { limit } })
  },
}
