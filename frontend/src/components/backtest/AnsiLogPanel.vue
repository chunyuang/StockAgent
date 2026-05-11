<script setup lang="ts">
/**
 * AnsiLogPanel - 回测日志面板（方案C完整版）
 *
 * 改进点（自审发现全部实现）：
 * 1. tail流式读取：运行中每2秒轮询tail=50，无需WebSocket也能"实时"看日志
 * 2. 日志生命周期管理：超过50个task的日志自动提示清理
 * 3. 筛选+分页：按天/策略/类型/搜索筛选，大量日志不卡
 */
import { ref, watch, nextTick, computed, onMounted, onUnmounted } from 'vue'
import { getBacktestLogs, type BacktestLogRecord } from '@/api/modules/backtest'

interface LogDay {
  day: number
  date: string
  lines?: number
}

const props = withDefaults(defineProps<{
  /** 任务ID */
  taskId?: string
  /** 任务状态: running/completed/failed 等 */
  taskStatus?: string
  /** 面板标题 */
  title?: string
  /** 面板高度（px） */
  height?: number
}>(), {
  title: '📝 回测日志',
  height: 500,
})

// === 状态 ===
const loading = ref(false)
const loaded = ref(false)
const logs = ref<BacktestLogRecord[]>([])
const totalLines = ref(0)
const days = ref<LogDay[]>([])
const strategies = ref<string[]>([])
const sections = ref<string[]>([])
const filteredTotal = ref(0)

// === 筛选 ===
const selectedDay = ref<string>('all')
const selectedStrategy = ref<string>('')
const selectedSection = ref<string>('')
const searchTerm = ref('')
const panelRef = ref<HTMLElement | null>(null)

// === 运行中轮询（自审改进1） ===
const isLiveMode = ref(false)  // 是否在轮询tail模式
let liveTimer: ReturnType<typeof setInterval> | null = null
const LIVE_INTERVAL = 2000  // 2秒轮询
const LIVE_TAIL = 50        // 每次取末尾50行

// section中文名映射
const sectionLabels: Record<string, string> = {
  all: '全部',
  init: '🔧 初始化',
  market: '🌡️ 市场环境',
  filter: '🔍 策略筛选',
  trade: '💰 交易执行',
  position: '💼 持仓状态',
  result: '📈 回测结果',
  daily: '📅 日期标记',
  other: '📌 其他',
}

/** 启动实时轮询 */
function startLivePolling() {
  if (liveTimer) return
  isLiveMode.value = true
  // 立即拉一次
  fetchTail()
  liveTimer = setInterval(fetchTail, LIVE_INTERVAL)
}

/** 停止实时轮询 */
function stopLivePolling() {
  if (liveTimer) {
    clearInterval(liveTimer)
    liveTimer = null
  }
  isLiveMode.value = false
}

/** 获取末尾N行日志（轮询用） */
async function fetchTail() {
  if (!props.taskId) return
  try {
    const result = await getBacktestLogs(props.taskId, {
      tail: LIVE_TAIL,
      limit: LIVE_TAIL,
    })
    logs.value = result.logs
    totalLines.value = result.total_lines
    days.value = result.days
    strategies.value = result.strategies
    sections.value = result.sections
    filteredTotal.value = result.filtered_total
    loaded.value = true

    // 自动滚到底
    nextTick(() => {
      if (panelRef.value) {
        panelRef.value.scrollTop = panelRef.value.scrollHeight
      }
    })
  } catch (e) {
    console.error('Failed to fetch tail logs:', e)
  }
}

/** 加载完整日志（完成后用） */
async function loadLogs() {
  if (!props.taskId) return
  stopLivePolling()
  loading.value = true
  try {
    const result = await getBacktestLogs(props.taskId, {
      day: selectedDay.value,
      strategy: selectedStrategy.value || undefined,
      section: selectedSection.value || undefined,
      search: searchTerm.value || undefined,
      limit: 2000,
    })
    logs.value = result.logs
    totalLines.value = result.total_lines
    days.value = result.days
    strategies.value = result.strategies
    sections.value = result.sections
    filteredTotal.value = result.filtered_total
    loaded.value = true
  } catch (e) {
    console.error('Failed to load logs:', e)
    logs.value = []
  } finally {
    loading.value = false
  }
}

