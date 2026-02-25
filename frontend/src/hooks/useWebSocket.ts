/**
 * WebSocket Hook - 统一的 WebSocket 连接管理
 * 
 * 功能：
 * - 自动重连
 * - 心跳保活
 * - 消息分发到 Pinia Store
 * - 任务订阅/取消订阅
 */

import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import type { WSMessage } from '@/api/types'

// ==================== 类型定义 ====================

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

interface UseWebSocketOptions {
  /** 自动连接，默认 true */
  autoConnect?: boolean
  /** 最大重连次数，默认 5 */
  maxRetries?: number
  /** 重连间隔 ms，默认 3000 */
  retryInterval?: number
  /** 心跳间隔 ms，默认 30000 */
  heartbeatInterval?: number
}

// ==================== 单例管理 ====================

let wsInstance: WebSocket | null = null
let heartbeatTimer: number | null = null
let reconnectTimer: number | null = null
const subscribers = new Set<(message: WSMessage) => void>()

// ==================== Hook 实现 ====================

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    autoConnect = true,
    maxRetries = 5,
    retryInterval = 3000,
    heartbeatInterval = 30000,
  } = options
  
  // 响应式状态
  const status = ref<ConnectionStatus>('disconnected')
  const retryCount = ref(0)
  const lastMessage = ref<WSMessage | null>(null)
  
  // 计算属性
  const isConnected = computed(() => status.value === 'connected')
  
  // 获取 Store
  const taskStore = useTaskStore()
  
  // ==================== 核心方法 ====================
  
  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    const baseUrl = import.meta.env.VITE_WS_URL || 
      `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
    return `${baseUrl}/ws?token=${token}`
  }
  
  function connect(): void {
    if (wsInstance?.readyState === WebSocket.OPEN) {
      return
    }
    
    const token = localStorage.getItem('access_token')
    if (!token) {
      console.warn('[WebSocket] No token available, skip connect')
      return
    }
    
    status.value = 'connecting'
    
    try {
      wsInstance = new WebSocket(getWsUrl())
      
      wsInstance.onopen = () => {
        console.log('[WebSocket] Connected')
        status.value = 'connected'
        retryCount.value = 0
        startHeartbeat()
      }
      
      wsInstance.onmessage = (event) => {
        handleMessage(event.data)
      }
      
      wsInstance.onclose = (event) => {
        console.log('[WebSocket] Closed', event.code, event.reason)
        status.value = 'disconnected'
        stopHeartbeat()
        
        // 非正常关闭，尝试重连
        if (event.code !== 1000 && retryCount.value < maxRetries) {
          scheduleReconnect()
        }
      }
      
      wsInstance.onerror = (error) => {
        console.error('[WebSocket] Error', error)
      }
      
    } catch (error) {
      console.error('[WebSocket] Connect failed', error)
      scheduleReconnect()
    }
  }
  
  function disconnect(): void {
    stopHeartbeat()
    clearReconnect()
    
    if (wsInstance) {
      wsInstance.close(1000, 'User disconnect')
      wsInstance = null
    }
    
    status.value = 'disconnected'
  }
  
  function send(data: unknown): boolean {
    if (wsInstance?.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] Cannot send, not connected')
      return false
    }
    
    try {
      wsInstance.send(JSON.stringify(data))
      return true
    } catch (error) {
      console.error('[WebSocket] Send failed', error)
      return false
    }
  }
  
  // ==================== 任务订阅 ====================
  
  function subscribeTask(taskId: string): boolean {
    return send({ type: 'subscribe', task_id: taskId })
  }
  
  function unsubscribeTask(taskId: string): boolean {
    return send({ type: 'unsubscribe', task_id: taskId })
  }
  
  // ==================== 消息处理 ====================
  
  function handleMessage(data: string): void {
    try {
      const message = JSON.parse(data) as WSMessage
      lastMessage.value = message
      
      // 分发给订阅者
      subscribers.forEach((callback) => callback(message))
      
      // 根据消息类型更新 Store
      switch (message.type) {
        case 'task_progress':
          taskStore.updateTaskProgress({
            taskId: message.task_id,
            status: message.status,
            progress: message.progress,
            currentStep: message.current_step,
            message: message.message,
          })
          break
          
        case 'task_completed':
        case 'task_failed':
          taskStore.updateTaskResult({
            taskId: message.task_id,
            status: message.status,
            result: message.result,
            errorMessage: message.error_message,
            executionTimeMs: message.execution_time_ms,
          })
          break
          
        case 'agent_thought':
          taskStore.appendAgentThought({
            taskId: message.task_id,
            nodeName: message.node_name,
            content: message.content,
            isFinal: message.is_final,
          })
          break
          
        case 'pong':
          // 心跳响应，无需处理
          break
          
        case 'connected':
          console.log('[WebSocket] Server confirmed connection', message.user_id)
          break
      }
      
    } catch (error) {
      console.error('[WebSocket] Parse message failed', error)
    }
  }
  
  // ==================== 心跳 ====================
  
  function startHeartbeat(): void {
    stopHeartbeat()
    heartbeatTimer = window.setInterval(() => {
      send({ type: 'ping' })
    }, heartbeatInterval)
  }
  
  function stopHeartbeat(): void {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }
  
  // ==================== 重连 ====================
  
  function scheduleReconnect(): void {
    if (reconnectTimer) return
    
    status.value = 'reconnecting'
    retryCount.value++
    
    console.log(`[WebSocket] Reconnecting in ${retryInterval}ms (${retryCount.value}/${maxRetries})`)
    
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, retryInterval)
  }
  
  function clearReconnect(): void {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    retryCount.value = 0
  }
  
  // ==================== 订阅管理 ====================
  
  function subscribe(callback: (message: WSMessage) => void): () => void {
    subscribers.add(callback)
    return () => subscribers.delete(callback)
  }
  
  // ==================== 生命周期 ====================
  
  onMounted(() => {
    if (autoConnect) {
      connect()
    }
  })
  
  onUnmounted(() => {
    // 不断开连接，只清理订阅
    // 因为其他组件可能还在使用
  })
  
  return {
    // 状态
    status,
    isConnected,
    retryCount,
    lastMessage,
    
    // 方法
    connect,
    disconnect,
    send,
    subscribe,
    subscribeTask,
    unsubscribeTask,
  }
}
