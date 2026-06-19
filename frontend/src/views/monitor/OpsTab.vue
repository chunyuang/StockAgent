<script setup lang="ts">
/**
 * OpsTab — 运维操作Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取】
 */
import { ref, computed } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import SystemHealth from './SystemHealth.vue'
import { ElButton, ElTag, ElInput, ElSelect, ElOption, ElInputNumber } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { formatTradeDate, formatFullDate } from '@/utils/scanner'

const m = useScannerMonitorInject()

// 【v2.9.96】展开决策详情
const expandedOrderIds = ref<Set<string>>(new Set())
const tradesExpanded = ref(false)  // 自动交易列表默认折叠
function toggleTradeExpand(orderId: string) {
  if (expandedOrderIds.value.has(orderId)) expandedOrderIds.value.delete(orderId)
  else expandedOrderIds.value.add(orderId)
  expandedOrderIds.value = new Set(expandedOrderIds.value) // trigger reactivity
}
function layerStatusIcon(layer: any): string {
  if (!layer || (typeof layer === 'object' && Object.keys(layer).length === 0)) return '⚪'
  const detail = layer.detail || layer
  // L1强制空仓: triggered=true表示禁止下单
  if (detail.triggered === true) return '⛔'
  if (detail.applied === false) return '⏭️'
  return '✅'
}
function formatLayerName(key: string): string {
  const map: Record<string, string> = {
    L1_force_empty: 'L1·强制空仓判断',
    L2_special_period: 'L2·特殊时期(月末/季末)',
    L3_sentiment: 'L3·情绪周期映射',
    L4_premarket: 'L4·盘前过滤(ST/退市/次新/低流动)',
    L5_auction: 'L5·竞价过滤',
    L6_strategy: 'L6·策略筛选',
    L7_ranking: 'L7·候选排序去重',
    L8_ma60: 'L8·大盘MA60',
    L8_position: 'L8·总仓位/单票上限',
    L9_sector: 'L9·行业集中度',
  }
  return map[key] || key
}
function formatLayerDetail(key: string, layer: any): string {
  if (!layer) return '无数据'
  const detail = layer.detail || layer
  if (typeof detail !== 'object' || Object.keys(detail).length === 0) return '未触发/无数据'
  // 提取关键字段
  const parts: string[] = []
  for (const [k, v] of Object.entries(detail)) {
    if (v === undefined || v === null || v === '' || k === 'applied') continue
    if (typeof v === 'object') continue
    parts.push(`${k}=${v}`)
  }
  return parts.join(' · ') || JSON.stringify(detail)
}
function fmtPct(v: any, digits = 1): string {
  if (v === undefined || v === null || v === '') return '-'
  return (Number(v) * 100).toFixed(digits) + '%'
}
function fmt(v: any, digits = 2): string {
  if (v === undefined || v === null || v === '') return '-'
  return Number(v).toFixed(digits)
}
function hasDecisionTrace(t: any): boolean {
  return !!(t?.decision_trace && Object.keys(t.decision_trace).length)
}
const autoTradesSummary = computed(() => {
  const trades = m.autoTrades.value || []
  if (!trades.length) return '无记录'
  const buys = trades.filter((t: any) => t.side === 'buy').length
  const sells = trades.filter((t: any) => t.side === 'sell').length
  return `${trades.length}笔 (买${buys} 卖${sells})`
})

function shortTradeReason(reason: string): string {
  if (!reason) return '-'
  return reason
    .replace(/同行业「(.+?)」已选\d+只信号,本只被集中度过滤剔除/g, '行业集中度：$1')
    .replace(/同行业「(.+?)」已选\d+只信号,本只被集中度过滤剔/g, '行业集中度：$1')
    .replace(/本只被集中度过滤剔除/g, '集中度过滤')
}
function fmtTraceValue(v: any): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)))
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'object') return JSON.stringify(v, null, 0)
  return String(v)
}
function entriesOf(obj: any): Array<[string, any]> {
  if (!obj || typeof obj !== 'object') return []
  return Object.entries(obj).filter(([, v]) => v !== undefined && v !== null && v !== '')
}

