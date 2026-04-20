<script setup lang="ts">
/**
 * 系统状态页面
 * 功能：显示策略近期表现、策略权重配置、支持手动调整权重
 */
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

// 导入组件
import {
  ElCard,
  ElButton,
  ElTable,
  ElTableColumn,
  ElInputNumber,
  ElDescriptions,
  ElDescriptionItem,
  ElTag,
  ElAlert,
  ElDivider,
  ElSwitch,
  ElForm,
  ElFormItem,
  ElProgress,
  ElSpace,
} from 'element-plus'

// 导入 API 客户端（自动注入认证 Token）
import { api } from '@/api'

// ==================== 状态 ====================

// 加载状态
const loading = ref(false)
const saving = ref(false)

// 策略状态数据
const strategyStatus = ref<any[]>([])
const weightConfig = ref<Record<string, number>>({})

// 风控配置
const riskControlConfig = reactive({
  enable_enhanced_stop_loss: true,
  enhanced_stop_loss_pct: 0.08,
  enable_dynamic_take_profit: true,
  dynamic_take_profit_pct: 0.10,
  enable_ma60_filter: true,
  enable_sector_concentration_filter: true,
  max_sector_stocks: 3,
})

// ==================== 方法 ====================

// 获取策略状态
const fetchStrategyStatus = async () => {
  loading.value = true
  try {
    const result = await api.get('/system/strategy-stats')
    if (result.success) {
      strategyStatus.value = result.data.strategies || []
      // 从返回数据中提取权重
      strategyStatus.value.forEach(s => {
        weightConfig.value[s.code] = s.weight
      })
      ElMessage.success('获取策略状态成功')
      // 获取风控配置
      await fetchRiskConfig()
    } else {
      ElMessage.error(result.message || '获取失败')
    }
  } catch (error) {
    console.error('获取失败:', error)
    ElMessage.error('获取失败: ' + (error as Error).message)
  } finally {
    loading.value = false
  }
}

// 获取风控配置
const fetchRiskConfig = async () => {
  try {
    const result = await api.get('/system/risk-config')
    if (result.success) {
      // 转换字段名适配前端
      const data = result.data
      if (data) {
        riskControlConfig.enable_enhanced_stop_loss = data.enable_stop_loss ?? true
        riskControlConfig.enhanced_stop_loss_pct = data.stop_loss_pct ?? 0.08
        riskControlConfig.enable_dynamic_take_profit = data.enable_take_profit ?? true
        riskControlConfig.dynamic_take_profit_pct = data.take_profit_pct ?? 0.10
        riskControlConfig.enable_ma60_filter = data.enable_ma60_filter ?? true
        riskControlConfig.enable_sector_concentration_filter = data.enable_sector_concentration ?? true
        riskControlConfig.max_sector_stocks = data.sector_concentration_top_n ?? 3
      }
    }
  } catch (error) {
    console.error('获取风控配置失败:', error)
  }
}

