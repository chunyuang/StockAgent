<script setup lang="ts">
/**
 * StrategyRiskConfigPanel - 按策略类型Tab切换的风控独立配置
 * 5种策略：半路追涨 / 首板打板 / 涨停开板 / 龙头低吸 / 跌停翘板
 * 每种策略有独立的风控覆盖参数
 */
import { reactive, onMounted, watch } from 'vue'
import { systemApi } from '@/api'
import {
  ElTabs,
  ElTabPane,
  ElForm,
  ElFormItem,
  ElSwitch,
  ElInputNumber,
  ElInput,
  ElTag,
  ElMessage,
} from 'element-plus'

// ==================== 类型 ====================

interface StrategyRiskOverride {
  enabled: boolean               // 是否启用策略级风控覆盖
  max_position_pct: number       // 该策略最大仓位占比 0.3
  max_daily_trades: number       // 单日最大交易笔数 3
  stop_loss_pct: number          // 策略止损覆盖 0.02
  take_profit_pct: number        // 策略止盈覆盖 0.07
  min_confidence: number         // 最低置信度 0.6
  max_slippage_pct: number       // 最大允许滑点 0.005
  time_restrict_enabled: boolean // 时间限制开关
  earliest_entry: string         // 最早入场时间 "09:35"
  latest_entry: string           // 最晚入场时间 "14:30"
  no_entry_before_close: number  // 收盘前N分钟禁止入场 15
}

interface AllStrategyRiskConfig {
  halfway_chase: StrategyRiskOverride & { name: string }
  first_limit_up: StrategyRiskOverride & { name: string }
  limit_up_open: StrategyRiskOverride & { name: string }
  leader_buy_dip: StrategyRiskOverride & { name: string }
  limit_down_qiao: StrategyRiskOverride & { name: string }
}

// ==================== 默认值 ====================

function defaultOverride(name: string): StrategyRiskOverride & { name: string } {
  return {
    name,
    enabled: false,
    max_position_pct: 0.3,
    max_daily_trades: 3,
    stop_loss_pct: 0.02,
    take_profit_pct: 0.07,
    min_confidence: 0.6,
    max_slippage_pct: 0.005,
    time_restrict_enabled: true,
    earliest_entry: '09:35',
    latest_entry: '14:30',
    no_entry_before_close: 15,
  }
}

const config = reactive<AllStrategyRiskConfig>({
  halfway_chase: defaultOverride('🏃‍♂️ 半路追涨'),
  first_limit_up: defaultOverride('🥇 首板打板'),
  limit_up_open: defaultOverride('📈 涨停开板'),
  leader_buy_dip: defaultOverride('🐲 龙头低吸'),
  limit_down_qiao: defaultOverride('💥 跌停翘板'),
})

// 预设覆盖值
const strategyPresets: Record<string, Partial<StrategyRiskOverride>> = {
  halfway_chase: { max_position_pct: 0.25, stop_loss_pct: 0.025, take_profit_pct: 0.05, earliest_entry: '09:35', latest_entry: '10:30' },
  first_limit_up: { max_position_pct: 0.20, stop_loss_pct: 0.03, take_profit_pct: 0.10, min_confidence: 0.7, latest_entry: '10:00' },
  limit_up_open: { max_position_pct: 0.15, stop_loss_pct: 0.02, take_profit_pct: 0.08, min_confidence: 0.65 },
  leader_buy_dip: { max_position_pct: 0.30, stop_loss_pct: 0.025, take_profit_pct: 0.12, min_confidence: 0.5, no_entry_before_close: 30 },
  limit_down_qiao: { max_position_pct: 0.10, stop_loss_pct: 0.015, take_profit_pct: 0.06, max_daily_trades: 1, min_confidence: 0.75, no_entry_before_close: 30 },
}

const STORAGE_KEY = 'stockagent_strategy_risk_config'

// ==================== 生命周期 ====================

onMounted(async () => {
  let loaded = false
  try {
    // 尝试从后端加载策略风控覆盖配置
    const res = await systemApi.getRiskConfig()
    if (res?.success && res?.data?.strategy_overrides) {
      const overrides = res.data.strategy_overrides
      for (const key of Object.keys(config) as (keyof AllStrategyRiskConfig)[]) {
        if (overrides[key]) Object.assign(config[key], overrides[key])
      }
      loaded = true
    }
  } catch { /* fallback */ }

  if (!loaded) {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        for (const key of Object.keys(config) as (keyof AllStrategyRiskConfig)[]) {
          if (parsed[key]) Object.assign(config[key], parsed[key])
        }
      } catch { /* ignore */ }
    } else {
      // 首次加载应用预设
      for (const [key, preset] of Object.entries(strategyPresets)) {
        Object.assign(config[key as keyof AllStrategyRiskConfig], preset)
      }
    }
  }
})

watch(config, () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  // 异步保存到后端
  systemApi.saveStrategyRiskConfig(config as any).catch(() => { /* silent fallback */ })
}, { deep: true })

// ==================== 方法 ====================

function applyPresetForStrategy(key: keyof AllStrategyRiskConfig) {
  const preset = strategyPresets[key]
  if (preset) {
    Object.assign(config[key], preset)
    config[key].enabled = true
    ElMessage.success(`${config[key].name} 已应用推荐参数`)
  }
}

