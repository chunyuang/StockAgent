<script setup lang="ts">
/**
 * MonitorView - 实时监控大屏页面
 * 四阶段Tab：盘前信号 / 盘中风控 / 盘后报告 / 调度器状态
 * WebSocket实时推送
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ElTabs,
  ElTabPane,
  ElBadge,
  ElButton,
  ElAlert,
} from 'element-plus'
import { Connection } from '@element-plus/icons-vue'

import PreMarketSignalList from '@/components/monitor/PreMarketSignalList.vue'
import IntradayRiskPanel from '@/components/monitor/IntradayRiskPanel.vue'
import PostMarketReport from '@/components/monitor/PostMarketReport.vue'
import SchedulerStatusPanel from '@/components/monitor/SchedulerStatusPanel.vue'

// ==================== Tab & 阶段 ====================

type Phase = 'pre_market' | 'intraday' | 'post_market' | 'scheduler'
const activePhase = ref<Phase>('intraday')

/** 根据当前时间自动判断阶段 */
function detectPhase(): Phase {
  const hour = new Date().getHours()
  if (hour < 9) return 'pre_market'
  if (hour < 15) return 'intraday'
  if (hour < 20) return 'post_market'
  return 'scheduler'
}

// ==================== WebSocket ====================

const wsConnected = ref(false)
const wsReconnecting = ref(false)
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
const wsUrl = computed(() => {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/ws`
})

function connectWS() {
  if (ws && ws.readyState === WebSocket.OPEN) return

  try {
    ws = new WebSocket(wsUrl.value)

    ws.onopen = () => {
      wsConnected.value = true
      wsReconnecting.value = false
      // 发送ping保活
      ws?.send(JSON.stringify({ type: 'ping' }))
      // 订阅调度器事件频道
      ws?.send(JSON.stringify({ type: 'subscribe_scheduler' }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleWSMessage(msg)
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => {
      wsConnected.value = false
      scheduleReconnect()
    }

    ws.onerror = () => {
      wsConnected.value = false
      ws?.close()
    }
  } catch {
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return
  wsReconnecting.value = true
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectWS()
  }, 5000)
}

function disconnectWS() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  ws?.close()
  ws = null
  wsConnected.value = false
}

// ==================== 消息分发 ====================

const preMarketRef = ref<InstanceType<typeof PreMarketSignalList>>()
const intradayRef = ref<InstanceType<typeof IntradayRiskPanel>>()
const schedulerRef = ref<InstanceType<typeof SchedulerStatusPanel>>()

function handleWSMessage(msg: { type: string; [key: string]: any }) {
  switch (msg.type) {
    case 'connected':
      // 连接确认
      break
    case 'pong':
      // 心跳响应
      break
    case 'subscribed_scheduler':
      // 调度器频道订阅确认
      console.log('[WS] Scheduler channel subscribed')
      break
    case 'new_signal':
      // 新交易信号
      preMarketRef.value?.onNewSignal(msg.signal)
      break
    case 'risk_event':
      // 风控事件
      intradayRef.value?.onRiskEvent(msg as unknown as { risk_level: string; message: string })
      break
    case 'position_alert':
      // 持仓异动
      intradayRef.value?.onPositionAlert(msg.alert)
      break
    case 'task_progress':
      // 回测任务进度
      ElMessage.info(`任务进度：${msg.task_id} - ${msg.progress}%`)
      break
    // 调度器 Redis Pub/Sub 消息 — 后端bridge推送 type=scheduler_status/scheduler_phase
    case 'scheduler_status':
    case 'scheduler:status':
      // 调度器启停状态变更
      schedulerRef.value?.onSchedulerUpdate()
      ElMessage.info(`调度器状态变更：${msg.action || msg.data?.action}`)
      break
    case 'scheduler_phase':
    case 'scheduler:phase':
      // 阶段执行进度
      schedulerRef.value?.onSchedulerUpdate()
      if (msg.event === 'started') {
        ElMessage.info(`调度阶段开始：${msg.phase} (${msg.trade_date})`)
      } else if (msg.event === 'completed') {
        ElMessage.success(`调度阶段完成：${msg.phase}`)
      } else if (msg.event === 'failed') {
        ElMessage.error(`调度阶段失败：${msg.phase}`)
      }
      break
    case 'scheduler_update':
      // 旧格式兼容
      schedulerRef.value?.onSchedulerUpdate()
      break
    default:
      break
  }
}

// ==================== 心跳 ====================

let heartbeatTimer: ReturnType<typeof setInterval> | null = null

function startHeartbeat() {
  heartbeatTimer = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }))
    }
  }, 30000)
}

// ==================== 生命周期 ====================

onMounted(() => {
  activePhase.value = detectPhase()
  connectWS()
  startHeartbeat()
})

onUnmounted(() => {
  disconnectWS()
  if (heartbeatTimer) clearInterval(heartbeatTimer)
})
</script>

<template>
  <div class="monitor-view">
    <!-- 头部 -->
    <div class="monitor-header">
      <h2>🖥️ 实时监控大屏</h2>
      <div class="header-status">
        <ElBadge :type="wsConnected ? 'success' : 'danger'" is-dot>
          <ElButton
            size="small"
            :icon="Connection"
            :type="wsConnected ? 'success' : 'danger'"
            plain
            @click="wsConnected ? disconnectWS() : connectWS()"
          >
            {{ wsConnected ? 'WS已连接' : wsReconnecting ? '重连中...' : 'WS断开' }}
          </ElButton>
        </ElBadge>
      </div>
    </div>

    <!-- WS断开提示 -->
    <ElAlert
      v-if="!wsConnected && !wsReconnecting"
      title="WebSocket未连接，实时推送暂不可用"
      description="页面数据仍可通过API轮询获取，点击右上角按钮重连"
      type="warning"
      show-icon
      closable
      style="margin-bottom: 12px"
    />

    <!-- 四阶段Tab -->
    <ElTabs v-model="activePhase" type="border-card">
      <ElTabPane name="pre_market">
        <template #label>
          <span>📋 盘前信号</span>
        </template>
        <PreMarketSignalList ref="preMarketRef" />
      </ElTabPane>

      <ElTabPane name="intraday">
        <template #label>
          <span>⚠️ 盘中风控</span>
        </template>
        <IntradayRiskPanel ref="intradayRef" />
      </ElTabPane>

      <ElTabPane name="post_market">
        <template #label>
          <span>📊 盘后报告</span>
        </template>
        <PostMarketReport />
      </ElTabPane>

      <ElTabPane name="scheduler">
        <template #label>
          <span>⏰ 调度器</span>
        </template>
        <SchedulerStatusPanel ref="schedulerRef" />
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<script lang="ts">
export default { name: 'MonitorView' }
</script>

<style scoped>
.monitor-view {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}
.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.monitor-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.header-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Tab面板内容区统一padding */
:deep(.el-tabs__content) {
  padding: 16px;
}
</style>
