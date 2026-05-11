<script setup lang="ts">
/**
 * TradingSignalsView - 交易信号页面
 * 合并: 交易信号 + 今日预选池
 * Tab1: 全部信号(含执行操作)
 * Tab2: 今日预选(信号生成+导出)
 */
import { ref, onMounted, computed } from 'vue'
import { ElCard, ElTable, ElTableColumn, ElButton, ElMessage, ElTag, ElSpace, ElSwitch, ElMessageBox, ElTabs, ElTabPane, ElStatistic } from 'element-plus'
import { Bell, RefreshRight, Check, Download, Opportunity } from '@element-plus/icons-vue'
import { tradingApi, type TradingSignal } from '@/api'

const activeTab = ref('pool')
const signals = ref<TradingSignal[]>([])
const loading = ref(false)
const onlyUnexecuted = ref(true)
const tradeDate = ref('')

const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨', first_limit_up: '首板打板',
  limit_up_open: '涨停开板', leader_buy_dip: '龙头低吸', limit_down_qiao: '跌停翘板',
}

// 今日预选统计
const poolStats = computed(() => {
  const today = signals.value
  return {
    total: today.length,
    buy: today.filter(s => s.signal_type === 'buy').length,
    strategies: [...new Set(today.map(s => s.strategy))].length,
    avgConfidence: today.length ? (today.reduce((a, s) => a + s.confidence, 0) / today.length * 100).toFixed(1) + '%' : '-',
  }
})

