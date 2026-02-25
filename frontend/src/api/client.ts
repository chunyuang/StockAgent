/**
 * API Client - 统一的 HTTP 请求客户端
 * 
 * 所有 HTTP 请求必须通过此模块，统一处理：
 * - JWT Token 自动注入
 * - Token 过期自动刷新
 * - 错误统一处理
 * - Trace ID 注入
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import router from '@/router'

// ==================== 类型定义 ====================

/** API 响应基础结构 */
export interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  message?: string
  error_code?: string
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** 请求配置扩展 */
interface RequestConfig extends AxiosRequestConfig {
  /** 是否跳过错误提示 */
  skipErrorToast?: boolean
  /** 是否跳过 Token 注入 */
  skipAuth?: boolean
  /** 重试次数 */
  retryCount?: number
}

// ==================== 客户端配置 ====================

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const TIMEOUT = 30000

// Token 刷新状态
let isRefreshing = false
let refreshSubscribers: ((token: string) => void)[] = []

function subscribeTokenRefresh(callback: (token: string) => void): void {
  refreshSubscribers.push(callback)
}

function onTokenRefreshed(token: string): void {
  refreshSubscribers.forEach((callback) => callback(token))
  refreshSubscribers = []
}

// ==================== 创建实例 ====================

const client: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ==================== 请求拦截器 ====================

client.interceptors.request.use(
  (config: InternalAxiosRequestConfig & { skipAuth?: boolean }) => {
    // 注入 JWT Token
    if (!config.skipAuth) {
      const token = localStorage.getItem('access_token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    
    // 注入 Trace ID (用于分布式追踪)
    const traceId = crypto.randomUUID()
    config.headers['X-Trace-ID'] = traceId
    
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// ==================== 响应拦截器 ====================

client.interceptors.response.use(
  (response: AxiosResponse) => {
    // 直接返回数据部分
    return response.data
  },
  async (error) => {
    const originalRequest = error.config as RequestConfig & { _retry?: boolean }
    
    // 401 未授权 - 尝试刷新 Token
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // 正在刷新，等待新 Token
        return new Promise((resolve) => {
          subscribeTokenRefresh((token: string) => {
            originalRequest.headers = originalRequest.headers || {}
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(client(originalRequest))
          })
        })
      }
      
      originalRequest._retry = true
      isRefreshing = true
      
      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) {
          throw new Error('No refresh token')
        }
        
        // 刷新 Token
        const response = await axios.post<{
          access_token: string
          refresh_token: string
        }>(`${BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        
        const { access_token, refresh_token } = response.data
        localStorage.setItem('access_token', access_token)
        localStorage.setItem('refresh_token', refresh_token)
        
        // 通知等待的请求
        onTokenRefreshed(access_token)
        
        // 重试原请求
        originalRequest.headers = originalRequest.headers || {}
        originalRequest.headers.Authorization = `Bearer ${access_token}`
        return client(originalRequest)
        
      } catch {
        // 刷新失败，跳转登录
        handleAuthError()
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }
    
    // 其他错误处理
    if (!originalRequest.skipErrorToast) {
      handleApiError(error)
    }
    
    return Promise.reject(error)
  }
)

// ==================== 错误处理 ====================

function handleAuthError(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  
  ElMessageBox.confirm(
    '登录已过期，请重新登录',
    '提示',
    {
      confirmButtonText: '去登录',
      cancelButtonText: '取消',
      type: 'warning',
    }
  ).then(() => {
    router.push('/login')
  }).catch(() => {
    // 用户取消
  })
}

function handleApiError(error: unknown): void {
  let message = '请求失败'
  
  if (axios.isAxiosError(error) && error.response) {
    const { status, data } = error.response
    
    const errorMessages: Record<number, string> = {
      400: (data as { detail?: string })?.detail || '请求参数错误',
      401: '未授权，请登录',
      403: '没有权限访问',
      404: '请求的资源不存在',
      429: '请求过于频繁，请稍后再试',
      500: '服务器内部错误',
      502: '网关错误',
      503: '服务暂不可用',
    }
    
    message = errorMessages[status] || `请求失败 (${status})`
  } else if (error instanceof Error) {
    if (error.message.includes('Network Error')) {
      message = '网络连接失败，请检查网络'
    } else if (error.message.includes('timeout')) {
      message = '请求超时，请稍后重试'
    } else {
      message = error.message
    }
  }
  
  ElMessage.error(message)
}

// ==================== 请求方法封装 ====================

export const api = {
  get<T>(url: string, config?: RequestConfig): Promise<T> {
    return client.get(url, config)
  },
  
  post<T>(url: string, data?: unknown, config?: RequestConfig): Promise<T> {
    return client.post(url, data, config)
  },
  
  put<T>(url: string, data?: unknown, config?: RequestConfig): Promise<T> {
    return client.put(url, data, config)
  },
  
  patch<T>(url: string, data?: unknown, config?: RequestConfig): Promise<T> {
    return client.patch(url, data, config)
  },
  
  delete<T>(url: string, config?: RequestConfig): Promise<T> {
    return client.delete(url, config)
  },
}

export default client
