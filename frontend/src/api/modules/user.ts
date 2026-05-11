/**
 * 用户 API (最小版 - mock模式)
 */
import { api } from '../client'

export const userApi = {
  async getUserInfo() { return { username: 'admin', nickname: '管理员', email: '' } },
  async updateProfile() { return { success: true } },
  async getPreferences() { return {} },
  async updatePreferences() { return { success: true } },
}

export default userApi
