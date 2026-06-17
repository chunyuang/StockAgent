<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控
 * 
 * 逻辑已拆到 useScannerMonitor.ts composable
 * 此文件只负责: 调用composable + 渲染template
 * 【v2.9.74: 清理26个未使用解构变量, 消除TS6133】
 */
import { provide, defineAsyncComponent } from 'vue'
import { useScannerMonitor } from './useScannerMonitor'
import { SCANNER_MONITOR_KEY, type ScannerMonitorData } from './scannerMonitorInject'
import { useThemeStore } from '@/stores/theme'
// 默认显示的Tab同步加载，其他Tab懒加载(减小首屏chunk)
import GuideTab from './GuideTab.vue'
const ReviewTab = defineAsyncComponent(() => import('./ReviewTab.vue'))
const OpsTab = defineAsyncComponent(() => import('./OpsTab.vue'))
const PremarketTab = defineAsyncComponent(() => import('./PremarketTab.vue'))
const SentimentTab = defineAsyncComponent(() => import('./SentimentTab.vue'))
const HistoryTab = defineAsyncComponent(() => import('./HistoryTab.vue'))
const AnalysisTab = defineAsyncComponent(() => import('./AnalysisTab.vue'))
const AccountTab = defineAsyncComponent(() => import('./AccountTab.vue'))
const ScanTraceTab = defineAsyncComponent(() => import('./ScanTraceTab.vue'))
const PositionRiskMatrix = defineAsyncComponent(() => import('./PositionRiskMatrix.vue'))
const MiniKline = defineAsyncComponent(() => import('./MiniKline.vue'))
const StrategyPerfBoard = defineAsyncComponent(() => import('./StrategyPerfBoard.vue'))
const SignalTracePanel = defineAsyncComponent(() => import('./SignalTracePanel.vue'))
import KeyboardShortcuts from './KeyboardShortcuts.vue'
import UnifiedDateBar from '@/components/UnifiedDateBar.vue'

const monitorData = useScannerMonitor()
provide(SCANNER_MONITOR_KEY, monitorData as unknown as ScannerMonitorData)

// 确保themeStore独立初始化(避免composable返回undefined的问题)
const themeStore = monitorData.themeStore || useThemeStore()

// 在模板中使用的变量仍需解构(vue-tsc要求) — 必须从同一个实例解构
const {
  // 【v2.9.97】统一日期选择器
  unified,
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
  startScanner, stopScanner, fetchScanner,
  manualScan, forceScan, quickBuy, quickSell, fetchReviewData, fetchSentimentData,
  // sentiment sub-composable
  openTradeDetail,
  runBacktest, saveParamSnapshot,
  setTrailingStop,
  showConfirm: _showConfirm, handleConfirm, emergencyLiquidate,
  saveStrategy,
  layerLabel,
  posSort, sortedPositions,
  strategyCN, strategyMeta, normalizePct, formatSlTp, formatRemaining,
  modeMeta,
  onModeChange, confirmReplay, cancelReplay, dryRun,
  // 【v2.9.71: WS连接状态】
  wsStatus, wsIsConnected, wsRetryCount,
  stratCollapsed, stratSectionCollapsed, toggleStrat, toggleStrategy,
  openEditDialog, factorLabel,
  // scanTrace/layerDebug/signalStatus/formatLayerTrace/formatDecisionDetail
  // are accessed by ScanTraceTab via inject; not needed in this template
  // compareVisible/compareData passed as ReviewTab props
  compareVisible, compareData,
  openScanTrace,
  reviewDate, reviewHero, reviewForward,
  backtestRunning, liveBacktestDiff, executionQuality,
  tradeAttributions, paramDriftData, factorEffectData,
  disciplineCheck,
} = monitorData