// 解构需要的变量(从inject对象)
const {
  loading, isRunning, dryRun, circuitBreakerPaused,
  autoTrades, opsDate, scanConfig, scanConfigLoading,
  timeline, orders, historyData, historyDate, historyLoading,
  manualTrade, manualQuote,
  cumulativePnl,
  strategyCN,
  // 方法
  manualScan, forceScan, dailySettlement, openTradeAudit,
  fetchAutoTrades, fetchScanConfig, fetchDailyReport,
  openWeeklyReport, toggleDryRun, resetCircuitBreaker,
  exportTradeLog, saveSnapshot, resetAccount, sellAllPositions,
  loadCompare, compareLoading, layerDebugVisible, layerDebugLoading,
  onManualCodeChange, executeManualTrade,
  loadHistory, openTradeDetail,
  dailyReportVisible,
} = m
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 快捷操作 -->
      <div class="st">⚡ 快捷操作</div>
      <div class="ops-grid">
        <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning">📡 扫描</ElButton>
        <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning">⚡ 强扫</ElButton>
        <ElButton size="small" @click="dailySettlement" :disabled="!isRunning">📅 日结</ElButton>
        <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 审查</ElButton>
        <ElButton size="small" @click="fetchDailyReport(); dailyReportVisible = true">📈 复盘</ElButton>
        <ElButton size="small" @click="openWeeklyReport">📊 周报</ElButton>
        <ElButton size="small" @click="layerDebugVisible = true" :loading="layerDebugLoading">🧪 9层调试</ElButton>
        <ElButton size="small" @click="loadCompare" :loading="compareLoading">📊 回测对比</ElButton>
        <ElButton size="small" @click="toggleDryRun">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
        <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker">🔓 解熔断</ElButton>
        <ElButton size="small" @click="exportTradeLog">📥 导出日志</ElButton>
        <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
        <ElButton size="small" type="warning" @click="resetAccount">🗑️ 清仓重置</ElButton>
        <ElButton size="small" @click="sellAllPositions">💰 一键清仓</ElButton>
      </div>

      <!-- 自动交易操作流 -->
      <div class="st collapsible" @click="tradesExpanded = !tradesExpanded">🤖 自动交易操作流 <span class="collapse-summary">{{ autoTradesSummary }}</span> <span class="collapse-arrow">{{ tradesExpanded ? '▲' : '▼' }}</span>
        <UnifiedDateBar @change="(_d: string) => { opsDate = _d; fetchAutoTrades() }" @click.stop />
      </div>
      <template v-if="tradesExpanded">
      <div v-if="!autoTrades.length" class="empty">暂无自动交易记录</div>
      <div v-else class="auto-trades-list">
        <div class="at-header"><span>时间</span><span>来源</span><span>操作</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span><span>原因/详情</span></div>
        <template v-for="t in autoTrades" :key="t.order_id">
          <div class="at-row" :class="{ 'auto-trade': t.source === 'auto', 'manual-trade': t.source === 'manual' }">
            <span class="tl-time">{{ t.time }}</span>
            <span><ElTag size="small" :type="t.source === 'auto' ? 'primary' : 'warning'" style="font-size:10px">{{ t.source === 'auto' ? '🤖自动' : '✋手动' }}</ElTag></span>
            <span class="tl-action" :class="t.side === 'buy' ? 'buy' : 'sell'">{{ t.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ t.ts_code }}</span>
            <span class="name">{{ t.stock_name }}</span>
            <span>{{ t.quantity }}股</span>
            <span>¥{{ Number(t.price || 0).toFixed(2) }}</span>
            <span v-if="t.strategy" class="tl-strat">{{ strategyCN(t.strategy) }}</span><span v-else>-</span>
            <span class="reason-cell">
              <span class="text-tertiary reason-preview" :title="t.reason" style="font-size:11px">{{ shortTradeReason(t.reason) }}</span>
              <ElButton size="small" link class="trace-toggle" @click="toggleTradeExpand(t.order_id)">
                {{ expandedOrderIds.has(t.order_id) ? '▽ 收起' : (hasDecisionTrace(t) ? '▶ 决策' : '▶ 原因') }}
              </ElButton>
            </span>
          </div>
          <!-- 原因/完整决策轨迹展开 -->
          <div v-if="expandedOrderIds.has(t.order_id)" class="trace-detail">
            <div class="trace-reason-full">
              <div class="tb-title">📝 原因/详情</div>
              <div class="reason-full-text">{{ t.reason || '无原因记录' }}</div>
              <div class="reason-meta">
                <span>订单 {{ t.order_id || '-' }}</span>
                <span>{{ t.source === 'auto' ? '自动交易' : '手动交易' }}</span>
                <span>{{ t.side === 'buy' ? '买入' : '卖出' }} {{ t.quantity }}股 @ ¥{{ Number(t.price || 0).toFixed(2) }}</span>
              </div>
            </div>
            <div v-if="hasDecisionTrace(t) && t.decision_trace.decision_steps?.length" class="decision-steps">
              <div class="tb-title">🧭 决策步骤（逻辑 / 参数 / 当时值 / 结果）</div>
              <div v-for="(s, i) in t.decision_trace.decision_steps" :key="i" class="decision-step">
                <div class="ds-head"><span class="ds-no">{{ i + 1 }}</span><b>{{ s.step }}</b><span class="ds-result">{{ s.result }}</span></div>
                <div class="ds-logic">{{ s.logic }}</div>
                <div class="ds-cols">
                  <div v-if="entriesOf(s.params).length" class="ds-col"><div class="ds-title">参数</div><div v-for="pair in entriesOf(s.params)" :key="pair[0]" class="ds-kv"><span>{{ pair[0] }}</span><b>{{ fmtTraceValue(pair[1]) }}</b></div></div>
                  <div v-if="entriesOf(s.observed).length" class="ds-col"><div class="ds-title">当时值/考虑</div><div v-for="pair in entriesOf(s.observed)" :key="pair[0]" class="ds-kv"><span>{{ pair[0] }}</span><b>{{ fmtTraceValue(pair[1]) }}</b></div></div>
                </div>
              </div>
            </div>
            <div v-if="hasDecisionTrace(t)" class="trace-grid">
              <!-- 行情快照 -->
              <div class="trace-block" v-if="t.decision_trace.market_data">
                <div class="tb-title">📊 行情快照</div>
                <div class="tb-kv">
                  <span>价格</span><b>¥{{ fmt(t.decision_trace.market_data.price) }} → 成交¥{{ fmt(t.decision_trace.market_data.filled_price) }}</b>
                  <span>涨幅</span><b :class="(t.decision_trace.market_data.pct_chg||0)>=0?'up':'down'">{{ fmt(t.decision_trace.market_data.pct_chg, 2) }}%</b>
                  <span>量比</span><b>{{ fmt(t.decision_trace.market_data.volume_ratio, 2) }}</b>
                  <span>换手率</span><b>{{ fmt(t.decision_trace.market_data.turnover_rate, 1) }}%</b>
                  <span v-if="t.decision_trace.market_data.is_limit_up">封板</span><b v-if="t.decision_trace.market_data.is_limit_up" class="up">涨停</b>
                  <span v-if="t.decision_trace.market_data.limit_up_count">连板</span><b v-if="t.decision_trace.market_data.limit_up_count">{{ t.decision_trace.market_data.limit_up_count }}板</b>
                  <span>开/高/低</span><b>{{ fmt(t.decision_trace.market_data.open) }}/{{ fmt(t.decision_trace.market_data.high) }}/{{ fmt(t.decision_trace.market_data.low) }}</b>
                  <span>流通市值</span><b>{{ t.decision_trace.market_data.circ_mv ? (Number(t.decision_trace.market_data.circ_mv)/10000).toFixed(0) + '亿' : '-' }}</b>
                </div>
              </div>
              <!-- 选股参数 -->
              <div class="trace-block" v-if="t.decision_trace.selection_params">
                <div class="tb-title">📋 选股参数(当前策略)</div>
                <div class="tb-kv">
                  <template v-for="(v, k) in t.decision_trace.selection_params" :key="k">
                    <template v-if="v !== null && v !== undefined && v !== '' && k !== 'strategy'">
                      <span>{{ k }}</span><b>{{ v }}</b>
                    </template>
                  </template>
                </div>
              </div>
              <!-- 风控参数 -->
              <div class="trace-block" v-if="t.decision_trace.risk_params">
                <div class="tb-title">🛡️ 风控参数</div>
                <div class="tb-kv">
                  <span>止损</span><b class="down">{{ fmtPct(t.decision_trace.risk_params.stop_loss_pct) }}</b>
                  <span>止盈</span><b class="up">{{ fmtPct(t.decision_trace.risk_params.take_profit_pct) }}</b>
                  <template v-if="t.decision_trace.risk_params.trailing_stop_pct"><span>追踪止损</span><b>{{ fmtPct(t.decision_trace.risk_params.trailing_stop_pct) }}</b></template>
                  <template v-if="t.decision_trace.risk_params.max_hold_days"><span>最大持有</span><b>{{ t.decision_trace.risk_params.max_hold_days }}天</b></template>
                  <template v-if="t.decision_trace.risk_params.slippage_pct"><span>滑点</span><b>{{ fmtPct(t.decision_trace.risk_params.slippage_pct, 2) }}</b></template>
                  <template v-if="t.decision_trace.risk_params.hold_protection_threshold !== undefined"><span>持有保护</span><b>{{ fmtPct(t.decision_trace.risk_params.hold_protection_threshold) }}</b></template>
                </div>
              </div>
              <!-- L1-L9逐层轨迹 -->
              <div class="trace-block trace-block-wide" v-if="t.decision_trace.layers">
                <div class="tb-title">🔍 9层筛选决策轨迹</div>
                <div class="layer-list">
                  <div v-for="(layer, key) in t.decision_trace.layers" :key="key" class="layer-row">
                    <span class="layer-icon">{{ layerStatusIcon(layer) }}</span>
                    <span class="layer-name">{{ formatLayerName(String(key)) }}</span>
                    <span class="layer-detail">{{ formatLayerDetail(String(key), layer) }}</span>
                  </div>
                </div>
              </div>
              <!-- 情绪上下文 -->
              <div class="trace-block" v-if="t.decision_trace.sentiment">
                <div class="tb-title">🌡️ 情绪上下文</div>
                <div class="tb-kv">
                  <span>情绪期</span><b>{{ t.decision_trace.sentiment.phase_name || t.decision_trace.sentiment.period }}</b>
                  <span>评分</span><b>{{ fmt(t.decision_trace.sentiment.score, 0) }}/100</b>
                  <span>仓位系数</span><b>{{ fmtPct(t.decision_trace.sentiment.position_ratio_factor, 0) }}</b>
                </div>
              </div>
              <!-- 账户上下文 -->
              <div class="trace-block" v-if="t.decision_trace.account_context">
                <div class="tb-title">💰 账户上下文</div>
                <div class="tb-kv">
                  <span>买入金额</span><b>¥{{ fmt(t.decision_trace.account_context.buy_amount, 0) }}({{ t.decision_trace.account_context.buy_shares }}股)</b>
                  <span>可用现金</span><b>¥{{ fmt(t.decision_trace.account_context.available_cash_before, 0) }}</b>
                  <span>总资产</span><b>¥{{ fmt(t.decision_trace.account_context.total_assets_before, 0) }}</b>
                  <span>持仓数</span><b>{{ t.decision_trace.account_context.position_count_before }}→{{ (t.decision_trace.account_context.position_count_before||0)+1 }}/{{ t.decision_trace.account_context.max_positions }}</b>
                  <span>仓位比例</span><b>{{ fmtPct(t.decision_trace.account_context.calculated_position_ratio) }}·上限{{ fmtPct(t.decision_trace.account_context.max_position_ratio) }}</b>
                  <span>单票上限</span><b>{{ fmtPct(t.decision_trace.account_context.single_position_cap) }}</b>
                  <template v-if="t.decision_trace.account_context.circuit_breaker">
                    <span>熔断器</span><b :class="t.decision_trace.account_context.circuit_breaker.paused?'down':''">{{ t.decision_trace.account_context.circuit_breaker.paused ? '⚠️暂停' : '✅正常' }} · 连亏{{ t.decision_trace.account_context.circuit_breaker.consecutive_losses }}</b>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
      </template>

      <!-- 扫描器配置 -->
      <div class="st" style="margin-top:16px">⏱️ 扫描器配置</div>
      <div v-if="scanConfig" class="scan-config-grid">
        <div class="sc-item"><span class="sc-label">自动扫描间隔</span><span class="sc-value">{{ scanConfig.scan_interval_desc || scanConfig.scan_interval_sec + '秒' }}</span></div>
        <div class="sc-item"><span class="sc-label">持仓检查间隔</span><span class="sc-value">{{ scanConfig.position_check_interval_sec }}秒</span></div>
        <div class="sc-item"><span class="sc-label">持仓快速检查</span><span class="sc-value">{{ scanConfig.position_check_fast_sec }}秒(接近止损)</span></div>
        <div class="sc-item"><span class="sc-label">持仓紧急检查</span><span class="sc-value">{{ scanConfig.position_check_critical_sec }}秒(触及止损)</span></div>
        <div class="sc-item"><span class="sc-label">信号过期时间</span><span class="sc-value">{{ scanConfig.signal_expire_desc || scanConfig.signal_expire_sec + '秒' }}</span></div>
        <div class="sc-item"><span class="sc-label">最大持仓数</span><span class="sc-value">{{ scanConfig.max_positions }}只</span></div>
        <div class="sc-item"><span class="sc-label">最大仓位比例</span><span class="sc-value">{{ ((Number(scanConfig.max_position_ratio) || 0) * 100).toFixed(0) }}%</span></div>
        <div class="sc-item" v-if="scanConfig.current_smart_interval"><span class="sc-label">当前智能检查间隔</span><span class="sc-value">{{ scanConfig.current_smart_interval }}秒</span></div>
        <div class="sc-item"><span class="sc-label">交易模式</span><span class="sc-value">{{ scanConfig.trade_mode === 'simulated' ? '模拟' : scanConfig.trade_mode === 'gm' ? '掘金' : scanConfig.trade_mode }}</span></div>
        <div class="sc-item"><span class="sc-label">运行状态</span><span class="sc-value" :style="{ color: scanConfig.is_running ? 'var(--el-color-success)' : 'var(--el-color-danger)' }">{{ scanConfig.is_running ? '🟢 运行中' : '🔴 未启动' }}</span></div>
      </div>

      <!-- 系统健康 -->
      <SystemHealth />

      <!-- 手动下单 -->
      <div class="st" style="margin-top:16px">🔧 手动下单</div>
      <div class="mf ops-mf">
        <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
        <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
        <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
        <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
        <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ Number(manualQuote.pct_chg || 0).toFixed(2) }}%</span></div>
      </div>

      <!-- 交易时间线 -->
      <div class="st" style="margin-top:16px">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ Number(cumulativePnl || 0).toFixed(0) }}</span>
        <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElButton size="small" @click="loadHistory" :loading="historyLoading">📜 回放</ElButton></div>
      </div>
      <div v-if="!timeline.length && !historyData.length" class="empty">暂无交易</div>
      <div v-else class="ops-timeline">
        <div v-if="historyData.length" class="history-tag">📜 {{ formatFullDate(opsDate) }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><template v-if="item.action !== 'blocked'"><span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price?.toFixed(2) || '-' }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ Number(item.profit_pct ?? 0).toFixed(1) }}%</span><span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ Number(item.profit_amount ?? 0).toFixed(0) }}</span></template><span v-else class="tl-blocked-reason">{{ item.reason }}</span></div>
      </div>

      <!-- 历史订单 -->
      <div v-if="orders.length" class="st" style="margin-top:16px">📋 历史订单 ({{ orders.length }})</div>
      <div v-if="orders.length" class="ops-timeline">
        <div v-for="o in orders.slice(0, 50)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ formatTradeDate(o.trade_date) }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.st.collapsible { cursor: pointer; user-select: none; &:hover { color: var(--el-color-primary); } }
