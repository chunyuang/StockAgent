<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElCard, ElTable, ElTableColumn, ElButton, ElMessage, ElTag, ElSpace, ElSwitch, ElMessageBox } from 'element-plus'
import { Bell, RefreshRight, Check } from '@element-plus/icons-vue'
import { tradingApi, type TradingSignal } from '@/api'

// 状态
const signals = ref<TradingSignal[]>([])
const loading = ref(false)
const onlyUnexecuted = ref(false)

// 加载信号列表
async function loadSignals() {
  try {
    loading.value = true
    const res = await tradingApi.getTradingSignals(50, 0, onlyUnexecuted.value)
    signals.value = res.items
  } catch (e: any) {
    ElMessage.error(`加载信号失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// 执行信号
async function executeSignal(signal: TradingSignal) {
  try {
    await ElMessageBox.confirm(
      `确认执行信号：${signal.stock_name}(${signal.ts_code}) ${signal.signal_type === 'buy' ? '买入' : '卖出'} ${signal.suggest_quantity}股，价格 ${signal.price.toFixed(2)}元？`,
      '执行交易信号',
      { confirmButtonText: '确认执行', cancelButtonText: '取消', type: 'warning' }
    )
    
    // 这里应该让用户选择账户，暂时用默认账户
    await tradingApi.executeSignal(signal.signal_id, 'default_account', signal.suggest_quantity)
    ElMessage.success('信号执行成功')
    loadSignals()
  } catch {
    // 取消不提示
  }
}

// 手动触发信号生成
async function triggerGenerate() {
  try {
    await ElMessageBox.confirm(
      '确认手动触发今日交易信号生成？会覆盖今日已生成的信号。',
      '生成交易信号',
      { confirmButtonText: '确认生成', cancelButtonText: '取消', type: 'warning' }
    )
    
    const res = await tradingApi.triggerSignalGeneration()
    ElMessage.success(`信号生成完成，共生成 ${res.signal_count} 个信号`)
    loadSignals()
  } catch {
    // 取消不提示
  }
}

// 信号类型颜色
function getSignalTypeColor(type: string): 'success' | 'danger' | 'info' {
  switch (type) {
    case 'buy': return 'success'
    case 'sell': return 'danger'
    default: return 'info'
  }
}

// 信号类型文本
function getSignalTypeText(type: string): string {
  switch (type) {
    case 'buy': return '买入'
    case 'sell': return '卖出'
    default: return '持有'
  }
}

// 置信度颜色
function getConfidenceColor(confidence: number): 'success' | 'warning' | 'info' {
  if (confidence >= 0.8) return 'success'
  if (confidence >= 0.6) return 'warning'
  return 'info'
}

onMounted(() => {
  loadSignals()
})
</script>

<template>
  <div class="trading-signals-page p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold">交易信号</h1>
      <ElSpace>
        <ElSwitch
          v-model="onlyUnexecuted"
          @change="loadSignals"
          active-text="仅看未执行"
          inactive-text="全部信号"
        />
        <ElButton :icon="RefreshRight" @click="loadSignals">刷新</ElButton>
        <ElButton type="primary" :icon="Bell" @click="triggerGenerate">生成今日信号</ElButton>
      </ElSpace>
    </div>

    <!-- 信号列表 -->
    <ElCard v-loading="loading">
      <ElTable :data="signals" border stripe>
        <ElTableColumn prop="generated_at" label="生成时间" width="160" />
        <ElTableColumn prop="stock_name" label="股票名称" width="120" />
        <ElTableColumn prop="ts_code" label="股票代码" width="120" />
        <ElTableColumn prop="strategy" label="策略来源" width="120" />
        <ElTableColumn label="信号类型" width="100">
          <template #default="{ row }">
            <ElTag :type="getSignalTypeColor(row.signal_type)">
              {{ getSignalTypeText(row.signal_type) }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="price" label="信号价格" width="100" />
        <ElTableColumn prop="suggest_quantity" label="建议数量" width="100" />
        <ElTableColumn label="置信度" width="100">
          <template #default="{ row }">
            <ElTag :type="getConfidenceColor(row.confidence)">
              {{ (row.confidence * 100).toFixed(0) }}%
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="row.executed ? 'info' : 'warning'">
              {{ row.executed ? '已执行' : '待执行' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="expired_at" label="过期时间" width="160" />
        <ElTableColumn prop="reason" label="信号原因" min-width="250" />
        <ElTableColumn label="操作" width="120" fixed="right" v-if="!onlyUnexecuted">
          <template #default="{ row }">
            <ElButton
              v-if="!row.executed && row.signal_type !== 'hold'"
              type="primary"
              size="small"
              :icon="Check"
              @click="executeSignal(row)"
            >
              执行
            </ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
</style>
