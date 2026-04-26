<script setup lang="ts">
/**
 * RiskControlView - 风控中心页面
 * 包含3个Tab：风控参数配置 / 实时风控状态 / 策略风控覆盖
 */
import { ref } from 'vue'
import {
  ElCard,
  ElTabs,
  ElTabPane,
} from 'element-plus'
import RiskConfigPanel from '@/components/risk/RiskConfigPanel.vue'
import RiskStatusPanel from '@/components/risk/RiskStatusPanel.vue'
import StrategyRiskConfigPanel from '@/components/risk/StrategyRiskConfigPanel.vue'

const activeTab = ref('config')
</script>

<template>
  <div class="risk-control-page">
    <div class="page-header">
      <h1 class="page-title">🛡️ 风控中心</h1>
      <p class="page-desc">多层级风险控制，保护交易安全</p>
    </div>

    <ElCard>
      <ElTabs v-model="activeTab" type="border-card">
        <ElTabPane label="⚙️ 风控参数配置" name="config">
          <RiskConfigPanel />
        </ElTabPane>
        <ElTabPane label="📡 实时风控状态" name="status">
          <RiskStatusPanel />
        </ElTabPane>
        <ElTabPane label="🎯 策略风控覆盖" name="strategy">
          <StrategyRiskConfigPanel />
        </ElTabPane>
      </ElTabs>
    </ElCard>
  </div>
</template>

<script lang="ts">
export default { name: 'RiskControlView' }
</script>

<style scoped lang="scss">
.risk-control-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}
.page-header {
  margin-bottom: 20px;
  .page-title {
    font-size: 24px;
    font-weight: 700;
    color: #303133;
    margin: 0 0 6px 0;
  }
  .page-desc {
    color: #909399;
    margin: 0;
    font-size: 14px;
  }
}
</style>