// 【v2.9.94】交易详情弹窗时间显示：优先后端 time_display，后退到 trade_date + time 拼接
function formatTradeDateTime(rec: any): string {
  if (!rec) return '-'
  if (rec.time_display) return rec.time_display
  const td = String(rec.trade_date || '').trim()
  const t = String(rec.time || '').trim()
  if (td && /^\d{8}$/.test(td)) {
    const ymd = `${td.slice(0,4)}-${td.slice(4,6)}-${td.slice(6,8)}`
    return t ? `${ymd} ${t}` : ymd
  }
  if (td && /^\d{4}-\d{2}-\d{2}$/.test(td)) {
    return t ? `${td} ${t}` : td
  }
  return t || '-'
}
</script>
<template>
  <div class="mm" :class="{ dark: themeStore.isDark }">
    <!-- 顶部状态栏(一行: 风控+状态+资产+操作) -->
    <div class="mm-header">
      <div class="hh-left">
        <div class="hh-title">市场监听</div>
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
        <span class="ha">资产<span class="hv">{{ ((accountInfo.total_assets || 0) / 10000).toFixed(1) }}万</span></span>
        <span class="ha">可用<span class="hv">{{ ((accountInfo.available_cash || 0) / 10000).toFixed(1) }}万</span></span>
        <span class="ha">仓位<span class="hv">{{ positionRatio }}%</span></span>
        <span class="ha">盈亏<span class="hv" :class="(totalPnl ?? 0) >= 0 ? 'up' : 'down'">{{ (totalPnl ?? 0) >= 0 ? '+' : '' }}{{ (totalPnl ?? 0).toFixed(0) }}</span></span>
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
        <span class="tab-text"><span class="tab-label">指南</span><span class="tab-desc">架构操作</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'trading' ? 'active' : '']" @click="activeTab = 'trading'">
        <span class="tab-icon">🎯</span>
        <span class="tab-text"><span class="tab-label">实盘</span><span class="tab-desc">信号交易</span></span>
        <span v-if="filteredSignals.length" class="tab-badge">{{ filteredSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'premarket' ? 'active' : '']" @click="activeTab = 'premarket'">
        <span class="tab-icon">🌅</span>
        <span class="tab-text"><span class="tab-label">竞价</span><span class="tab-desc">9:00-9:25</span></span>
        <span v-if="premarketSignals.length" class="tab-badge">{{ premarketSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'scan-trace' ? 'active' : '']" @click="activeTab = 'scan-trace'">
        <span class="tab-icon">🔍</span>
        <span class="tab-text"><span class="tab-label">追踪</span><span class="tab-desc">9层漏斗</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'review' ? 'active' : '']" @click="activeTab = 'review'">
        <span class="tab-icon">📋</span>
        <span class="tab-text"><span class="tab-label">复盘</span><span class="tab-desc">日周归因</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'risk' ? 'active' : '']" @click="activeTab = 'risk'">
        <span class="tab-icon">🛡️</span>
        <span class="tab-text"><span class="tab-label">风控</span><span class="tab-desc">止损矩阵</span></span>
        <span v-if="positions.some(p => p.risk_level === 'high')" class="tab-badge-danger">!</span>
      </button>
      <button :class="['tab-btn', activeTab === 'sentiment' ? 'active' : '']" @click="activeTab = 'sentiment'; fetchSentimentData()">
        <span class="tab-icon">🌡️</span>
        <span class="tab-text"><span class="tab-label">情绪</span><span class="tab-desc">周期曲线</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'history' ? 'active' : '']" @click="activeTab = 'history'">
        <span class="tab-icon">📜</span>
        <span class="tab-text"><span class="tab-label">历史</span><span class="tab-desc">时间订单</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'analysis' ? 'active' : '']" @click="activeTab = 'analysis'">
        <span class="tab-icon">📊</span>
        <span class="tab-text"><span class="tab-label">分析</span><span class="tab-desc">KPI归因</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'account' ? 'active' : '']" @click="activeTab = 'account'">
        <span class="tab-icon">💰</span>
        <span class="tab-text"><span class="tab-label">账户</span><span class="tab-desc">资产持仓</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'ops' ? 'active' : '']" @click="activeTab = 'ops'">
        <span class="tab-icon">⚙️</span>
        <span class="tab-text"><span class="tab-label">运维</span><span class="tab-desc">系统操作</span></span>
      </button>
    </div>

    <!-- 📖 指南Tab -->
    <GuideTab v-if="activeTab === 'guide'" />

    <!-- 3列主布局 -->
    <div v-if="activeTab === 'trading'" class="mm-body">
      <!-- 左列: 日期+策略控制 -->
      <div class="mm-left">
        <div class="st">📅 日期 <UnifiedDateBar @change="(_d: string, dApi: string) => fetchScanner(dApi)" /></div>
        <div class="st cp" @click="stratSectionCollapsed = !stratSectionCollapsed" style="margin-top:4px">🎛️ 策略控制 <span class="sc-arrow">{{ stratSectionCollapsed ? '▶' : '▼' }}</span></div>
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
            <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="min-width:52px;text-align:center">{{ sig.strategy_name }}</ElTag><ElTag v-if="sig.signal_status === 'executed'" size="small" type="success">已买</ElTag><ElTag v-if="sig.signal_status === 'skipped'" size="small" type="warning">跳过</ElTag><ElTag v-if="sig.signal_status === 'expired'" size="small" type="info">过期</ElTag><span class="code">{{ sig.ts_code }}</span><span class="name">{{ sig.stock_name }}</span><span v-if="sig.signal_status === 'new' && sigRemaining(sig) >= 0" class="expire-tag" :class="{ urgent: sigRemaining(sig) < 60000 }">⏱{{ formatRemaining(sigRemaining(sig)) }}</span><span :class="(sig.pct_chg || 0) >= 0 ? 'up' : 'down'" class="pct ml-auto" style="font-weight:600">{{ (sig.pct_chg || 0) >= 0 ? '+' : '' }}{{ (sig.pct_chg || 0).toFixed(1) }}%</span><ElButton v-if="!dryRun && sig.signal_status === 'new'" size="small" type="danger" plain @click="quickBuy(sig)" class="btn-xs">买</ElButton><ElButton v-if="sig.decision_detail" size="small" type="info" plain @click="openTradeDetail(sig.ts_code)" class="btn-xs">🔍</ElButton><ElButton v-if="sig.layer_trace" size="small" type="warning" plain @click="openScanTrace(sig.ts_code)" class="btn-xs">🧪</ElButton>
          </div>
        </div>

      </div>

      <!-- 右列: 持仓 -->
      <div class="mm-right">
        <div class="st">📊 持仓监控 <ElBadge :value="positions.length" :max="99" style="margin-left:4px" /><ElSelect v-model="posSort" size="small" style="width:80px;margin-left:auto"><ElOption label="盈亏" value="profit" /><ElOption label="市值" value="cost" /><ElOption label="策略" value="strategy" /><ElOption label="时间" value="time" /></ElSelect></div>
        <div class="sl">
          <div v-if="!positions.length" class="empty">暂无持仓</div>
          <div v-for="(pos, idx) in sortedPositions" :key="pos.ts_code" class="pos-card" :class="{ 'pos-focused': idx === focusIndex }">
            <div class="pos-top"><ElTag size="small" :color="strategyMeta[pos.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px;min-width:48px;text-align:center">{{ pos.strategy_name || strategyCN(pos.strategy) }}</ElTag><span class="code">{{ pos.ts_code }}</span><span class="name">{{ pos.stock_name }}</span><MiniKline :tsCode="pos.ts_code" :compact="true" :days="5" /><span :class="(pos.profit_pct || 0) >= 0 ? 'up' : 'down'" class="pct">{{ (pos.profit_pct || 0) >= 0 ? '+' : '' }}{{ (pos.profit_pct || 0).toFixed(1) }}%</span><span class="mini-bar"><span class="mini-bar-fill" :style="{ width: Math.min(Math.abs(pos.profit_pct || 0) / 10 * 100, 100) + '%' }" :class="(pos.profit_pct || 0) >= 0 ? 'bar-up' : 'bar-down'"></span></span><span v-if="pos.today_buy > 0" class="t1-tag">T+1</span><ElButton size="small" type="danger" plain @click="quickSell(pos)" :disabled="pos.available_qty <= 0" class="btn-xs ml-auto">卖出</ElButton><ElButton size="small" type="info" plain @click="openTradeDetail(pos.ts_code)" class="btn-xs">详情</ElButton></div>
            <div class="pos-info"><span>{{ pos.shares }}股</span><span>成本¥{{ Number(pos.cost_price || 0).toFixed(2) }}</span><span>现价¥{{ Number(pos.current_price || 0).toFixed(2) }}</span><span v-if="pos.market_value" class="mv">市值{{ (Number(pos.market_value) / 10000).toFixed(1) }}万</span><span v-if="pos.profit_amount != null" :class="pos.profit_amount >= 0 ? 'up' : 'down'" class="pamt">{{ pos.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(Number(pos.profit_amount)).toFixed(0) }}</span></div>
            <div class="pos-prices-row">
              <span v-if="pos.stop_loss_price" class="pp-sl">止损¥{{ Number(pos.stop_loss_price).toFixed(2) }}</span>
              <span v-if="pos.take_profit_price" class="pp-tp">止盈¥{{ Number(pos.take_profit_price).toFixed(2) }}</span>
              <span v-if="pos.trailing_stop?.activated" class="pp-trail">📍追踪¥{{ Number(pos.trailing_stop.stop_price || 0).toFixed(2) }}({{ ((Number(pos.trailing_stop.trailing_stop_pct) || 0) * 100).toFixed(0) }}%)</span>
              <span v-if="pos.risk_level && pos.risk_level !== 'normal'" class="pp-risk" :class="pos.risk_level">{{ {high:'🔴高风险',elevated:'🟡较高',low:'🟢低风险'}[pos.risk_level] || pos.risk_level }}</span>
            </div>
            <div v-if="pos.stop_loss_pct != null" class="pos-risk-row">
              <div class="risk-track"><div class="risk-fill" :style="{ width: Math.max(0, Math.min(100, (() => { const pPct = pos.profit_pct || 0, sl = normalizePct(pos.stop_loss_pct, 3), tp = normalizePct(pos.take_profit_pct, 7), d = sl + tp; return d > 0 ? (pPct + sl) / d * 100 : 0 })())) + '%' }" :class="(pos.profit_pct || 0) + normalizePct(pos.stop_loss_pct, 3) < 1 ? 'danger' : (pos.profit_pct || 0) + normalizePct(pos.stop_loss_pct, 3) < 2 ? 'warning' : 'safe'"></div></div>
              <div class="risk-labels-row"><span class="rl stop">止损{{ formatSlTp(pos.stop_loss_pct, 3) }}</span><span v-if="pos.trailing_stop?.activated" class="rl trail">📍{{ ((pos.trailing_stop.trailing_stop_pct || 0) * 100).toFixed(0) }}%</span><span class="rd" :class="{ danger: (pos.profit_pct || 0) + normalizePct(pos.stop_loss_pct, 3) < 2 }">距止损{{ ((pos.profit_pct || 0) + normalizePct(pos.stop_loss_pct, 3)).toFixed(1) }}%</span><span class="rl profit">止盈{{ formatSlTp(pos.take_profit_pct, 7) }}</span></div>
            </div>
          </div>
        </div>

        <!-- 盈亏曲线 → 已移至绩效Tab -->
        <!-- 策略绩效看板 -->
        <StrategyPerfBoard />
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
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ formatTradeDateTime(tradeDetailData.buy) }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ Number(tradeDetailData.buy.price || 0).toFixed(2) }}</div></div>
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
                    <div class="td2-card sm"><div class="td2-label">仓位比例</div><div class="td2-val">{{ ((Number(tradeDetailData.buy.decision_detail.execution.position_ratio ?? 0) || 0) * 100).toFixed(0) }}%</div></div>
                    <div class="td2-card sm"><div class="td2-label">可用资金</div><div class="td2-val">¥{{ Number(tradeDetailData.buy.decision_detail.execution.available_cash || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">买入金额</div><div class="td2-val">¥{{ Number(tradeDetailData.buy.decision_detail.execution.total_cost || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">成交价</div><div class="td2-val">¥{{ Number(tradeDetailData.buy.decision_detail.execution.filled_price || 0).toFixed(2) }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.sentiment"><div class="td2-label">情绪</div><div class="td2-val">{{ Number(tradeDetailData.buy.decision_detail.execution.sentiment.score || 0).toFixed(0) }}→{{ tradeDetailData.buy.decision_detail.execution.sentiment.period }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.circuit_breaker"><div class="td2-label">熔断</div><div class="td2-val" :class="tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? 'down' : ''">{{ tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? '⛔暂停' : '✅正常' }}</div></div>
                  </div>
                </template>
                <template v-if="tradeDetailData.buy.decision_detail.factors && Object.values(tradeDetailData.buy.decision_detail.factors).some(v => v !== 0 && v !== null)">
                  <div class="td2-chain-title">📈 关键因子</div>
                  <div class="td2-factors">
                    <div v-for="(v, k) in tradeDetailData.buy.decision_detail.factors" :key="k" v-show="v !== 0 && v !== null" class="td2-factor"><span class="td2-fk">{{ factorLabel(k) }}</span><span class="td2-fv">{{ typeof v === 'number' && isFinite(v) ? v.toFixed(2) : v }}</span></div>
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
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ formatTradeDateTime(tradeDetailData.sell) }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ Number(tradeDetailData.sell.price || 0).toFixed(2) }}</div></div>
              <div class="td2-card"><div class="td2-label">📊 盈亏</div><div class="td2-val" :class="(tradeDetailData.sell.profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (tradeDetailData.sell.profit_pct || 0) >= 0 ? '+' : '' }}{{ Number(tradeDetailData.sell.profit_pct || 0).toFixed(2) }}%</div></div>
              <div class="td2-card"><div class="td2-label">💵 盈亏额</div><div class="td2-val" :class="(tradeDetailData.sell.profit_amount || 0) >= 0 ? 'up' : 'down'">¥{{ Number(tradeDetailData.sell.profit_amount || 0).toFixed(0) }}</div></div>
            </div>
            <div class="td2-reason">📋 卖出原因: {{ tradeDetailData.sell.reason }}</div>
            <template v-if="tradeDetailData.sell.decision_detail">
              <div class="td2-chain">
                <div class="td2-grid">
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.cost_price"><div class="td2-label">成本价</div><div class="td2-val">¥{{ Number(tradeDetailData.sell.decision_detail.cost_price).toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.current_price"><div class="td2-label">卖出价</div><div class="td2-val">¥{{ Number(tradeDetailData.sell.decision_detail.current_price).toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_pct"><div class="td2-label">止损线</div><div class="td2-val text-stock-up">{{ tradeDetailData.sell.decision_detail.stop_loss_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_pct"><div class="td2-label">止盈线</div><div class="td2-val text-stock-down">{{ tradeDetailData.sell.decision_detail.take_profit_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ Number(tradeDetailData.sell.decision_detail.stop_loss_price).toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ Number(tradeDetailData.sell.decision_detail.take_profit_price).toFixed(2) }}</div></div>
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
            <div class="td2-card"><div class="td2-label">成本</div><div class="td2-val">¥{{ Number(tradeDetailData.position.cost_price || 0).toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">现价</div><div class="td2-val">¥{{ Number(tradeDetailData.position.current_price || 0).toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">盈亏</div><div class="td2-val" :class="(tradeDetailData.position.profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (tradeDetailData.position.profit_pct || 0) >= 0 ? '+' : '' }}{{ Number(tradeDetailData.position.profit_pct || 0).toFixed(2) }}%</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_pct"><div class="td2-label">止损</div><div class="td2-val text-stock-up">{{ formatSlTp(tradeDetailData.position.stop_loss_pct, 3) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_pct"><div class="td2-label">止盈</div><div class="td2-val text-stock-down">{{ formatSlTp(tradeDetailData.position.take_profit_pct, 7) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ Number(tradeDetailData.position.stop_loss_price).toFixed(2) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ Number(tradeDetailData.position.take_profit_price).toFixed(2) }}</div></div>
          </div>
          <!-- 追踪止损 -->
          <div v-if="tradeDetailData.position.trailing_stop" class="td2-trail-section">
            <div class="td2-chain-title">📍 追踪止损</div>
            <div class="td2-grid">
              <div class="td2-card sm"><div class="td2-label">状态</div><div class="td2-val" :class="tradeDetailData.position.trailing_stop?.activated ? 'up' : ''">{{ tradeDetailData.position.trailing_stop?.activated ? '✅已激活' : '⏸未激活' }}</div></div>
              <div class="td2-card sm"><div class="td2-label">比例</div><div class="td2-val">{{ ((Number(tradeDetailData.position.trailing_stop?.trailing_stop_pct) || 0) * 100).toFixed(1) }}%</div></div>
              <div class="td2-card sm"><div class="td2-label">最高价</div><div class="td2-val">¥{{ Number(tradeDetailData.position.trailing_stop?.high_price || 0).toFixed(2) }}</div></div>
              <div class="td2-card sm"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ Number(tradeDetailData.position.trailing_stop?.stop_price || 0).toFixed(2) }}</div></div>
            </div>
            <div class="td2-trail-ctrl">
              <ElInputNumber v-model="trailEditPct" :min="1" :max="20" :step="0.5" :precision="1" size="small" style="width:110px" />
              <span style="font-size:12px;color:var(--text-tertiary)">%回撤</span>
              <ElButton size="small" type="primary" @click="setTrailingStop(tradeDetailData.ts_code, true)" :loading="trailSaving">激活</ElButton>
              <ElButton v-if="tradeDetailData.position.trailing_stop?.activated" size="small" @click="setTrailingStop(tradeDetailData.ts_code, false)" :loading="trailSaving">停用</ElButton>
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
      <div v-if="tradeAuditData.length" class="al"><div class="ah"><span>股票</span><span>策略</span><span>买入</span><span>卖出</span><span>盈亏</span><span>状态</span></div><div v-for="t in tradeAuditData" :key="t.ts_code" class="ar" @click="openTradeDetail(t.ts_code); tradeAuditVisible = false"><span class="code">{{ t.ts_code }}</span><span><ElTag size="small" type="info">{{ strategyCN(t.strategy) }}</ElTag></span><span>{{ t.buy_time }} {{ t.buy_price?.toFixed(2) }}</span><span>{{ t.sell_time || '-' }} {{ t.sell_price?.toFixed(2) || '-' }}</span><span :class="t.profit_pct !== null && t.profit_pct >= 0 ? 'up' : 'down'">{{ t.profit_pct !== null ? (t.profit_pct >= 0 ? '+' : '') + Number(t.profit_pct).toFixed(2) + '%' : '-' }}</span><span class="text-tertiary-sm">{{ t.status }}</span></div></div>
      <div v-else class="empty">暂无交易记录</div>
    </ElDialog>
    

    

    
    <!-- 回放日期弹窗 -->
    <ElDialog v-model="replayDateVisible" title="🔄 回放模式" width="380px" :close-on-click-modal="false">
      <div style="margin-bottom:12px;font-size:14px">选择要回放的交易日期，将使用历史数据重放扫描：</div>
      <UnifiedDateBar @change="(_d: string) => { replayDateInput = _d }" />
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
      :compareVisible="compareVisible" :compareData="compareData"
      :dailyReportVisible="dailyReportVisible" :dailyReport="dailyReport"
      :weeklyReportVisible="weeklyReportVisible"
      @update:reviewTab="reviewTab = $event as 'daily' | 'weekly' | 'monthly'" @update:reviewDate="reviewDate = $event"
      @update:compareVisible="compareVisible = $event" @update:dailyReportVisible="dailyReportVisible = $event" @update:weeklyReportVisible="weeklyReportVisible = $event"
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
    <AnalysisTab v-if="activeTab === 'analysis'" />
    <AccountTab v-if="activeTab === 'account'" />

    <OpsTab v-if="activeTab === 'ops'" />

    <!-- 【V50.1】信号链路追踪面板(可收起, 跨Tab) -->
    <div v-if="signalTraceVisible" class="mm-trace">
      <SignalTracePanel />
    </div>

    <!-- P2-10: 键盘快捷键 -->
    <KeyboardShortcuts
      @force-scan="forceScan"
      @manual-scan="manualScan"
      @start-scanner="startScanner"
      @stop-scanner="stopScanner"
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

.mm-header { display: flex; align-items: center; gap: 8px; padding: 4px 10px; min-height: 34px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; min-width: 0; overflow-x: auto; }

.hh-left { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }

.hh-title { font-size: 15px; font-weight: 700; color: var(--text-primary); padding-right: 8px; border-right: 1px solid var(--border-default); white-space: nowrap; }

.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 12px; white-space: nowrap; }

.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }

.hh-status.running .dot { background: var(--stock-down); animation: pulse 1.5s infinite; }

.hh-status.stopped .dot { background: var(--text-tertiary); }

@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.hh-account { display: flex; align-items: center; gap: 8px; flex: 1; justify-content: center; min-width: 320px; }

.ha { display: inline-flex; align-items: baseline; gap: 2px; font-size: 11px; white-space: nowrap; }

.hv { font-weight: 600; }

.hv { font-size: 12px; font-weight: 600; }

.hh-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

.up { color: var(--stock-up); }

.down { color: var(--stock-down); }

.emergency-btn-inline { font-size: 14px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--stock-up); color: var(--stock-up); background: transparent; cursor: pointer; }

.emergency-btn-inline:hover { background: var(--stock-up); color: var(--text-inverse); }

.emergency-btn-inline.disabled { opacity: 0.4; cursor: not-allowed; }

/* 【v2.9.97h-v8 布局重构】3列比例: 左1.5/中2.5/右3，改用gap+圆角分隔 */
.mm-body { flex: 1; display: grid; grid-template-columns: minmax(220px, 1.5fr) minmax(280px, 2.5fr) minmax(380px, 3fr); gap: 8px; padding: 8px; overflow: hidden; min-width: 0; background: var(--bg-tertiary, var(--bg-secondary)); }

.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 12px; min-width: 0; min-height: 0; background: var(--bg-secondary); border-radius: 8px; border: 1px solid var(--border-default); }

.mm-left { background: var(--bg-secondary); }

/* 【v2.9.97h-v8】一级标题 - 加粗+下划线增强层级 */
.st { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border-default); display: flex; align-items: center; gap: 4px; }

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
  .mm-body { grid-template-columns: minmax(200px, 1.5fr) minmax(260px, 2.5fr) minmax(340px, 3fr); gap: 6px; padding: 6px; }
  .pos-info { flex-wrap: wrap; gap: 4px; }
  .tl-body { flex-wrap: wrap; }
  .tl-col { min-width: 180px; }
}

