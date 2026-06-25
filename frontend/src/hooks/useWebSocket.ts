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
import { useScannerStore } from '@/stores/scanner'
import type { WSMessage } from '@/api/types'

// ==================== 类型定义 ====================

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

interface UseWebSocketOptions {
  /** 自动连接，默认 true */
  autoConnect?: boolean
  /** 最大重连次数，默认 Infinity (无限重连) */
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

// 【v2.9.83】WS重连断线补发: 记录最后收到的scanner stream ID
let lastSignalStreamId: string | null = null
let lastPositionStreamId: string | null = null

// ==================== Hook 实现 ====================

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    autoConnect = true,
    maxRetries = Infinity,
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
  let scannerStore: ReturnType<typeof useScannerStore> | null = null
  try {
    scannerStore = useScannerStore()
  } catch (e) {
    // ScannerStore可能未在当前上下文中初始化
    console.warn('[useWebSocket] ScannerStore not available:', e)
  }
  
  // ==================== 核心方法 ====================
  
  function getWsUrl(): string {
    // 【v2.9.49】P0安全修复: Token不再拼入URL(避免泄漏到日志/DevTools)
    // 改用首条消息认证, WebSocket连接后再发送auth消息
    const baseUrl = import.meta.env.VITE_WS_URL || 
      `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
    return `${baseUrl}/ws`
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
      
      // 【v2.9.49】连接成功后发送auth消息(替代URL token)
      wsInstance.onopen = () => {
        if (__DEV__) console.log('[WebSocket] Connected')
        const token = localStorage.getItem('access_token')
        if (token) {
          wsInstance!.send(JSON.stringify({ type: 'auth', token }))
        }
        status.value = 'connected'
        retryCount.value = 0
        startHeartbeat()
      }
      
      wsInstance.onmessage = (event) => {
        handleMessage(event.data)
      }
      
      wsInstance.onclose = (event) => {
        if (__DEV__) console.log('[WebSocket] Closed', event.code, event.reason)
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
  
  function subscribeScanner(): boolean {
    // 【v2.9.83】重连时携带last_stream_id, 服务端可从断开位置补发
    return send({
      type: 'subscribe_scanner',
      last_signal_stream_id: lastSignalStreamId || undefined,
      last_position_stream_id: lastPositionStreamId || undefined,
    })
  }
  
  function unsubscribeScanner(): boolean {
    return send({ type: 'unsubscribe_scanner' })
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
          if (__DEV__) console.log('[WebSocket] Server confirmed connection', message.user_id)
          break
          
        // 【v2.9.49】P1修复: Scanner事件类型映射
        // Bridge发送scanner_signal/position/timeline/status, Store期望signal/position/timeline/status
        case 'scanner_signal':
          if (scannerStore) {
            // 【v2.9.82修复】信号可能批量到达(signals数组), 必须逐条更新
            // 之前只取signals[0]导致后续信号丢失
            const signalItems = message.signals || (message.item ? [message.item] : [])
            for (const item of signalItems) {
              scannerStore.updateFromWs('signal', { item })
            }
          }
          // 【v2.9.83】记录最新stream_id用于重连续传
          if (message._stream_id) lastSignalStreamId = message._stream_id
          break
          
        case 'scanner_position':
          if (scannerStore) {
            // 【v2.9.82修复】区分全量/增量: 有positions数组=全量, 有event=增量通知
            scannerStore.updateFromWs('position', {
              positions: message.positions,
              account: message.account,
              event: message.event,
              ts_code: message.ts_code,
              action: message.action,
            })
          }
          // 【v2.9.83】记录最新stream_id用于重连续传
          if (message._stream_id) lastPositionStreamId = message._stream_id
          break
          
        case 'scanner_timeline':
          if (scannerStore) {
            scannerStore.updateFromWs('timeline', { item: message.item })
          }
          break
          
        case 'scanner_status':
          if (scannerStore) {
            scannerStore.updateFromWs('status', message.status || message)
          }
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
    
    if (__DEV__) console.log(`[WebSocket] Reconnecting in ${retryInterval}ms (${retryCount.value}/${maxRetries})`)
    
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
  
  // ==================== 引用计数(防止最后一个用户卸载后连接泄漏) ====================
  let refCount = 0
  
  function acquire(): void {
    refCount++
    if (refCount === 1 && status.value !== 'connected') {
      connect()
    }
  }
  
  function release(): void {
    refCount = Math.max(0, refCount - 1)
    if (refCount === 0 && status.value === 'connected') {
      // 【v2.9.49】最后一个使用者释放时断开连接
      if (__DEV__) console.log('[WebSocket] Last subscriber released, disconnecting')
      disconnect()
    }
  }
  
  // ==================== 订阅管理 ====================
  
  function subscribe(callback: (message: WSMessage) => void): () => void {
    subscribers.add(callback)
    acquire()
    return () => {
      subscribers.delete(callback)
      release()
    }
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
    subscribeScanner,
    unsubscribeScanner,
  }
}
