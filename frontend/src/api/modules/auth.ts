/**
 * 认证 API (最小版 - mock模式)
 */
export const authApi = {
  async login() { return { access_token: 'mock-token-123456', refresh_token: 'mock-refresh' } },
  async register() { return { success: true } },
  async refreshToken() { return { access_token: 'mock-token-123456' } },
  async logout() { return { success: true } },
}

export default authApi
