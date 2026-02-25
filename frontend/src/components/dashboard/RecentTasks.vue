<script setup lang="ts">
/**
 * 最近分析任务卡片
 * 
 * 视觉升级版 - 增加信号徽章和时间线样式
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '@/stores/task'
import { ElSkeleton, ElIcon } from 'element-plus'
import { ArrowRight, Clock, TrendCharts, DataAnalysis, Document, Check } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

defineProps<{
  loading?: boolean
}>()

const router = useRouter()
const taskStore = useTaskStore()

// 最近完成的任务
const recentTasks = computed(() => (taskStore.completedTasks || []).slice(0, 5))

// 任务类型配置
const taskTypeConfig: Record<string, { label: string; icon: typeof TrendCharts; color: string }> = {
  stock_analysis: { label: '个股分析', icon: DataAnalysis, color: '#3b82f6' },
  market_overview: { label: '大盘分析', icon: TrendCharts, color: '#8b5cf6' },
  strategy_backtest: { label: '策略回测', icon: Clock, color: '#06b6d4' },
  news_sentiment: { label: '舆情分析', icon: Document, color: '#f59e0b' },
  report_generate: { label: '研报生成', icon: Document, color: '#10b981' },
  custom_query: { label: '自定义查询', icon: Document, color: '#6366f1' },
}

// 信号配置
const signalConfig: Record<string, { label: string; color: string; bg: string }> = {
  buy: { label: '买入', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' },
  sell: { label: '卖出', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' },
  hold: { label: '持有', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)' },
  strong_buy: { label: '强烈买入', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.15)' },
  strong_sell: { label: '强烈卖出', color: '#16a34a', bg: 'rgba(22, 163, 74, 0.15)' },
}

function getTaskConfig(taskType: string) {
  return taskTypeConfig[taskType] || { label: taskType, icon: Document, color: '#64748b' }
}

function getSignalConfig(signal: string) {
  return signalConfig[signal] || { label: signal, color: '#64748b', bg: 'rgba(100, 116, 139, 0.1)' }
}

// 格式化时间
function formatTime(time: string): string {
  return dayjs(time).fromNow()
}
</script>

<template>
  <div class="recent-tasks card">
    <div class="card-header">
      <span class="header-title">最近分析</span>
      <router-link to="/analysis" class="view-all">
        全部
        <ElIcon :size="14"><ArrowRight /></ElIcon>
      </router-link>
    </div>
    
    <div class="card-body">
      <el-skeleton v-if="loading" :rows="4" animated />
      
      <template v-else>
        <div v-if="recentTasks.length > 0" class="task-list">
          <div
            v-for="(task, index) in recentTasks"
            :key="task.task_id"
            class="task-item"
            :style="{ animationDelay: `${index * 0.05}s` }"
            @click="router.push(`/analysis/${task.task_id}`)"
          >
            <!-- 时间线节点 -->
            <div class="timeline-node">
              <div class="node-dot">
                <Check />
              </div>
              <div v-if="index < recentTasks.length - 1" class="node-line" />
            </div>
            
            <!-- 任务内容 -->
            <div class="task-content">
              <div class="task-header">
                <div class="task-info">
                  <span 
                    class="task-type"
                    :style="{ color: getTaskConfig(task.task_type).color }"
                  >
                    {{ getTaskConfig(task.task_type).label }}
                  </span>
                  <span v-if="task.ts_codes?.length > 0" class="task-target">
                    {{ task.ts_codes.slice(0, 2).join(', ') }}
                    <template v-if="task.ts_codes.length > 2">
                      +{{ task.ts_codes.length - 2 }}
                    </template>
                  </span>
                </div>
                
                <span class="task-time">
                  <ElIcon :size="12"><Clock /></ElIcon>
                  {{ formatTime(task.created_at) }}
                </span>
              </div>
              
              <!-- 结果信号 -->
              <div v-if="task.result?.signal" class="task-result">
                <span 
                  class="signal-badge"
                  :style="{ 
                    color: getSignalConfig(task.result.signal).color,
                    background: getSignalConfig(task.result.signal).bg
                  }"
                >
                  {{ getSignalConfig(task.result.signal).label }}
                </span>
                <span v-if="task.result.confidence" class="confidence-badge">
                  置信度 {{ (task.result.confidence * 100).toFixed(0) }}%
                </span>
              </div>
            </div>
            
            <!-- 右侧箭头 -->
            <div class="task-arrow">
              <ElIcon :size="16"><ArrowRight /></ElIcon>
            </div>
          </div>
        </div>
        
        <div v-else class="empty-state">
          <div class="empty-icon">
            <Document />
          </div>
          <p class="empty-text">暂无分析记录</p>
          <p class="empty-hint">开始您的第一次股票分析</p>
        </div>
      </template>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.recent-tasks {
  .card-header {
    .header-title {
      font-weight: 600;
      color: var(--text-primary);
    }
    
    .view-all {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 13px;
      color: var(--primary-500);
      font-weight: 500;
      transition: all var(--transition-fast);
      
      &:hover {
        color: var(--primary-600);
        gap: 8px;
      }
    }
  }
  
  .card-body {
    padding: 16px 24px 20px;
  }
}

.task-list {
  display: flex;
  flex-direction: column;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 12px 0;
  cursor: pointer;
  animation: fadeSlide 0.3s ease-out both;
  
  &:hover {
    .task-content {
      background: var(--bg-hover);
    }
    
    .task-arrow {
      opacity: 1;
      transform: translateX(0);
    }
    
    .timeline-node .node-dot {
      transform: scale(1.1);
      box-shadow: 0 0 0 4px var(--primary-100);
    }
  }
}

.timeline-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 4px;
  
  .node-dot {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--primary-100);
    color: var(--primary-600);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all var(--transition-fast);
    
    svg {
      width: 12px;
      height: 12px;
    }
  }
  
  .node-line {
    width: 2px;
    flex: 1;
    min-height: 40px;
    background: var(--border-light);
    margin-top: 8px;
  }
}

.task-content {
  flex: 1;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
}

.task-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-type {
  font-size: 14px;
  font-weight: 600;
}

.task-target {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 3px 8px;
  background: var(--bg-tertiary);
  border-radius: 6px;
}

.task-time {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.task-result {
  display: flex;
  align-items: center;
  gap: 10px;
}

.signal-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.confidence-badge {
  font-size: 12px;
  color: var(--text-secondary);
}

.task-arrow {
  color: var(--text-tertiary);
  opacity: 0;
  transform: translateX(-8px);
  transition: all var(--transition-fast);
  padding-top: 16px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 24px;
  text-align: center;
  
  .empty-icon {
    width: 56px;
    height: 56px;
    border-radius: 14px;
    background: var(--bg-tertiary);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;
    color: var(--text-tertiary);
    
    svg {
      width: 28px;
      height: 28px;
    }
  }
  
  .empty-text {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-secondary);
    margin: 0 0 6px;
  }
  
  .empty-hint {
    font-size: 13px;
    color: var(--text-tertiary);
    margin: 0;
  }
}

@keyframes fadeSlide {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