@media (max-width: 1024px) {
  .mm-body { grid-template-columns: 1fr; gap: 4px; padding: 4px; }
  .mm-left, .mm-right { border-bottom: 1px solid var(--border-default); }
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
  gap: 4px;
  padding: 4px 10px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
  overflow-x: auto;
}

.mm-tab-bar .tab-btn {
  position: relative;
  flex: 1 1 0;
  min-width: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
  height: 34px;
}

.mm-tab-bar .tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
  border-color: var(--border-light);
}

.mm-tab-bar .tab-btn.active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
  font-weight: 700;
}

.tab-icon { font-size: 14px; line-height: 1; }

.tab-text { display: flex; align-items: center; justify-content: center; min-width: 28px; }

.tab-label { font-size: 13px; line-height: 1; font-weight: 600; letter-spacing: 0.08em; }

/* 二字主名保持统一；超宽屏再露出副标题 */
.tab-desc { display: none; font-size: 10px; color: var(--text-tertiary); line-height: 1; margin-left: 4px; letter-spacing: 0; }
@media (min-width: 1600px) {
  .tab-text { flex-direction: column; gap: 2px; align-items: center; }
  .tab-desc { display: inline; margin-left: 0; }
  .mm-tab-bar .tab-btn { height: 42px; }
}

