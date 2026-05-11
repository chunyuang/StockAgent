<script setup lang="ts">
/**
 * LiveTradingView - 实盘交易页面
 * 合并: 交易信号 + 今日持仓 + 风控告警 + 绩效报告
 * 
 * 4个Tab:
 * 1. 📋 今日预选 - 信号生成 + 预选池 + 执行
 * 2. 📦 持仓监控 - 持仓明细 + 盈亏 + 止损止盈
 * 3. 📊 交易记录 - 操作时间线 + 历史报告
 * 4. 🎛️ 调度控制 - 启停DailyScheduler + 手动触发
 */
import { ref, onMounted, computed } from 'vue'
import {
  ElCard, ElTable, ElTableColumn, ElButton, ElMessage, ElTag, ElSpace,
  ElTabs, ElTabPane, ElStatistic, ElSwitch, ElDescriptions, ElDescriptionsItem,
  ElAlert, ElProgress, ElTooltip,
} from 'element-plus'
import {
  RefreshRight, Check, Download, VideoPlay, VideoPause,
  CaretRight, TrendCharts, Opportunity,
} from '@element-plus/icons-vue'
import { tradingApi, type TradingSignal, type SimAccount, type Position, type TradeRecord } from '@/api'
import { systemApi } from '@/api'

// ==================== 状态 ====================
const activeTab = ref('pool')
const loading = ref(false)
const schedulerLoading = ref(false)
const tradeDate = ref('')

// 信号
const signals = ref<TradingSignal[]>([])
const onlyUnexecuted = ref(true)

// 账户 & 持仓
const accounts = ref<SimAccount[]>([])
const selectedAccountId = ref('')
const positions = ref<Position[]>([])
const trades = ref<TradeRecord[]>([])

// 调度器
const schedulerRunning = ref(false)
const schedulerPhase = ref('idle')

// 策略名称映射
const strategyNameMap: Record<string, string> = {
  halfway_chase: '半路追涨', first_limit_up: '首板打板',
  limit_up_open: '涨停开板', leader_buy_dip: '龙头低吸', limit_down_qiao: '跌停翘板',
}
const typeMap: Record<string, string> = { buy: '买入', sell: '卖出', hold: '持有' }
const directionMap: Record<string, string> = { buy: '买入', sell: '卖出' }

// ==================== 计算属性 ====================
const selectedAccount = computed(() => accounts.value.find(a => a.account_id === selectedAccountId.value))

const poolStats = computed(() => {
  const s = signals.value
  return {
    total: s.length,
    buy: s.filter(x => x.signal_type === 'buy').length,
    executed: s.filter(x => x.executed).length,
    strategies: [...new Set(s.map(x => x.strategy))].length,
  }
})

const positionStats = computed(() => {
  const p = positions.value
  const profitable = p.filter(x => x.profit_pct > 0).length
  const losing = p.filter(x => x.profit_pct < 0).length
  return { total: p.length, profitable, losing }
})

// 风控: 接近止损的持仓(-2%以上)
const riskPositions = computed(() => {
  return positions.value
    .filter(p => p.profit_pct < -1)
    .sort((a, b) => a.profit_pct - b.profit_pct)
})

// ==================== 方法 ====================
function getTodayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadPool(), loadAccounts()])
  } finally {
    loading.value = false
  }
}

async function loadPool() {
  try {
    const res = await tradingApi.getTodayPool(200)
    signals.value = res.items || []
    if (signals.value.length > 0 && signals.value[0].generated_at) {
      const d = new Date(signals.value[0].generated_at)
      tradeDate.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    } else {
      tradeDate.value = getTodayStr()
    }
  } catch (e: any) {
    tradeDate.value = getTodayStr()
  }
}

async function loadAllSignals() {
  try {
    const res = await tradingApi.getTradingSignals(50, 0, onlyUnexecuted.value)
    signals.value = res.items || []
  } catch (e: any) {
    ElMessage.error(`加载信号失败`)
  }
}

