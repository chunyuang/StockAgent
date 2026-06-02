/**
 * 用户 API (最小版 - mock模式)
 */
import { api } from '../client'
import type { UserInfo } from '../types'

export const userApi = {
  async getUserInfo() { return { username: 'admin', nickname: '管理员', email: '' } },
  async updateProfile() { return { success: true } },
  async getPreferences() { return {} },
  async updatePreferences(_prefs?: Record<string, unknown>) { return { success: true } },

  /** 获取完整用户信息(含watchlist) */
  async getCurrentUser() { return await api.get<UserInfo>('/user/me') },

  /** 添加自选股 */
  async addToWatchlist(tsCode: string) { return await api.post<{ success: boolean }>('/user/watchlist', { ts_code: tsCode }) },

  /** 移除自选股 */
  async removeFromWatchlist(tsCode: string) { return await api.delete<{ success: boolean }>(`/user/watchlist/${tsCode}`) },
}

export default userApi
