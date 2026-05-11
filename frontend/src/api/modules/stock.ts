import { api } from '../client'
export const stockApi = {
  async getStockInfo(tsCode: string) { return await api.get(`/stocks/${tsCode}`) },
  async searchStocks(query: string) { return await api.get('/stocks/search', { params: { query } }) },
}
export default stockApi
