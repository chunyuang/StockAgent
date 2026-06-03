<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控
 * 
 * 逻辑已拆到 useScannerMonitor.ts composable
 * 此文件只负责: 调用composable + 渲染template
 * 【v2.9.74: 清理26个未使用解构变量, 消除TS6133】
 */
import { provide } from 'vue'
import { useScannerMonitor } from './useScannerMonitor'
import { SCANNER_MONITOR_KEY } from './scannerMonitorInject'
import ReviewTab from './ReviewTab.vue'
import OpsTab from './OpsTab.vue'
import PremarketTab from './PremarketTab.vue'
import SentimentTab from './SentimentTab.vue'
import GuideTab from './GuideTab.vue'
import HistoryTab from './HistoryTab.vue'
import ScanTraceTab from './ScanTraceTab.vue'

const monitorData = useScannerMonitor()
provide(SCANNER_MONITOR_KEY, monitorData)

// 在模板中使用的变量仍需解构(vue-tsc要求)
const {
  loading, autoRefresh,
  status, signals, positions,
  signalFilter, filteredSignals,
  isRunning, accountInfo, positionRatio, totalPnl,
  circuitBreakerPaused, focusIndex, emergencyLiquidating,
  activeTab, reviewTab,
  strategies,
  editingStrategy, editDialogVisible, editTab, editParams, editRiskParams, saving,
  sigRemaining,
  dailyReport, dailyReportData, dailyReportVisible, weeklyReportVisible,
  premarketSignals,
  reviewLoading,
  monthlyReviewData, weeklyReviewData, weeklyReportData,
  deviationData, closedLoopData,
  signalTraceVisible, tradeDetailVisible, tradeDetailData,
  tradeAuditVisible, tradeAuditData,
  confirmVisible, confirmLoading, confirmData,
  manualTrade, trailEditPct, trailSaving,
  tradeMode, replayDate, replayDateInput,
  replayDateVisible,
  startScanner, stopScanner,
  manualScan, forceScan, quickBuy, quickSell, fetchReviewData,
  // sentiment sub-composable
  openTradeDetail,
  runBacktest, saveParamSnapshot,
  setTrailingStop,
  showConfirm: _showConfirm, handleConfirm, emergencyLiquidate,
  saveStrategy,
  layerLabel,
  posSort, sortedPositions,
  strategyCN, strategyMeta, normalizePct, formatSlTp, formatRemaining,
  themeStore, modeMeta,
  onModeChange, confirmReplay, cancelReplay, dryRun,
  // 【v2.9.71: WS连接状态】
  wsStatus, wsIsConnected, wsRetryCount,
  stratCollapsed, stratSectionCollapsed, toggleStrat, toggleStrategy,
  openEditDialog, factorLabel,
  scanTraceVisible, scanTraceData, scanTraceCode,
  layerDebugVisible, layerDebugData,
  compareVisible, compareData,
  openScanTrace, signalStatusTag,
  formatLayerTrace, formatDecisionDetail,
  reviewDate, reviewHero, reviewForward,
  backtestRunning, liveBacktestDiff, executionQuality,
  tradeAttributions, paramDriftData, factorEffectData,
  disciplineCheck,
} = useScannerMonitor()
</script>
<template>
  <div class="mm" :class="{ dark: themeStore.isDark }">
    <!-- 顶部状态栏(一行: 风控+状态+资产+操作) -->
    <div class="mm-header">
      <div class="hh-left">
        <div class="hh-status" :class="{ running: isRunning, stopped: !isRunning }"><span class="dot"></span><span>{{ isRunning ? '扫描中' : '已停止' }}</span></div>
        <ElSelect v-model="tradeMode" size="small" style="width:96px" @change="onModeChange">
          <ElOption v-for="(m, key) in modeMeta" :key="key" :value="key" :label="m.emoji + ' ' + m.text" />
        </ElSelect>
        <ElTag v-if="tradeMode === 'replay' && replayDate" type="warning" size="small">🔄 {{ replayDateInput }}</ElTag>
        <ElTag v-if="circuitBreakerPaused" type="danger" size="small">⚠️熔断</ElTag>
        <div v-if="status?.data_sources?.length" class="ds-indicator">
          <span v-for="ds in (status?.data_sources || [])" :key="ds.name" class="ds-dot" :class="{ ok: ds.available, err: !ds.available }">{{ ds.name === 'eastmoney' ? '东财' : ds.name === 'biying' ? '必盈' : ds.name }}</span>
        </div>
        <!-- 【v2.9.71: WS连接状态指示器】 -->
        <div class="ws-indicator" :class="wsIsConnected ? 'ws-ok' : wsStatus === 'reconnecting' ? 'ws-warn' : 'ws-off'" :title="`WebSocket: ${wsStatus}${wsRetryCount > 0 ? ' (重试' + wsRetryCount + ')' : ''}`">
          <span class="ws-dot"></span>
          <span class="ws-text">{{ wsIsConnected ? 'WS' : wsStatus === 'reconnecting' ? '重连' : '离线' }}</span>
        </div>
      </div>
      <div class="hh-account" v-if="status">
        <span class="ha">资产<span class="hv">{{ (accountInfo.total_assets / 10000).toFixed(1) }}万</span></span>
        <span class="ha">可用<span class="hv">{{ (accountInfo.available_cash / 10000).toFixed(1) }}万</span></span>
        <span class="ha">仓位<span class="hv">{{ positionRatio }}%</span></span>
        <span class="ha">盈亏<span class="hv" :class="totalPnl >= 0 ? 'up' : 'down'">{{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl.toFixed(0) }}</span></span>
      </div>
      <div class="hh-actions">
        <ElButton v-if="!isRunning" type="success" size="small" @click="startScanner">▶ 启动</ElButton>
        <ElButton v-else type="danger" size="small" @click="stopScanner">⏹ 停止</ElButton>
        <ElButton size="small" :loading="loading" @click="manualScan" :disabled="!isRunning">📡 扫描</ElButton>
        <button class="emergency-btn-inline" :class="{ disabled: !isRunning || emergencyLiquidating }" @click="isRunning && !emergencyLiquidating && emergencyLiquidate()" :disabled="!isRunning || emergencyLiquidating" title="紧急平仓">🚨</button>
        <ElSwitch v-model="autoRefresh" size="small" active-text="自动" inactive-text="" />
        <span class="dark-toggle" @click="themeStore.toggleTheme()">{{ themeStore.isDark ? '☀️' : '🌙' }}</span>
      </div>
    </div>

    <!-- Tab 导航栏 -->
    <div class="mm-tab-bar">
      <button :class="['tab-btn', activeTab === 'guide' ? 'active' : '']" @click="activeTab = 'guide'">
        <span class="tab-icon">📖</span>
        <span class="tab-text"><span class="tab-label">指南</span><span class="tab-desc">架构·策略·操作</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'trading' ? 'active' : '']" @click="activeTab = 'trading'">
        <span class="tab-icon">🎯</span>
        <span class="tab-text"><span class="tab-label">实盘</span><span class="tab-desc">信号·持仓·交易</span></span>
        <span v-if="filteredSignals.length" class="tab-badge">{{ filteredSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'premarket' ? 'active' : '']" @click="activeTab = 'premarket'">
        <span class="tab-icon">🌅</span>
        <span class="tab-text"><span class="tab-label">盘前竞价</span><span class="tab-desc">9:00-9:25</span></span>
        <span v-if="premarketSignals.length" class="tab-badge">{{ premarketSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'scan-trace' ? 'active' : '']" @click="activeTab = 'scan-trace'">
        <span class="tab-icon">🔍</span>
        <span class="tab-text"><span class="tab-label">扫描追踪</span><span class="tab-desc">9层漏斗·执行链</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'review' ? 'active' : '']" @click="activeTab = 'review'">
        <span class="tab-icon">📋</span>
        <span class="tab-text"><span class="tab-label">复盘</span><span class="tab-desc">日/周·归因·对比</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'risk' ? 'active' : '']" @click="activeTab = 'risk'">
        <span class="tab-icon">🛡️</span>
        <span class="tab-text"><span class="tab-label">风控</span><span class="tab-desc">止损·矩阵</span></span>
        <span v-if="positions.some(p => p.risk_level === 'high')" class="tab-badge-danger">!</span>
      </button>
      <button :class="['tab-btn', activeTab === 'sentiment' ? 'active' : '']" @click="activeTab = 'sentiment'">
        <span class="tab-icon">🌡️</span>
        <span class="tab-text"><span class="tab-label">情绪</span><span class="tab-desc">周期·曲线·矩阵</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'history' ? 'active' : '']" @click="activeTab = 'history'">
        <span class="tab-icon">📜</span>
        <span class="tab-text"><span class="tab-label">历史</span><span class="tab-desc">时间线·订单</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'ops' ? 'active' : '']" @click="activeTab = 'ops'">
        <span class="tab-icon">⚙️</span>
        <span class="tab-text"><span class="tab-label">运维</span><span class="tab-desc">系统·操作</span></span>
      </button>
    </div>

    <!-- 📖 指南Tab -->
    <GuideTab v-if="activeTab === 'guide'" />

    <!-- 3列主布局 -->
    <div v-if="activeTab === 'trading'" class="mm-body">
      <!-- 左列: 策略控制 -->
      <div class="mm-left">
        <div class="st cp" @click="stratSectionCollapsed = !stratSectionCollapsed">🎛️ 策略控制 <span class="sc-arrow">{{ stratSectionCollapsed ? '▶' : '▼' }}</span></div>
        <template v-if="!stratSectionCollapsed">
        <div v-for="s in strategies" :key="s.id" class="sc" :class="{ disabled: !s.enabled }">
          <div class="sc-top cp" @click="toggleStrat(s.id)"><span class="sc-icon">{{ strategyMeta[s.id]?.icon || '📋' }}</span><span class="sc-name">{{ s.name }}</span><ElSwitch :model-value="s.enabled" @change="toggleStrategy(s.id, $event)" size="small" @click.stop /><span class="sc-arrow">{{ stratCollapsed[s.id] ? '▶' : '▼' }}</span></div>
          <div v-if="!stratCollapsed[s.id]">
            <div class="sc-desc">{{ strategyMeta[s.id]?.desc || '' }}</div>
            <div class="sc-params"><div v-for="p in (s.paramDescriptions || []).slice(0, 3)" :key="p.key" class="pm"><span class="pk">{{ p.label }}</span><span class="pv">{{ p.displayValue }}{{ p.unit }}</span></div></div>
            <ElButton size="small" text type="primary" @click="openEditDialog(s)">⚙️ 编辑</ElButton>
          </div>
        </div>
        </template>
        <div class="st mt-10" style="font-size:11px;color:var(--text-tertiary)">更多操作见 <span class="cp" style="color:var(--el-color-primary)" @click="activeTab='ops'">⚙️ 运维Tab</span></div>

      </div>

      <!-- 中列: 信号+行情 -->
      <div class="mm-center">
        <div class="st">🎯 活跃信号 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag v-for="f in [{k:'all',l:'全部'},{k:'halfway_chase',l:'半路'},{k:'first_limit_up',l:'首板'},{k:'limit_down_qiao',l:'跌停'},{k:'anomaly',l:'异动'}]" :key="f.k" size="small" :type="signalFilter===f.k?'primary':'info'" class="cp" @click="signalFilter=f.k">{{ f.l }}</ElTag></div> <ElBadge :value="filteredSignals.length" :max="99" style="margin-left:4px" /></div>
        <div class="sl">
          <div v-if="!signals.length" class="empty">启动后扫描获取信号</div>
          <div v-for="sig in filteredSignals" :key="sig.ts_code + sig.strategy" class="sig-row" :title="`${sig.ts_code} ${sig.stock_name}\n策略: ${sig.strategy_name}\n量比: ${sig.volume_ratio?.toFixed(1) || '-'}\n换手: ${sig.turnover_rate?.toFixed(1) || '-'}%\n${sig.reason}`">
            <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="min-width:52px;text-align:center">{{ sig.strategy_name }}</ElTag><ElTag v-if="sig.signal_status === 'executed'" size="small" type="success">已买</ElTag><ElTag v-if="sig.signal_status === 'skipped'" size="small" type="warning">跳过</ElTag><ElTag v-if="sig.signal_status === 'expired'" size="small" type="info">过期</ElTag><span class="code">{{ sig.ts_code }}</span><span class="name">{{ sig.stock_name }}</span><span v-if="sig.signal_status === 'new' && sigRemaining(sig) >= 0" class="expire-tag" :class="{ urgent: sigRemaining(sig) < 60000 }">⏱{{ formatRemaining(sigRemaining(sig)) }}</span><span :class="sig.pct_chg >= 0 ? 'up' : 'down'" class="pct ml-auto" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span><ElButton v-if="!dryRun && sig.signal_status === 'new'" size="small" type="danger" plain @click="quickBuy(sig)" class="btn-xs">买</ElButton><ElButton v-if="sig.decision_detail" size="small" type="info" plain @click="openTradeDetail(sig.ts_code)" class="btn-xs">🔍</ElButton><ElButton v-if="sig.layer_trace" size="small" type="warning" plain @click="openScanTrace(sig.ts_code)" class="btn-xs">🧪</ElButton>
          </div>
        </div>

      </div>

      <!-- 右列: 持仓 -->
      <div class="mm-right">
        <div class="st">📊 持仓监控 <ElBadge :value="positions.length" :max="99" style="margin-left:4px" /><ElSelect v-model="posSort" size="small" style="width:80px;margin-left:auto"><ElOption label="盈亏" value="profit" /><ElOption label="市值" value="cost" /><ElOption label="策略" value="strategy" /><ElOption label="时间" value="time" /></ElSelect></div>
        <div class="sl">
          <div v-if="!positions.length" class="empty">暂无持仓</div>
          <div v-for="(pos, idx) in sortedPositions" :key="pos.ts_code" class="pos-card" :class="{ 'pos-focused': idx === focusIndex }">
            <div class="pos-top"><ElTag size="small" :color="strategyMeta[pos.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px;min-width:48px;text-align:center">{{ pos.strategy_name || strategyCN(pos.strategy) }}</ElTag><span class="code">{{ pos.ts_code }}</span><span class="name">{{ pos.stock_name }}</span><MiniKline :tsCode="pos.ts_code" :compact="true" :days="5" /><span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span><span class="mini-bar"><span class="mini-bar-fill" :style="{ width: Math.min(Math.abs(pos.profit_pct) / 10 * 100, 100) + '%' }" :class="pos.profit_pct >= 0 ? 'bar-up' : 'bar-down'"></span></span><span v-if="pos.today_buy > 0" class="t1-tag">T+1</span><ElButton size="small" type="danger" plain @click="quickSell(pos)" :disabled="pos.available_qty <= 0" class="btn-xs ml-auto">卖出</ElButton><ElButton size="small" type="info" plain @click="openTradeDetail(pos.ts_code)" class="btn-xs">详情</ElButton></div>
            <div class="pos-info"><span>{{ pos.shares }}股</span><span>成本¥{{ pos.cost_price.toFixed(2) }}</span><span>现价¥{{ pos.current_price.toFixed(2) }}</span><span v-if="pos.market_value" class="mv">市值{{ (pos.market_value / 10000).toFixed(1) }}万</span><span v-if="pos.profit_amount != null" :class="pos.profit_amount >= 0 ? 'up' : 'down'" class="pamt">{{ pos.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(pos.profit_amount).toFixed(0) }}</span></div>
            <div class="pos-prices-row">
              <span v-if="pos.stop_loss_price" class="pp-sl">止损¥{{ pos.stop_loss_price.toFixed(2) }}</span>
              <span v-if="pos.take_profit_price" class="pp-tp">止盈¥{{ pos.take_profit_price.toFixed(2) }}</span>
              <span v-if="pos.trailing_stop?.activated" class="pp-trail">📍追踪¥{{ pos.trailing_stop.stop_price?.toFixed(2) }}({{ (pos.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%)</span>
              <span v-if="pos.risk_level && pos.risk_level !== 'normal'" class="pp-risk" :class="pos.risk_level">{{ {high:'🔴高风险',elevated:'🟡较高',low:'🟢低风险'}[pos.risk_level] || pos.risk_level }}</span>
            </div>
            <div v-if="pos.stop_loss_pct != null" class="pos-risk-row">
              <div class="risk-track"><div class="risk-fill" :style="{ width: Math.max(0, Math.min(100, (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)) / (normalizePct(pos.stop_loss_pct, 3) + normalizePct(pos.take_profit_pct, 7)) * 100)) + '%' }" :class="pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 1 ? 'danger' : pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 ? 'warning' : 'safe'"></div></div>
              <div class="risk-labels-row"><span class="rl stop">止损{{ formatSlTp(pos.stop_loss_pct, 3) }}</span><span v-if="pos.trailing_stop?.activated" class="rl trail">📍{{ (pos.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%</span><span class="rd" :class="{ danger: pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 }">距止损{{ (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)).toFixed(1) }}%</span><span class="rl profit">止盈{{ formatSlTp(pos.take_profit_pct, 7) }}</span></div>
            </div>
          </div>
        </div>

        <!-- 盈亏曲线 → 已移至绩效Tab -->

      </div>
    </div>

    <!-- 策略编辑弹窗 -->
    <ElDialog v-model="editDialogVisible" :title="`编辑 ${editingStrategy?.name}`" width="560px" :close-on-click-modal="false">
      <ElTabs v-model="editTab">
        <ElTabPane label="选股参数" name="params"><div v-for="p in editingStrategy?.paramDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElInputNumber v-model="editParams[p.key]" :min="p.min" :max="p.max" :step="p.step" :precision="p.step < 1 ? 2 : 1" size="small" controls-position="right" style="width:160px" /></div></ElTabPane>
        <ElTabPane label="风控参数" name="risk"><div v-for="p in editingStrategy?.riskDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElInputNumber v-model="editRiskParams[p.key]" :min="p.min" :max="p.max" :step="p.step" :precision="p.step < 1 ? 2 : 1" size="small" controls-position="right" style="width:160px" /></div></ElTabPane>
      </ElTabs>
      <template #footer><ElButton @click="editDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="saveStrategy">保存</ElButton></template>
    </ElDialog>

    <!-- 交易详情弹窗 — 结构化卡片 -->
    <ElDialog v-model="tradeDetailVisible" :title="`🔍 交易审查 — ${tradeDetailData?.ts_code || ''} ${tradeDetailData?.stock_name || tradeDetailData?.buy?.stock_name || tradeDetailData?.sell?.stock_name || ''}`" width="780px">
      <div v-if="tradeDetailData" class="td2">
        <!-- 买入决策 -->
        <div class="td2-sec"><div class="td2-title">📥 买入决策</div>
          <template v-if="tradeDetailData.buy">
            <div class="td2-grid">
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ tradeDetailData.buy.time }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ tradeDetailData.buy.price?.toFixed(2) }}</div></div>
              <div class="td2-card"><div class="td2-label">📊 数量</div><div class="td2-val">{{ tradeDetailData.buy.shares }}股</div></div>
              <div class="td2-card"><div class="td2-label">🎯 策略</div><div class="td2-val"><ElTag size="small" :color="strategyMeta[tradeDetailData.buy.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(tradeDetailData.buy.strategy) }}</ElTag></div></div>
            </div>
            <div class="td2-reason">📋 选股原因: {{ tradeDetailData.buy.reason }}</div>
            <template v-if="tradeDetailData.buy.decision_detail">
              <div class="td2-chain">
                <template v-if="tradeDetailData.buy.decision_detail.filter_pipeline">
                  <div class="td2-chain-title">🔍 9层筛选管道</div>
                  <div class="td2-pipeline">
                    <div v-for="(applied, layer) in tradeDetailData.buy.decision_detail.filter_pipeline.layers_applied || {}" :key="layer" class="td2-pipe-step" :class="{ passed: applied }">
                      <span class="td2-pipe-icon">{{ applied ? '✅' : '⏭️' }}</span>
                      <span class="td2-pipe-name">{{ layerLabel(layer) }}</span>
                      <span class="td2-pipe-detail">{{ tradeDetailData.buy.decision_detail.filter_pipeline.layer_details?.[layer] || (applied ? '通过' : '跳过') }}</span>
                    </div>
                  </div>
                </template>
                <template v-if="tradeDetailData.buy.decision_detail.execution">
                  <div class="td2-chain-title">⚡ 执行决策</div>
                  <div class="td2-grid">
                    <div class="td2-card sm"><div class="td2-label">仓位比例</div><div class="td2-val">{{ ((tradeDetailData.buy.decision_detail.execution.position_ratio || 0) * 100).toFixed(0) }}%</div></div>
                    <div class="td2-card sm"><div class="td2-label">可用资金</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.available_cash || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">买入金额</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.total_cost || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">成交价</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.filled_price || 0).toFixed(2) }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.sentiment"><div class="td2-label">情绪</div><div class="td2-val">{{ tradeDetailData.buy.decision_detail.execution.sentiment.score?.toFixed(0) }}→{{ tradeDetailData.buy.decision_detail.execution.sentiment.period }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.circuit_breaker"><div class="td2-label">熔断</div><div class="td2-val" :class="tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? 'down' : ''">{{ tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? '⛔暂停' : '✅正常' }}</div></div>
                  </div>
                </template>
                <template v-if="tradeDetailData.buy.decision_detail.factors && Object.values(tradeDetailData.buy.decision_detail.factors).some(v => v !== 0 && v !== null)">
                  <div class="td2-chain-title">📈 关键因子</div>
                  <div class="td2-factors">
                    <div v-for="(v, k) in tradeDetailData.buy.decision_detail.factors" :key="k" v-show="v !== 0 && v !== null" class="td2-factor"><span class="td2-fk">{{ factorLabel(k) }}</span><span class="td2-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
                  </div>
                </template>
              </div>
            </template>
          </template>
          <div v-else class="td2-empty">暂无买入记录</div>
        </div>
        <!-- 卖出决策 -->
        <div class="td2-sec"><div class="td2-title">📤 卖出决策</div>
          <template v-if="tradeDetailData.sell">
            <div class="td2-grid">
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ tradeDetailData.sell.time }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ tradeDetailData.sell.price?.toFixed(2) }}</div></div>
              <div class="td2-card"><div class="td2-label">📊 盈亏</div><div class="td2-val" :class="tradeDetailData.sell.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.sell.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.sell.profit_pct?.toFixed(2) }}%</div></div>
              <div class="td2-card"><div class="td2-label">💵 盈亏额</div><div class="td2-val" :class="(tradeDetailData.sell.profit_amount || 0) >= 0 ? 'up' : 'down'">¥{{ (tradeDetailData.sell.profit_amount || 0).toFixed(0) }}</div></div>
            </div>
            <div class="td2-reason">📋 卖出原因: {{ tradeDetailData.sell.reason }}</div>
            <template v-if="tradeDetailData.sell.decision_detail">
              <div class="td2-chain">
                <div class="td2-grid">
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.cost_price"><div class="td2-label">成本价</div><div class="td2-val">¥{{ tradeDetailData.sell.decision_detail.cost_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.current_price"><div class="td2-label">卖出价</div><div class="td2-val">¥{{ tradeDetailData.sell.decision_detail.current_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_pct"><div class="td2-label">止损线</div><div class="td2-val text-stock-up">{{ tradeDetailData.sell.decision_detail.stop_loss_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_pct"><div class="td2-label">止盈线</div><div class="td2-val text-stock-down">{{ tradeDetailData.sell.decision_detail.take_profit_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.sell.decision_detail.stop_loss_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ tradeDetailData.sell.decision_detail.take_profit_price?.toFixed(2) }}</div></div>
                </div>
              </div>
            </template>
          </template>
          <div v-else class="td2-empty">暂无卖出记录</div>
        </div>
        <!-- 当前持仓 -->
        <div class="td2-sec" v-if="tradeDetailData.position"><div class="td2-title">📊 当前持仓</div>
          <div class="td2-grid">
            <div class="td2-card"><div class="td2-label">持仓</div><div class="td2-val">{{ tradeDetailData.position.shares }}股</div></div>
            <div class="td2-card"><div class="td2-label">成本</div><div class="td2-val">¥{{ tradeDetailData.position.cost_price?.toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">现价</div><div class="td2-val">¥{{ tradeDetailData.position.current_price?.toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">盈亏</div><div class="td2-val" :class="tradeDetailData.position.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.position.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.position.profit_pct?.toFixed(2) }}%</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_pct"><div class="td2-label">止损</div><div class="td2-val text-stock-up">{{ formatSlTp(tradeDetailData.position.stop_loss_pct, 3) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_pct"><div class="td2-label">止盈</div><div class="td2-val text-stock-down">{{ formatSlTp(tradeDetailData.position.take_profit_pct, 7) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.position.stop_loss_price?.toFixed(2) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ tradeDetailData.position.take_profit_price?.toFixed(2) }}</div></div>
          </div>
          <!-- 追踪止损 -->
          <div v-if="tradeDetailData.position.trailing_stop" class="td2-trail-section">
            <div class="td2-chain-title">📍 追踪止损</div>
            <div class="td2-grid">
              <div class="td2-card sm"><div class="td2-label">状态</div><div class="td2-val" :class="tradeDetailData.position.trailing_stop.activated ? 'up' : ''">{{ tradeDetailData.position.trailing_stop.activated ? '✅已激活' : '⏸未激活' }}</div></div>
              <div class="td2-card sm"><div class="td2-label">比例</div><div class="td2-val">{{ (tradeDetailData.position.trailing_stop.trailing_stop_pct * 100).toFixed(1) }}%</div></div>
              <div class="td2-card sm"><div class="td2-label">最高价</div><div class="td2-val">¥{{ tradeDetailData.position.trailing_stop.high_price?.toFixed(2) }}</div></div>
              <div class="td2-card sm"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.position.trailing_stop.stop_price?.toFixed(2) }}</div></div>
            </div>
            <div class="td2-trail-ctrl">
              <ElInputNumber v-model="trailEditPct" :min="1" :max="20" :step="0.5" :precision="1" size="small" style="width:110px" />
              <span style="font-size:12px;color:var(--text-tertiary)">%回撤</span>
              <ElButton size="small" type="primary" @click="setTrailingStop(tradeDetailData.ts_code, true)" :loading="trailSaving">激活</ElButton>
              <ElButton v-if="tradeDetailData.position.trailing_stop.activated" size="small" @click="setTrailingStop(tradeDetailData.ts_code, false)" :loading="trailSaving">停用</ElButton>
            </div>
          </div>
          <div v-else class="td2-trail-section">
            <div class="td2-chain-title">📍 追踪止损</div>
            <div class="td2-trail-ctrl">
              <ElInputNumber v-model="trailEditPct" :min="1" :max="20" :step="0.5" :precision="1" size="small" style="width:110px" />
              <span style="font-size:12px;color:var(--text-tertiary)">%回撤</span>
              <ElButton size="small" type="primary" @click="setTrailingStop(tradeDetailData.ts_code, true)" :loading="trailSaving">激活追踪止损</ElButton>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">无数据</div>
    </ElDialog>

    <!-- 审查弹窗 -->
    <ElDialog v-model="tradeAuditVisible" title="🔍 全部交易审查" width="800px">
      <div v-if="tradeAuditData.length" class="al"><div class="ah"><span>股票</span><span>策略</span><span>买入</span><span>卖出</span><span>盈亏</span><span>状态</span></div><div v-for="t in tradeAuditData" :key="t.ts_code" class="ar" @click="openTradeDetail(t.ts_code); tradeAuditVisible = false"><span class="code">{{ t.ts_code }}</span><span><ElTag size="small" type="info">{{ strategyCN(t.strategy) }}</ElTag></span><span>{{ t.buy_time }} {{ t.buy_price?.toFixed(2) }}</span><span>{{ t.sell_time || '-' }} {{ t.sell_price?.toFixed(2) || '-' }}</span><span :class="t.profit_pct !== null && t.profit_pct >= 0 ? 'up' : 'down'">{{ t.profit_pct !== null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(2) + '%' : '-' }}</span><span class="text-tertiary-sm">{{ t.status }}</span></div></div>
      <div v-else class="empty">暂无交易记录</div>
    </ElDialog>
    

    

    
    <!-- 回放日期弹窗 -->
    <ElDialog v-model="replayDateVisible" title="🔄 回放模式" width="380px" :close-on-click-modal="false">
      <div style="margin-bottom:12px;font-size:14px">选择要回放的交易日期，将使用历史数据重放扫描：</div>
      <ElDatePicker v-model="replayDateInput" type="date" placeholder="选择回放日期" value-format="YYYY-MM-DD" style="width:100%" :disabled-date="(d: Date) => d > new Date()" />
      <template #footer><ElButton @click="cancelReplay">取消</ElButton><ElButton type="primary" @click="confirmReplay" :disabled="!replayDateInput">确认回放</ElButton></template>
    </ElDialog>

    <!-- 【P1-7】交易确认弹窗 -->
    <ElDialog v-model="confirmVisible" :title="confirmData.title" width="420px" :close-on-click-modal="false">
      <div style="font-size:14px;line-height:1.8;white-space:pre-line">{{ confirmData.message }}</div>
      <template #footer><ElButton @click="confirmVisible = false" :disabled="confirmLoading">取消</ElButton><ElButton type="danger" :loading="confirmLoading" @click="handleConfirm">确认执行</ElButton></template>
    </ElDialog>

    

    
    <!-- ==================== 🌅 盘前竞价Tab ==================== -->
    <PremarketTab v-if="activeTab === 'premarket'" />

    <!-- ==================== 🔍 扫描追踪Tab ==================== -->
    <ScanTraceTab v-if="activeTab === 'scan-trace'" />

    <!-- ==================== 📋 复盘Tab (专业版) ==================== -->
    <ReviewTab :visible="activeTab === 'review'" :strategyCN="strategyCN" :strategyMeta="strategyMeta"
      :reviewTab="reviewTab" :reviewLoading="reviewLoading" :reviewDate="reviewDate"
      :reviewHero="reviewHero" :reviewForward="reviewForward"
      :dailyReportData="dailyReportData" :weeklyReportData="weeklyReportData"
      :weeklyReviewData="weeklyReviewData" :monthlyReviewData="monthlyReviewData"
      :deviationData="deviationData" :closedLoopData="closedLoopData"
      :tradeAttributions="tradeAttributions" :paramDriftData="paramDriftData"
      :factorEffectData="factorEffectData" :disciplineCheck="disciplineCheck"
      :executionQuality="executionQuality" :liveBacktestDiff="liveBacktestDiff"
      :backtestRunning="backtestRunning"
      @update:reviewTab="reviewTab = $event as 'daily' | 'weekly' | 'monthly'" @update:reviewDate="reviewDate = $event"
      @fetchReviewData="fetchReviewData" @runBacktest="runBacktest"
      @saveParamSnapshot="saveParamSnapshot"
    />
    <!-- ==================== 🛡️ 风控Tab ==================== -->
    <div v-if="activeTab === 'risk'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <PositionRiskMatrix />
      </div>
    </div>

    <!-- ==================== 🌡️ 情绪Tab ==================== -->
    <SentimentTab v-if="activeTab === 'sentiment'" />

    <!-- ==================== 📜 历史Tab ==================== -->
    <HistoryTab v-if="activeTab === 'history'" />

    <OpsTab v-if="activeTab === 'ops'" />

    <!-- 【V50.1】信号链路追踪面板(可收起, 跨Tab) -->
    <div v-if="signalTraceVisible" class="mm-trace">
      <SignalTracePanel />
    </div>

    <!-- P2-10: 键盘快捷键 -->
    <KeyboardShortcuts
      @force-scan="forceScan"
      @manual-buy="() => { manualTrade.ts_code = ''; const input = $refs.codeInput as any; input?.focus() }"
      @sell-selected="() => { if (focusIndex >= 0 && focusIndex < sortedPositions.length) quickSell(sortedPositions[focusIndex]) }"
      @emergency-liquidate="emergencyLiquidate"
      @toggle-strategy="(i: number) => { const keys = ['halfway_chase','first_limit_up','dragon_head','limit_down_qiao']; const s = strategies.find((x: any) => x.id === keys[i]); if (s) toggleStrat(s.id) }"
      @focus-prev="() => { if (focusIndex > 0) focusIndex-- }"
      @focus-next="() => { if (focusIndex < sortedPositions.length - 1) focusIndex++ }"
      @show-detail="() => { if (focusIndex >= 0 && focusIndex < sortedPositions.length) openTradeDetail(sortedPositions[focusIndex].ts_code) }"
    />

  </div>
</template>
<style scoped lang="scss">
.mm { height: 100%; display: flex; flex-direction: column; background: var(--bg-base); overflow: hidden; min-width: 0; }

.mm-header { display: flex; align-items: center; gap: 8px; padding: 5px 12px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; min-width: 0; overflow-x: auto; }

.hh-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }

.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }

.hh-status.running .dot { background: var(--stock-down); animation: pulse 1.5s infinite; }

.hh-status.stopped .dot { background: var(--text-tertiary); }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.hh-account { display: flex; align-items: center; gap: 8px; flex: 1; justify-content: center; }

.ha { display: inline-flex; align-items: baseline; gap: 2px; font-size: 12px; }

.hv { font-weight: 600; }

.hv { font-size: 13px; font-weight: 600; }

.hh-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

.up { color: var(--stock-up); }

.down { color: var(--stock-down); }

.emergency-btn-inline { font-size: 14px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--stock-up); color: var(--stock-up); background: transparent; cursor: pointer; }

.emergency-btn-inline:hover { background: var(--stock-up); color: var(--text-inverse); }

.emergency-btn-inline.disabled { opacity: 0.4; cursor: not-allowed; }

.mm-body { flex: 1; display: grid; grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr); gap: 0; overflow: hidden; min-width: 0; }

