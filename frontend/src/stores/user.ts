/**
 * User Store - 用户状态管理
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { userApi } from '@/api'
import type { UserInfo, UserPreferences } from '@/api/types'

export const useUserStore = defineStore('user', () => {
  // ==================== 状态 ====================
  
  /** 用户信息 */
  const userInfo = ref<UserInfo | null>(null)
  
  /** 是否已登录 */
  const isLoggedIn = ref(false)
  
  /** 加载状态 */
  const loading = ref(false)
  
  // ==================== 计算属性 ====================
  
  /** 用户 ID */
  const userId = computed(() => userInfo.value?.user_id || '')
  
  /** 用户名 */
  const username = computed(() => userInfo.value?.username || '')
  
  /** 昵称 */
  const nickname = computed(() => 
    userInfo.value?.nickname || userInfo.value?.username || '用户'
  )
  
  /** 头像 */
  const avatar = computed(() => userInfo.value?.avatar || '')
  
  /** 自选股列表 */
  const watchlist = computed(() => userInfo.value?.watchlist || [])
  
  /** 用户偏好 */
  const preferences = computed(() => userInfo.value?.preferences || {})
  
  /** 主题 */
  const theme = computed(() => userInfo.value?.preferences?.theme || 'light')
  
  /** 是否为管理员 */
  const isAdmin = computed(() => userInfo.value?.is_admin || false)
  
  // ==================== Actions ====================
  
  /** 获取用户信息 */
  async function fetchUserInfo(): Promise<void> {
    loading.value = true
    try {
      const data = await userApi.getCurrentUser()
      userInfo.value = data
      isLoggedIn.value = true
    } finally {
      loading.value = false
    }
  }
  
  /** 设置登录状态 */
  function setLoggedIn(value: boolean): void {
    isLoggedIn.value = value
  }
  
  /** 设置加载状态 */
  function setLoading(value: boolean): void {
    loading.value = value
  }
  
  /** 清除用户信息 */
  function clearUser(): void {
    userInfo.value = null
    isLoggedIn.value = false
  }
  
  /** 添加自选股 */
  async function addToWatchlist(tsCode: string): Promise<boolean> {
    try {
      await userApi.addToWatchlist(tsCode)
      if (userInfo.value && !userInfo.value.watchlist.includes(tsCode)) {
        userInfo.value.watchlist.push(tsCode)
      }
      return true
    } catch {
      return false
    }
  }
  
  /** 移除自选股 */
  async function removeFromWatchlist(tsCode: string): Promise<boolean> {
    try {
      await userApi.removeFromWatchlist(tsCode)
      if (userInfo.value) {
        userInfo.value.watchlist = userInfo.value.watchlist.filter(c => c !== tsCode)
      }
      return true
    } catch {
      return false
    }
  }
  
  /** 更新偏好设置 */
  async function updatePreferences(prefs: Partial<UserPreferences>): Promise<boolean> {
    try {
      await userApi.updatePreferences(prefs)
      if (userInfo.value) {
        userInfo.value.preferences = { ...userInfo.value.preferences, ...prefs }
      }
      return true
    } catch {
      return false
    }
  }
  
  return {
    // 状态
    userInfo,
    isLoggedIn,
    loading,
    
    // 计算属性
    userId,
    username,
    nickname,
    avatar,
    watchlist,
    preferences,
    theme,
    isAdmin,
    
    // Actions
    fetchUserInfo,
    setLoggedIn,
    setLoading,
    clearUser,
    addToWatchlist,
    removeFromWatchlist,
    updatePreferences,
  }
})
