/**
 * 认证 API (最小版 - mock模式)
 */
import { api } from '../client'

export const authApi = {
  async login() { return { access_token: 'mock-token-123456', refresh_token: 'mock-refresh' } },
  async register() { return { success: true } },
  async refreshToken() { return { access_token: 'mock-token-123456' } },
  async logout() { return { success: true } },

  /** 登录(用户名+密码) */
  async loginWithCredentials(username: string, password: string) {
    return await api.post<{ access_token: string; refresh_token: string }>('/auth/login', { username, password })
  },

  /** 注册(用户名+密码+邮箱) */
  async registerWithCredentials(username: string, password: string, email: string) {
    return await api.post<{ success: boolean }>('/auth/register', { username, password, email })
  },

  /** 修改密码 */
  async changePassword(oldPassword: string, newPassword: string) {
    return await api.post<{ success: boolean }>('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
  },
}

export default authApi