.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 10px; min-width: 0; min-height: 0; }

.mm-left { background: var(--bg-secondary); border-right: 1px solid var(--border-default); }

.st { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; }

.sc { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); transition: border-color 0.2s; min-width: 0; }

.sc:hover { border-color: var(--text-muted); }

.sc.disabled { opacity: 0.5; }

.sc-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }

.sc-icon { font-size: 16px; }

.sc-name { font-size: 13px; font-weight: 600; flex: 1 1 auto; min-width: 0; }

.sc-arrow { font-size: 10px; color: var(--text-tertiary); margin-left: 4px; }

.sc-desc { font-size: 11px; color: var(--text-tertiary); margin: 2px 0 4px 24px; overflow-wrap: break-word; }

.sc-params { margin-left: 24px; min-width: 0; }

.pm { display: flex; justify-content: space-between; font-size: 11px; gap: 4px; min-width: 0; }

.pk { color: var(--text-tertiary); white-space: nowrap; }

.pv { color: var(--text-secondary); font-weight: 500; overflow-wrap: break-word; }

@keyframes risk-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

@keyframes blink { 50% { opacity: 0.5; } }

.ds-indicator { display: inline-flex; gap: 4px; margin-left: 4px; }

.ds-dot { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: 600; cursor: help; }

.ds-dot.ok { color: var(--stock-down); background: var(--stock-down-bg); }