// 保存权重配置
const saveWeights = async () => {
  saving.value = true
  try {
    // 转换为后端期望的格式
    const strategies = strategyStatus.value.map(s => ({
      code: s.code,
      weight: weightConfig.value[s.code] ?? s.weight,
    }))
    
    const result = await api.post('/system/save-weights', { strategies })
    if (result.success) {
      ElMessage.success('权重配置保存成功')
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error('保存失败: ' + (error as Error).message)
  } finally {
    saving.value = false
  }
}

// 保存风控配置
const saveRiskControl = async () => {
  saving.value = true
  try {
    // 转换为后端期望的格式
    const config = {
      enable_stop_loss: riskControlConfig.enable_enhanced_stop_loss,
      stop_loss_pct: riskControlConfig.enhanced_stop_loss_pct,
      enable_take_profit: riskControlConfig.enable_dynamic_take_profit,
      take_profit_pct: riskControlConfig.dynamic_take_profit_pct,
      enable_ma60_filter: riskControlConfig.enable_ma60_filter,
      enable_sector_concentration: riskControlConfig.enable_sector_concentration_filter,
      sector_concentration_top_n: riskControlConfig.max_sector_stocks,
    }
    
    const result = await api.post('/system/save-risk-config', { config })
    if (result.success) {
      ElMessage.success('风控配置保存成功')
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error('保存失败: ' + (error as Error).message)
  } finally {
    saving.value = false
  }
}

// 格式化百分比
const formatPercent = (val: number): string => {
  return `${(val * 100).toFixed(2)}%`
}

// 总权重
const totalWeight = computed(() => {
  return Object.values(weightConfig.value).reduce((sum, w) => sum + w, 0)
})

// 页面加载
onMounted(() => {
  fetchStrategyStatus()
})
</script>

<template>
  <div class="system-status-page">
    <div class="page-header">
      <h1 class="page-title">📊 系统状态与策略配置</h1>
      <p class="page-description">查看策略近期表现、调整策略权重、配置风控规则</p>
    </div>

    <!-- 策略状态表格 -->
    <ElCard class="status-card" header="🎯 策略近期表现">
      <ElTable 
        :data="strategyStatus" 
        v-loading="loading"
        border
        stripe
      >
        <ElTableColumn 
          prop="name" 
          label="策略名称" 
          width="160"
        />
        <ElTableColumn 
          prop="cumulative_return" 
          label="累计收益率" 
          width="120"
          v-slot="{ row }"
        >
          <span :class="{ 'positive': row.cumulative_return > 0, 'negative': row.cumulative_return < 0 }">
            {{ ((row.cumulative_return || 0)).toFixed(2) }}%
          </span>
        </ElTableColumn>
        <ElTableColumn 
          prop="win_rate" 
          label="胜率" 
          width="100"
          v-slot="{ row }"
        >
          {{ ((row.win_rate || 0)).toFixed(2) }}%
        </ElTableColumn>
        <ElTableColumn 
          prop="profit_loss_ratio" 
          label="盈亏比" 
          width="100"
          v-slot="{ row }"
        >
          {{ (row.profit_loss_ratio || 0).toFixed(2) }}
        </ElTableColumn>
        <ElTableColumn 
          prop="max_drawdown" 
          label="最大回撤" 
          width="100"
          v-slot="{ row }"
        >
          <span class="negative">
            {{ ((row.max_drawdown || 0)).toFixed(2) }}%
          </span>
        </ElTableColumn>
        <ElTableColumn 
          prop="total_trades" 
          label="交易次数" 
          width="100"
        />
        <ElTableColumn 
          label="当前权重" 
          width="140"
          v-slot="{ row }"
        >
          <ElInputNumber
            v-model="weightConfig[row.code]"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
            size="small"
          />
        </ElTableColumn>
      </ElTable>

      <div class="mt-4 weight-summary">
        <ElAlert 
          :type="totalWeight === 1 ? 'success' : 'warning'"
          :title="`总权重: ${(totalWeight * 100).toFixed(0)}%，推荐调整到 100%`"
        />
      </div>

      <div class="mt-4">
        <ElButton 
          type="primary" 
          @click="saveWeights"
          :loading="saving"
        >
          💾 保存权重配置
        </ElButton>
        <ElButton 
          type="default" 
          @click="fetchStrategyStatus"
          :disabled="saving"
        >
          🔄 刷新
        </ElButton>
      </div>
    </ElCard>

    <ElDivider />

    <!-- 风控配置面板 -->
    <ElCard class="risk-card" header="🛡️ 风控配置">
      <ElForm label-width="200px">
        <ElFormItem label="启用强化止损">
          <ElSwitch 
            v-model="riskControlConfig.enable_enhanced_stop_loss" 
            active-text="启用"
            inactive-text="禁用"
          />
        </ElFormItem>
        <ElFormItem label="强化止损线" v-if="riskControlConfig.enable_enhanced_stop_loss">
          <ElInputNumber
            v-model="riskControlConfig.enhanced_stop_loss_pct"
            :min="0.01"
            :max="0.5"
            :step="0.01"
            style="width: 150px"
          />
          <span class="unit ml-2">{{ (riskControlConfig.enhanced_stop_loss_pct * 100).toFixed(0) }}%</span>
        </ElFormItem>

        <ElFormItem label="启用动态止盈">
          <ElSwitch 
            v-model="riskControlConfig.enable_dynamic_take_profit" 
            active-text="启用"
            inactive-text="禁用"
          />
        </ElFormItem>
        <ElFormItem label="动态止盈线" v-if="riskControlConfig.enable_dynamic_take_profit">
          <ElInputNumber
            v-model="riskControlConfig.dynamic_take_profit_pct"
            :min="0.01"
            :max="1.0"
            :step="0.01"
            style="width: 150px"
          />
          <span class="unit ml-2">{{ (riskControlConfig.dynamic_take_profit_pct * 100).toFixed(0) }}%</span>
        </ElFormItem>

        <ElFormItem label="启用 MA60 过滤">
          <ElSwitch 
            v-model="riskControlConfig.enable_ma60_filter" 
            active-text="启用"
            inactive-text="禁用"
          />
          <div class="desc ml-2">价格在MA60上方才允许买入</div>
        </ElFormItem>

        <ElFormItem label="启用板块集中度过滤">
          <ElSwitch 
            v-model="riskControlConfig.enable_sector_concentration_filter" 
            active-text="启用"
            inactive-text="禁用"
          />
        </ElFormItem>
        <ElFormItem label="单板块最大持股数" v-if="riskControlConfig.enable_sector_concentration_filter">
          <ElInputNumber
            v-model="riskControlConfig.max_sector_stocks"
            :min="1"
            :max="10"
            :step="1"
            style="width: 150px"
          />
          <span class="unit ml-2">只，同一板块最多持有N只</span>
        </ElFormItem>
      </ElForm>

      <div class="mt-4">
        <ElButton 
          type="primary" 
          @click="saveRiskControl"
          :loading="saving"
        >
          💾 保存风控配置
        </ElButton>
      </div>
    </ElCard>

  </div>
</template>

<style scoped lang="scss">
.system-status-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
  
  .page-title {
    font-size: 26px;
    font-weight: 700;
    color: #303133;
    margin: 0 0 8px 0;
  }
  
  .page-description {
    color: #606266;
    margin: 0;
  }
}

.status-card {
  margin-bottom: 20px;
}

.risk-card {
  margin-bottom: 20px;
}

.mt-4 {
  margin-top: 16px;
}

.ml-2 {
  margin-left: 8px;
}

.mb-4 {
  margin-bottom: 16px;
}

.unit {
  margin-left: 8px;
  color: #909399;
}

.desc {
  margin-left: 12px;
  color: #606266;
  font-size: 13px;
}

.positive {
  color: #67c23a;
  font-weight: 600;
}

.negative {
  color: #f56c6c;
  font-weight: 500;
}

.weight-summary {
  max-width: 500px;
}
</style>