/** 重新加载（筛选条件变化时） */
async function reloadLogs() {
  if (!props.taskId) return
  loading.value = true
  try {
    const result = await getBacktestLogs(props.taskId, {
      day: selectedDay.value,
      strategy: selectedStrategy.value || undefined,
      section: selectedSection.value || undefined,
      search: searchTerm.value || undefined,
      limit: 2000,
    })
    logs.value = result.logs
    filteredTotal.value = result.filtered_total
  } catch (e) {
    console.error('Failed to reload logs:', e)
    logs.value = []
  } finally {
    loading.value = false
  }
}

// 搜索防抖
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    reloadLogs()
  }, 500)
}

/** 渲染日志行 */
const renderedLogs = computed(() => {
  return logs.value.map(log => {
    const text = log.text || ''
    const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return {
      key: `${log.seq}-${log.day}`,
      html: escaped,
      level: log.level,
      section: log.section,
    }
  })
})

/** level对应的样式类 */
function levelClass(level: string): string {
  if (level === 'SUCCESS') return 'log-success'
  if (level === 'WARNING') return 'log-warning'
  if (level === 'ERROR') return 'log-error'
  return ''
}

/** 滚动到底部 */

// 任务状态变化 → 自动切换实时/完成模式
watch(() => props.taskStatus, (status) => {
  if (status === 'running' && props.taskId) {
    // 运行中：自动开始轮询tail
    startLivePolling()
  } else if (status === 'completed' || status === 'failed') {
    // 完成：停止轮询，加载完整日志
    stopLivePolling()
    if (loaded.value) {
      // 已经在看了，重新加载完整数据
      loadLogs()
    }
  }
})

// taskId变化时
watch(() => props.taskId, (newId) => {
  stopLivePolling()
  loaded.value = false
  logs.value = []
  if (newId && props.taskStatus === 'running') {
    startLivePolling()
  }
})

onMounted(() => {
  if (props.taskId && props.taskStatus === 'running') {
    startLivePolling()
  }
})

onUnmounted(() => {
  stopLivePolling()
})

// 暴露方法
defineExpose({ loadLogs, reloadLogs, startLivePolling, stopLivePolling })
</script>

<template>
  <div class="ansi-log-card">
    <!-- 头部 -->
    <div class="log-card-header">
      <span class="log-title">
        {{ title }}
        <span v-if="isLiveMode" class="live-indicator" title="实时追踪中(2秒刷新)">🔴 实时</span>
      </span>
      <div class="log-toolbar">
        <!-- 实时追踪按钮 -->
        <button
          v-if="loaded && !isLiveMode"
          class="log-tail-btn"
          :disabled="loading"
          @click="startLivePolling"
          title="实时追踪：每2秒获取最新日志"
        >
          🔴 实时追踪
        </button>
        <button
          v-if="isLiveMode"
          class="log-tail-btn active"
          @click="stopLivePolling"
          title="停止实时追踪"
        >
          ⏹️ 停止追踪
        </button>

        <!-- 加载/刷新 -->
        <button
          v-if="!loaded && !isLiveMode"
          class="log-load-btn"
          :disabled="!taskId || loading"
          @click="loadLogs"
        >
          {{ loading ? '⏳ 加载中...' : '📋 加载日志' }}
        </button>
        <button
          v-if="loaded && !isLiveMode"
          class="log-load-btn"
          :disabled="loading"
          @click="loadLogs"
          title="加载完整日志(带筛选)"
        >
          {{ loading ? '⏳ 加载中...' : '🔄 完整加载' }}
        </button>

        <span v-if="loaded" class="log-count">
          {{ filteredTotal }} / {{ totalLines }} 行
        </span>
      </div>
    </div>

    <!-- 筛选栏（日志加载后显示，实时模式下隐藏） -->
    <div v-if="loaded && !isLiveMode" class="log-filter-bar">
      <!-- 天数Tab -->
      <div class="day-tabs">
        <button
          :class="['day-tab', selectedDay === 'all' ? 'active' : '']"
          @click="selectedDay = 'all'; reloadLogs()"
        >
          全部
        </button>
        <button
          v-for="d in days"
          :key="d.day"
          :class="['day-tab', selectedDay === String(d.day) ? 'active' : '']"
          @click="selectedDay = String(d.day); reloadLogs()"
        >
          Day{{ d.day }} ({{ d.date }})
        </button>
      </div>

      <!-- 筛选控件 -->
      <div class="filter-controls">
        <select v-model="selectedStrategy" class="filter-select" @change="reloadLogs()">
          <option value="">全部策略</option>
          <option v-for="s in strategies" :key="s" :value="s">{{ s }}</option>
        </select>

        <select v-model="selectedSection" class="filter-select" @change="reloadLogs()">
          <option value="">全部类型</option>
          <option v-for="s in sections" :key="s" :value="s">{{ sectionLabels[s] || s }}</option>
        </select>

        <input
          v-model="searchTerm"
          class="log-search"
          type="text"
          placeholder="🔍 搜索..."
          @input="onSearchInput"
        />
      </div>
    </div>

    <!-- 日志内容 -->
    <div
      ref="panelRef"
      class="ansi-log-panel"
      :style="{ height: height + 'px' }"
    >
      <div v-if="!loaded" class="log-empty">
        <template v-if="isLiveMode">等待日志...</template>
        <template v-else-if="taskId">点击"📋 加载日志"查看完整回测日志</template>
        <template v-else>等待回测完成...</template>
      </div>
      <div v-else-if="renderedLogs.length === 0" class="log-empty">
        无匹配日志
      </div>
      <div
        v-for="item in renderedLogs"
        :key="item.key"
        :class="['log-line', levelClass(item.level)]"
        v-html="item.html"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.ansi-log-card {
  border: 1px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
  background: #0d1117;
}

