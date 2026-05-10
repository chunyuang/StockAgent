<script setup lang="ts">
/**
 * RiskConfigPanel - 风控参数配置面板
 * 基于 pre_buy_risk_check.py 的参数结构
 * 4大分组：市场环境过滤 / 日内回撤控制 / 连续亏损熔断 / 个股风险过滤
 * 已对接后端API /system/risk-config，API不可用时自动降级到localStorage
 */
import { reactive, onMounted, watch } from 'vue'
import {
  ElForm,
  ElFormItem,
  ElSwitch,
  ElInputNumber,
  ElSelect,
  ElOption,
  ElButton,
  ElDivider,
  ElMessage,
} from 'element-plus'
import { Refresh, Check } from '@element-plus/icons-vue'
import { systemApi } from '@/api'

// ==================== 类型定义 ====================

interface MarketFilterConfig {
  enabled: boolean
  reference_index: string
  max_index_drop: number          // 0.03 = 3%
  limit_up_count_threshold: number // 涨停家数阈值
  limit_down_count_threshold: number // 跌停家数阈值
}

interface DrawdownConfig {
  daily_max_drawdown: number      // 0.03 = 3%
  weekly_max_drawdown: number     // 0.05 = 5%
  monthly_max_drawdown: number    // 0.10 = 10%
}

interface LossCircuitConfig {
  consecutive_loss_limit: number  // 3次
  consecutive_loss_pause_days: number // 1天
  max_daily_loss_count: number    // 单日最大亏损笔数
}

interface StockRiskConfig {
  exclude_st_stocks: boolean
  min_market_cap: number          // 30亿
  max_volatility: number          // 0.20 = 20%
  limit_board_caution: boolean
  max_limit_up_days: number       // 连续涨停天数上限
  max_limit_down_days: number     // 连续跌停天数上限
}

interface RiskConfig {
  market_filter: MarketFilterConfig
  drawdown: DrawdownConfig
  loss_circuit: LossCircuitConfig
  stock_risk: StockRiskConfig
}

// ==================== 默认配置 ====================

const defaultConfig: RiskConfig = {
  market_filter: {
    enabled: true,
    reference_index: 'sh000001',
    max_index_drop: 0.03,
    limit_up_count_threshold: 10,
    limit_down_count_threshold: 50,
  },
  drawdown: {
    daily_max_drawdown: 0.03,
    weekly_max_drawdown: 0.05,
    monthly_max_drawdown: 0.10,
  },
  loss_circuit: {
    consecutive_loss_limit: 3,
    consecutive_loss_pause_days: 1,
    max_daily_loss_count: 5,
  },
  stock_risk: {
    exclude_st_stocks: true,
    min_market_cap: 30,
    max_volatility: 0.20,
    limit_board_caution: true,
    max_limit_up_days: 2,
    max_limit_down_days: 2,
  },
}


// ==================== 状态 ====================

const config = reactive<RiskConfig>(JSON.parse(JSON.stringify(defaultConfig)))
const saving = reactive({ value: false })


const STORAGE_KEY = 'stockagent_risk_config'

// ==================== 生命周期 ====================

onMounted(async () => {
  // 1. 尝试从后端加载
  let loaded = false
  try {
    const res = await systemApi.getRiskConfig()
    if (res?.success && res?.data) {
      if (res.data.market_filter) Object.assign(config.market_filter, res.data.market_filter)
      if (res.data.drawdown) Object.assign(config.drawdown, res.data.drawdown)
      if (res.data.loss_circuit) Object.assign(config.loss_circuit, res.data.loss_circuit)
      if (res.data.stock_risk) Object.assign(config.stock_risk, res.data.stock_risk)
      loaded = true
    }
  } catch { /* fallback to localStorage */ }

  // 2. 从localStorage加载
  if (!loaded) {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        Object.assign(config.market_filter, parsed.market_filter || {})
        Object.assign(config.drawdown, parsed.drawdown || {})
        Object.assign(config.loss_circuit, parsed.loss_circuit || {})
        Object.assign(config.stock_risk, parsed.stock_risk || {})
      } catch { /* ignore */ }
    }
  }
})

// 自动保存到localStorage
watch(config, () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}, { deep: true })

// ==================== 预设方案 ====================

