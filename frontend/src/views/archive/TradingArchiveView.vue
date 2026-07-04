<script setup lang="ts">
/**
 * 交易归档页面 — 参考掘金量化交易归档
 * 按日期+账户查看: 摘要/资金/持仓/成交/委托/日志
 */
import { ref, computed, onMounted } from 'vue'
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
  ElDivider,
} from 'element-plus'
import { api } from '@/api'

// ==================== 状态 ====================

const dates = ref<number[]>([])
const selectedDate = ref<number>(0)
const accountData = ref<any>(null)
const loading = ref(false)
const activeTab = ref('summary')

// ==================== 计算 ====================

const dateOptions = computed(() => {
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  return dates.value.map(d => {
    const s = String(d)
    const dt = new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8))
    const wd = weekdays[dt.getDay()]
    const isWeekend = dt.getDay() === 0 || dt.getDay() === 6
    return { value: d, label: `${s.slice(4, 6)}/${s.slice(6, 8)} 周${wd}`, isWeekend }
  })
})

const pnlClass = computed(() => {
  if (!accountData.value?.summary) return ''
  return accountData.value.summary.realized_pnl >= 0 ? 'pnl-win' : 'pnl-lose'
})

// ==================== 方法 ====================

async function fetchDates() {
  try {
    const res = await api.get('/trading-archive/dates')
    dates.value = res?.dates || []
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
    accountData.value = res
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

/** 持仓行背景：盈利浅绿、亏损浅红 */
function posRowClass({ row }: { row: any }): string {
  if (row.profit_pct > 0) return 'row-win'
  if (row.profit_pct < 0) return 'row-lose'
  return ''
}

/** 成交/委托行背景：买入浅红、卖出浅绿 */
function tradeRowClass({ row }: { row: any }): string {
  if (row.side === 'buy') return 'row-buy'
  if (row.side === 'sell') return 'row-sell'
  return ''
}

/** 日志行背景 */
function logRowClass({ row }: { row: any }): string {
  if (row.type === 'buy' || row.type === 'signal') return 'row-signal'
  if (row.type === 'sell' || row.type === 'risk') return 'row-risk'
  if (row.type === 'circuit') return 'row-circuit'
  return ''
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
        <span class="date-label">交易日</span>
        <ElSelect v-model="selectedDate" placeholder="选择交易日" size="default" style="width:160px" @change="onDateChange">
          <ElOption v-for="d in dateOptions" :key="d.value" :label="d.label" :value="d.value" />
        </ElSelect>
        <ElButton type="primary" :loading="loading" @click="fetchDay(selectedDate)" :disabled="!selectedDate">
          加载
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

      <!-- ===== 顶部概览条 ===== -->
      <div class="overview-bar" :class="pnlClass">
        <div class="ov-item">
          <span class="ov-label">总资产</span>
          <span class="ov-value">{{ fmtMoney(accountData.summary.total_assets) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">已实现盈亏</span>
          <span class="ov-value pnl">{{ fmtMoney(accountData.summary.realized_pnl, '万', 2) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">买入</span>
          <span class="ov-value">{{ accountData.summary.buy_orders }}笔 / {{ fmtMoney(accountData.summary.total_buy_amount) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">卖出</span>
          <span class="ov-value">{{ accountData.summary.sell_orders }}笔 / {{ fmtMoney(accountData.summary.total_sell_amount) }}</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-label">持仓</span>
          <span class="ov-value">{{ accountData.summary.position_count }}只 / {{ fmtMoney(accountData.summary.position_value) }}</span>
        </div>
      </div>

      <ElTabs v-model="activeTab" type="border-card" class="archive-tabs">

        <!-- ========== 摘要 ========== -->
        <ElTabPane name="summary">
          <template #label><span>📋 摘要</span></template>
          <div class="summary-grid">
            <!-- 委托统计 -->
            <div class="summary-card card-blue">
              <div class="sc-header">
                <span class="sc-icon">📝</span>
                <span class="sc-title">委托统计</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>总委托</span><b>{{ accountData.summary.total_orders }}</b></div>
                <div class="sc-row sc-buy"><span>买入</span><b>{{ accountData.summary.buy_orders }}</b></div>
                <div class="sc-row sc-sell"><span>卖出</span><b>{{ accountData.summary.sell_orders }}</b></div>
                <div class="sc-row"><span>已成交</span><b class="ok">{{ accountData.summary.filled_orders }}</b></div>
                <div class="sc-row"><span>已取消</span><b class="muted">{{ accountData.summary.cancelled_orders }}</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row"><span>成交率</span><b>{{ accountData.summary.total_orders ? ((accountData.summary.filled_orders / accountData.summary.total_orders) * 100).toFixed(0) + '%' : '-' }}</b></div>
              </div>
            </div>
            <!-- 成交统计 -->
            <div class="summary-card card-orange">
              <div class="sc-header">
                <span class="sc-icon">📊</span>
                <span class="sc-title">成交统计</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>成交笔数</span><b>{{ accountData.summary.total_trades }}</b></div>
                <div class="sc-row sc-buy"><span>买入金额</span><b>{{ fmtMoney(accountData.summary.total_buy_amount) }}</b></div>
                <div class="sc-row sc-sell"><span>卖出金额</span><b>{{ fmtMoney(accountData.summary.total_sell_amount) }}</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row">
                  <span>已实现盈亏</span>
                  <b :class="accountData.summary.realized_pnl >= 0 ? 'ok' : 'err'">
                    {{ fmtMoney(accountData.summary.realized_pnl, '万', 2) }}
                  </b>
                </div>
                <div class="sc-row sc-note">
                  <ElTooltip content="卖出成交的盈亏合计（含佣金），不含浮动盈亏" placement="top">
                    <span>💡仅含已平仓</span>
                  </ElTooltip>
                </div>
              </div>
            </div>
            <!-- 资金概况 -->
            <div class="summary-card card-green">
              <div class="sc-header">
                <span class="sc-icon">💰</span>
                <span class="sc-title">资金概况</span>
              </div>
              <div class="sc-body">
                <div class="sc-row"><span>总资产</span><b>{{ fmtMoney(accountData.summary.total_assets) }}</b></div>
                <div class="sc-row"><span>可用资金</span><b>{{ fmtMoney(accountData.summary.available_cash) }}</b></div>
                <div class="sc-row"><span>持仓市值</span><b>{{ fmtMoney(accountData.summary.position_value) }}</b></div>
                <div class="sc-row"><span>持仓数</span><b>{{ accountData.summary.position_count }}只</b></div>
                <ElDivider class="sc-divider" />
                <div class="sc-row"><span>仓位比例</span>
                  <b>{{ accountData.summary.total_assets ? ((accountData.summary.position_value / accountData.summary.total_assets) * 100).toFixed(1) + '%' : '-' }}</b>
                </div>
              </div>
            </div>
          </div>
        </ElTabPane>

        <!-- ========== 资金 ========== -->
        <ElTabPane name="capital">
          <template #label><span>💰 资金</span></template>
          <div class="capital-grid" v-if="accountData.capital">
            <div class="cap-card">
              <div class="cap-label">可用资金</div>
              <div class="cap-value">{{ fmtMoney(accountData.capital.available_cash) }}</div>
            </div>
            <div class="cap-card">
              <div class="cap-label">总资产</div>
              <div class="cap-value">{{ fmtMoney(accountData.capital.total_assets) }}</div>
            </div>
            <div class="cap-card">
              <div class="cap-label">持仓市值</div>
              <div class="cap-value">{{ fmtMoney(accountData.capital.market_value) }}</div>
            </div>
            <div class="cap-card" :class="accountData.capital.total_profit >= 0 ? 'cap-win' : 'cap-lose'">
              <div class="cap-label">总盈亏</div>
              <div class="cap-value">{{ fmtMoney(accountData.capital.total_profit, '万', 2) }}</div>
              <div class="cap-sub">{{ accountData.capital.total_assets ? ((accountData.capital.total_profit / 1000000) * 100).toFixed(2) + '%' : '-' }}</div>
            </div>
            <div class="cap-card">
              <div class="cap-label">已实现盈亏<ElTooltip content="已卖出部分的盈亏合计" placement="top"><span class="cap-tip">ⓘ</span></ElTooltip></div>
              <div class="cap-value">{{ fmtMoney(accountData.capital.realized_pnl, '万', 2) }}</div>
            </div>
          </div>
          <div v-else class="center-hint">暂无资金数据</div>
        </ElTabPane>

        <!-- ========== 持仓 ========== -->
        <ElTabPane name="positions">
          <template #label><span>📊 持仓 <ElTag v-if="accountData.positions.length" size="small" round type="info">{{ accountData.positions.length }}</ElTag></span></template>
          <div class="tab-note">按盈亏着色：盈利行浅绿底色，亏损行浅红底色</div>
          <ElTable :data="accountData.positions" size="small" stripe :row-class-name="posRowClass" class="archive-table">
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
            <ElTableColumn label="盈亏%" width="90" align="right" sortable>
              <template #default="{ row }">
                <span :class="row.profit_pct >= 0 ? 'ok' : 'err'">
                  {{ row.profit_pct > 0 ? '+' : '' }}{{ fmtPct(row.profit_pct) }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.positions.length === 0" class="center-hint">该日无持仓</div>
        </ElTabPane>

        <!-- ========== 成交 ========== -->
        <ElTabPane name="trades">
          <template #label><span>✅ 成交 <ElTag v-if="accountData.trades.length" size="small" round type="info">{{ accountData.trades.length }}</ElTag></span></template>
          <div class="tab-note">买入行浅红底色，卖出行浅绿底色；盈亏仅卖出时显示</div>
          <ElTable :data="accountData.trades" size="small" stripe :row-class-name="tradeRowClass" class="archive-table">
            <ElTableColumn prop="fill_time" label="时间" width="160" />
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="方向" width="60" align="center">
              <template #default="{ row }">
                <span class="dir-badge" :class="row.side === 'buy' ? 'dir-buy' : 'dir-sell'">
                  {{ row.side === 'buy' ? '买' : '卖' }}
                </span>
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
                  <span :class="row.profit_amount >= 0 ? 'ok' : 'err'">
                    {{ row.profit_amount > 0 ? '+' : '' }}{{ fmtMoney(row.profit_amount, '万', 2) }}
                  </span>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.trades.length === 0" class="center-hint">该日无成交</div>
        </ElTabPane>

        <!-- ========== 委托 ========== -->
        <ElTabPane name="orders">
          <template #label><span>📝 委托 <ElTag v-if="accountData.orders.length" size="small" round type="info">{{ accountData.orders.length }}</ElTag></span></template>
          <div class="tab-note">包含所有委托（含未成交和已取消），买入浅红、卖出浅绿</div>
          <ElTable :data="accountData.orders" size="small" stripe :row-class-name="tradeRowClass" class="archive-table">
            <ElTableColumn prop="create_time" label="时间" width="160" />
            <ElTableColumn prop="ts_code" label="代码" width="110" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="方向" width="60" align="center">
              <template #default="{ row }">
                <span class="dir-badge" :class="row.side === 'buy' ? 'dir-buy' : 'dir-sell'">
                  {{ row.side === 'buy' ? '买' : '卖' }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="quantity" label="委托量" width="80" align="right" />
            <ElTableColumn prop="filled_qty" label="成交量" width="80" align="right" />
            <ElTableColumn label="成交价" width="80" align="right">
              <template #default="{ row }">{{ row.filled_price ? fmtPrice(row.filled_price) : '-' }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="80" align="center">
              <template #default="{ row }">
                <ElTag size="small" :type="row.status === 'filled' ? 'success' : row.status === 'cancelled' ? 'info' : 'warning'" effect="plain">
                  {{ row.status === 'filled' ? '已成交' : row.status === 'cancelled' ? '已取消' : row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="reason" label="原因" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="strategy" label="策略" min-width="100" />
          </ElTable>
          <div v-if="accountData.orders.length === 0" class="center-hint">该日无委托</div>
        </ElTabPane>

        <!-- ========== 日志 ========== -->
        <ElTabPane name="logs">
          <template #label><span>📋 日志 <ElTag v-if="accountData.logs.length" size="small" round type="info">{{ accountData.logs.length }}</ElTag></span></template>
          <div class="tab-note">买卖信号浅绿、风控/卖出浅红、熔断浅橙</div>
          <ElTable :data="accountData.logs" size="small" stripe :row-class-name="logRowClass" class="archive-table">
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
  margin-bottom: 16px;
  gap: 16px;

  .header-left {
    h2 { margin: 0; font-size: 20px; font-weight: 700; }
    .subtitle { margin: 4px 0 0; font-size: 13px; color: var(--text-tertiary); }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    .date-label { font-size: 13px; color: var(--text-secondary); }
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

/* ===== 顶部概览条 ===== */
.overview-bar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 14px 24px;
  margin-bottom: 16px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  border-left: 4px solid var(--el-color-info);

  &.pnl-win { border-left-color: var(--el-color-success); background: rgba(34,197,94,0.04); }
  &.pnl-lose { border-left-color: var(--el-color-danger); background: rgba(239,68,68,0.04); }

  .ov-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0 24px;
    min-width: 0;

    .ov-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; white-space: nowrap; }
    .ov-value { font-size: 16px; font-weight: 700; font-family: 'Menlo','Monaco',monospace; white-space: nowrap; }
    .ov-value.pnl { font-size: 18px; }
  }

  .ov-sep { width: 1px; height: 32px; background: var(--el-border-color-lighter); flex-shrink: 0; }
}

.overview-bar.pnl-win .ov-value.pnl { color: var(--el-color-success); }
.overview-bar.pnl-lose .ov-value.pnl { color: var(--el-color-danger); }

@media (max-width: 768px) {
  .overview-bar { flex-wrap: wrap; gap: 8px; padding: 12px 16px; }
  .ov-sep { display: none; }
  .ov-item { padding: 4px 12px; }
}

/* ===== 摘要卡片 ===== */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 900px) {
  .summary-grid { grid-template-columns: 1fr; }
}

.summary-card {
  border-radius: 10px;
  padding: 16px 20px;
  border-left: 4px solid transparent;
  background: var(--el-fill-color-lighter);

  &.card-blue   { border-left-color: #409eff; }
  &.card-orange { border-left-color: #e6a23c; }
  &.card-green  { border-left-color: #67c23a; }
}

.sc-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  .sc-icon { font-size: 16px; }
  .sc-title { font-size: 14px; font-weight: 600; }
}

.card-blue   .sc-title { color: #409eff; }
.card-orange .sc-title { color: #e6a23c; }
.card-green  .sc-title { color: #67c23a; }

.sc-body {
  .sc-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    padding: 3px 0;
    b { font-family: 'Menlo','Monaco',monospace; font-weight: 600; }
  }
  .sc-buy  { b { color: #f56c6c; } }
  .sc-sell { b { color: #67c23a; } }
  .sc-note { font-size: 12px; color: var(--text-quaternary); justify-content: flex-end; span { cursor: help; } }
  .sc-divider { margin: 8px 0; }
}

/* ===== 资金卡片 ===== */
.capital-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

@media (max-width: 900px) {
  .capital-grid { grid-template-columns: repeat(2, 1fr); }
}

.cap-card {
  background: var(--el-fill-color-lighter);
  border-radius: 10px;
  padding: 16px;
  text-align: center;
  border-top: 3px solid var(--el-color-primary);

  &.cap-win { border-top-color: var(--el-color-success); background: rgba(34,197,94,0.04); }
  &.cap-lose { border-top-color: var(--el-color-danger); background: rgba(239,68,68,0.04); }

  .cap-label {
    font-size: 12px;
    color: var(--text-tertiary);
    margin-bottom: 6px;
  }
  .cap-value {
    font-size: 18px;
    font-weight: 700;
    font-family: 'Menlo','Monaco',monospace;
  }
  .cap-sub {
    font-size: 12px;
    color: var(--text-tertiary);
    margin-top: 2px;
  }
  .cap-tip {
    cursor: help;
    color: var(--el-color-primary);
    font-size: 11px;
    margin-left: 2px;
  }
}

.cap-win .cap-value { color: var(--el-color-success); }
.cap-lose .cap-value { color: var(--el-color-danger); }

/* ===== 通用表格 ===== */
.tab-note {
  font-size: 12px;
  color: var(--text-quaternary);
  margin-bottom: 8px;
  padding: 0 2px;
}

.archive-table {
  :deep(.row-win)  { background: rgba(34,197,94,0.06) !important; }
  :deep(.row-lose) { background: rgba(239,68,68,0.06) !important; }
  :deep(.row-buy)  { background: rgba(245,108,108,0.05) !important; }
  :deep(.row-sell) { background: rgba(103,194,58,0.05) !important; }
  :deep(.row-signal) { background: rgba(103,194,58,0.06) !important; }
  :deep(.row-risk)   { background: rgba(245,108,108,0.06) !important; }
  :deep(.row-circuit){ background: rgba(230,162,60,0.06) !important; }
}

/* ===== 方向标记 ===== */
.dir-badge {
  display: inline-block;
  width: 28px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;

  &.dir-buy  { background: rgba(245,108,108,0.12); color: #f56c6c; }
  &.dir-sell { background: rgba(103,194,58,0.12); color: #67c23a; }
}

/* ===== 通用 ===== */
.ok   { color: var(--el-color-success); }
.err  { color: var(--el-color-danger); }
.muted { color: var(--text-quaternary); }

/* ===== Tabs ===== */
.archive-tabs {
  border-radius: 10px;
  :deep(.el-tabs__content) { padding: 16px; }
}
</style>
