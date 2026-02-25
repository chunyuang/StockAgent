/**
 * 策略 API
 * 
 * 简化架构：
 * - 每种策略类型只有一条策略数据
 * - 普通用户只能添加/移除个股
 * - 管理员可修改策略参数
 */

import { api } from '../client'
import type { 
  Strategy, 
  CreateStrategyRequest, 
  CreateTaskResponse,
  StrategySubscription,
  AddStockResponse,
  ToggleSubscriptionResponse,
  StrategyTypeInfo,
} from '../types'

export const strategyApi = {
  /** 创建策略 */
  createStrategy(data: CreateStrategyRequest): Promise<{
    strategy_id: string
    name: string
    message: string
  }> {
    return api.post('/strategies', data)
  },
  
  /** 获取策略列表 */
  listStrategies(includePublic = false): Promise<{ strategies: Strategy[] }> {
    return api.get('/strategies', { params: { include_public: includePublic } })
  },
  
  /** 获取策略详情 */
  getStrategy(strategyId: string): Promise<Strategy> {
    return api.get(`/strategies/${strategyId}`)
  },
  
  /** 更新策略 */
  updateStrategy(strategyId: string, data: Partial<CreateStrategyRequest>): Promise<{ message: string }> {
    return api.put(`/strategies/${strategyId}`, data)
  },
  
  /** 执行策略 */
  runStrategy(strategyId: string): Promise<CreateTaskResponse> {
    return api.post(`/strategies/${strategyId}/run`)
  },
  
  /** 删除策略 */
  deleteStrategy(strategyId: string): Promise<{ message: string }> {
    return api.delete(`/strategies/${strategyId}`)
  },
}

// ==================== 策略订阅 API (Listener 节点) ====================
// 简化架构：每种策略类型只有一条数据

export const subscriptionApi = {
  /**
   * 获取可用的策略类型列表
   * 只返回服务端已实现的策略
   */
  getStrategyTypes(): Promise<StrategyTypeInfo[]> {
    return api.get('/strategy/subscriptions/types')
  },

  /**
   * 获取策略订阅列表
   * 每种策略类型只有一条记录
   */
  getSubscriptions(params?: {
    is_active?: boolean
    strategy_type?: string
  }): Promise<StrategySubscription[]> {
    return api.get('/strategy/subscriptions', { params })
  },

  /**
   * 获取指定类型的策略
   * 如果不存在会自动创建
   * @param strategyType 策略类型 (如 ma5_buy)
   */
  getSubscriptionByType(strategyType: string): Promise<StrategySubscription> {
    return api.get(`/strategy/subscriptions/${strategyType}`)
  },

  /**
   * 向策略添加个股（所有用户可用）
   * @param strategyType 策略类型
   * @param tsCode 股票代码 (如 000001.SZ)
   */
  addStockToStrategy(strategyType: string, tsCode: string): Promise<AddStockResponse> {
    return api.post(`/strategy/subscriptions/${strategyType}/stocks`, { 
      ts_code: tsCode.toUpperCase() 
    })
  },

  /**
   * 从策略移除个股（所有用户可用）
   * @param strategyType 策略类型
   * @param tsCode 股票代码
   */
  removeStockFromStrategy(strategyType: string, tsCode: string): Promise<AddStockResponse> {
    return api.delete(`/strategy/subscriptions/${strategyType}/stocks/${tsCode.toUpperCase()}`)
  },

  // ==================== 管理员功能 ====================
  // 以下接口需要登录且用户具有管理员权限 (is_admin: true)
  // Token 会通过 axios 拦截器自动添加

  /**
   * 更新策略参数（仅管理员）
   * @param strategyType 策略类型
   * @param params 策略参数
   */
  updateStrategyParams(
    strategyType: string, 
    params: Record<string, unknown>
  ): Promise<StrategySubscription> {
    return api.put(`/strategy/subscriptions/${strategyType}/params`, { params })
  },

  /**
   * 切换策略激活状态（仅管理员）
   * @param strategyType 策略类型
   */
  toggleSubscription(strategyType: string): Promise<ToggleSubscriptionResponse> {
    return api.patch(`/strategy/subscriptions/${strategyType}/toggle`)
  },

  /**
   * 初始化所有策略（仅管理员）
   * 为每种已实现的策略类型创建一条记录
   */
  initAllStrategies(): Promise<{
    message: string
    created: string[]
    existing: string[]
  }> {
    return api.post('/strategy/subscriptions/init')
  },
}