function disableOverride(key: keyof AllStrategyRiskConfig) {
  config[key].enabled = false
  ElMessage.info(`${config[key].name} 已恢复使用全局风控参数`)
}

// ==================== 暴露 ====================

defineExpose({ config })
</script>

<template>
  <div class="strategy-risk-config-panel">
    <div class="panel-hint">
      <ElTag type="info" size="small" effect="plain">💡 启用覆盖后，该策略将使用独立风控参数，未覆盖项仍使用全局配置</ElTag>
    </div>

    <ElTabs type="border-card">
      <ElTabPane v-for="(cfg, key) in config" :key="key" :label="cfg.name">
        <div class="strategy-header">
          <ElSwitch v-model="cfg.enabled" active-text="独立风控" inactive-text="使用全局" />
          <span style="flex:1" />
          <ElTag v-if="cfg.enabled" type="success" size="small">已启用覆盖</ElTag>
          <ElTag v-else type="info" size="small">使用全局风控</ElTag>
        </div>

        <ElForm label-width="140px" size="small" :disabled="!cfg.enabled" class="strategy-form">
          <!-- 仓位与频率 -->
          <div class="form-group-title">📊 仓位与频率</div>
          <ElFormItem label="最大仓位占比">
            <ElInputNumber v-model="cfg.max_position_pct" :min="0.05" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">{{ (cfg.max_position_pct * 100).toFixed(0) }}%</span>
          </ElFormItem>
          <ElFormItem label="单日最大交易笔数">
            <ElInputNumber v-model="cfg.max_daily_trades" :min="1" :max="20" style="width: 150px" />
            <span class="unit">笔</span>
          </ElFormItem>

          <!-- 止盈止损 -->
          <div class="form-group-title">💹 止盈止损</div>
          <ElFormItem label="止损比例">
            <ElInputNumber v-model="cfg.stop_loss_pct" :min="0.005" :max="0.10" :step="0.005" :precision="3" style="width: 150px" />
            <span class="unit">{{ (cfg.stop_loss_pct * 100).toFixed(1) }}%</span>
          </ElFormItem>
          <ElFormItem label="止盈比例">
            <ElInputNumber v-model="cfg.take_profit_pct" :min="0.01" :max="0.30" :step="0.01" :precision="3" style="width: 150px" />
            <span class="unit">{{ (cfg.take_profit_pct * 100).toFixed(1) }}%</span>
          </ElFormItem>

          <!-- 信号质量 -->
          <div class="form-group-title">🎯 信号质量</div>
          <ElFormItem label="最低置信度">
            <ElInputNumber v-model="cfg.min_confidence" :min="0" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">{{ (cfg.min_confidence * 100).toFixed(0) }}%</span>
          </ElFormItem>
          <ElFormItem label="最大允许滑点">
            <ElInputNumber v-model="cfg.max_slippage_pct" :min="0" :max="0.02" :step="0.001" :precision="3" style="width: 150px" />
            <span class="unit">{{ (cfg.max_slippage_pct * 1000).toFixed(1) }}‰</span>
          </ElFormItem>

          <!-- 时间限制 -->
          <div class="form-group-title">⏰ 时间限制</div>
          <ElFormItem label="启用时间限制">
            <ElSwitch v-model="cfg.time_restrict_enabled" />
          </ElFormItem>
          <ElFormItem label="最早入场时间" :disabled="!cfg.time_restrict_enabled">
            <ElInput v-model="cfg.earliest_entry" style="width: 100px" :disabled="!cfg.time_restrict_enabled" placeholder="HH:MM" />
          </ElFormItem>
          <ElFormItem label="最晚入场时间" :disabled="!cfg.time_restrict_enabled">
            <ElInput v-model="cfg.latest_entry" style="width: 100px" :disabled="!cfg.time_restrict_enabled" placeholder="HH:MM" />
          </ElFormItem>
          <ElFormItem label="收盘前禁止入场" :disabled="!cfg.time_restrict_enabled">
            <ElInputNumber v-model="cfg.no_entry_before_close" :min="0" :max="60" style="width: 150px" :disabled="!cfg.time_restrict_enabled" />
            <span class="unit">分钟</span>
          </ElFormItem>
        </ElForm>

        <div class="strategy-actions">
          <ElTag class="clickable" type="primary" size="small" @click="applyPresetForStrategy(key as keyof AllStrategyRiskConfig)">⚡ 应用推荐参数</ElTag>
          <ElTag class="clickable" type="info" size="small" @click="disableOverride(key as keyof AllStrategyRiskConfig)">🔄 恢复全局风控</ElTag>
        </div>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<script lang="ts">
export default { name: 'StrategyRiskConfigPanel' }
</script>

<style scoped lang="scss">
.strategy-risk-config-panel {
  padding: 8px 0;
}
.panel-hint {
  margin-bottom: 12px;
}
.strategy-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.strategy-form {
  margin-top: 8px;
}
.form-group-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
  margin: 12px 0 8px;
  padding-left: 4px;
  border-left: 3px solid var(--el-color-primary);
  line-height: 1;
}
.unit {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.strategy-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  .clickable { cursor: pointer; }
}
</style>
