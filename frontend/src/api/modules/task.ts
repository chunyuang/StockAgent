import { api } from '../client'

export const taskApi = {
  async list() { return [] },
  async get() { return {} },
  async create() { return {} },
  async cancel() { return { success: true } },

  /** 列出任务(支持分页/筛选) */
  async listTasks(params?: Record<string, unknown>) {
    return await api.get<{ tasks: any[]; total: number }>('/tasks', { params })
  },

  /** 创建任务 */
  async createTask(data: Record<string, unknown>) {
    return await api.post<{ task_id: string }>('/tasks', data)
  },

  /** 取消任务 */
  async cancelTask(taskId: string) {
    return await api.post<{ success: boolean }>(`/tasks/${taskId}/cancel`)
  },
}
export default taskApi