.collapse-arrow { font-size: 9px; color: var(--text-tertiary); margin-left: 4px; }
.collapse-summary { font-size: 10px; color: var(--text-tertiary); margin-left: 6px; font-weight: 400; }

.mf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.mf-row { display: flex; gap: 4px; min-width: 0; flex-wrap: wrap; }

.mf-q { font-size: 11px; color: var(--stock-down); padding: 2px 0; }

.mf-hint { font-size: 11px; color: var(--el-color-primary); cursor: pointer; padding: 0 4px; white-space: nowrap; }

.tl-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); cursor: pointer; flex-wrap: wrap; min-width: 0; }

.tl-row:hover { background: var(--bg-base); }

.tl-time { font-size: 11px; color: var(--text-tertiary); min-width: 40px; }

.tl-action { font-size: 11px; font-weight: 600; min-width: 20px; }

.tl-action.buy { color: var(--stock-up); }

.tl-action.sell { color: var(--stock-down); }

.tl-action.blocked { color: var(--text-tertiary, var(--text-tertiary)); font-size: 11px; }

.tl-strat { font-size: 10px; color: var(--el-color-primary); background: var(--bg-tertiary); padding: 1px 5px; border-radius: 3px; white-space: nowrap; }

.tl-blocked-reason { font-size: 12px; color: var(--text-tertiary, var(--text-tertiary)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }

.tl-detail { font-size: 11px; color: var(--text-secondary); }

.history-tag { font-size: 12px; color: var(--el-color-primary); background: var(--info-bg); padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

.tl-amt { font-size: 11px; font-weight: 700; min-width: 50px; text-align: right; }

.auto-trades-list { font-size: 12px; }

.at-header, .at-row { display: grid; grid-template-columns: 52px 50px 28px 72px 56px 50px 60px 56px 1fr; gap: 4px; padding: 3px 0; align-items: center; }

.at-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); font-size: 11px; }