const presets: Record<string, RiskConfig> = {
  conservative: {
    market_filter: { enabled: true, reference_index: 'sh000001', max_index_drop: 0.02, limit_up_count_threshold: 15, limit_down_count_threshold: 30 },
    drawdown: { daily_max_drawdown: 0.02, weekly_max_drawdown: 0.04, monthly_max_drawdown: 0.08 },
    loss_circuit: { consecutive_loss_limit: 2, consecutive_loss_pause_days: 2, max_daily_loss_count: 3 },
    stock_risk: { exclude_st_stocks: true, min_market_cap: 50, max_volatility: 0.15, limit_board_caution: true, max_limit_up_days: 1, max_limit_down_days: 1 },
  },
  standard: JSON.parse(JSON.stringify(defaultConfig)),
  aggressive: {
    market_filter: { enabled: true, reference_index: 'sh000001', max_index_drop: 0.05, limit_up_count_threshold: 5, limit_down_count_threshold: 80 },
    drawdown: { daily_max_drawdown: 0.05, weekly_max_drawdown: 0.08, monthly_max_drawdown: 0.15 },
    loss_circuit: { consecutive_loss_limit: 5, consecutive_loss_pause_days: 1, max_daily_loss_count: 10 },
    stock_risk: { exclude_st_stocks: true, min_market_cap: 20, max_volatility: 0.30, limit_board_caution: false, max_limit_up_days: 3, max_limit_down_days: 3 },
  },
}

function applyPreset(name: string) {
  const preset = presets[name]
  if (!preset) return
  Object.assign(config.market_filter, preset.market_filter)
  Object.assign(config.drawdown, preset.drawdown)
  Object.assign(config.loss_circuit, preset.loss_circuit)
  Object.assign(config.stock_risk, preset.stock_risk)
  ElMessage.success(`已应用"${name === 'conservative' ? '保守' : name === 'standard' ? '标准' : '激进'}"预设`)
}

// ==================== 保存 ====================

async function saveConfig() {
  saving.value = true
  try {
    try {
      await systemApi.saveRiskConfig(config as any)
      ElMessage.success('风控配置已保存到服务器')
    } catch {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
      ElMessage.success('风控配置已保存到本地（服务器暂不可用）')
    }
  } catch (e: any) {
    ElMessage.error(`保存失败：${e.message}`)
  } finally {
    saving.value = false
  }
}

function resetConfig() {
  Object.assign(config.market_filter, defaultConfig.market_filter)
  Object.assign(config.drawdown, defaultConfig.drawdown)
  Object.assign(config.loss_circuit, defaultConfig.loss_circuit)
  Object.assign(config.stock_risk, defaultConfig.stock_risk)
  ElMessage.info('已恢复默认配置')
}

// ==================== 暴露配置给父组件 ====================

defineExpose({ config })
</script>

