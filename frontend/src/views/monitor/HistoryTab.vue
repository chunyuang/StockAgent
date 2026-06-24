<script setup lang="ts">
/**
 * HistoryTab — 交易历史Tab
 * v2.9.92g: 双栏紧凑布局 — 左栏timeline，右栏订单+平仓+审计
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'

const m = useScannerMonitorInject()

const {
  auditLog, auditLogLoading, closedPositions, cumulativePnl,
  exportTradeLog, exportJSON, fetchAuditLog, historyData, historyDate, historyOrders, historyLoading,
  loadHistory,
  openTradeAudit, openTradeDetail, orders,
  strategyCN, timeline,
} = m

import { computed, ref, onMounted, watch } from 'vue'

// 【v2.9.99-r3】进入 Tab 后自动加载今天数据 (historyDate 默认为今天)
const { activeTab } = m
onMounted(() => {
  if (historyDate.value && (activeTab?.value === 'history' || !activeTab?.value)) {
    loadHistory()
  }
})
watch(() => activeTab?.value, (t) => {
  if (t === 'history' && historyDate.value) loadHistory()
})

const tlFilter = ref<'all'|'trade'|'blocked'>('trade')

/** 获取中国时区的日期字符串 YYYYMMDD */
function getChinaDateInt(): string { const now = new Date(); const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' })); const y = china.getFullYear(), m = String(china.getMonth() + 1).padStart(2, '0'), d = String(china.getDate()).padStart(2, '0'); return `${y}${m}${d}` }
function getChinaDateStr(): string { const now = new Date(); const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' })); const y = china.getFullYear(), m = String(china.getMonth() + 1).padStart(2, '0'), d = String(china.getDate()).padStart(2, '0'); return `${y}-${m}-${d}` }

// 检测 timeline 是否包含历史回放数据(trade_date != today)
const todayStr = getChinaDateInt()
const hasHistoricalFallback = computed(() => {
  return timeline.value.some((t: any) => t._historical_fallback || (t.trade_date && String(t.trade_date) !== todayStr))
})

// 非交易日保护: 选了日期但API无数据 → 不fallback到今日数据
const isHistoricalMode = computed(() => {
  // 选了日期 且 不是今天 → 历史模式
  if (!historyDate.value) return false
  const today = getChinaDateStr()
  return historyDate.value !== today
})

const displaySource = computed(() => {
  if (historyData.value.length) return historyData.value
  // 历史模式但API无数据 → 返回空(非交易日/无数据)
  if (isHistoricalMode.value) return []
  return timeline.value
})

const filteredTimeline = computed(() => {
  const src = displaySource.value
  if (tlFilter.value === 'trade') return src.filter((t: any) => t.action !== 'blocked')
  if (tlFilter.value === 'blocked') return src.filter((t: any) => t.action === 'blocked')
  return src
})

const tlStats = computed(() => {
  const src = displaySource.value
  const buy = src.filter((t: any) => t.action === 'buy').length
  const sell = src.filter((t: any) => t.action === 'sell').length
  const blocked = src.filter((t: any) => t.action === 'blocked').length
  return { buy, sell, blocked, total: src.length }
})

const displayOrders = computed(() => {
  let source
  if (historyData.value.length) {
    source = historyOrders.value
  } else if (isHistoricalMode.value) {
    source = [] // 非交易日/无数据 → 不fallback
  } else {
    source = orders.value
  }
  return source.filter((o: any) => o.status === 'filled' || o.filled_qty > 0)
})

const historyClosedPositions = computed(() => {
  // 历史模式但API无数据 → 直接返回空
  if (isHistoricalMode.value && !historyData.value.length) return []
  
  const source = historyData.value.length ? historyData.value : timeline.value
  const result: any[] = []
  const openBuys = new Map<string, any[]>()
  const selectedDate = historyDate.value || ''
  const dateLabel = selectedDate ? selectedDate.replace(/-/g, '').slice(-4) : ''
  
  for (const item of source) {
    if (item.action === 'buy') {
      const key = item.ts_code + '|' + (item.strategy || '')
      if (!openBuys.has(key)) openBuys.set(key, [])
      openBuys.get(key)!.push(item)
    } else if (item.action === 'sell') {
      const key = item.ts_code + '|' + (item.strategy || '')
      const queue = openBuys.get(key)
      const buy = queue?.length ? queue.shift() : undefined
      const buyPrice = buy?.price ?? item?.decision_detail?.cost_price ?? 0
      const profitAmount = item.profit_amount ?? (buyPrice > 0 ? (item.price - buyPrice) * (item.shares || 0) : 0)
      const profitPct = item.profit_pct ?? (buyPrice > 0 ? (item.price - buyPrice) / buyPrice * 100 : 0)
      const buyTimeStr = buy ? (dateLabel + ' ' + (buy.time || '')) : ('昨日 ' + (item.time || ''))
      const sellTimeStr = dateLabel + ' ' + (item.time || '')
      result.push({ 
        ts_code: item.ts_code, 
        stock_name: item.stock_name || buy?.stock_name || '', 
        strategy: item.strategy, 
        buy_price: buyPrice, sell_price: item.price, 
        profit_amount: profitAmount, profit_pct: profitPct, 
        buy_time: buyTimeStr, sell_time: sellTimeStr,
        is_overnight: !buy
      })
    }
  }
  return result.sort((a: any, b: any) => Math.abs(b.profit_amount) - Math.abs(a.profit_amount))
})
const displayClosedPositions = computed(() => {
  // 历史模式但API无数据 → 返回空(非交易日/无数据)
  if (isHistoricalMode.value && !historyData.value.length) return []
  if (historyData.value.length) return historyClosedPositions.value
  return closedPositions.value
})

// 平仓汇总统计
const closedStats = computed(() => {
  const items = displayClosedPositions.value
  if (!items.length) return null
  const totalProfit = items.reduce((s: number, c: any) => s + (c.profit_amount || 0), 0)
  const wins = items.filter((c: any) => c.profit_pct >= 0).length
  return { count: items.length, totalProfit, winRate: items.length > 0 ? (wins / items.length * 100).toFixed(0) : '0', wins }
})
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll ht-wrap">
      <!-- 顶部工具栏 -->
      <div class="ht-toolbar">
        <div class="ht-toolbar-left">
          <span class="ht-title">📜 交易历史</span>
          <span v-if="historyData.length" class="ht-badge">{{ historyDate }} 回放 · {{ historyData.length }}条</span>
          <span v-else-if="timeline.length" class="ht-badge">{{ hasHistoricalFallback ? '历史回放' : '今日' }} · 成交{{ tlStats.buy + tlStats.sell }}·拦截{{ tlStats.blocked }}</span>
          <span v-if="cumulativePnl" :class="cumulativePnl >= 0 ? 'up' : 'down'" class="ht-pnl">{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ Number(cumulativePnl || 0).toFixed(0) }}</span>
        </div>
        <div class="ht-toolbar-right">
          <UnifiedDateBar @change="(_d: string) => { historyDate = _d }" />
          <ElButton size="small" @click="loadHistory" :loading="historyLoading">回放</ElButton>
          <ElButton v-if="historyData.length" size="small" type="info" @click="historyData = []; historyDate = ''">返回今日</ElButton>
          <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit">🔍 审查</ElButton>
          <ElButton size="small" @click="exportTradeLog">📥 CSV</ElButton>
          <ElButton size="small" @click="exportJSON">📋 JSON</ElButton>
        </div>
      </div>

      <!-- 双栏主体 -->
      <div class="ht-body">
        <!-- 左栏: 交易时间线 -->
        <div class="ht-left">
          <div class="ht-sec-header">
            <span>⏱️ 时间线</span>
            <div class="ht-filter">
              <button :class="{active: tlFilter==='trade'}" @click="tlFilter='trade'">交易 {{ tlStats.buy + tlStats.sell }}</button>
              <button :class="{active: tlFilter==='blocked'}" @click="tlFilter='blocked'">⛔ {{ tlStats.blocked }}</button>
              <button :class="{active: tlFilter==='all'}" @click="tlFilter='all'">全部 {{ tlStats.total }}</button>
            </div>
          </div>
          <div v-if="!filteredTimeline.length" class="ht-empty">暂无记录</div>
          <div class="ht-tl-list">
            <div v-for="(item, i) in filteredTimeline" :key="i" class="tl-row" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)">
              <span class="tl-time">{{ item.time }}</span>
              <span class="tl-act" :class="item.action">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span>
              <span class="tl-code">{{ item.ts_code?.slice(0,6) }}</span>
              <span class="tl-name">{{ item.stock_name }}</span>
              <template v-if="item.action !== 'blocked'">
                <span class="tl-strat">{{ strategyCN(item.strategy) }}</span>
                <span class="tl-qty">{{ item.shares }}@¥{{ item.price?.toFixed(2) || '-' }}</span>
                <span v-if="item.action==='sell' && item.profit_pct != null && item.profit_pct !== 0" class="tl-pct" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ Number(item.profit_pct).toFixed(1) }}%</span>
              </template>
              <span v-else class="tl-reason">{{ item.reason?.slice(0,20) }}</span>
            </div>
          </div>
        </div>

        <!-- 右栏: 订单 + 平仓 + 审计 -->
        <div class="ht-right">
          <!-- 已平仓汇总(置顶,最关键) -->
          <div class="ht-panel">
            <div class="ht-sec-header">
              <span>💰 已平仓</span>
              <span v-if="closedStats" class="ht-stat">{{ closedStats.count }}笔 · 胜率{{ closedStats.winRate }}%</span>
              <span v-if="closedStats" :class="closedStats.totalProfit >= 0 ? 'up' : 'down'" class="ht-stat-pnl">{{ closedStats.totalProfit >= 0 ? '+' : '' }}¥{{ Number(closedStats.totalProfit).toFixed(0) }}</span>
            </div>
            <div v-if="!displayClosedPositions.length" class="ht-empty-sm">暂无</div>
            <div class="ht-cp-list">
              <div v-for="cp in displayClosedPositions" :key="cp.ts_code + cp.strategy + cp.sell_time" class="cp-row" :class="cp.profit_pct >= 0 ? 'win' : 'loss'" @click="openTradeDetail(cp.ts_code)">
                <span class="cp-code">{{ cp.ts_code?.slice(0,6) }}</span>
                <span class="cp-name">{{ cp.stock_name }}</span>
                <span class="cp-pct" :class="(cp.profit_pct??0) >= 0 ? 'up' : 'down'">{{ (cp.profit_pct??0) >= 0 ? '+' : '' }}{{ Number(cp.profit_pct??0).toFixed(1) }}%</span>
                <span class="cp-amt" :class="(cp.profit_amount??0) >= 0 ? 'up' : 'down'">¥{{ Number(cp.profit_amount??0).toFixed(0) }}</span>
                <span class="cp-time" :class="{overnight: cp.is_overnight}">{{ cp.is_overnight ? '昨→今' : '今→今' }}</span>
              </div>
            </div>
          </div>

          <!-- 历史订单 -->
          <div class="ht-panel">
            <div class="ht-sec-header"><span>📋 成交订单</span><span class="ht-stat">{{ displayOrders.length }}笔</span></div>
            <div v-if="!displayOrders.length" class="ht-empty-sm">暂无</div>
            <div class="ht-ord-list">
              <div v-for="o in displayOrders" :key="o.order_id" class="ord-row" @click="openTradeDetail(o.ts_code)">
                <span class="ord-dir" :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '买' : '卖' }}</span>
                <span class="ord-code">{{ o.ts_code?.slice(0,6) }}</span>
                <span class="ord-name">{{ o.stock_name }}</span>
                <span class="ord-qty">{{ o.filled_qty }}@¥{{ o.filled_price?.toFixed(2) }}</span>
                <span class="ord-time">{{ String(o.create_time || '').slice(0,8) }}</span>
              </div>
            </div>
          </div>

          <!-- 审计日志 -->
          <div class="ht-panel">
            <div class="ht-sec-header"><span>📝 审计</span><ElButton size="small" @click="fetchAuditLog" :loading="auditLogLoading" style="font-size:10px;padding:2px 6px">🔄</ElButton></div>
            <div v-if="!auditLog.length" class="ht-empty-sm">暂无</div>
            <div class="ht-audit-list">
              <div v-for="(log, i) in auditLog.slice(0, 20)" :key="i" class="aud-row">
                <span class="aud-time">{{ String(log.timestamp || log.time_str || '').replace(/T/, ' ').substring(11, 19) || '' }}</span>
                <span class="aud-act">{{ log.action }}</span>
                <span class="aud-detail">{{ (log.reason || log.detail || '').slice(0, 30) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 整体 */
.ht-wrap { display: flex; flex-direction: column; height: 100%; }
.ht-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 8px 0 6px; gap: 8px; flex-wrap: wrap; border-bottom: 1px solid var(--border-default); margin-bottom: 8px; }
.ht-toolbar-left { display: flex; align-items: center; gap: 8px; }
.ht-toolbar-right { display: flex; align-items: center; gap: 4px; }
.ht-title { font-size: 14px; font-weight: 700; }
.ht-badge { font-size: 11px; color: var(--text-tertiary); background: var(--bg-muted); padding: 2px 8px; border-radius: 10px; }
.ht-pnl { font-size: 13px; font-weight: 700; }

/* 双栏 */
.ht-body { display: grid; grid-template-columns: 1fr 340px; gap: 12px; flex: 1; min-height: 0; overflow: hidden; }
.ht-left { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.ht-right { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; min-height: 0; }

/* 段头 */
.ht-sec-header { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-primary); padding: 4px 0; }
.ht-stat { font-size: 10px; color: var(--text-tertiary); font-weight: 400; }
.ht-stat-pnl { font-size: 11px; font-weight: 700; }

/* 过滤器 */
.ht-filter { display: flex; gap: 2px; margin-left: auto; }
.ht-filter button { font-size: 10px; padding: 1px 6px; border: 1px solid var(--border-default); border-radius: 3px; background: transparent; color: var(--text-tertiary); cursor: pointer; }
.ht-filter button.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }

