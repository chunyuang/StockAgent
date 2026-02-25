/**
 * 任务 API
 */

import { api } from '../client'
import type {
  CreateTaskRequest,
  CreateTaskResponse,
  Task,
  TaskListResponse,
  TaskType,
  TaskStatus,
} from '../types'

export const taskApi = {
  /** 创建任务 */
  createTask(data: CreateTaskRequest): Promise<CreateTaskResponse> {
    return api.post('/tasks', data)
  },
  
  /** 获取任务列表 */
  listTasks(params?: {
    status?: TaskStatus
    task_type?: TaskType
    limit?: number
    offset?: number
  }): Promise<TaskListResponse> {
    return api.get('/tasks', { params })
  },
  
  /** 获取任务详情 */
  getTask(taskId: string): Promise<Task> {
    return api.get(`/tasks/${taskId}`)
  },
  
  /** 取消任务 */
  cancelTask(taskId: string): Promise<{ message: string }> {
    return api.delete(`/tasks/${taskId}`)
  },
  
  /** 删除任务 */
  deleteTask(taskId: string): Promise<{ message: string; task_id: string }> {
    return api.delete(`/tasks/${taskId}/delete`)
  },
  
  // ==================== 快捷分析 ====================
  
  /** 快速个股分析 */
  analyzeStock(tsCode: string, analysisType = 'comprehensive'): Promise<CreateTaskResponse> {
    return api.post('/tasks/analyze/stock', null, {
      params: { ts_code: tsCode, analysis_type: analysisType },
    })
  },
  
  /** 快速大盘分析 */
  analyzeMarket(): Promise<CreateTaskResponse> {
    return api.post('/tasks/analyze/market')
  },
  
  /** 自然语言查询 */
  query(queryText: string): Promise<CreateTaskResponse> {
    return api.post('/tasks/analyze/query', null, {
      params: { query: queryText },
    })
  },
}
