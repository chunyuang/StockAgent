<script setup lang="ts">
/**
 * AgentThinking 组件 - Agent 推理过程展示
 * 
 * 功能：
 * - 流式渲染 Agent 思考过程
 * - 打字机效果
 * - 自动滚动
 * - 步骤状态展示
 */

import { ref, watch, nextTick, computed } from 'vue'
import { ElIcon, ElTag, ElScrollbar } from 'element-plus'
import { Loading, Check, Close, Timer } from '@element-plus/icons-vue'
import { TaskStatus } from '@/api/types'

// ==================== 类型定义 ====================

interface ThoughtStep {
  nodeName: string
  content: string
  isFinal: boolean
  timestamp: Date
}

interface Props {
  /** 思考步骤列表 */
  thoughts: ThoughtStep[]
  /** 任务状态 */
  status: TaskStatus
  /** 是否启用打字机效果 */
  typewriter?: boolean
  /** 打字速度 (ms/字符) */
  typeSpeed?: number
  /** 最大高度 */
  maxHeight?: string
}

const props = withDefaults(defineProps<Props>(), {
  typewriter: true,
  typeSpeed: 30,
  maxHeight: '400px',
})

// ==================== 响应式状态 ====================

const scrollbarRef = ref<InstanceType<typeof ElScrollbar>>()
const displayedContent = ref<Map<number, string>>(new Map())
const typingIndex = ref(-1)

// ==================== 计算属性 ====================

const isRunning = computed(() => 
  props.status === TaskStatus.RUNNING || props.status === TaskStatus.PENDING
)

const statusIcon = computed(() => {
  switch (props.status) {
    case TaskStatus.RUNNING:
    case TaskStatus.PENDING:
      return Loading
    case TaskStatus.COMPLETED:
      return Check
    case TaskStatus.FAILED:
      return Close
    default:
      return Timer
  }
})

const statusClass = computed(() => {
  switch (props.status) {
    case TaskStatus.RUNNING:
    case TaskStatus.PENDING:
      return 'status-running'
    case TaskStatus.COMPLETED:
      return 'status-success'
    case TaskStatus.FAILED:
      return 'status-error'
    default:
      return 'status-default'
  }
})

// ==================== 节点名称映射 ====================

const nodeNameMap: Record<string, string> = {
  'data_collection': '📊 数据采集',
  'fundamental_analysis': '📈 基本面分析',
  'technical_analysis': '📉 技术分析',
  'sentiment_analysis': '💬 舆情分析',
  'synthesis': '🎯 综合研判',
  'risk_assessment': '⚠️ 风险评估',
  'recommendation': '💡 投资建议',
}

function formatNodeName(name: string): string {
  return nodeNameMap[name] || name
}

// ==================== 打字机效果 ====================

function typeContent(index: number, content: string): void {
  if (!props.typewriter) {
    displayedContent.value.set(index, content)
    return
  }
  
  typingIndex.value = index
  let currentPos = 0
  
  function typeNext(): void {
    if (currentPos < content.length) {
      displayedContent.value.set(index, content.substring(0, currentPos + 1))
      currentPos++
      setTimeout(typeNext, props.typeSpeed)
    } else {
      typingIndex.value = -1
    }
  }
  
  typeNext()
}

// ==================== 自动滚动 ====================

async function scrollToBottom(): Promise<void> {
  await nextTick()
  scrollbarRef.value?.setScrollTop(99999)
}

// ==================== 监听变化 ====================

watch(
  () => props.thoughts,
  (newThoughts) => {
    if (newThoughts.length > 0) {
      const lastIndex = newThoughts.length - 1
      const lastThought = newThoughts[lastIndex]
      
      // 检查是否是新增的内容
      const currentDisplayed = displayedContent.value.get(lastIndex)
      if (!currentDisplayed || currentDisplayed !== lastThought.content) {
        typeContent(lastIndex, lastThought.content)
      }
      
      scrollToBottom()
    }
  },
  { deep: true, immediate: true }
)

// ==================== 获取显示内容 ====================

function getDisplayedContent(index: number, thought: ThoughtStep): string {
  const displayed = displayedContent.value.get(index)
  if (displayed !== undefined) {
    return displayed
  }
  // 首次加载，直接显示完整内容（无打字效果）
  return thought.content
}

function isTyping(index: number): boolean {
  return typingIndex.value === index
}
</script>

<template>
  <div class="agent-thinking" :class="statusClass">
    <!-- 标题栏 -->
    <div class="thinking-header">
      <ElIcon class="status-icon" :class="{ spinning: isRunning }">
        <component :is="statusIcon" />
      </ElIcon>
      <span class="title">Agent 推理过程</span>
      <ElTag v-if="isRunning" type="primary" size="small" effect="dark">
        进行中
      </ElTag>
    </div>
    
    <!-- 内容区 -->
    <ElScrollbar ref="scrollbarRef" :max-height="maxHeight" class="thinking-content">
      <div v-if="thoughts.length === 0" class="empty-state">
        等待 Agent 开始分析...
      </div>
      
      <div
        v-for="(thought, index) in thoughts"
        :key="index"
        class="thought-step"
        :class="{ 'is-final': thought.isFinal }"
      >
        <div class="step-header">
          <span class="node-name">{{ formatNodeName(thought.nodeName) }}</span>
          <span class="timestamp">
            {{ thought.timestamp.toLocaleTimeString() }}
          </span>
        </div>
        <div class="step-content">
          <span>{{ getDisplayedContent(index, thought) }}</span>
          <span v-if="isTyping(index)" class="cursor">|</span>
        </div>
      </div>
    </ElScrollbar>
  </div>
</template>

<style scoped lang="scss">
.agent-thinking {
  border-radius: 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  overflow: hidden;
  
  &.status-running {
    border-color: var(--el-color-primary-light-5);
    box-shadow: 0 0 20px rgba(64, 158, 255, 0.1);
  }
  
  &.status-success {
    border-color: var(--el-color-success-light-5);
  }
  
  &.status-error {
    border-color: var(--el-color-danger-light-5);
  }
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
  
  .status-icon {
    font-size: 18px;
    color: var(--el-color-primary);
    
    &.spinning {
      animation: spin 1s linear infinite;
    }
  }
  
  .title {
    font-weight: 600;
    flex: 1;
  }
}

.thinking-content {
  padding: 16px;
}

.empty-state {
  text-align: center;
  color: var(--el-text-color-secondary);
  padding: 40px 0;
}

.thought-step {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  border-left: 3px solid var(--el-color-primary-light-3);
  
  &.is-final {
    border-left-color: var(--el-color-success);
    background: var(--el-color-success-light-9);
  }
  
  &:last-child {
    margin-bottom: 0;
  }
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  
  .node-name {
    font-weight: 500;
    color: var(--el-text-color-primary);
  }
  
  .timestamp {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

.step-content {
  color: var(--el-text-color-regular);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  
  .cursor {
    animation: blink 0.7s infinite;
    color: var(--el-color-primary);
    font-weight: bold;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>
