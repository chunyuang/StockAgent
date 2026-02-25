/**
 * 认证 API
 */

import { api } from '../client'
import type {
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisterResponse,
} from '../types'

export const authApi = {
  /** 用户登录 */
  login(data: LoginRequest): Promise<LoginResponse> {
    // 使用 form-urlencoded 格式 (OAuth2 标准)
    const formData = new URLSearchParams()
    formData.append('username', data.username)
    formData.append('password', data.password)
    
    return api.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },
  
  /** 用户注册 */
  register(data: RegisterRequest): Promise<RegisterResponse> {
    return api.post('/auth/register', data)
  },
  
  /** 刷新 Token */
  refreshToken(refreshToken: string): Promise<LoginResponse> {
    return api.post('/auth/refresh', { refresh_token: refreshToken })
  },
  
  /** 登出 */
  logout(): Promise<{ message: string }> {
    return api.post('/auth/logout')
  },
  
  /** 修改密码 */
  changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }> {
    return api.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
}