/* 时间线列表 */
.ht-tl-list { flex: 1; overflow-y: auto; min-height: 0; }
.tl-row { display: flex; align-items: center; gap: 4px; padding: 2px 4px; font-size: 11px; border-bottom: 1px solid var(--border-light); cursor: pointer; }
.tl-row:hover { background: var(--bg-muted); }
.tl-time { font-size: 10px; color: var(--text-tertiary); min-width: 52px; font-family: 'JetBrains Mono', monospace; }
.tl-act { font-weight: 700; min-width: 16px; font-size: 11px; }
.tl-act.buy { color: var(--stock-up); }
.tl-act.sell { color: var(--stock-down); }
.tl-act.blocked { color: var(--text-tertiary); font-size: 10px; }
.tl-code { font-family: 'JetBrains Mono', monospace; font-size: 11px; min-width: 50px; }
.tl-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-strat { font-size: 9px; color: var(--el-color-primary); background: var(--el-color-primary-light-9); padding: 0 4px; border-radius: 2px; }
.tl-qty { font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.tl-pct { font-weight: 600; font-size: 11px; min-width: 40px; text-align: right; }
.tl-reason { font-size: 10px; color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 右栏面板 */
.ht-panel { background: var(--bg-base, var(--bg-muted)); border: 1px solid var(--border-default); border-radius: 6px; padding: 6px 8px; }

/* 已平仓 */
.ht-cp-list { max-height: 200px; overflow-y: auto; }
.cp-row { display: flex; align-items: center; gap: 4px; padding: 2px 4px; font-size: 11px; border-bottom: 1px solid var(--border-light); cursor: pointer; }
.cp-row:hover { background: var(--bg-muted); }
.cp-row.win { border-left: 2px solid var(--stock-up); }
.cp-row.loss { border-left: 2px solid var(--stock-down); }
.cp-code { font-family: 'JetBrains Mono', monospace; font-size: 11px; min-width: 48px; }
.cp-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cp-pct { font-weight: 600; min-width: 36px; text-align: right; }
.cp-amt { font-size: 10px; min-width: 44px; text-align: right; }
.cp-time { font-size: 9px; color: var(--text-tertiary); white-space: nowrap; }
.cp-time.overnight { color: var(--el-color-warning); }

/* 订单 */
.ht-ord-list { max-height: 160px; overflow-y: auto; }
.ord-row { display: flex; align-items: center; gap: 4px; padding: 2px 4px; font-size: 11px; border-bottom: 1px solid var(--border-light); cursor: pointer; }
.ord-row:hover { background: var(--bg-muted); }
.ord-dir { font-weight: 700; font-size: 10px; min-width: 14px; }
.ord-code { font-family: 'JetBrains Mono', monospace; font-size: 11px; min-width: 48px; }
.ord-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ord-qty { font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.ord-time { font-size: 10px; color: var(--text-tertiary); font-family: 'JetBrains Mono', monospace; }

/* 审计 */
.ht-audit-list { max-height: 120px; overflow-y: auto; }
.aud-row { display: flex; align-items: center; gap: 4px; padding: 1px 4px; font-size: 10px; }
.aud-time { font-family: 'JetBrains Mono', monospace; color: var(--text-tertiary); min-width: 52px; }
.aud-act { color: var(--el-color-primary); font-weight: 600; min-width: 40px; }
.aud-detail { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 空状态 */
.ht-empty { padding: 40px 0; text-align: center; color: var(--text-tertiary); font-size: 13px; }
.ht-empty-sm { padding: 12px 0; text-align: center; color: var(--text-tertiary); font-size: 11px; }

/* 通用 */
.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

/* 响应式: 窄屏退回单列 */
@media (max-width: 900px) {
  .ht-body { grid-template-columns: 1fr; }
  .ht-right { max-height: 400px; }
}
</style>
