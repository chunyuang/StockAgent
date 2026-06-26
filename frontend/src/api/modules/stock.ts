import { api } from '../client'
import type { MarketOverview, StockQuote, StockBasic } from '../types'

export const stockApi = {
  async getStockInfo(tsCode: string) { return await api.get(`/stocks/${tsCode}`) },
  async searchStocks(query: string) { return await api.get<StockBasic[]>('/stocks/search', { params: { keyword: query } }) },

  /** 获取大盘概览(上证/深证/创业板+涨跌统计+热门板块) */
  async getMarketOverview() {
    // market_router已移除, 改用scanner/health获取系统状态
    return await api.get<any>('/scanner/health')
  },

  /** 批量获取实时行情 — 后端是POST /stocks/realtime, body={ts_codes: [...]} */
  async getRealtimeQuotes(tsCodes: string[]) {
    return await api.post<StockQuote[]>('/stocks/realtime', { ts_codes: tsCodes })
  },

  /** 获取单只股票基本信息 */
  async getStockBasic(tsCode: string) { return await api.get<StockBasic>(`/stocks/${tsCode}/basic`) },

  /** 获取行业列表 — 后端路由 /stocks/industries */
  async getIndustries() { return await api.get<string[]>('/stocks/industries') },

  /** 获取股票日线数据 */
  async getStockDaily(tsCode: string, params?: { limit?: number }) {
    return await api.get(`/stocks/${tsCode}/daily`, { params })
  },
}
export default stockApi