.at-row { border-bottom: 1px solid var(--border-default); }

.at-row:last-child { border-bottom: none; }

.at-row.auto-trade { background: rgba(22,119,255,0.03); }

.at-row.manual-trade { background: rgba(250,173,20,0.03); }

/* 【v2.9.96】决策详情展开 */
.reason-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.reason-cell > span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.trace-toggle { font-size: 11px !important; padding: 0 4px !important; flex: none; }
.trace-detail {
  background: var(--bg-tertiary, rgba(0,0,0,0.02));
  border-left: 3px solid var(--el-color-primary);
  margin: 4px 0 8px;
  padding: 10px 12px;
  border-radius: 4px;
  font-size: 11px;
}
.trace-reason-full { margin-bottom: 10px; padding: 8px 10px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; }
.reason-full-text { color: var(--text-primary); line-height: 1.6; word-break: break-word; white-space: normal; }
.reason-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; color: var(--text-tertiary); font-size: 10px; }
.reason-meta span { padding: 1px 5px; background: var(--bg-tertiary); border-radius: 3px; }
.decision-steps { margin-bottom: 10px; padding: 8px 10px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; }
.decision-step { position: relative; padding: 8px 0 8px 22px; border-bottom: 1px dashed var(--border-default); }
.decision-step:last-child { border-bottom: none; }
.ds-head { display: flex; align-items: center; gap: 8px; color: var(--text-primary); }
.ds-no { position: absolute; left: 0; top: 8px; width: 16px; height: 16px; border-radius: 50%; background: var(--el-color-primary); color: white; font-size: 10px; display: inline-flex; align-items: center; justify-content: center; }
.ds-result { margin-left: auto; color: #67c23a; font-size: 11px; font-weight: 600; }
.ds-logic { color: var(--text-secondary); line-height: 1.5; margin: 4px 0 6px; }
.ds-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.ds-col { background: var(--bg-tertiary); border-radius: 5px; padding: 6px; }
.ds-title { font-weight: 600; color: var(--text-secondary); margin-bottom: 4px; }
.ds-kv { display: grid; grid-template-columns: minmax(90px, 38%) 1fr; gap: 6px; padding: 2px 0; border-bottom: 1px solid rgba(127,127,127,0.08); }
.ds-kv:last-child { border-bottom: none; }
.ds-kv span { color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ds-kv b { color: var(--text-primary); font-weight: 500; word-break: break-word; }
.trace-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px;
}
.trace-block { background: var(--bg-secondary, rgba(255,255,255,0.6)); border: 1px solid var(--border-default); border-radius: 6px; padding: 6px 10px; }
.trace-block-wide { grid-column: 1 / -1; }
.tb-title { font-weight: 600; font-size: 12px; color: var(--el-color-primary); margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px dashed var(--border-default); }
.tb-kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; font-size: 11px; }
.tb-kv > span { color: var(--text-tertiary); }
.tb-kv > b { font-weight: 600; word-break: break-all; }
.tb-kv > b.up { color: var(--el-color-danger); }
.tb-kv > b.down { color: var(--el-color-success); }
.layer-list { display: flex; flex-direction: column; gap: 3px; }
.layer-row {
  display: grid;
  grid-template-columns: 22px 200px 1fr;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 3px;
  font-size: 11px;
  align-items: center;
}
.layer-row:hover { background: rgba(22,119,255,0.05); }
.layer-icon { font-size: 14px; text-align: center; }
.layer-name { font-weight: 600; color: var(--text-secondary); }
.layer-detail { color: var(--text-tertiary); word-break: break-all; }

.ops-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.scan-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 6px;
}

.sc-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
}

.sc-label { color: var(--text-secondary); }

.sc-value { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }

.ops-mf {
  max-width: 400px;
}

.ops-timeline {
  max-height: 400px;
  overflow-y: auto;
}
</style>
