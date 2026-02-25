<script setup lang="ts">
/**
 * 大盘概览卡片
 * 
 * 视觉升级版 - 增加涨跌对比条、动态颜色
 */
import { computed, ref, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import { ElSkeleton, ElIcon } from 'element-plus'
import { Refresh, ArrowUp, ArrowDown, Clock } from '@element-plus/icons-vue'

defineProps<{
  loading?: boolean
}>()

const marketStore = useMarketStore()
const isRefreshing = ref(false)

// 指数数据
const indices = computed(() => [
  {
    name: '上证指数',
    code: 'SH',
    value: marketStore.shIndex || 0,
    change: marketStore.shChange || 0,
    color: '#3b82f6',
  },
  {
    name: '深证成指',
    code: 'SZ',
    value: marketStore.szIndex || 0,
    change: marketStore.szChange || 0,
    color: '#8b5cf6',
  },
  {
    name: '创业板指',
    code: 'CYB',
    value: marketStore.cybIndex || 0,
    change: marketStore.cybChange || 0,
    color: '#06b6d4',
  },
])

// 涨跌统计
const stats = computed(() => {
  const up = marketStore.marketStats.up || 0
  const down = marketStore.marketStats.down || 0
  const flat = marketStore.marketStats.flat || 0
  const total = up + down + flat || 1
  
  return {
    up,
    down,
    flat,
    limitUp: marketStore.marketStats.limitUp || 0,
    limitDown: marketStore.marketStats.limitDown || 0,
    upPercent: (up / total) * 100,
    downPercent: (down / total) * 100,
    flatPercent: (flat / total) * 100,
  }
})

// 格式化时间
const updateTimeStr = computed(() => {
  if (!marketStore.lastUpdated) return ''
  return marketStore.lastUpdated.toLocaleTimeString('zh-CN', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit' 
  })
})

// 涨跌样式
function getChangeClass(change: number): string {
  return change > 0 ? 'up' : change < 0 ? 'down' : 'flat'
}