.tab-badge {
  position: absolute;
  top: 2px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  font-size: 9px;
  font-weight: 600;
  border-radius: 8px;
  background: var(--el-color-primary);
  color: var(--text-inverse);
  padding: 0 4px;
}

.tab-badge-danger {
  position: absolute;
  top: 2px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
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

/* ========== 交易详情弹窗样式(v2.9.75死CSS清理误删补回) ========== */
.td2-sec { margin-bottom: 16px; padding: 12px; background: var(--bg-secondary); border-radius: 8px; }
.td2-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); }
.td2-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.td2-card { padding: 8px 10px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); }
.td2-card.sm { padding: 6px 8px; }
.td2-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 2px; }
.td2-val { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.td2-reason { padding: 8px 10px; margin: 8px 0; background: var(--bg-elevated); border-radius: 6px; border-left: 3px solid var(--el-color-primary); font-size: 13px; color: var(--text-secondary); }
.td2-chain { margin-top: 8px; }
.td2-chain-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin: 8px 0 6px; padding-left: 4px; border-left: 2px solid var(--el-color-primary); }
.td2-pipeline { display: flex; flex-direction: column; gap: 3px; }
.td2-pipe-step { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--bg-elevated); border-radius: 4px; font-size: 12px; }
.td2-pipe-step.passed { border-left: 2px solid var(--success); }
.td2-pipe-icon { font-size: 12px; flex-shrink: 0; }
.td2-pipe-name { font-weight: 500; min-width: 100px; color: var(--text-primary); }
.td2-pipe-detail { color: var(--text-tertiary); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td2-factors { display: flex; flex-wrap: wrap; gap: 6px; }
.td2-factor { padding: 4px 8px; background: var(--bg-elevated); border-radius: 4px; font-size: 12px; }
.td2-fk { color: var(--text-tertiary); margin-right: 4px; }
.td2-fv { font-weight: 500; color: var(--text-primary); }
.td2-empty { text-align: center; padding: 16px; color: var(--text-tertiary); font-size: 13px; }
.td2-trail-section { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-default); }
.td2-trail-ctrl { display: flex; align-items: center; gap: 8px; margin-top: 8px; }

