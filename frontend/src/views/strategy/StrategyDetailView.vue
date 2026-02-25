<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { strategyApi, type Strategy } from '@/api'

const route = useRoute()
const router = useRouter()

const strategyId = computed(() => route.params.strategyId as string)
const strategy = ref<Strategy | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    strategy.value = await strategyApi.getStrategy(strategyId.value)
  } finally {
    loading.value = false
  }
})

async function runStrategy() {
  if (!strategy.value) return
  const response = await strategyApi.runStrategy(strategy.value.strategy_id)
  router.push(`/analysis/${response.task_id}`)
}
</script>

<template>
  <div class="strategy-detail-view">
    <div class="page-header">
      <el-button :icon="ArrowLeft" @click="router.back()">返回</el-button>
      <div v-if="strategy" class="actions">
        <el-button @click="router.push(`/strategy/${strategyId}/edit`)">编辑</el-button>
        <el-button type="primary" @click="runStrategy">执行策略</el-button>
      </div>
    </div>
    
    <div v-if="strategy && !loading" class="content">
      <!-- 基本信息 -->
      <div class="info-section card">
        <h2>{{ strategy.name }}</h2>
        <p v-if="strategy.description" class="description">{{ strategy.description }}</p>
        
        <div class="meta-grid">
          <div class="meta-item">
            <span class="label">状态</span>
            <el-tag :type="strategy.is_active ? 'success' : 'info'">
              {{ strategy.is_active ? '启用' : '禁用' }}
            </el-tag>
          </div>
          <div class="meta-item">
            <span class="label">可见性</span>
            <span>{{ strategy.is_public ? '公开' : '私有' }}</span>
          </div>
          <div class="meta-item">
            <span class="label">执行次数</span>
            <span>{{ strategy.run_count }}</span>
          </div>
          <div class="meta-item">
            <span class="label">预警</span>
            <span>{{ strategy.alert_enabled ? '已开启' : '未开启' }}</span>
          </div>
        </div>
      </div>
      
      <!-- 股票池 -->
      <div class="stock-pool-section card">
        <h3>股票池 ({{ strategy.stock_pool.length }})</h3>
        <div class="stock-tags">
          <el-tag
            v-for="code in strategy.stock_pool"
            :key="code"
            @click="router.push(`/stock/${code}`)"
            style="cursor: pointer"
          >
            {{ code }}
          </el-tag>
          <span v-if="strategy.stock_pool.length === 0" class="empty">未设置</span>
        </div>
      </div>
      
      <!-- 权重配置 -->
      <div v-if="Object.keys(strategy.weights).length > 0" class="weights-section card">
        <h3>分析权重</h3>
        <div class="weight-list">
          <div v-for="(value, key) in strategy.weights" :key="key" class="weight-item">
            <span class="label">{{ key }}</span>
            <el-progress :percentage="value" :stroke-width="8" />
          </div>
        </div>
      </div>
    </div>
    
    <div v-else class="loading">
      <el-skeleton :rows="10" animated />
    </div>
  </div>
</template>

<script lang="ts">
import { ArrowLeft } from '@element-plus/icons-vue'
export default {
  data() {
    return { ArrowLeft }
  }
}
</script>

<style lang="scss" scoped>
.strategy-detail-view {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  
  .actions {
    display: flex;
    gap: 12px;
  }
}

.content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-section {
  padding: 24px;
  
  h2 {
    font-size: 24px;
    margin-bottom: 8px;
  }
  
  .description {
    color: var(--text-secondary);
    margin-bottom: 20px;
  }
  
  .meta-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
    
    .meta-item {
      .label {
        display: block;
        font-size: 12px;
        color: var(--text-tertiary);
        margin-bottom: 4px;
      }
    }
  }
}

.stock-pool-section,
.weights-section {
  padding: 20px;
  
  h3 {
    margin-bottom: 16px;
  }
}

.stock-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  
  .empty {
    color: var(--text-tertiary);
  }
}

.weight-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  
  .weight-item {
    display: flex;
    align-items: center;
    gap: 16px;
    
    .label {
      width: 80px;
      font-size: 14px;
    }
    
    .el-progress {
      flex: 1;
    }
  }
}

.loading {
  padding: 40px;
}
</style>