// 格式化涨跌
function formatChange(change: number): string {
  const sign = change > 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}%`
}

// 格式化数值
function formatValue(value: number): string {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 刷新数据
async function refreshData() {
  isRefreshing.value = true
  await marketStore.fetchOverview()
  setTimeout(() => {
    isRefreshing.value = false
  }, 500)
}

onMounted(() => {
  // 自动刷新
  const interval = setInterval(() => {
    marketStore.fetchOverview()
  }, 30000) // 30秒刷新一次
  
  return () => clearInterval(interval)
})
</script>

<template>
  <div class="market-overview-card card">
    <div class="card-header">
      <div class="header-left">
        <span class="header-title">大盘概览</span>
        <span v-if="updateTimeStr" class="update-time">
          <ElIcon :size="12"><Clock /></ElIcon>
          {{ updateTimeStr }}
        </span>
      </div>
      <button 
        class="refresh-btn" 
        :class="{ 'is-spinning': isRefreshing }"
        @click="refreshData"
      >
        <ElIcon :size="16"><Refresh /></ElIcon>
      </button>
    </div>
    
    <div class="card-body">
      <el-skeleton v-if="loading" :rows="3" animated />
      
      <template v-else>
        <!-- 指数卡片 -->
        <div class="indices-grid">
          <div
            v-for="index in indices"
            :key="index.code"
            class="index-card"
            :class="getChangeClass(index.change)"
          >
            <div class="index-header">
              <span class="index-name">{{ index.name }}</span>
              <span class="index-code">{{ index.code }}</span>
            </div>
            
            <div class="index-value">
              {{ formatValue(index.value) }}
            </div>
            
            <div class="index-change" :class="getChangeClass(index.change)">
              <ElIcon v-if="index.change > 0" :size="14"><ArrowUp /></ElIcon>
              <ElIcon v-else-if="index.change < 0" :size="14"><ArrowDown /></ElIcon>
              <span>{{ formatChange(index.change) }}</span>
            </div>
            
            <!-- Mini Sparkline 模拟 -->
            <div class="index-trend">
              <svg viewBox="0 0 60 20" class="trend-line" :class="getChangeClass(index.change)">
                <path 
                  d="M0,15 Q10,12 15,10 T30,8 T45,12 T60,5" 
                  fill="none" 
                  stroke="currentColor" 
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>
            </div>
          </div>
        </div>
        
        <!-- 涨跌分布条 -->
        <div class="distribution-section">
          <div class="distribution-header">
            <span class="section-label">涨跌分布</span>
            <div class="distribution-legend">
              <span class="legend-item up">涨 {{ stats.up }}</span>
              <span class="legend-item flat">平 {{ stats.flat }}</span>
              <span class="legend-item down">跌 {{ stats.down }}</span>
            </div>
          </div>
          
          <div class="distribution-bar">
            <div 
              class="bar-segment up" 
              :style="{ width: stats.upPercent + '%' }"
            />
            <div 
              class="bar-segment flat" 
              :style="{ width: stats.flatPercent + '%' }"
            />
            <div 
              class="bar-segment down" 
              :style="{ width: stats.downPercent + '%' }"
            />
          </div>
        </div>
        
        <!-- 涨跌停统计 -->
        <div class="limit-stats">
          <div class="limit-item up">
            <div class="limit-icon">
              <ArrowUp />
            </div>
            <div class="limit-info">
              <span class="limit-label">涨停</span>
              <span class="limit-value">{{ stats.limitUp }}</span>
            </div>
          </div>
          
          <div class="limit-divider" />
          
          <div class="limit-item down">
            <div class="limit-icon">
              <ArrowDown />
            </div>
            <div class="limit-info">
              <span class="limit-label">跌停</span>
              <span class="limit-value">{{ stats.limitDown }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.market-overview-card {
  .card-header {
    .header-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    
    .header-title {
      font-weight: 600;
      color: var(--text-primary);
    }
    
    .update-time {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      color: var(--text-tertiary);
      font-weight: 400;
    }
    
    .refresh-btn {
      width: 32px;
      height: 32px;
      border-radius: 8px;
      border: 1px solid var(--border-color);
      background: var(--bg-secondary);
      color: var(--text-secondary);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all var(--transition-fast);
      
      &:hover {
        border-color: var(--primary-500);
        color: var(--primary-500);
        background: var(--primary-50);
      }
      
      &.is-spinning {
        .el-icon {
          animation: spin 0.8s linear infinite;
        }
      }
    }
  }
  
  .card-body {
    padding: 20px 24px 24px;
  }
}

// ==================== 指数卡片 ====================

.indices-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.index-card {
  position: relative;
  padding: 16px 18px;
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  border: 1px solid var(--border-light);
  transition: all var(--transition-normal);
  overflow: hidden;
  
  &:hover {
    border-color: var(--border-color);
    box-shadow: var(--shadow-sm);
  }
  
  &.up {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.03) 0%, rgba(239, 68, 68, 0.06) 100%);
    border-color: rgba(239, 68, 68, 0.1);
  }
  
  &.down {
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.03) 0%, rgba(34, 197, 94, 0.06) 100%);
    border-color: rgba(34, 197, 94, 0.1);
  }
  
  .index-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  
  .index-name {
    font-size: 13px;
    color: var(--text-secondary);
    font-weight: 500;
  }
  
  .index-code {
    font-size: 11px;
    color: var(--text-tertiary);
    padding: 2px 6px;
    background: var(--bg-tertiary);
    border-radius: 4px;
  }
  
  .index-value {
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 6px;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.5px;
  }
  
  .index-change {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    font-weight: 600;
    
    &.up {
      color: var(--stock-up);
    }
    
    &.down {
      color: var(--stock-down);
    }
    
    &.flat {
      color: var(--stock-flat);
    }
  }
  
  .index-trend {
    position: absolute;
    right: 12px;
    bottom: 12px;
    width: 60px;
    height: 20px;
    opacity: 0.4;
    
    .trend-line {
      width: 100%;
      height: 100%;
      
      &.up {
        color: var(--stock-up);
      }
      
      &.down {
        color: var(--stock-down);
      }
      
      &.flat {
        color: var(--stock-flat);
      }
    }
  }
}

// ==================== 涨跌分布条 ====================

.distribution-section {
  margin-bottom: 20px;
}

.distribution-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.section-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.distribution-legend {
  display: flex;
  gap: 16px;
  
  .legend-item {
    font-size: 12px;
    font-weight: 500;
    
    &.up {
      color: var(--stock-up);
    }
    
    &.down {
      color: var(--stock-down);
    }
    
    &.flat {
      color: var(--stock-flat);
    }
  }
}

.distribution-bar {
  height: 8px;
  border-radius: 4px;
  background: var(--bg-tertiary);
  display: flex;
  overflow: hidden;
  
  .bar-segment {
    height: 100%;
    transition: width var(--transition-slow);
    
    &.up {
      background: var(--stock-up);
    }
    
    &.down {
      background: var(--stock-down);
    }
    
    &.flat {
      background: var(--stock-flat);
    }
  }
}

// ==================== 涨跌停统计 ====================

.limit-stats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.limit-item {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  justify-content: center;
  
  .limit-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    
    svg {
      width: 18px;
      height: 18px;
    }
  }
  
  &.up .limit-icon {
    background: var(--stock-up-bg);
    color: var(--stock-up);
  }
  
  &.down .limit-icon {
    background: var(--stock-down-bg);
    color: var(--stock-down);
  }
  
  .limit-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .limit-label {
    font-size: 12px;
    color: var(--text-tertiary);
  }
  
  .limit-value {
    font-size: 20px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  
  &.up .limit-value {
    color: var(--stock-up);
  }
  
  &.down .limit-value {
    color: var(--stock-down);
  }
}

.limit-divider {
  width: 1px;
  height: 40px;
  background: var(--border-color);
  margin: 0 24px;
}

// ==================== 响应式 ====================

@media (max-width: 640px) {
  .indices-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  
  .index-card {
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-rows: auto auto;
    gap: 4px 16px;
    
    .index-header {
      grid-column: 1;
      margin-bottom: 0;
    }
    
    .index-value {
      grid-column: 1;
      font-size: 22px;
    }
    
    .index-change {
      grid-column: 2;
      grid-row: 1 / 3;
      align-self: center;
    }
    
    .index-trend {
      display: none;
    }
  }
  
  .limit-stats {
    flex-direction: column;
    gap: 16px;
  }
  
  .limit-divider {
    width: 80%;
    height: 1px;
    margin: 0;
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
