/**
 * API 模块统一导出
 */

// 客户端
export { api, default as client } from './client'

// 类型
export * from './types'

// 模块 API
export { stockApi } from './modules/stock'
export { strategyApi, subscriptionApi } from './modules/strategy'
export { default as backtestApi } from './modules/backtest'
export * from './modules/backtest'
export { default as tradingApi } from './modules/trading'
export * from './modules/trading'
export { default as systemApi } from './modules/system'
export * from './modules/system'
export { userApi } from './modules/user'
export { authApi } from './modules/auth'
export { taskApi } from './modules/task'