/* 审计日志弹窗 */
.al { max-height: 500px; overflow-y: auto; }
.ah { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.ar { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); cursor: pointer; overflow: hidden; }
.ar:hover { background: var(--bg-hover); }

/* 【v2.9.97h-v8 持仓卡重构】两栏网格布局，头部/左下金额/右下风险 */
.pos-card { display: grid; grid-template-areas: "head head" "metrics risk" "riskbar riskbar"; grid-template-columns: 1fr minmax(150px, 200px); column-gap: 12px; row-gap: 6px; padding: 10px 12px; margin-bottom: 8px; background: var(--bg-elevated); border-radius: 8px; border: 1px solid var(--border-default); min-width: 0; transition: all 0.15s; }
.pos-card:hover { border-color: var(--el-color-primary); transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.pos-focused { border: 2px solid var(--el-color-primary) !important; box-shadow: 0 0 8px var(--el-color-primary-light-5); }
.pos-top { grid-area: head; display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; min-width: 0; overflow: hidden; }
.pos-top .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80px; }
.pos-top .pct { font-weight: 700; font-size: 14px; margin-left: auto; flex-shrink: 0; }
.pos-card:hover .pct { transform: scale(1.05); }
/* MiniKline hover才高亮 */
.pos-top :deep(.mini-kline-wrapper), .pos-top :deep(canvas) { opacity: 0.5; transition: opacity 0.2s; flex-shrink: 0; }
.pos-card:hover .pos-top :deep(.mini-kline-wrapper), .pos-card:hover .pos-top :deep(canvas) { opacity: 1; }
.pos-risk-row { grid-area: riskbar; margin-top: 2px; }
.pos-prices-row { grid-area: risk; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; padding: 0; font-size: 10px; color: var(--text-tertiary); flex-wrap: nowrap; }
.pos-prices-row > span { white-space: nowrap; }
/* 【v2.9.97h-v8】左下金额信息块 */
.pos-info { grid-area: metrics; display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; color: var(--text-secondary); align-content: flex-start; }
.pos-info > span { white-space: nowrap; }
.pos-info .mv { color: var(--text-tertiary); }
.pos-info .pamt { font-weight: 600; font-size: 12px; }
/* mini-bar 隐藏 (与riskTrack重复) */
.mini-bar { display: none !important; }
/* T+1 标签紧凑 */
.t1-tag { background: var(--el-color-warning-light-9, #fdf6ec); color: var(--el-color-warning, #e6a23c); font-size: 9px; padding: 1px 4px; border-radius: 3px; font-weight: 600; flex-shrink: 0; }
.emergency-btn-inline { font-size: 14px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--stock-up); color: var(--stock-up); background: transparent; cursor: pointer; }
.emergency-btn-inline:hover { background: var(--stock-up); color: var(--text-inverse); }
.emergency-btn-inline.disabled { opacity: 0.4; cursor: not-allowed; }
.emergency-btn { position: relative; display: inline-flex; align-items: center; justify-content: center; padding: 4px 14px; border: 2px solid var(--stock-up); border-radius: 6px; background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; color: var(--stock-up); transition: all 0.2s; }
.emergency-btn.active { animation: emergency-pulse 1.5s infinite; }
.emergency-btn.disabled { opacity: 0.4; cursor: not-allowed; animation: none; }
.emergency-btn:not(.disabled):hover { background: var(--stock-up); color: var(--text-inverse); }
.mm-trace { flex-shrink: 0; max-height: 45vh; overflow-y: auto; border-top: 1px solid var(--border-default); background: var(--bg-elevated); }
/* 【v2.9.97h-v8】信号行紧凑布局，禁止wrap，按钮 hover 才出 */
.sig-row { display: flex; align-items: center; gap: 6px; padding: 6px 8px; margin-bottom: 3px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); font-size: 12px; flex-wrap: nowrap; min-width: 0; overflow: hidden; transition: all 0.15s; }
.sig-row:hover { border-color: var(--el-color-primary); background: var(--bg-hover); }
.sig-row .el-button { padding: 1px 6px; font-size: 11px; opacity: 0; transition: opacity 0.15s; flex-shrink: 0; }
.sig-row:hover .el-button { opacity: 1; }
.sig-row .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60px; }
.sig-row .pct { margin-left: auto; flex-shrink: 0; }
.risk-track { height: 4px; background: var(--bg-muted); border-radius: 2px; overflow: hidden; }
.risk-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.risk-fill.safe { background: linear-gradient(90deg, var(--warning), var(--success)); }
.risk-fill.warning { background: linear-gradient(90deg, var(--warning), var(--stock-up)); }
.risk-fill.danger { background: var(--stock-up); animation: risk-pulse 1s infinite; }
.t1-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; font-weight: 600; }
.expire-tag { font-size: 11px; color: var(--el-color-primary); background: var(--info-bg); padding: 1px 5px; border-radius: 3px; font-weight: 600; }
.expire-tag.urgent { color: var(--stock-up); background: var(--stock-up-bg); animation: blink 1s infinite; }
.btn-xs { padding: 1px 6px; font-size: 11px; }
.tag-solid { color: var(--text-inverse); border: none; }
.mini-bar { display: inline-block; width: 40px; height: 4px; background: var(--border-default); border-radius: 2px; vertical-align: middle; margin-left: 4px; }
.mini-bar-fill { display: block; height: 100%; border-radius: 2px; transition: width 0.3s; }
.text-stock-up { color: var(--stock-up) !important; }
.text-stock-down { color: var(--stock-down) !important; }
.text-tertiary-sm { font-size: 11px; color: var(--text-tertiary); }
.mini-bar-fill.bar-up { background: var(--stock-up) !important; }
.mini-bar-fill.bar-down { background: var(--stock-down) !important; }
.pp-sl { color: var(--stock-up); }
.pp-tp { color: var(--stock-down); }
.pp-trail { color: var(--el-color-warning); }
.pp-risk { font-weight: 600; }
.pp-risk.high { color: var(--stock-up); }
.pp-risk.elevated { color: var(--el-color-warning); }
.pp-risk.low { color: var(--stock-down); }
@keyframes risk-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
@keyframes blink { 50% { opacity: 0.5; } }
@keyframes emergency-pulse { 0%,100% { box-shadow: 0 0 4px var(--stock-up); } 50% { box-shadow: 0 0 12px var(--stock-up); } }
</style>

