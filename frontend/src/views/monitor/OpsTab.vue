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
// 【v2.9.105】阶段表 + 扫描频率矩阵默认折叠
const phaseTableExpanded = ref(false)
function toggleTradeExpand(orderId: string) {
  if (expandedOrderIds.value.has(orderId)) expandedOrderIds.value.delete(orderId)
  else expandedOrderIds.value.add(orderId)
  expandedOrderIds.value = new Set(expandedOrderIds.value) // trigger reactivity
}
function layerStatusIcon(layer: any): string {
  if (!layer || (typeof layer === 'object' && Object.keys(layer).length === 0)) return '⚪'
  // 后端格式: { detail: "...", applied: true/false, triggered?: bool }
  // 优先看 layer 顶层, 再看 layer.detail (字段能是字符串也能是 dict)
  const top = layer
  const detail = layer.detail
  const detailIsDict = detail && typeof detail === 'object'
  if (top.triggered === true || (detailIsDict && detail.triggered === true)) return '⛔'
  if (top.applied === false || (detailIsDict && detail.applied === false)) return '⏭️'
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
function formatLayerDetail(_key: string, layer: any): string {
  if (!layer) return '无数据'
  const detail = layer.detail !== undefined ? layer.detail : layer
  // 后端格式: { detail: "✅ 未触发 (...)", applied: true } —— detail 是字符串
  if (typeof detail === 'string') return detail || '未触发/无数据'
  if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail)
  if (!detail || typeof detail !== 'object') return '未触发/无数据'
  if (Object.keys(detail).length === 0) return '未触发/无数据'
  // 兜底: dict 提取关键字段
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
  const n = Number(v)
  return Number.isFinite(n) ? (n * 100).toFixed(digits) + '%' : '-'
}
function fmt(v: any, digits = 2): string {
  if (v === undefined || v === null || v === '') return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : '-'
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
  if (typeof v === 'number') return (Number.isNaN(v) || !Number.isFinite(v)) ? '-' : (Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4))))
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
  autoTrades, opsDate, scanConfig,
  timeline, orders, historyData, historyLoading,
  manualTrade, manualQuote,
  cumulativePnl,
  strategyCN,
  // 方法
  manualScan, forceScan, dailySettlement, openTradeAudit,
  fetchAutoTrades, fetchDailyReport,
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
        <div class="at-header"><span>日期/策略</span><span>来源</span><span>操作</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>原因/详情</span></div>
        <template v-for="t in autoTrades" :key="t.order_id">
          <div class="at-row" :class="{ 'auto-trade': t.source === 'auto', 'manual-trade': t.source === 'manual' }">
            <span class="tl-date-strat">
              <span class="tl-date">{{ formatTradeDate(t.trade_date) }} {{ t.time }}</span>
              <span v-if="t.strategy" class="tl-strat">{{ strategyCN(t.strategy) }}</span>
            </span>
            <span><ElTag size="small" :type="t.source === 'auto' ? 'primary' : 'warning'" style="font-size:10px">{{ t.source === 'auto' ? '🤖自动' : '✋手动' }}</ElTag></span>
            <span class="tl-action" :class="t.side === 'buy' ? 'buy' : 'sell'">{{ t.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ t.ts_code }}</span>
            <span class="name">{{ t.stock_name }}</span>
            <span>{{ t.quantity }}股</span>
            <span>¥{{ Number(t.price || 0).toFixed(2) }}</span>
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
                    <template v-if="v !== null && v !== undefined && v !== '' && String(k) !== 'strategy'">
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

      <!-- 【v2.9.105】阶段表 + 扫描频率矩阵 默认折叠 -->
      <div class="st collapsible" @click="phaseTableExpanded = !phaseTableExpanded" style="margin-top:12px">
        📅 交易阶段表 · 扫描频率矩阵
        <span class="collapse-summary">10 个阶段 · 扫描与下单闸锁说明</span>
        <span class="collapse-arrow">{{ phaseTableExpanded ? '▲' : '▼' }}</span>
      </div>
      <template v-if="phaseTableExpanded">
        <div class="phase-doc">
          <div class="pd-section">
            <div class="pd-title">⏰ 完整交易阶段表</div>
            <table class="pd-table">
              <thead>
                <tr><th>阶段</th><th>时间</th><th>扫描</th><th>下单</th><th>说明</th></tr>
              </thead>
              <tbody>
                <tr><td><code>weekend</code></td><td>周六 / 周日</td><td>✅ 低频持仓查</td><td>❌</td><td>调试模式, 60s/轮</td></tr>
                <tr><td><code>deep_night</code></td><td>23:00-08:00</td><td>💤 30min/次</td><td>❌</td><td>极低频</td></tr>
                <tr><td><code>premarket</code></td><td>09:00-09:15</td><td>⏸ 120s/次</td><td>❌</td><td>仅持仓跳空检查</td></tr>
                <tr><td><code>premarket</code></td><td>09:15-09:25</td><td>✅ 60s/次 竞价全市场扫</td><td>❌</td><td>生成今日候选</td></tr>
                <tr><td><code>auction</code></td><td>09:25-09:30</td><td>✅ 竞价</td><td>❌</td><td>集合竞价不接受订单</td></tr>
                <tr class="hi"><td><code>morning</code></td><td>09:30-11:30</td><td>✅✅ 主扫 5min/轮 + 持仓 30s</td><td>✅</td><td>早盘 可开仓</td></tr>
                <tr class="hi-warn"><td><code>lunch</code></td><td>11:30-13:00</td><td>✅✅ 主扫照常跑</td><td>❌</td><td><b>结果被闸锁拦截</b> · A 股午休不接受订单</td></tr>
                <tr class="hi"><td><code>afternoon</code></td><td>13:00-14:30</td><td>✅✅ 主扫 5min/轮 + 持仓 30s</td><td>✅</td><td>午盘 可开仓</td></tr>
                <tr><td><code>late_trading</code></td><td>14:30-15:00</td><td>⚠️ 仅持仓查 3s/次</td><td>⚠️ 只能卖</td><td>尾盘 禁开新仓</td></tr>
                <tr><td><code>after_close</code></td><td>15:05+</td><td>💾 60s/次</td><td>❌</td><td>结算写入 broker_orders</td></tr>
              </tbody>
            </table>
          </div>

          <div class="pd-section">
            <div class="pd-title">🛡️ 下单闸锁设计 · 3 道防线</div>
            <ul class="pd-list">
              <li><b>防线 1</b> <code>scan_loop_runner._scan_loop</code> 主循环按时段降频 · 避免非交易时间点高频驱动</li>
              <li><b>防线 2</b> <code>_scan_loop_trading</code> 尾盘 (14:30+) 禁开新仓 · 只走止损止盈</li>
              <li><b>防线 3</b> <code>execute_signals</code> 最后闸锁 · phase 不在 <code>{MORNING, AFTERNOON, LATE_TRADING}</code> 则拦截下单</li>
            </ul>
            <div class="pd-note">⚠️ 事故案例 6/16 9:28: 手动 <code>scan_once(force=True)</code> 穿越了交易时段检查, 生成 10 笔未开盘时的伪交易. 防线 3 即为后续修复.</div>
          </div>

          <div class="pd-section">
            <div class="pd-title">🍱 lunch 阶段的特殊处理 · 为什么扫描照样跑</div>
            <ul class="pd-list">
              <li><b>数据连续性</b> 午休价格走势对下午开盘有参考意义</li>
              <li><b>scanner 暖机</b> 避免 13:00 启动延迟错过开盘 · 扫描器持续保鲜</li>
              <li><b>交易所规则</b> A 股 11:30-13:00 撮合停止, 服务器接到订单也不会成交</li>
            </ul>
            <div class="pd-note">表现: 你会看到日志 <code>[EXEC] 非交易时间(lunch), 跳过 N 个信号的下单</code> · timeline 写入 blocked 但不影响实盘.</div>
          </div>

          <div class="pd-section">
            <div class="pd-title">🎯 数据采集 vs 下单 · 解耦原则</div>
            <ul class="pd-list">
              <li>扫描产生信号 = "判断市场状态" · 不受交易时间限制</li>
              <li>下单 = "执行行动" · 必须在 morning/afternoon/late_trading 三个阶段</li>
              <li>何时变 blocked 仅仅是 UI 可见性 · 未在账户产生资金变动</li>
            </ul>
          </div>
        </div>
      </template>

      <!-- 手动下单 -->
      <div class="st" style="margin-top:16px">🔧 手动下单</div>
      <div class="mf ops-mf">
        <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
        <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
        <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
        <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
        <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price != null ? Number(manualQuote.price).toFixed(2) : '-' }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ Number(manualQuote.pct_chg || 0).toFixed(2) }}%</span></div>
      </div>

      <!-- 交易时间线 -->
      <div class="st" style="margin-top:16px">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ Number(cumulativePnl || 0).toFixed(0) }}</span>
        <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElButton size="small" @click="loadHistory" :loading="historyLoading">📜 回放</ElButton></div>
      </div>
      <div v-if="!timeline.length && !historyData.length" class="empty">暂无交易</div>
      <div v-else class="ops-timeline">
        <div v-if="historyData.length" class="history-tag">📜 {{ formatFullDate(opsDate) }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><template v-if="item.action !== 'blocked'"><span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price != null ? Number(item.price).toFixed(2) : '-' }}</span><span v-if="item.action==='sell' && item.profit_pct != null" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ Number(item.profit_pct).toFixed(1) }}%</span><span v-if="item.action==='sell' && item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ Number(item.profit_amount).toFixed(0) }}</span></template><span v-else class="tl-blocked-reason">{{ item.reason }}</span></div>
      </div>

      <!-- 历史订单 -->
      <div v-if="orders.length" class="st" style="margin-top:16px">📋 历史订单 ({{ orders.length }})</div>
      <div v-if="orders.length" class="ops-timeline">
        <div v-for="o in orders.slice(0, 50)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ formatTradeDate(o.trade_date) }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price != null ? Number(o.filled_price).toFixed(2) : '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.st.collapsible { cursor: pointer; user-select: none; &:hover { color: var(--el-color-primary); } }
