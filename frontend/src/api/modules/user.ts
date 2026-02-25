/**
 * 用户 API
 */

import { api } from '../client'
import type { UserInfo, UserPreferences } from '../types'

export const userApi = {
  /** 获取当前用户信息 */
  getCurrentUser(): Promise<UserInfo> {
    return api.get('/users/me')
  },
  
  /** 更新用户信息 */
  updateUser(data: { nickname?: string; avatar?: string }): Promise<{ message: string }> {
    return api.put('/users/me', data)
  },
  
  /** 获取自选股列表 */
  getWatchlist(): Promise<string[]> {
    return api.get('/users/me/watchlist')
  },
  
  /** 添加自选股 */
  addToWatchlist(tsCode: string): Promise<{ message: string }> {
    return api.post(`/users/me/watchlist?ts_code=${tsCode}`)
  },
  
  /** 移除自选股 */
  removeFromWatchlist(tsCode: string): Promise<{ message: string }> {
    return api.delete(`/users/me/watchlist/${tsCode}`)
  },
  
  /** 更新偏好设置 */
  updatePreferences(preferences: Partial<UserPreferences>): Promise<{ message: string }> {
    return api.put('/users/me/preferences', preferences)
  },
}