<template>
  <div class="risk-config-panel">
    <!-- 预设方案 -->
    <div class="preset-bar">
      <span class="preset-label">⚡ 快速预设：</span>
      <ElButton size="small" @click="applyPreset('conservative')">🛡️ 保守型</ElButton>
      <ElButton size="small" type="primary" @click="applyPreset('standard')">📊 标准型</ElButton>
      <ElButton size="small" @click="applyPreset('aggressive')">🔥 激进型</ElButton>
      <ElButton size="small" :icon="Refresh" @click="resetConfig" style="margin-left: auto">恢复默认</ElButton>
    </div>

    <!-- 1. 市场环境过滤 -->
    <ElDivider content-position="left">🌍 市场环境过滤</ElDivider>
    <ElForm label-width="160px" size="small">
      <ElFormItem label="启用市场环境过滤">
        <ElSwitch v-model="config.market_filter.enabled" />
      </ElFormItem>
      <ElFormItem label="参考指数" :disabled="!config.market_filter.enabled">
        <ElSelect v-model="config.market_filter.reference_index" style="width: 200px" :disabled="!config.market_filter.enabled">
          <ElOption label="上证指数 (sh000001)" value="sh000001" />
          <ElOption label="深证成指 (sz399001)" value="sz399001" />
          <ElOption label="创业板指 (sz399006)" value="sz399006" />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="指数最大跌幅" :disabled="!config.market_filter.enabled">
        <ElInputNumber v-model="config.market_filter.max_index_drop" :min="0.01" :max="0.10" :step="0.005" :precision="3" style="width: 150px" :disabled="!config.market_filter.enabled" />
        <span class="unit">{{ (config.market_filter.max_index_drop * 100).toFixed(1) }}%</span>
      </ElFormItem>
      <ElFormItem label="涨停家数阈值<" :disabled="!config.market_filter.enabled">
        <ElInputNumber v-model="config.market_filter.limit_up_count_threshold" :min="0" :max="100" style="width: 150px" :disabled="!config.market_filter.enabled" />
        <span class="unit">只（低于此值谨慎）</span>
      </ElFormItem>
      <ElFormItem label="跌停家数阈值≥" :disabled="!config.market_filter.enabled">
        <ElInputNumber v-model="config.market_filter.limit_down_count_threshold" :min="0" :max="200" style="width: 150px" :disabled="!config.market_filter.enabled" />
        <span class="unit">只（超过此值暂停开仓）</span>
      </ElFormItem>
    </ElForm>

    <!-- 2. 日内回撤控制 -->
    <ElDivider content-position="left">📉 回撤控制</ElDivider>
    <ElForm label-width="160px" size="small">
      <ElFormItem label="单日最大回撤">
        <ElInputNumber v-model="config.drawdown.daily_max_drawdown" :min="0.01" :max="0.10" :step="0.005" :precision="3" style="width: 150px" />
        <span class="unit">{{ (config.drawdown.daily_max_drawdown * 100).toFixed(1) }}%</span>
      </ElFormItem>
      <ElFormItem label="周最大回撤">
        <ElInputNumber v-model="config.drawdown.weekly_max_drawdown" :min="0.02" :max="0.15" :step="0.01" :precision="3" style="width: 150px" />
        <span class="unit">{{ (config.drawdown.weekly_max_drawdown * 100).toFixed(1) }}%</span>
      </ElFormItem>
      <ElFormItem label="月最大回撤">
        <ElInputNumber v-model="config.drawdown.monthly_max_drawdown" :min="0.05" :max="0.25" :step="0.01" :precision="3" style="width: 150px" />
        <span class="unit">{{ (config.drawdown.monthly_max_drawdown * 100).toFixed(1) }}%</span>
      </ElFormItem>
    </ElForm>

    <!-- 3. 连续亏损熔断 -->
    <ElDivider content-position="left">🔴 连续亏损熔断</ElDivider>
    <ElForm label-width="160px" size="small">
      <ElFormItem label="连续亏损次数上限">
        <ElInputNumber v-model="config.loss_circuit.consecutive_loss_limit" :min="1" :max="10" style="width: 150px" />
        <span class="unit">次（触发熔断）</span>
      </ElFormItem>
      <ElFormItem label="熔断后暂停天数">
        <ElInputNumber v-model="config.loss_circuit.consecutive_loss_pause_days" :min="0" :max="7" style="width: 150px" />
        <span class="unit">天</span>
      </ElFormItem>
      <ElFormItem label="单日最大亏损笔数">
        <ElInputNumber v-model="config.loss_circuit.max_daily_loss_count" :min="1" :max="20" style="width: 150px" />
        <span class="unit">笔</span>
      </ElFormItem>
    </ElForm>

    <!-- 4. 个股风险过滤 -->
    <ElDivider content-position="left">⚠️ 个股风险过滤</ElDivider>
    <ElForm label-width="160px" size="small">
      <ElFormItem label="排除ST/*ST股票">
        <ElSwitch v-model="config.stock_risk.exclude_st_stocks" />
      </ElFormItem>
      <ElFormItem label="最小市值">
        <ElInputNumber v-model="config.stock_risk.min_market_cap" :min="5" :max="200" style="width: 150px" />
        <span class="unit">亿元</span>
      </ElFormItem>
      <ElFormItem label="最大波动率">
        <ElInputNumber v-model="config.stock_risk.max_volatility" :min="0.05" :max="0.50" :step="0.01" :precision="2" style="width: 150px" />
        <span class="unit">{{ (config.stock_risk.max_volatility * 100).toFixed(0) }}%</span>
      </ElFormItem>
      <ElFormItem label="涨跌停次日谨慎">
        <ElSwitch v-model="config.stock_risk.limit_board_caution" />
      </ElFormItem>
      <ElFormItem label="连续涨停天数上限" :disabled="!config.stock_risk.limit_board_caution">
        <ElInputNumber v-model="config.stock_risk.max_limit_up_days" :min="1" :max="10" style="width: 150px" :disabled="!config.stock_risk.limit_board_caution" />
        <span class="unit">天</span>
      </ElFormItem>
      <ElFormItem label="连续跌停天数上限" :disabled="!config.stock_risk.limit_board_caution">
        <ElInputNumber v-model="config.stock_risk.max_limit_down_days" :min="1" :max="10" style="width: 150px" :disabled="!config.stock_risk.limit_board_caution" />
        <span class="unit">天</span>
      </ElFormItem>
    </ElForm>

    <!-- 保存按钮 -->
    <div class="save-bar">
      <ElButton type="primary" :icon="Check" :loading="saving.value" @click="saveConfig">
        保存风控配置
      </ElButton>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'RiskConfigPanel' }
</script>

<style scoped lang="scss">
.risk-config-panel {
  padding: 8px 0;
}
.preset-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  .preset-label {
    font-weight: 600;
    font-size: 13px;
    color: var(--el-text-color-primary);
    white-space: nowrap;
  }
}
.unit {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.save-bar {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 16px;
}
:deep(.el-divider__text) {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
</style>
