<script setup lang="ts">
/**
 * 交易归档页面 — 参考掘金量化交易归档
 * 按日期+账户查看: 摘要/资金/持仓/成交/委托/日志/异常
 */
import { ref, onMounted, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import {
  ElCard,
  ElSelect,
  ElOption,
  ElButton,
  ElIcon,
  ElTabs,
  ElTabPane,
  ElDescriptions,
  ElDescriptionsItem,
  ElTable,
  ElTableColumn,
  ElTag,
  ElEmpty,
  ElTooltip,
} from 'element-plus'
import { api } from '@/api'

// ==================== 状态 ====================

const dates = ref<number[]>([])
const selectedDate = ref<number>(0)
const accountData = ref<any>(null)
const loading = ref(false)
const activeTab = ref('summary')

// ==================== 方法 ====================

async function fetchDates() {
  try {
    const res = await api.get('/trading-archive/dates')
    dates.value = res.data?.dates || []
    if (dates.value.length > 0 && !selectedDate.value) {
      selectedDate.value = dates.value[0]
      fetchDay(selectedDate.value)
    }
  } catch (e) {
    console.warn('加载归档日期失败', e)
  }
}

async function fetchDay(date: number) {
  if (!date) return
  loading.value = true
  accountData.value = null
  try {
    const res = await api.get(`/trading-archive/day/${date}`)
    accountData.value = res.data
  } catch (e) {
    console.warn('加载归档数据失败', e)
  } finally {
    loading.value = false
  }
}

function onDateChange(date: number) {
  selectedDate.value = date
  fetchDay(date)
}

function fmtMoney(val: number | undefined, unit: '万' | '亿' = '万', digits = 1): string {
  if (val == null) return '-'
  const v = unit === '亿' ? val / 100000000 : val / 10000
  return v.toFixed(digits) + unit
}

function fmtPct(val: number | undefined): string {
  if (val == null) return '-'
  return val.toFixed(2) + '%'
}

function fmtPrice(val: number | undefined): string {
  if (val == null) return '-'
  return val.toFixed(2)
}

// ==================== 生命周期 ====================

onMounted(() => {
  fetchDates()
})
</script>

<template>
  <div class="archive-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-left">
        <h2>交易归档</h2>
        <p class="subtitle">每日交易数据归档与复盘分析</p>
      </div>
      <div class="header-right">
        <span class="date-label">交易日:</span>
        <ElSelect v-model="selectedDate" placeholder="选择交易日" size="default" style="width:160px" @change="onDateChange">
          <ElOption v-for="d in dates" :key="d" :label="String(d)" :value="d" />
        </ElSelect>
        <ElButton type="primary" :loading="loading" @click="fetchDay(selectedDate)" :disabled="!selectedDate">
          刷新
        </ElButton>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="center-hint">
      <ElIcon class="is-loading" :size="24"><Loading /></ElIcon>
      <span>加载中...</span>
    </div>

    <!-- 无数据 -->
    <div v-else-if="!accountData && !loading" class="center-hint">
      <ElEmpty description="请选择交易日查看归档数据" />
    </div>

    <!-- 归档内容 -->
    <div v-else-if="accountData" class="archive-body">
      <ElTabs v-model="activeTab" type="border-card" class="archive-tabs">

        <!-- ========== 摘要 ========== -->
        <ElTabPane label="📋 摘要" name="summary">
          <div class="summary-grid">
            <!-- 委托统计 -->
            <div class="summary-card">
              <div class="sc-title">委托统计</div>
              <div class="sc-row"><span>总委托</span><b>{{ accountData.summary.total_orders }}</b></div>
              <div class="sc-row"><span>买入</span><b>{{ accountData.summary.buy_orders }}</b></div>
              <div class="sc-row"><span>卖出</span><b>{{ accountData.summary.sell_orders }}</b></div>
              <div class="sc-row"><span>已成交</span><b class="ok">{{ accountData.summary.filled_orders }}</b></div>
              <div class="sc-row"><span>已取消</span><b class="muted">{{ accountData.summary.cancelled_orders }}</b></div>
              <div class="sc-row"><span>成交率</span><b>{{ accountData.summary.total_orders ? ((accountData.summary.filled_orders / accountData.summary.total_orders) * 100).toFixed(0) + '%' : '-' }}</b></div>
            </div>
            <!-- 成交统计 -->
            <div class="summary-card">
              <div class="sc-title">成交统计</div>
              <div class="sc-row"><span>成交笔数</span><b>{{ accountData.summary.total_trades }}</b></div>
              <div class="sc-row"><span>买入金额</span><b>{{ fmtMoney(accountData.summary.total_buy_amount) }}</b></div>
              <div class="sc-row"><span>卖出金额</span><b>{{ fmtMoney(accountData.summary.total_sell_amount) }}</b></div>
              <div class="sc-row">
                <span>已实现盈亏</span>
                <b :class="accountData.summary.realized_pnl >= 0 ? 'ok' : 'err'">
                  {{ fmtMoney(accountData.summary.realized_pnl, '万', 2) }}
                </b>
              </div>
            </div>
            <!-- 资金概况 -->
            <div class="summary-card">
              <div class="sc-title">资金概况</div>
              <div class="sc-row"><span>总资产</span><b>{{ fmtMoney(accountData.summary.total_assets) }}</b></div>
              <div class="sc-row"><span>可用资金</span><b>{{ fmtMoney(accountData.summary.available_cash) }}</b></div>
              <div class="sc-row"><span>持仓市值</span><b>{{ fmtMoney(accountData.summary.position_value) }}</b></div>
              <div class="sc-row"><span>持仓数</span><b>{{ accountData.summary.position_count }}只</b></div>
              <div class="sc-row">
                <span>仓位比例</span>
                <b>{{ accountData.summary.total_assets ? ((accountData.summary.position_value / accountData.summary.total_assets) * 100).toFixed(1) + '%' : '-' }}</b>
              </div>
            </div>
          </div>

          <!-- 异常提示 -->
          <div v-if="accountData.summary.anomaly_count > 0" class="anomaly-alert">
            <ElTag type="warning">⚠️ 检测到 {{ accountData.summary.anomaly_count }} 个异常合约（持仓差异 ≠ 0）</ElTag>
          </div>
        </ElTabPane>

        <!-- ========== 资金 ========== -->
        <ElTabPane label="💰 资金" name="capital">
          <ElDescriptions :column="2" border size="default" v-if="accountData.capital">
            <ElDescriptionsItem label="可用资金">{{ fmtMoney(accountData.capital.available_cash) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="总资产">{{ fmtMoney(accountData.capital.total_assets) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="持仓市值">{{ fmtMoney(accountData.capital.market_value) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="总盈亏">
              <span :class="accountData.capital.total_profit >= 0 ? 'ok' : 'err'">{{ fmtMoney(accountData.capital.total_profit, '万', 2) }}</span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="已实现盈亏">{{ fmtMoney(accountData.capital.realized_pnl, '万', 2) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="盈亏比例">
              <span :class="accountData.capital.total_profit >= 0 ? 'ok' : 'err'">
                {{ accountData.capital.total_assets ? ((accountData.capital.total_profit / 1000000) * 100).toFixed(2) + '%' : '-' }}
              </span>
            </ElDescriptionsItem>
          </ElDescriptions>
          <div v-else class="center-hint">暂无资金数据</div>
        </ElTabPane>

        <!-- ========== 持仓 ========== -->
        <ElTabPane label="📊 持仓" name="positions">
          <ElTable :data="accountData.positions" size="small" stripe>
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn prop="quantity" label="数量" width="80" align="right" />
            <ElTableColumn label="成本" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.avg_cost) }}</template>
            </ElTableColumn>
            <ElTableColumn label="现价" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.current_price) }}</template>
            </ElTableColumn>
            <ElTableColumn label="市值" width="100" align="right">
              <template #default="{ row }">{{ fmtMoney(row.market_value) }}</template>
            </ElTableColumn>
            <ElTableColumn label="盈亏%" width="80" align="right">
              <template #default="{ row }">
                <span :class="row.profit_pct >= 0 ? 'ok' : 'err'">{{ fmtPct(row.profit_pct) }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.positions.length === 0" class="center-hint">该日无持仓</div>
        </ElTabPane>

        <!-- ========== 成交 ========== -->
        <ElTabPane label="✅ 成交" name="trades">
          <ElTable :data="accountData.trades" size="small" stripe>
            <ElTableColumn prop="fill_time" label="时间" width="160" />
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="方向" width="60" align="center">
              <template #default="{ row }">
                <ElTag size="small" :type="row.side === 'buy' ? 'danger' : 'success'" effect="plain">
                  {{ row.side === 'buy' ? '买' : '卖' }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="filled_qty" label="数量" width="80" align="right" />
            <ElTableColumn label="价格" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.filled_price) }}</template>
            </ElTableColumn>
            <ElTableColumn label="金额" width="100" align="right">
              <template #default="{ row }">{{ fmtMoney(row.filled_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="盈亏" width="100" align="right">
              <template #default="{ row }">
                <template v-if="row.side === 'sell'">
                  <span :class="row.profit_amount >= 0 ? 'ok' : 'err'">{{ fmtMoney(row.profit_amount, '万', 2) }}</span>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.trades.length === 0" class="center-hint">该日无成交</div>
        </ElTabPane>

        <!-- ========== 委托 ========== -->
        <ElTabPane label="📝 委托" name="orders">
          <ElTable :data="accountData.orders" size="small" stripe>
            <ElTableColumn prop="create_time" label="时间" width="160" />
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="方向" width="60" align="center">
              <template #default="{ row }">
                <ElTag size="small" :type="row.side === 'buy' ? 'danger' : 'success'" effect="plain">
                  {{ row.side === 'buy' ? '买' : '卖' }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="quantity" label="委托量" width="80" align="right" />
            <ElTableColumn prop="filled_qty" label="成交量" width="80" align="right" />
            <ElTableColumn label="成交价" width="80" align="right">
              <template #default="{ row }">{{ fmtPrice(row.filled_price) }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="80" align="center">
              <template #default="{ row }">
                <ElTag size="small" :type="row.status === 'filled' ? 'success' : row.status === 'cancelled' ? 'info' : 'warning'">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="reason" label="原因" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.orders.length === 0" class="center-hint">该日无委托</div>
        </ElTabPane>

        <!-- ========== 日志 ========== -->
        <ElTabPane label="📋 日志" name="logs">
          <ElTable :data="accountData.logs" size="small" stripe>
            <ElTableColumn prop="timestamp" label="时间" width="180" />
            <ElTableColumn label="类型" width="80" align="center">
              <template #default="{ row }">
                <ElTag size="small" :type="row.type === 'buy' || row.type === 'signal' ? 'success' : row.type === 'sell' || row.type === 'risk' ? 'danger' : 'warning'" effect="plain">
                  {{ row.type }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="message" label="内容" min-width="300" show-overflow-tooltip />
          </ElTable>
          <div v-if="accountData.logs.length === 0" class="center-hint">该日无日志记录</div>
        </ElTabPane>

      </ElTabs>
    </div>
  </div>
</template>

<style scoped lang="scss">
.archive-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;

  .header-left {
    h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
    }
    .subtitle {
      margin: 4px 0 0;
      font-size: 13px;
      color: var(--text-tertiary);
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;

    .date-label {
      font-size: 13px;
      color: var(--text-secondary);
    }
  }
}

.center-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: var(--text-quaternary);
  font-size: 14px;
}

/* ===== 摘要卡片 ===== */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

@media (max-width: 900px) {
  .summary-grid { grid-template-columns: 1fr; }
}

.summary-card {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 14px 18px;
}

.sc-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--el-color-primary);
}

.sc-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 3px 0;

  b {
    font-family: 'Menlo', 'Monaco', monospace;
    font-weight: 600;
  }
}

.ok { color: var(--el-color-success); }
.err { color: var(--el-color-danger); }
.muted { color: var(--text-quaternary); }

.anomaly-alert {
  margin-top: 12px;
}

/* ===== Tabs ===== */
.archive-tabs {
  border-radius: 8px;
}

.archive-tabs :deep(.el-tabs__content) {
  padding: 16px;
}
</style>
