<script setup lang="ts">
/**
 * DataGuardBanner - 前端数据运行时告警组件
 * 
 * 【2026-07-16新增】审查盲区: 前端没有运行时数据异常告警
 * 近期bug: 持仓13只>上限10但前端无告警; 账户数据全0但前端正常显示
 * 
 * 检查项:
 * 1. 持仓数超限 (> MAX_POSITIONS)
 * 2. 总资产异常 (为负数或为0)
 * 3. 盈亏异常 (单日亏损>5%)
 * 4. 持仓mv为0 (有持仓但市值为0)
 * 5. available_cash为负
 * 6. 持仓数与风控矩阵不一致
 */
import { computed } from 'vue'
import { ElAlert } from 'element-plus'
import { useScannerMonitorInject } from './scannerMonitorInject'

const m = useScannerMonitorInject()

const MAX_POSITIONS = 10

interface AlertItem {
  type: 'error' | 'warning' | 'info'
  title: string
  message: string
}

const alerts = computed<AlertItem[]>(() => {
  const items: AlertItem[] = []
  
  // 1. 持仓数超限
  const positions = m.positions.value
  if (positions && positions.length > MAX_POSITIONS) {
    items.push({
      type: 'error',
      title: '持仓数超限',
      message: `当前持仓 ${positions.length} 只，超过上限 ${MAX_POSITIONS} 只`,
    })
  }
  
  // 2. 总资产异常
  const account = m.account.value
  if (account) {
    const total = account.total_assets ?? 0
    const cash = account.available_cash ?? 0
    const mv = account.market_value ?? 0
    
    if (total <= 0) {
      items.push({
        type: 'error',
        title: '总资产异常',
        message: `总资产为 ${total}，可能数据错误`,
      })
    }
    
    // 3. available_cash为负
    if (cash < 0) {
      items.push({
        type: 'error',
        title: '可用资金为负',
        message: `available_cash = ${cash.toFixed(2)}，资金可能虚增`,
      })
    }
    
    // 4. 有持仓但mv为0
    if (positions && positions.length > 0 && mv <= 0) {
      items.push({
        type: 'warning',
        title: '持仓市值为0',
        message: `有 ${positions.length} 只持仓但 market_value = 0，可能未更新价格`,
      })
    }
    
    // 5. 单日亏损>5%
    const todayProfit = account.today_profit ?? 0
    const initialCash = 1_000_000
    if (todayProfit < -initialCash * 0.05) {
      items.push({
        type: 'error',
        title: '单日亏损超5%',
        message: `今日亏损 ${todayProfit.toFixed(0)} 元 (${(todayProfit / initialCash * 100).toFixed(1)}%)`,
      })
    }
    
    // 6. 账户等式不平衡
    if (total > 0 && Math.abs(total - cash - mv) > 1) {
      items.push({
        type: 'error',
        title: '账户等式不平衡',
        message: `total(${total.toFixed(0)}) ≠ cash(${cash.toFixed(0)}) + mv(${mv.toFixed(0)})，漂移 ${(total - cash - mv).toFixed(2)}`,
      })
    }
  }
  
  // 7. scanner假运行
  const status = m.scannerStatus.value
  if (status?.is_running && (status.scan_count ?? 0) === 0) {
    items.push({
      type: 'error',
      title: 'Scanner假运行',
      message: 'is_running=true 但 scan_count=0，可能需要 stop/start',
    })
  }
  
  return items
})
</script>

<template>
  <div v-if="alerts.length > 0" class="data-guard-banner">
    <ElAlert
      v-for="(alert, i) in alerts"
      :key="i"
      :type="alert.type"
      :title="alert.title"
      :description="alert.message"
      show-icon
      :closable="false"
      style="margin-bottom: 4px;"
    />
  </div>
</template>

<style scoped>
.data-guard-banner {
  margin-bottom: 8px;
}
</style>