/** 获取今日日期字符串 */
function getTodayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 加载预选池数据 */
async function loadPool() {
  try {
    loading.value = true
    const res = await tradingApi.getTodayPool(200)
    signals.value = res.items || []
    if (signals.value.length > 0 && signals.value[0].generated_at) {
      const d = new Date(signals.value[0].generated_at)
      tradeDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    } else {
      tradeDate.value = getTodayStr()
    }
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e.message || '未知错误'}`)
    tradeDate.value = getTodayStr()
  } finally {
    loading.value = false
  }
}

/** 加载全部信号 */
async function loadAllSignals() {
  try {
    loading.value = true
    const res = await tradingApi.getTradingSignals(50, 0, onlyUnexecuted.value)
    signals.value = res.items || res || []
  } catch (e: any) {
    ElMessage.error(`加载信号失败: ${e.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

/** 手动触发信号生成 */
async function handleGenerate() {
  try {
    const res = await tradingApi.triggerSignalGeneration()
    ElMessage.success(`信号生成完成，共 ${res.signal_count} 个信号`)
    await loadPool()
  } catch (e: any) {
    ElMessage.error(`信号生成失败: ${e.message || '未知错误'}`)
  }
}

/** 执行信号 */
async function handleExecute(signal: TradingSignal) {
  try {
    await tradingApi.executeSignal(signal.signal_id, 'default_account', signal.suggest_quantity)
    ElMessage.success(`${signal.stock_name} 信号已执行`)
    loadAllSignals()
  } catch (e: any) {
    ElMessage.error(`执行失败: ${e.message || '未知错误'}`)
  }
}

/** 导出CSV */
function handleExport() {
  if (!signals.value.length) { ElMessage.warning('暂无数据'); return }
  const headers = ['股票代码', '股票名称', '策略', '信号类型', '价格', '置信度', '建议数量', '状态']
  const typeMap: Record<string, string> = { buy: '买入', sell: '卖出', hold: '持有' }
  const rows = signals.value.map(s => [
    s.ts_code, s.stock_name, strategyNameMap[s.strategy] || s.strategy,
    typeMap[s.signal_type] || s.signal_type, s.price?.toFixed(2) || '',
    (s.confidence * 100).toFixed(1) + '%', String(s.suggest_quantity),
    s.executed ? '已执行' : '待执行',
  ])
  const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `预选池_${tradeDate.value}.csv`
  link.click()
}

onMounted(() => { loadPool() })
</script>

<template>
  <div class="trading-signals-page">
    <div class="page-header">
      <h2>🎯 交易信号</h2>
      <ElSpace>
        <ElButton size="small" @click="activeTab === 'pool' ? loadPool() : loadAllSignals()" :loading="loading" :icon="RefreshRight">刷新</ElButton>
        <ElButton size="small" type="primary" @click="handleGenerate" :loading="loading">生成今日信号</ElButton>
        <ElButton size="small" @click="handleExport" :disabled="!signals.length" :icon="Download">导出</ElButton>
      </ElSpace>
    </div>

    <ElTabs v-model="activeTab" type="border-card" @tab-change="(t: string) => t === 'pool' ? loadPool() : loadAllSignals()">
      <!-- Tab1: 今日预选池 -->
      <ElTabPane name="pool">
        <template #label><span>📋 今日预选 <ElTag size="small" type="primary" style="margin-left:4px">{{ poolStats.total }}</ElTag></span></template>
        <!-- 概览 -->
        <div class="pool-stats" v-if="signals.length">
          <ElStatistic title="买入信号" :value="poolStats.buy" />
          <ElStatistic title="覆盖策略" :value="poolStats.strategies" />
          <ElStatistic title="平均置信度" :value="poolStats.avgConfidence" />
        </div>
        <ElTable :data="signals" size="small" border stripe v-loading="loading" style="margin-top:12px" empty-text="暂无信号，点击「生成今日信号」">
          <ElTableColumn prop="stock_name" label="股票" width="120" />
          <ElTableColumn prop="ts_code" label="代码" width="110" />
          <ElTableColumn label="策略" width="100">
            <template #default="{ row }">{{ strategyNameMap[row.strategy] || row.strategy }}</template>
          </ElTableColumn>
          <ElTableColumn label="类型" width="80">
            <template #default="{ row }"><ElTag :type="row.signal_type === 'buy' ? 'danger' : 'success'" size="small">{{ row.signal_type === 'buy' ? '买入' : '卖出' }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="price" label="价格" width="90" />
          <ElTableColumn label="置信度" width="90">
            <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
          </ElTableColumn>
          <ElTableColumn prop="suggest_quantity" label="建议量" width="80" />
          <ElTableColumn label="状态" width="80">
            <template #default="{ row }"><ElTag :type="row.executed ? 'success' : 'info'" size="small">{{ row.executed ? '已执行' : '待执行' }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="reason" label="推荐理由" min-width="150" show-overflow-tooltip />
        </ElTable>
      </ElTabPane>

      <!-- Tab2: 全部信号 -->
      <ElTabPane name="all">
        <template #label><span>🔔 全部信号</span></template>
        <div style="margin-bottom:12px">
          <ElSwitch v-model="onlyUnexecuted" active-text="仅未执行" @change="loadAllSignals" />
        </div>
        <ElTable :data="signals" size="small" border stripe v-loading="loading" empty-text="暂无信号">
          <ElTableColumn prop="generated_at" label="时间" width="160" />
          <ElTableColumn prop="stock_name" label="股票" width="120" />
          <ElTableColumn prop="ts_code" label="代码" width="110" />
          <ElTableColumn label="策略" width="100">
            <template #default="{ row }">{{ strategyNameMap[row.strategy] || row.strategy }}</template>
          </ElTableColumn>
          <ElTableColumn label="类型" width="80">
            <template #default="{ row }"><ElTag :type="row.signal_type === 'buy' ? 'danger' : 'success'" size="small">{{ row.signal_type === 'buy' ? '买入' : '卖出' }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="price" label="价格" width="90" />
          <ElTableColumn prop="suggest_quantity" label="建议量" width="80" />
          <ElTableColumn label="置信度" width="80">
            <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <ElButton v-if="!row.executed" type="primary" size="small" :icon="Check" @click="handleExecute(row)">执行</ElButton>
              <ElTag v-else type="success" size="small">已执行</ElTag>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<script lang="ts">
export default { name: 'TradingSignalsView' }
</script>

<style scoped>
.trading-signals-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { font-size: 20px; font-weight: 600; margin: 0; }
.pool-stats { display: flex; gap: 32px; padding: 12px 0; }
</style>