.collapse-arrow { font-size: 9px; color: var(--text-tertiary); margin-left: 4px; }
.collapse-summary { font-size: 10px; color: var(--text-tertiary); margin-left: 6px; font-weight: 400; }

/* 【v2.9.105】阶段表 + 扫描频率矩阵 文档样式 */
.phase-doc { margin: 8px 0 12px; padding: 10px 12px; background: var(--bg-tertiary, rgba(0,0,0,0.02)); border-radius: 6px; border: 1px solid var(--border-light, rgba(0,0,0,0.05)); }
.pd-section { margin-bottom: 14px; }
.pd-section:last-child { margin-bottom: 0; }
.pd-title { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.pd-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.pd-table th { text-align: left; padding: 5px 6px; background: var(--bg-base, rgba(0,0,0,0.04)); color: var(--text-secondary); font-weight: 600; border-bottom: 1px solid var(--border-default, rgba(0,0,0,0.08)); }
.pd-table td { padding: 5px 6px; border-bottom: 1px solid var(--border-light, rgba(0,0,0,0.04)); vertical-align: top; }
.pd-table td code { font-size: 10px; padding: 1px 4px; background: var(--bg-hover, rgba(0,0,0,0.06)); border-radius: 3px; font-family: ui-monospace, SFMono-Regular, Monaco, Consolas, monospace; }
.pd-table tr.hi td { background: rgba(34,197,94,0.06); }
.pd-table tr.hi-warn td { background: rgba(250,173,20,0.08); }
.pd-list { margin: 4px 0 0; padding-left: 18px; font-size: 11px; line-height: 1.7; color: var(--text-secondary); }
.pd-list li { margin-bottom: 2px; }
.pd-list li code { font-size: 10px; padding: 1px 4px; background: var(--bg-hover, rgba(0,0,0,0.06)); border-radius: 3px; font-family: ui-monospace, SFMono-Regular, Monaco, Consolas, monospace; }
.pd-note { margin-top: 5px; padding: 5px 8px; background: rgba(245,158,11,0.06); border-left: 2px solid var(--el-color-warning, #faad14); border-radius: 0 4px 4px 0; font-size: 11px; color: var(--text-secondary); line-height: 1.5; }
.pd-note code { font-size: 10px; padding: 1px 4px; background: var(--bg-hover, rgba(0,0,0,0.06)); border-radius: 3px; font-family: ui-monospace, SFMono-Regular, Monaco, Consolas, monospace; }

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

.tl-date-strat { display: flex; flex-direction: column; gap: 1px; }
.tl-date-strat .tl-date { font-size: 11px; color: var(--text-tertiary); }
.tl-date-strat .tl-strat { font-size: 11px; }

.at-header, .at-row { display: grid; grid-template-columns: 80px 50px 28px 72px 56px 50px 60px 1fr; gap: 4px; padding: 3px 0; align-items: center; }

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