async function loadAccounts() {
  try {
    accounts.value = await tradingApi.getSimAccounts()
    if (accounts.value.length > 0 && !selectedAccountId.value) {
      selectedAccountId.value = accounts.value[0].account_id
    }
    if (selectedAccountId.value) {
      await loadPositions()
    }
  } catch { /* ignore */ }
}

async function loadPositions() {
  if (!selectedAccountId.value) return
  try {
    positions.value = await tradingApi.getPositions(selectedAccountId.value)
  } catch { /* ignore */ }
}

async function loadTrades() {
  if (!selectedAccountId.value) return
  try {
    const res = await tradingApi.getTradeRecords(selectedAccountId.value, 50, 0)
    trades.value = res.items || []
  } catch { /* ignore */ }
}

async function handleGenerate() {
  try {
    const res = await tradingApi.triggerSignalGeneration()
    ElMessage.success(`信号生成完成，共 ${res.signal_count} 个信号`)
    await loadPool()
  } catch (e: any) {
    ElMessage.error(`信号生成失败`)
  }
}

async function handleExecute(signal: TradingSignal) {
  try {
    await tradingApi.executeSignal(signal.signal_id, 'default_account', signal.suggest_quantity)
    ElMessage.success(`${signal.stock_name} 信号已执行`)
    await loadPool()
    await loadPositions()
  } catch (e: any) {
    ElMessage.error(`执行失败`)
  }
}

