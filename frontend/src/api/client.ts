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
const TIMEOUT = 300000  // 5 minutes (回测需要几分钟，不能用30秒超时)
const SCAN_TRACE_TIMEOUT = 15000  // 扫描追踪/复盘等轻量API用15秒超时，防止大数据卡死

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
    let traceId: string
    try {
      traceId = crypto.randomUUID()
    } catch {
      // 兼容低版本浏览器/非HTTPS环境，生成简单UUID
      traceId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0
        const v = c == 'x' ? r : (r & 0x3 | 0x8)
        return v.toString(16)
      })
    }
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
    if (originalRequest && !originalRequest.skipErrorToast) {
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

function handleApiError(error: unknown): string {
  let message = '请求失败'
  
  if (axios.isAxiosError(error) && error.response) {
    const { status, data } = error.response
    
    // 尝试从响应中提取详细错误信息
    const extractDetail = (d: any): string => {
      if (!d) return ''
      if (typeof d === 'string') return d
      if (typeof d.detail === 'string') return d.detail
      if (d.detail?.message) return d.detail.message
      if (d.message) return d.message
      // 处理校验错误列表
      if (d.detail?.errors && Array.isArray(d.detail.errors)) {
        return d.detail.errors.map((e: any) => e.field_cn || e.field ? `${e.field_cn || e.field}: ${e.message}` : e.message).join('; ')
      }
      return ''
    }
    
    const errorMessages: Record<number, string> = {
      400: extractDetail(data) || '请求参数错误',
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
  return message
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
