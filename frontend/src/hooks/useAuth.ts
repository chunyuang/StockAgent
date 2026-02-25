/**
 * 认证 Hook - 统一的认证状态管理
 */

import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api'
import type { LoginRequest, RegisterRequest } from '@/api/types'

export function useAuth() {
  const router = useRouter()
  const userStore = useUserStore()
  
  // ==================== 计算属性 ====================
  
  const isLoggedIn = computed(() => userStore.isLoggedIn)
  const currentUser = computed(() => userStore.userInfo)
  const isLoading = computed(() => userStore.loading)
  
  // ==================== 登录 ====================
  
  async function login(data: LoginRequest): Promise<boolean> {
    userStore.setLoading(true)
    
    try {
      const response = await authApi.login(data)
      
      // 保存 Token
      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('refresh_token', response.refresh_token)
      
      // 更新 Store
      userStore.setLoggedIn(true)
      
      // 获取用户信息
      await userStore.fetchUserInfo()
      
      ElMessage.success('登录成功')
      
      // 跳转到首页
      const redirect = router.currentRoute.value.query.redirect as string
      router.push(redirect || '/dashboard')
      
      return true
      
    } catch (error) {
      console.error('Login failed:', error)
      return false
    } finally {
      userStore.setLoading(false)
    }
  }
  
  // ==================== 注册 ====================
  
  async function register(data: RegisterRequest): Promise<boolean> {
    userStore.setLoading(true)
    
    try {
      await authApi.register(data)
      
      ElMessage.success('注册成功，请登录')
      
      // 跳转到登录页
      router.push('/login')
      
      return true
      
    } catch (error) {
      console.error('Register failed:', error)
      return false
    } finally {
      userStore.setLoading(false)
    }
  }
  
  // ==================== 登出 ====================
  
  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // 忽略登出失败
    }
    
    // 清理本地状态
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    userStore.clearUser()
    
    ElMessage.success('已退出登录')
    router.push('/login')
  }
  
  // ==================== 检查登录状态 ====================
  
  async function checkAuth(): Promise<boolean> {
    const token = localStorage.getItem('access_token')
    
    if (!token) {
      userStore.setLoggedIn(false)
      return false
    }
    
    try {
      await userStore.fetchUserInfo()
      return true
    } catch {
      // Token 无效
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      userStore.clearUser()
      return false
    }
  }
  
  // ==================== 修改密码 ====================
  
  async function changePassword(
    oldPassword: string, 
    newPassword: string
  ): Promise<boolean> {
    try {
      await authApi.changePassword(oldPassword, newPassword)
      ElMessage.success('密码修改成功')
      return true
    } catch {
      return false
    }
  }
  
  return {
    // 状态
    isLoggedIn,
    currentUser,
    isLoading,
    
    // 方法
    login,
    register,
    logout,
    checkAuth,
    changePassword,
  }
}