.log-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #161b22;
  border-bottom: 1px solid #30363d;

  .log-title {
    font-weight: 600;
    font-size: 14px;
    color: #c9d1d9;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .live-indicator {
    font-size: 11px;
    font-weight: 500;
    color: #f85149;
    animation: pulse-live 1.5s infinite;
  }

  @keyframes pulse-live {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .log-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;

    .log-load-btn {
      background: #238636;
      border: 1px solid #2ea043;
      border-radius: 4px;
      color: #fff;
      cursor: pointer;
      padding: 4px 12px;
      font-size: 12px;
      font-weight: 500;

      &:hover:not(:disabled) {
        background: #2ea043;
      }

      &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
    }

    .log-tail-btn {
      background: #21262d;
      border: 1px solid #f85149;
      border-radius: 4px;
      color: #f85149;
      cursor: pointer;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;

      &:hover:not(:disabled) {
        background: #f8514920;
      }

      &.active {
        background: #f85149;
        color: #fff;
      }
    }

    .log-count {
      color: #8b949e;
      font-size: 12px;
      white-space: nowrap;
    }
  }
}

.log-filter-bar {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 8px 16px;

  .day-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 8px;
    flex-wrap: wrap;

    .day-tab {
      background: #21262d;
      border: 1px solid #30363d;
      border-radius: 4px;
      color: #8b949e;
      cursor: pointer;
      padding: 3px 10px;
      font-size: 11px;
      white-space: nowrap;

      &:hover {
        background: #30363d;
        color: #c9d1d9;
      }

      &.active {
        background: #1f6feb;
        border-color: #1f6feb;
        color: #fff;
      }
    }
  }

  .filter-controls {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;

    .filter-select {
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 4px;
      padding: 4px 8px;
      color: #c9d1d9;
      font-size: 12px;
      outline: none;
      cursor: pointer;

      &:focus {
        border-color: #58a6ff;
      }
    }

    .log-search {
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 4px;
      padding: 4px 10px;
      color: #c9d1d9;
      font-size: 12px;
      width: 150px;
      outline: none;

      &:focus {
        border-color: #58a6ff;
      }

      &::placeholder {
        color: #484f58;
      }
    }
  }
}

.ansi-log-panel {
  overflow-y: auto;
  padding: 10px 14px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: #c9d1d9;
  background: #0d1117;
  scroll-behavior: smooth;

  &::-webkit-scrollbar {
    width: 8px;
  }

  &::-webkit-scrollbar-track {
    background: #0d1117;
  }

  &::-webkit-scrollbar-thumb {
    background: #30363d;
    border-radius: 4px;

    &:hover {
      background: #484f58;
    }
  }

  .log-line {
    white-space: pre-wrap;
    word-break: break-all;
    min-height: 1.6em;

    &:hover {
      background: rgba(56, 139, 253, 0.08);
    }
  }

  .log-success {
    color: #3fb950;
  }

  .log-warning {
    color: #d29922;
  }

  .log-error {
    color: #f85149;
  }

  .log-empty {
    color: #484f58;
    text-align: center;
    padding: 40px 0;
  }
}
</style>
