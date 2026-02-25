/**
 * Task Store - 任务状态管理
 * 
 * 管理所有 Agent 任务的状态，包括：
 * - 任务列表
 * - 当前任务
 * - 实时进度
 * - Agent 思考流
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { TaskStatus } from '@/api/types'
import type { Task, AnalysisResult } from '@/api/types'

// ==================== 类型定义 ====================

export interface TaskProgress {
  taskId: string
  status: TaskStatus
  progress: number
  currentStep?: string
  message?: string
}

export interface TaskResult {
  taskId: string
  status: TaskStatus
  result?: AnalysisResult
  errorMessage?: string
  executionTimeMs?: number
}

export interface AgentThought {
  taskId: string
  nodeName: string
  content: string
  isFinal: boolean
  timestamp: Date
}

// ==================== Store 定义 ====================

export const useTaskStore = defineStore('task', () => {
  // ==================== 状态 ====================
  
  /** 任务列表 */
  const tasks = ref<Task[]>([])
  
  /** 当前选中的任务 */
  const currentTask = ref<Task | null>(null)
  
  /** 任务进度缓存 */
  const progressMap = ref<Map<string, TaskProgress>>(new Map())
  
  /** Agent 思考流 (按任务 ID 分组) */
  const thoughtsMap = ref<Map<string, AgentThought[]>>(new Map())
  
  /** 加载状态 */
  const loading = ref(false)
  
  // ==================== 计算属性 ====================
  
  /** 当前任务的思考流 */
  const currentThoughts = computed(() => {
    if (!currentTask.value) return []
    return thoughtsMap.value.get(currentTask.value.task_id) || []
  })
  
  /** 当前任务的进度 */
  const currentProgress = computed(() => {
    if (!currentTask.value) return null
    return progressMap.value.get(currentTask.value.task_id) || null
  })
  
  /** 活跃任务数量 */
  const activeTaskCount = computed(() => {
    return tasks.value.filter(t => 
      t.status === TaskStatus.RUNNING || t.status === TaskStatus.PENDING
    ).length
  })
  
  /** 运行中的任务 */
  const runningTasks = computed(() => 
    tasks.value.filter(t => 
      t.status === TaskStatus.RUNNING || t.status === TaskStatus.PENDING
    )
  )
  
  /** 已完成的任务 */
  const completedTasks = computed(() => 
    tasks.value.filter(t => 
      t.status === TaskStatus.COMPLETED || t.status === TaskStatus.FAILED
    )
  )
  
  /** 按状态分组的任务 */
  const tasksByStatus = computed(() => {
    const grouped: Record<TaskStatus, Task[]> = {
      [TaskStatus.PENDING]: [],
      [TaskStatus.QUEUED]: [],
      [TaskStatus.RUNNING]: [],
      [TaskStatus.COMPLETED]: [],
      [TaskStatus.FAILED]: [],
      [TaskStatus.CANCELLED]: [],
    }
    
    for (const task of tasks.value) {
      grouped[task.status].push(task)
    }
    
    return grouped
  })
  
  // ==================== Actions ====================
  
  /** 设置任务列表 */
  function setTasks(newTasks: Task[]): void {
    tasks.value = newTasks
  }
  
  /** 添加任务 */
  function addTask(task: Task): void {
    // 检查是否已存在
    const index = tasks.value.findIndex(t => t.task_id === task.task_id)
    if (index >= 0) {
      tasks.value[index] = task
    } else {
      tasks.value.unshift(task)
    }
  }
  
  /** 移除任务 */
  function removeTask(taskId: string): void {
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index >= 0) {
      tasks.value.splice(index, 1)
    }
    // 清理相关缓存
    progressMap.value.delete(taskId)
    thoughtsMap.value.delete(taskId)
  }
  
  /** 设置当前任务 */
  function setCurrentTask(task: Task | null): void {
    currentTask.value = task
  }
  
  /** 更新任务状态 */
  function updateTaskStatus(taskId: string, status: TaskStatus): void {
    const task = tasks.value.find(t => t.task_id === taskId)
    if (task) {
      task.status = status
    }
    if (currentTask.value?.task_id === taskId) {
      currentTask.value.status = status
    }
  }
  
  /** 更新任务进度 (来自 WebSocket) */
  function updateTaskProgress(progress: TaskProgress): void {
    progressMap.value.set(progress.taskId, progress)
    
    // 同时更新任务状态
    updateTaskStatus(progress.taskId, progress.status)
  }
  
  /** 更新任务结果 (来自 WebSocket) */
  function updateTaskResult(result: TaskResult): void {
    const task = tasks.value.find(t => t.task_id === result.taskId)
    if (task) {
      task.status = result.status
      task.result = result.result
      task.error_message = result.errorMessage
      if (result.executionTimeMs) {
        task.execution_time_ms = result.executionTimeMs
      }
      task.completed_at = new Date().toISOString()
    }
    
    // 更新当前任务
    if (currentTask.value?.task_id === result.taskId) {
      currentTask.value.status = result.status
      currentTask.value.result = result.result
      currentTask.value.error_message = result.errorMessage
    }
    
    // 清理进度缓存
    progressMap.value.delete(result.taskId)
  }
  
  /** 追加 Agent 思考 (来自 WebSocket) */
  function appendAgentThought(thought: Omit<AgentThought, 'timestamp'>): void {
    const thoughts = thoughtsMap.value.get(thought.taskId) || []
    
    thoughts.push({
      ...thought,
      timestamp: new Date(),
    })
    
    thoughtsMap.value.set(thought.taskId, thoughts)
  }
  
  /** 清除任务的思考流 */
  function clearThoughts(taskId: string): void {
    thoughtsMap.value.delete(taskId)
  }
  
  /** 清除所有状态 */
  function clearAll(): void {
    tasks.value = []
    currentTask.value = null
    progressMap.value.clear()
    thoughtsMap.value.clear()
  }
  
  /** 设置加载状态 */
  function setLoading(value: boolean): void {
    loading.value = value
  }
  
  /** 获取任务进度 */
  function getProgress(taskId: string): TaskProgress | null {
    return progressMap.value.get(taskId) || null
  }
  
  return {
    // 状态
    tasks,
    currentTask,
    loading,
    
    // 计算属性
    currentThoughts,
    currentProgress,
    activeTaskCount,
    runningTasks,
    completedTasks,
    tasksByStatus,
    
    // Actions
    setTasks,
    addTask,
    removeTask,
    setCurrentTask,
    updateTaskStatus,
    updateTaskProgress,
    updateTaskResult,
    appendAgentThought,
    clearThoughts,
    clearAll,
    setLoading,
    getProgress,
  }
})
