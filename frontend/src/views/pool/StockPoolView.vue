<script setup lang="ts">
/**
 * StockPoolView - 今日预选池页面
 * 展示策略生成的选股列表，包含概览统计和可筛选的选股表格
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight, Download } from '@element-plus/icons-vue'
import { tradingApi, type TradingSignal } from '@/api'

// 拆分子组件
import PoolOverviewCards from '@/components/pool/PoolOverviewCards.vue'
import PoolStockTable from '@/components/pool/PoolStockTable.vue'

// 状态
const signals = ref<TradingSignal[]>([])
const loading = ref(false)
const tradeDate = ref('')

/** 获取今日日期字符串 */
function getTodayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 加载预选池数据 */
async function loadPool() {
  try {
    loading.value = true
    const res = await tradingApi.getTodayPool(200)
    signals.value = res.items || []
    // 从信号中提取交易日期
    if (signals.value.length > 0 && signals.value[0].generated_at) {
      const d = new Date(signals.value[0].generated_at)
      tradeDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    } else {
      tradeDate.value = getTodayStr()
    }
  } catch (e: any) {
    ElMessage.error(`加载预选池失败: ${e.message || '未知错误'}`)
    tradeDate.value = getTodayStr()
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

/** 导出CSV */
function handleExport() {
  if (!signals.value.length) {
    ElMessage.warning('暂无数据可导出')
    return
  }
  const headers = ['股票代码', '股票名称', '策略', '信号类型', '价格', '置信度', '建议数量', '状态', '推荐理由']
  const typeMap: Record<string, string> = { buy: '买入', sell: '卖出', hold: '持有' }
  const strategyNameMap: Record<string, string> = {
    halfway_chase: '半路追涨',
    first_limit_up: '首板打板',
    limit_up_open: '涨停开板',
    leader_buy_dip: '龙头低吸',
    limit_down_qiao: '跌停翘板',
  }
  const rows = signals.value.map((s: TradingSignal) => [
    s.ts_code,
    s.stock_name,
    strategyNameMap[s.strategy] || s.strategy,
    typeMap[s.signal_type] || s.signal_type,
    s.price?.toFixed(2) || '',
    (s.confidence * 100).toFixed(1) + '%',
    String(s.suggest_quantity),
    s.executed ? '已执行' : '待执行',
    `"${(s.reason || '').replace(/"/g, '""')}"`,
  ])
  const csvContent = [headers.join(','), ...rows.map((r: any) => r.join(','))].join('\n')
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `今日预选池_${tradeDate.value}.csv`
  link.click()
}

onMounted(() => {
  loadPool()
})
</script>

<template>
  <div class="stock-pool-view">
    <div class="page-header">
      <h2>🎯 今日预选池</h2>
      <div class="header-actions">
        <el-button size="small" @click="loadPool" :loading="loading" :icon="RefreshRight">
          刷新
        </el-button>
        <el-button size="small" type="primary" @click="handleGenerate" :loading="loading">
          生成今日信号
        </el-button>
        <el-button size="small" @click="handleExport" :disabled="!signals.length" :icon="Download">
          导出CSV
        </el-button>
      </div>
    </div>

    <!-- 概览统计卡片 -->
    <PoolOverviewCards :signals="signals" :trade-date="tradeDate" />

    <!-- 选股列表表格 -->
    <div style="margin-top: 16px">
      <PoolStockTable :signals="signals" />
    </div>

    <!-- 底部刷新时间 -->
    <div class="pool-footer">
      <span v-if="signals.length">最后更新: {{ new Date().toLocaleTimeString() }}</span>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'StockPoolView' }
</script>

<style scoped>
.stock-pool-view {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
  color: var(--el-text-color-primary);
}
.header-actions {
  display: flex;
  gap: 8px;
}
.pool-footer {
  text-align: center;
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
</style>
