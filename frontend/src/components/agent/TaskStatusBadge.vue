<script setup lang="ts">
/**
 * TaskStatusBadge 组件 - 任务状态徽章
 * 
 * 根据规则要求，每个任务必须有明确的状态展示：
 * Pending, Running, Success, Failed
 */

import { computed } from 'vue'
import { ElTag, ElIcon, ElProgress } from 'element-plus'
import { 
  Loading, 
  Check, 
  Close, 
  Clock, 
  Remove,
  Timer 
} from '@element-plus/icons-vue'
import { TaskStatus } from '@/api/types'

interface Props {
  status: TaskStatus
  /** 进度百分比 (0-100) */
  progress?: number
  /** 显示进度条 */
  showProgress?: boolean
  /** 尺寸 */
  size?: 'small' | 'default' | 'large'
}

const props = withDefaults(defineProps<Props>(), {
  progress: 0,
  showProgress: false,
  size: 'default',
})

// ==================== 状态配置 ====================

interface StatusConfig {
  label: string
  type: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  icon: typeof Loading
  effect: 'dark' | 'light' | 'plain'
}

const statusConfigs: Record<TaskStatus, StatusConfig> = {
  [TaskStatus.PENDING]: {
    label: '等待中',
    type: 'info',
    icon: Clock,
    effect: 'plain',
  },
  [TaskStatus.QUEUED]: {
    label: '排队中',
    type: 'info',
    icon: Timer,
    effect: 'plain',
  },
  [TaskStatus.RUNNING]: {
    label: '运行中',
    type: 'primary',
    icon: Loading,
    effect: 'dark',
  },
  [TaskStatus.COMPLETED]: {
    label: '已完成',
    type: 'success',
    icon: Check,
    effect: 'dark',
  },
  [TaskStatus.FAILED]: {
    label: '失败',
    type: 'danger',
    icon: Close,
    effect: 'dark',
  },
  [TaskStatus.CANCELLED]: {
    label: '已取消',
    type: 'warning',
    icon: Remove,
    effect: 'plain',
  },
}

const config = computed(() => statusConfigs[props.status])

const isRunning = computed(() => props.status === TaskStatus.RUNNING)
</script>

<template>
  <div class="task-status-badge" :class="[`size-${size}`]">
    <ElTag
      :type="config.type"
      :effect="config.effect"
      :size="size"
      round
    >
      <span class="badge-content">
        <!-- 运行中使用自定义 spinner -->
        <span v-if="isRunning" class="custom-spinner" />
        <ElIcon v-else class="status-icon">
          <component :is="config.icon" />
        </ElIcon>
        <span class="status-label">{{ config.label }}</span>
      </span>
    </ElTag>
    
    <!-- 进度条 -->
    <ElProgress
      v-if="showProgress && isRunning"
      :percentage="progress"
      :stroke-width="4"
      :show-text="false"
      class="progress-bar"
    />
  </div>
</template>

<style scoped lang="scss">
.task-status-badge {
  display: inline-flex;
  flex-direction: column;
  gap: 4px;
  
  :deep(.el-tag) {
    padding: 0 12px !important;
    height: 28px !important;
    line-height: 28px !important;
  }
  
  .badge-content {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    height: 100%;
  }
  
  .status-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    font-size: 14px;
    flex-shrink: 0;
    
    :deep(svg) {
      width: 14px;
      height: 14px;
    }
  }
  
  // 自定义加载动画
  .custom-spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  
  .status-label {
    line-height: 28px;
    white-space: nowrap;
  }
  
  .progress-bar {
    width: 100%;
  }
  
  &.size-small {
    :deep(.el-tag) {
      height: 24px !important;
      padding: 0 10px !important;
      line-height: 24px !important;
    }
    
    .custom-spinner {
      width: 12px;
      height: 12px;
      border-width: 1.5px;
    }
    
    .status-icon {
      width: 12px;
      height: 12px;
      font-size: 12px;
      
      :deep(svg) {
        width: 12px;
        height: 12px;
      }
    }
    
    .status-label {
      font-size: 12px;
      line-height: 24px;
    }
  }
  
  &.size-large {
    :deep(.el-tag) {
      height: 32px !important;
      padding: 0 14px !important;
      line-height: 32px !important;
    }
    
    .custom-spinner {
      width: 16px;
      height: 16px;
    }
    
    .status-icon {
      width: 16px;
      height: 16px;
      font-size: 16px;
      
      :deep(svg) {
        width: 16px;
        height: 16px;
      }
    }
    
    .status-label {
      font-size: 14px;
      line-height: 32px;
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
