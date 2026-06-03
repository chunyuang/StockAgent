/**
 * 因子查看 API
 */
import { api } from '../client'

// ==================== 类型定义 ====================

/** 因子数据状态 */
export type FactorDataStatus = 'fresh' | 'stale' | 'error' | 'missing'

/** 因子分类 */
export type FactorCategory = 'intraday' | 'daily' | 'fundamental' | 'composite'

/** 更新粒度 */
export type UpdateScope = 'single' | 'watchlist' | 'market'

/** 因子元数据项 */
export interface FactorMeta {
  key: string
  name: string
  description: string
  category: FactorCategory
  unit?: string
  precision?: number
}

/** 因子值(带状态) */
export interface FactorValue {
  value: number | null
  status: FactorDataStatus
  updated_at?: string
}

/** 因子视图行 */
export interface FactorRow {
  code: string
  name: string
  updated_at: string
  data_status: FactorDataStatus
  factors: Record<string, FactorValue>
}

/** 因子视图请求参数 */
export interface FactorViewParams {
  codes?: string[]
  categories?: FactorCategory[]
  status_filter?: FactorDataStatus | 'all'
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

/** 因子视图响应 */
export interface FactorViewResponse {
  items: FactorRow[]
  total: number
  page: number
  page_size: number
}

/** 批量视图请求参数 */
export interface FactorBatchViewParams extends FactorViewParams {
  query?: string
}

/** 因子元数据响应 */
export interface FactorMetadataResponse {
  categories: { key: FactorCategory; name: string }[]
  factors: FactorMeta[]
  total_factors: number
}

/** 更新请求参数 */
export interface FactorUpdateParams {
  scope: UpdateScope
  codes?: string[]
  categories?: FactorCategory[]
}

/** 更新状态 */
export interface FactorUpdateStatus {
  is_updating: boolean
  scope: UpdateScope | null
  progress: number
  total: number
  success_count: number
  fail_count: number
  started_at?: string
  estimated_end?: string
  data_source_status: {
    eastmoney: 'ok' | 'error' | 'offline'
    liangmai: 'ok' | 'error' | 'offline'
    akshare: 'ok' | 'error' | 'offline'
  }
  last_update_time?: string
  market_phase: 'trading' | 'after_close' | 'non_trading'
}

/** 更新日志条目 */
export interface FactorUpdateLog {
  id: string
  timestamp: string
  scope: UpdateScope
  code?: string
  category?: FactorCategory
  status: 'success' | 'error' | 'warning'
  message: string
  duration_ms?: number
}

/** 更新日志请求参数 */
export interface FactorUpdateLogsParams {
  page?: number
  page_size?: number
  status?: 'success' | 'error' | 'warning'
  scope?: UpdateScope
}

/** 更新日志响应 */
export interface FactorUpdateLogsResponse {
  items: FactorUpdateLog[]
  total: number
  page: number
  page_size: number
}

// ==================== API 方法 ====================

export const factorApi = {
  /** 获取单只股票因子视图 */
  async getFactorView(params: FactorViewParams) {
    return api.get<FactorViewResponse>('/factor/view', { params })
  },

  /** 批量获取因子视图 */
  async getFactorBatchView(params: FactorBatchViewParams) {
    return api.get<FactorViewResponse>('/factor/batch-view', { params })
  },

  /** 获取因子元数据 */
  async getFactorMetadata() {
    return api.get<FactorMetadataResponse>('/factor/metadata')
  },

  /** 触发因子更新 */
  async triggerFactorUpdate(params: FactorUpdateParams) {
    return api.post<{ task_id: string; message: string }>('/factor/update', params)
  },

  /** 获取因子更新状态 */
  async getFactorUpdateStatus() {
    return api.get<FactorUpdateStatus>('/factor/update-status')
  },

  /** 获取因子更新日志 */
  async getFactorUpdateLogs(params?: FactorUpdateLogsParams) {
    return api.get<FactorUpdateLogsResponse>('/factor/update-logs', { params })
  },
}

export default factorApi