<!-- 共享基础样式(非scoped, 子Tab组件可继承) -->
<!-- v2.9.75死CSS清理误删补回: 这些样式被scoped限制不穿透到子Tab -->
<style lang="scss">
/* 市场监听器共享基础样式 - 子Tab组件通用 */
.mm .up { color: var(--stock-up); }
.mm .down { color: var(--stock-down); }
.mm .code { font-size: 12px; font-weight: 600; color: var(--text-primary); font-family: monospace; }
.mm .name { font-size: 12px; color: var(--text-secondary); }
.mm .empty { text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px 0; }
.mm .st { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border-default); display: flex; align-items: center; gap: 4px; }
.mm .pct { margin-left: auto; font-weight: 700; font-size: 14px; transition: transform 0.3s; }
.mm .cp { cursor: pointer; }
.mm .ml-auto { margin-left: auto; }
.mm .tag-solid { color: var(--text-inverse); border: none; }
.mm .btn-xs { padding: 1px 6px; font-size: 11px; }
.mm .text-tertiary { color: var(--text-tertiary); }
.mm .text-tertiary-sm { font-size: 11px; color: var(--text-tertiary); }
.mm .text-stock-up { color: var(--stock-up) !important; }
.mm .text-stock-down { color: var(--stock-down) !important; }
.mm .mm-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.mm .mm-tab-scroll { flex: 1; overflow-y: auto; padding: 12px 16px; }
.mm .tab-btn-sm { padding: 2px 10px; border-radius: 4px; border: 1px solid var(--border-default); background: transparent; font-size: 11px; cursor: pointer; color: var(--text-secondary); transition: all 0.15s; }
.mm .tab-btn-sm:hover { border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); }
.mm .tab-btn-sm.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); font-weight: 600; }
.mm .tab-btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