.ds-dot.err { color: var(--stock-up); background: var(--stock-up-bg); }

.ws-indicator { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; font-size: 10px; font-weight: 600; cursor: help; padding: 1px 5px; border-radius: 3px; }

.ws-indicator .ws-dot { width: 6px; height: 6px; border-radius: 50%; }

.ws-indicator.ws-ok { color: #67c23a; background: #f0f9eb; }

.ws-indicator.ws-ok .ws-dot { background: #67c23a; animation: ws-pulse 2s infinite; }

.ws-indicator.ws-warn { color: #e6a23c; background: #fdf6ec; }

.ws-indicator.ws-warn .ws-dot { background: #e6a23c; }

.ws-indicator.ws-off { color: #909399; background: #f4f4f5; }

.ws-indicator.ws-off .ws-dot { background: #909399; }

:deep(.dark) .ws-indicator.ws-ok { color: #95d475; background: rgba(103,194,58,0.15); }

:deep(.dark) .ws-indicator.ws-warn { color: #eebe77; background: rgba(230,162,60,0.15); }

:deep(.dark) .ws-indicator.ws-off { color: #73767a; background: rgba(144,147,153,0.15); }

@keyframes ws-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

@media (max-width: 1400px) {
  .mm-body { grid-template-columns: minmax(160px, 2fr) minmax(180px, 3fr) minmax(280px, 4fr); }
  .pos-info { flex-wrap: wrap; gap: 4px; }
  .tl-body { flex-wrap: wrap; }
  .tl-col { min-width: 180px; }
}

@media (max-width: 1024px) {
  .mm-body { grid-template-columns: 1fr; }
  .mm-left, .mm-right { border: none; border-bottom: 1px solid var(--border-default); }
  .tl-body { flex-direction: column; }
  .tl-col { max-height: 180px; }
  .tl-col + .tl-col { border-left: none; padding-left: 0; border-top: 1px solid var(--border-default); padding-top: 8px; }
}

@media (max-width: 1024px) {
  }

.scan-trace { font-size: 13px; }

.cp { cursor: pointer; }

.dark-toggle { font-size: 16px; cursor: pointer; padding: 0 4px; user-select: none; }

.emergency-btn.active { animation: emergency-pulse 1.5s infinite; }

@keyframes emergency-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.5); } 50% { box-shadow: 0 0 0 8px rgba(245, 108, 108, 0); } }

.mm-tab-bar {
  display: flex;
  gap: 2px;
  padding: 0 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.mm-tab-bar .tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
  white-space: nowrap;
}

.mm-tab-bar .tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.mm-tab-bar .tab-btn.active {
  color: var(--el-color-primary);
  border-bottom-color: var(--el-color-primary);
  font-weight: 600;
}

.tab-icon { font-size: 15px; }

.tab-text { display: flex; flex-direction: column; gap: 1px; }

.tab-label { font-size: 13px; line-height: 1.2; }

.tab-desc { font-size: 10px; color: var(--text-tertiary); line-height: 1; }

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 9px;
  background: var(--el-color-primary);
  color: var(--text-inverse);
  padding: 0 5px;
}

.tab-badge-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 9px;
  background: var(--stock-up);
  color: var(--text-inverse);
  padding: 0 5px;
}

.mm-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

.mm-tab-scroll { flex: 1; overflow-y: auto; padding: 12px 16px; }

mm-tab-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.mm-tab-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.tab-btn-sm.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); font-weight: 600; }

:deep(.el-date-table td.has-scan-data) {
  .el-date-table-cell__text {
    background: var(--el-color-primary);
    color: #fff;
    font-weight: 600;
    border-radius: 50%;
  }
}

:deep(.el-date-table td.has-scan-debug) {
  .el-date-table-cell__text {
    background: #e6a23c;
    color: #fff;
    font-weight: 600;
    border-radius: 50%;
  }
}
</style>