function handleExport() {
  if (!signals.value.length) { ElMessage.warning('暂无数据'); return }
  const headers = ['股票代码', '股票名称', '策略', '信号类型', '价格', '置信度', '建议数量', '状态']
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

// 调度器控制
async function loadSchedulerStatus() {
  try {
    const res = await fetch('/api/v1/scheduler/status')
    const data = await res.json()
    if (data.success) {
      schedulerRunning.value = data.data?.is_running || false
      schedulerPhase.value = data.data?.current_phase || 'idle'
    }
  } catch { /* ignore */ }
}

async function toggleScheduler(start: boolean) {
  schedulerLoading.value = true
  try {
    const url = start ? '/api/v1/scheduler/start' : '/api/v1/scheduler/stop'
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    const data = await res.json()
    if (data.success !== false) {
      schedulerRunning.value = start
      ElMessage.success(start ? '调度器已启动' : '调度器已停止')
    } else {
      ElMessage.error(data.detail || '操作失败')
    }
  } catch (e: any) {
    ElMessage.error('调度器操作失败')
  } finally {
    schedulerLoading.value = false
    await loadSchedulerStatus()
  }
}

async function triggerPhase(phase: string) {
  schedulerLoading.value = true
  try {
    const res = await fetch(`/api/v1/scheduler/trigger/${phase}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    const data = await res.json()
    if (data.success) {
      ElMessage.success(`阶段 ${phase} 执行成功`)
      await loadAll()
    } else {
      ElMessage.warning(data.message || `阶段 ${phase} 未完全成功`)
    }
  } catch (e: any) {
    ElMessage.error('触发失败')
  } finally {
    schedulerLoading.value = false
  }
}

function profitTagType(pct: number): 'success' | 'danger' | 'warning' | 'info' {
  if (pct > 0) return 'success'
  if (pct < -3) return 'danger'
  if (pct < 0) return 'warning'
  return 'info'
}

onMounted(() => {
  loadAll()
  loadSchedulerStatus()
})
</script>

<template>
  <div class="live-trading-page">
    <!-- 顶部概览栏 -->
    <div class="overview-bar">
      <div class="overview-left">
        <h2>📊 实盘交易</h2>
        <span class="trade-date">{{ tradeDate }}</span>
      </div>
      <ElSpace>
        <ElButton size="small" @click="loadAll" :loading="loading" :icon="RefreshRight">刷新</ElButton>
        <ElButton size="small" type="primary" @click="handleGenerate" :loading="loading">生成今日信号</ElButton>
        <ElButton size="small" @click="handleExport" :disabled="!signals.length" :icon="Download">导出</ElButton>
      </ElSpace>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row">
      <ElCard shadow="never" class="stat-card">
        <ElStatistic title="预选信号" :value="poolStats.total" />
      </ElCard>
      <ElCard shadow="never" class="stat-card">
        <ElStatistic title="买入信号" :value="poolStats.buy" />
      </ElCard>
      <ElCard shadow="never" class="stat-card" v-if="selectedAccount">
        <ElStatistic title="持仓数" :value="positionStats.total" />
      </ElCard>
      <ElCard shadow="never" class="stat-card" v-if="selectedAccount">
        <ElStatistic :title="`总资产`" :value="selectedAccount.total_assets || 0" :precision="0" prefix="¥" />
      </ElCard>
      <ElCard shadow="never" class="stat-card" v-if="selectedAccount">
        <ElStatistic title="今日收益" :value="selectedAccount.total_profit_pct || 0" :precision="2" suffix="%" />
      </ElCard>
      <!-- 风控告警 -->
      <ElCard shadow="never" class="stat-card risk-card" v-if="riskPositions.length > 0">
        <ElStatistic title="⚠️ 风控告警" :value="riskPositions.length" />
      </ElCard>
    </div>

    <!-- 主内容Tab -->
    <ElTabs v-model="activeTab" type="border-card" class="main-tabs">
      <!-- Tab1: 今日预选 -->
      <ElTabPane name="pool">
        <template #label>📋 今日预选 <ElTag size="small" type="primary" style="margin-left:4px">{{ poolStats.total }}</ElTag></template>
        <div class="pool-stats" v-if="signals.length">
          <ElTag type="success">买入 {{ poolStats.buy }}</ElTag>
          <ElTag type="info">已执行 {{ poolStats.executed }}</ElTag>
          <ElTag>覆盖 {{ poolStats.strategies }} 个策略</ElTag>
        </div>
        <ElTable :data="signals" size="small" border stripe v-loading="loading" empty-text="暂无信号，点击「生成今日信号」">
          <ElTableColumn prop="stock_name" label="股票" width="100" />
          <ElTableColumn prop="ts_code" label="代码" width="110" />
          <ElTableColumn label="策略" width="90">
            <template #default="{ row }">{{ strategyNameMap[row.strategy] || row.strategy }}</template>
          </ElTableColumn>
          <ElTableColumn label="类型" width="70">
            <template #default="{ row }"><ElTag :type="row.signal_type === 'buy' ? 'danger' : 'success'" size="small">{{ typeMap[row.signal_type] || row.signal_type }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="price" label="价格" width="80" />
          <ElTableColumn label="置信度" width="70">
            <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
          </ElTableColumn>
          <ElTableColumn prop="suggest_quantity" label="建议量" width="70" />
          <ElTableColumn label="状态" width="70">
            <template #default="{ row }"><ElTag :type="row.executed ? 'success' : 'info'" size="small">{{ row.executed ? '已执行' : '待执行' }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="reason" label="推荐理由" min-width="120" show-overflow-tooltip />
          <ElTableColumn label="操作" width="70" fixed="right">
            <template #default="{ row }">
              <ElButton v-if="!row.executed" type="primary" size="small" :icon="Check" @click="handleExecute(row)">执行</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElTabPane>

      <!-- Tab2: 持仓监控 -->
      <ElTabPane name="position">
        <template #label>📦 持仓监控 <ElTag size="small" :type="positionStats.total ? 'primary' : 'info'" style="margin-left:4px">{{ positionStats.total }}</ElTag></template>
        
        <!-- 风控告警区 -->
        <div v-if="riskPositions.length > 0" class="risk-alert-area">
          <ElAlert type="warning" :closable="false" show-icon>
            <template #title>⚠️ 风控告警: {{ riskPositions.length }} 只持仓接近止损线</template>
          </ElAlert>
          <div class="risk-cards">
            <ElCard v-for="p in riskPositions" :key="p.position_id" shadow="hover" class="risk-item" :class="{ 'danger': p.profit_pct < -3 }">
              <span class="risk-code">{{ p.ts_code }}</span>
              <span class="risk-name">{{ p.stock_name }}</span>
              <ElTag :type="profitTagType(p.profit_pct)" size="small">{{ p.profit_pct.toFixed(1) }}%</ElTag>
            </ElCard>
          </div>
        </div>

        <!-- 账户切换 -->
        <div class="account-bar" v-if="accounts.length > 1">
          <div v-for="acc in accounts" :key="acc.account_id"
            class="account-chip" :class="{ active: acc.account_id === selectedAccountId }"
            @click="selectedAccountId = acc.account_id; loadPositions()">
            <span class="chip-name">{{ acc.name }}</span>
            <span class="chip-assets">¥{{ (acc.total_assets || 0).toLocaleString() }}</span>
          </div>
        </div>

        <!-- 持仓表格 -->
        <ElTable :data="positions" size="small" border stripe v-loading="loading" empty-text="暂无持仓">
          <ElTableColumn prop="stock_name" label="股票" width="100" />
          <ElTableColumn prop="ts_code" label="代码" width="110" />
          <ElTableColumn label="策略" width="90">
            <template #default="{ row }">{{ strategyNameMap[row.strategy] || row.strategy }}</template>
          </ElTableColumn>
          <ElTableColumn prop="quantity" label="持仓" width="80" />
          <ElTableColumn prop="avg_cost" label="成本" width="80" />
          <ElTableColumn prop="current_price" label="现价" width="80" />
          <ElTableColumn label="盈亏%" width="80">
            <template #default="{ row }">
              <ElTag :type="profitTagType(row.profit_pct)" size="small">{{ row.profit_pct?.toFixed(1) }}%</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="hold_days" label="持有天数" width="80" />
        </ElTable>
      </ElTabPane>

      <!-- Tab3: 交易记录 -->
      <ElTabPane name="trades">
        <template #label>📝 交易记录</template>
        <ElButton size="small" @click="loadTrades" :loading="loading" style="margin-bottom:12px">加载交易记录</ElButton>
        <ElTable :data="trades" size="small" border stripe empty-text="暂无交易记录">
          <ElTableColumn prop="trade_time" label="时间" width="160" />
          <ElTableColumn prop="ts_code" label="代码" width="110" />
          <ElTableColumn prop="stock_name" label="股票" width="100" />
          <ElTableColumn label="方向" width="70">
            <template #default="{ row }"><ElTag :type="row.direction === 'buy' ? 'danger' : 'success'" size="small">{{ directionMap[row.direction] || row.direction }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn prop="quantity" label="数量" width="80" />
          <ElTableColumn prop="price" label="价格" width="80" />
          <ElTableColumn prop="amount" label="金额" width="100" />
          <ElTableColumn label="策略" width="90">
            <template #default="{ row }">{{ strategyNameMap[row.strategy] || row.strategy }}</template>
          </ElTableColumn>
          <ElTableColumn prop="reason" label="原因" min-width="120" show-overflow-tooltip />
        </ElTable>
      </ElTabPane>

      <!-- Tab4: 调度控制 -->
      <ElTabPane name="scheduler">
        <template #label>🎛️ 调度控制</template>
        
        <div class="scheduler-panel">
          <!-- 状态指示 -->
          <ElCard shadow="never" class="scheduler-status-card">
            <div class="scheduler-status">
              <span class="status-dot" :class="{ running: schedulerRunning }"></span>
              <span class="status-text">{{ schedulerRunning ? '运行中' : '已停止' }}</span>
              <ElTag v-if="schedulerPhase !== 'idle'" size="small" type="warning">当前阶段: {{ schedulerPhase }}</ElTag>
            </div>
            <div class="scheduler-actions">
              <ElButton v-if="!schedulerRunning" type="success" :icon="VideoPlay" @click="toggleScheduler(true)" :loading="schedulerLoading">
                启动调度器
              </ElButton>
              <ElButton v-else type="danger" :icon="VideoPause" @click="toggleScheduler(false)" :loading="schedulerLoading">
                停止调度器
              </ElButton>
            </div>
          </ElCard>

          <!-- 手动触发 -->
          <ElCard shadow="never" class="trigger-card">
            <template #header><span>手动触发阶段</span></template>
            <div class="trigger-buttons">
              <ElTooltip content="数据更新 + 信号生成 + 执行买入" placement="top">
                <ElButton :icon="CaretRight" @click="triggerPhase('premarket')" :loading="schedulerLoading">🌅 盘前准备</ElButton>
              </ElTooltip>
              <ElTooltip content="实时行情 + 止损止盈检查" placement="top">
                <ElButton :icon="TrendCharts" @click="triggerPhase('intraday')" :loading="schedulerLoading">📈 盘中监控</ElButton>
              </ElTooltip>
              <ElTooltip content="数据补全 + 绩效统计 + 日报" placement="top">
                <ElButton :icon="Opportunity" @click="triggerPhase('postmarket')" :loading="schedulerLoading">📉 盘后处理</ElButton>
              </ElTooltip>
            </div>
          </ElCard>

          <!-- 3阶段说明 -->
          <ElCard shadow="never">
            <template #header><span>每日调度流程</span></template>
            <ElDescriptions :column="1" border size="small">
              <ElDescriptionsItem label="09:15 盘前">数据更新(东方财富) → 因子计算 → 策略筛选 → 信号生成 → 模拟买入 → 飞书推送</ElDescriptionsItem>
              <ElDescriptionsItem label="09:30-15:00 盘中">每5分钟: 量脉实时行情 → 持仓盈亏更新 → 止损止盈检查 → 风控告警</ElDescriptionsItem>
              <ElDescriptionsItem label="15:30 盘后">当日数据补全 → 绩效统计(收益/回撤/胜率) → 日报推送</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
        </div>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<script lang="ts">
export default { name: 'LiveTradingView' }
</script>

<style scoped>
.live-trading-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.overview-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.overview-bar h2 { font-size: 20px; font-weight: 600; margin: 0; }
.overview-left { display: flex; align-items: center; gap: 12px; }
.trade-date { color: #909399; font-size: 14px; }
.stats-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.stat-card { flex: 1; min-width: 120px; }
.stat-card :deep(.el-statistic__number) { font-size: 20px; font-weight: 600; }
.risk-card { border-color: #e6a23c; background: #fdf6ec; }
.pool-stats { display: flex; gap: 12px; margin-bottom: 12px; }
.main-tabs { margin-top: 0; }
.risk-alert-area { margin-bottom: 16px; }
.risk-cards { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.risk-item { padding: 8px 12px; font-size: 13px; display: inline-flex; align-items: center; gap: 8px; }
.risk-item.danger { border-color: #f56c6c; }
.risk-code { font-family: monospace; }
.risk-name { color: #606266; }
.account-bar { display: flex; gap: 10px; margin-bottom: 12px; }
.account-chip { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 6px; border: 1px solid #dcdfe6; cursor: pointer; font-size: 13px; transition: all 0.2s; }
.account-chip:hover { border-color: #409eff; }
.account-chip.active { border-color: #409eff; background: #ecf5ff; }
.chip-name { font-weight: 600; }
.chip-assets { color: #909399; font-size: 12px; }
.scheduler-panel { display: flex; flex-direction: column; gap: 16px; }
.scheduler-status-card { display: flex; justify-content: space-between; align-items: center; }
.scheduler-status { display: flex; align-items: center; gap: 12px; }
.status-dot { width: 12px; height: 12px; border-radius: 50%; background: #909399; }
.status-dot.running { background: #67c23a; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.status-text { font-size: 16px; font-weight: 600; }
.trigger-card .trigger-buttons { display: flex; gap: 12px; flex-wrap: wrap; }
</style>
