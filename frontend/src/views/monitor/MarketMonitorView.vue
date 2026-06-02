<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控
 * 
 * 逻辑已拆到 useScannerMonitor.ts composable
 * 此文件只负责: 调用composable + 渲染template
 */
import { useScannerMonitor } from './useScannerMonitor'

const {
  loading, autoRefresh, soundEnabled,
  status, signals, positions, timeline, orders,
  signalFilter, filteredSignals, closedPositions,
  isRunning, accountInfo, positionRatio, totalPnl,
  circuitBreakerPaused, focusIndex, emergencyLiquidating,
  activeTab, reviewTab, limitPools, limitPoolTab,
  healthData, healthStatus, healthEmoji, healthCN, healthClass,
  riskBarCollapsed, strategies, globalRisk,
  editingStrategy, editDialogVisible, editTab, editParams, editRiskParams, saving,
  nowMs, sigRemaining,
  dailyReport, dailyReportData, dailyReportVisible,
  pnlHistory, perfData, perfChartOption,
  premarketSignals, premarketStatus, premarketCandidates,
  scanTraceDates, scanTraceList, scanTraceDetail,
  reviewData, reviewLoading, reviewHeroData, disciplineData,
  reviewForwardData, monthlyReviewData, weeklyReviewData,
  deviationData, closedLoopData,
  signalTraceVisible, tradeDetailVisible, tradeDetailData,
  tradeAuditVisible, tradeAuditData,
  confirmVisible, confirmLoading, confirmData,
  manualTrade, manualQuote, trailEditPct, trailSaving,
  dataSources, brokers, tradeMode, replayDate,
  fetchScanner, fetchAll, startScanner, stopScanner,
  manualScan, forceScan, quickBuy, quickSell,
  fetchStrategies, fetchHealth, fetchLimitPools,
  fetchDataSources, fetchPerformanceHistory,
  fetchPremarketData, fetchScanTraceDates, fetchScanHistory,
  fetchScanTrace, fetchReviewData, fetchAutoTrades,
  fetchParamCompare, fetchScanConfig, fetchAuditLog,
  fetchSentimentData, fetchDailyReport,
  openTradeDetail, openTradeAudit,
  runBacktest, runSamePeriodBacktest, saveParamSnapshot,
  setTrailingStop, onManualCodeChange, executeManualTrade,
  showConfirm, handleConfirm,
  sellAllPositions, resetAccount, emergencyLiquidate,
  saveStrategy, toggleScanHour,
  layerLabel, layerDesc, distanceToStopLoss,
  playSignalSound, posSort, sortedPositions,
  strategyCN, normalizePct, formatSlTp,
  scannerApi, configApi,
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
    <div v-if="activeTab === 'guide'" class="mm-guide">
      <!-- 顶部横幅 -->
      <div class="guide-banner">
        <div class="gb-left">
          <div class="gb-logo">📡</div>
          <div>
            <div class="gb-title">超短量化实盘监控系统</div>
            <div class="gb-sub">9层漏斗筛选 · 4策略联合选股 · 实时风控守护</div>
          </div>
        </div>
        <ElButton type="success" size="large" @click="startScanner" style="padding:10px 32px;font-size:15px">▶ 启动扫描器</ElButton>
      </div>

      <!-- 4列卡片网格 -->
      <div class="guide-grid">
        <!-- 系统架构 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">🏗️</span>系统架构</div>
          <div class="gg-body">
            <div class="gf-flow">
              <span class="gf-tag gf-input">5000+股票</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L1~L3 基础过滤</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L4~L6 策略筛选</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L7~L9 排序仓位</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag gf-output">买入信号</span>
            </div>
          </div>
        </div>

        <!-- 操作指南 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">📖</span>操作指南</div>
          <div class="gg-body">
            <div class="go-list">
              <div class="go-row"><span class="sn">1</span>▶ 启动 → 每5分钟自动扫描，30秒检查持仓</div>
              <div class="go-row"><span class="sn">2</span>📡 扫描 → 立即触发选股，⚡ 强扫跳缓存</div>
              <div class="go-row"><span class="sn">3</span>🎛️ 策略 → 左侧面板开关策略、调参数</div>
              <div class="go-row"><span class="sn">4</span>🟢 买入 → 信号区候选一键下单</div>
              <div class="go-row"><span class="sn">5</span>🔴 卖出 → 持仓卡片快捷平仓或自动止盈止损</div>
              <div class="go-row"><span class="sn">6</span>📋 复盘 / ⚙️ 运维 → 归因分析+系统健康</div>
            </div>
          </div>
        </div>

        <!-- 半路追涨 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🏃</span>半路追涨</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">盘中涨幅3-5% + 量能放大</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>12%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
            </div>
          </div>
        </div>

        <!-- 首板打板 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🥇</span>首板打板</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">首次涨停封板 + 成交概率</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>10%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>2天</span>
            </div>
          </div>
        </div>

        <!-- 龙头低吸 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🐲</span>龙头低吸</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">连板龙头回调 + MA支撑</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3.5%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>30%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>7天</span>
            </div>
          </div>
        </div>

        <!-- 跌停翘板 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">💥</span>跌停翘板</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">连续跌停翘板反转</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>5%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>20%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
            </div>
          </div>
        </div>

        <!-- 风控体系 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">🛡️</span>风控体系</div>
          <div class="gg-body">
            <div class="gr-grid">
              <div class="gr-row"><span class="gr-k">强制空仓</span><span class="gr-v">跌停≥80只 / 大盘跌≥3%</span></div>
              <div class="gr-row"><span class="gr-k">情绪仓位</span><span class="gr-v">高潮100% / 分化70% / 震荡50% / 冰点30%</span></div>
              <div class="gr-row"><span class="gr-k">单票上限</span><span class="gr-v">35% · 总仓位上限75%</span></div>
              <div class="gr-row"><span class="gr-k">盘中锁定</span><span class="gr-v">冲高≥6% 回撤≥2.5% → 利润保护</span></div>
              <div class="gr-row"><span class="gr-k">智能检查</span><span class="gr-v">盈利5s / 亏损3s / 接近止损1s</span></div>
              <div class="gr-row"><span class="gr-k">信号过期</span><span class="gr-v">5分钟未执行自动取消</span></div>
            </div>
          </div>
        </div>

        <!-- 快捷键 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">⌨️</span>快捷键</div>
          <div class="gg-body">
            <div class="gk-row">
              <span class="gk-g"><kbd>F5</kbd>强扫</span>
              <span class="gk-g"><kbd>F9</kbd>买入</span>
              <span class="gk-g"><kbd>Ctrl+S</kbd>卖出</span>
              <span class="gk-g"><kbd>Ctrl+E</kbd>紧急平仓</span>
              <span class="gk-g"><kbd>↑↓</kbd>切换持仓</span>
              <span class="gk-g"><kbd>Enter</kbd>详情</span>
              <span class="gk-g"><kbd>1-4</kbd>策略开关</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3列主布局 -->
    <div v-if="activeTab === 'trading'" class="mm-body">
      <!-- 左列: 策略控制 -->
      <div class="mm-left">
        <div class="st cp" @click="stratSectionCollapsed = !stratSectionCollapsed">🎛️ 策略控制 <span class="sc-arrow">{{ stratSectionCollapsed ? '▶' : '▼' }}</span></div>
        <template v-if="!stratSectionCollapsed">
        <div v-for="s in strategies" :key="s.id" class="sc" :class="{ disabled: !s.enabled }">
          <div class="sc-top cp" @click="toggleStrat(s.id)"><span class="sc-icon">{{ strategyMeta[s.id]?.icon || '📋' }}</span><span class="sc-name">{{ s.name }}</span><ElSwitch :model-value="s.enabled" @change="(v: boolean) => toggleStrategy(s.id, v)" size="small" @click.stop /><span class="sc-arrow">{{ stratCollapsed[s.id] ? '▶' : '▼' }}</span></div>
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
    <!-- 回测对比弹窗 -->
    <ElDialog v-model="compareVisible" title="📊 实盘 vs 回测对比" width="700px">
      <div v-if="compareData.length" class="cl-table">
        <div class="cl-h"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>实盘盈亏</span><span>回测收益</span><span>回测胜率</span><span>回测回撤</span><span>回测夏普</span></div>
        <div v-for="c in compareData" :key="c.strategy" class="cl-r">
          <span class="code">{{ strategyCN(c.strategy) }}</span>
          <span>{{ c.live_trades }}笔</span>
          <span :class="c.live_win_rate >= 50 ? 'up' : 'down'">{{ c.live_win_rate }}%</span>
          <span :class="c.live_pnl >= 0 ? 'up' : 'down'">{{ c.live_pnl >= 0 ? '+' : '' }}{{ c.live_pnl.toFixed(0) }}</span>
          <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
          <span>{{ c.bt_win_rate }}%</span>
          <span class="text-stock-up">{{ c.bt_drawdown }}%</span>
          <span>{{ c.bt_sharpe }}</span>
        </div>
      </div>
      <div v-else class="empty">暂无对比数据（需先运行回测）</div>
    </ElDialog>

    <!-- 【调试增强】9层筛选调试弹窗 -->
    <ElDialog v-model="layerDebugVisible" title="🧪 9层筛选管道调试" width="750px">
      <div v-if="layerDebugData" class="layer-debug">
        <div class="ld-header">
          <ElTag :type="layerDebugData.dry_run ? 'warning' : 'success'" size="small">{{ layerDebugData.dry_run ? '🔍调试模式' : '正常交易' }}</ElTag>
          <span>信号: {{ layerDebugData.total_signals }} | 已执行: {{ layerDebugData.executed_signals }} | 跳过: {{ layerDebugData.skipped_signals }} | 过期: {{ layerDebugData.expired_signals }}</span>
        </div>
        <div v-if="layerDebugData.pipeline_config" class="ld-pipeline">
          <div class="ld-title">管道配置</div>
          <div class="ld-layers">
            <div v-for="(enabled, layer) in layerDebugData.pipeline_config.layer_enabled" :key="layer" class="ld-layer">
              <span :class="enabled ? 'ld-on' : 'ld-off'">{{ enabled ? '✅' : '⏭️' }}</span>
              <span class="ld-name">{{ layerLabel(layer) }}</span>
            </div>
          </div>
          <div class="ld-sentiment" v-if="layerDebugData.pipeline_config.sentiment">
            情绪: {{ layerDebugData.pipeline_config.sentiment.score }} → {{ layerDebugData.pipeline_config.sentiment.period }} | 仓位系数: {{ (layerDebugData.pipeline_config.position_ratio * 100).toFixed(0) }}%
          </div>
        </div>
        <div v-if="layerDebugData.signal_traces?.length" class="ld-traces">
          <div class="ld-title">信号逐层链路</div>
          <div v-for="trace in layerDebugData.signal_traces" :key="trace.ts_code + trace.strategy" class="ld-trace-card">
            <div class="ld-trace-top"><span class="code">{{ trace.ts_code }}</span><span class="name">{{ trace.stock_name }}</span><ElTag size="small" type="info">{{ strategyCN(trace.strategy) }}</ElTag><ElTag size="small" :type="signalStatusTag(trace.signal_status).type">{{ signalStatusTag(trace.signal_status).text }}</ElTag></div>
            <div class="ld-trace-layers">
              <div v-for="(line, i) in formatLayerTrace(trace.layer_trace)" :key="i" class="ld-trace-line">{{ line }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无信号链路数据</div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>

    <!-- 单只股票扫描链路弹窗 -->
    <ElDialog v-model="scanTraceVisible" title="🧪 扫描链路 — {{ scanTraceCode }}" width="700px">
      <div v-if="scanTraceData" class="scan-trace">
        <div v-if="scanTraceData.status === 'not_found'" class="empty">{{ scanTraceData.message }}</div>
        <div v-else>
          <div class="st-header">
            <span class="code">{{ scanTraceData.ts_code }}</span>
            <span class="name">{{ scanTraceData.stock_name }}</span>
            <ElTag size="small" :type="signalStatusTag(scanTraceData.signal_status).type">{{ signalStatusTag(scanTraceData.signal_status).text }}</ElTag>
            <span :class="scanTraceData.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ scanTraceData.pct_chg >= 0 ? '+' : '' }}{{ scanTraceData.pct_chg?.toFixed(1) }}%</span>
          </div>
          <div class="st-reason">{{ scanTraceData.reason }}</div>
          <div v-if="scanTraceData.age_seconds" class="st-age">信号年龄: {{ scanTraceData.age_seconds }}秒</div>
          <div v-if="scanTraceData.layer_trace" class="st-trace">
            <div class="st-title">逐层筛选链路</div>
            <div v-for="(line, i) in formatLayerTrace(scanTraceData.layer_trace)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.decision_detail" class="st-detail">
            <div class="st-title">决策详情</div>
            <div v-for="(line, i) in formatDecisionDetail(scanTraceData.decision_detail)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.factors" class="st-factors">
            <div class="st-title">关键因子</div>
            <div class="st-fg">
              <div v-for="(v, k) in scanTraceData.factors" :key="k" class="st-fi"><span class="st-fl">{{ factorLabel(k) }}</span><span class="st-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">加载中...</div>
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

    <!-- 【P1-6】复盘报告弹窗 -->
    <ElDialog v-model="dailyReportVisible" title="📈 每日复盘报告" width="750px">
      <div v-if="dailyReport" class="dr">
        <div class="dr-sec"><div class="dr-t">💰 账户概览</div><div class="dr-g"><div class="dr-i"><span class="dr-l">总资产</span><span class="dr-v">{{ (dailyReport.account.total_assets / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">可用</span><span class="dr-v">{{ (dailyReport.account.available_cash / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">仓位</span><span class="dr-v">{{ dailyReport.account.position_ratio }}%</span></div><div class="dr-i"><span class="dr-l">今日盈亏</span><span class="dr-v" :class="dailyReport.account.today_profit >= 0 ? 'up' : 'down'">{{ dailyReport.account.today_profit >= 0 ? '+' : '' }}{{ dailyReport.account.today_profit.toFixed(0) }}</span></div></div></div>
        <div class="dr-sec"><div class="dr-t">📊 持仓概况</div><div class="dr-g"><div class="dr-i"><span class="dr-l">持仓数</span><span class="dr-v">{{ dailyReport.positions.count }}</span></div><div class="dr-i"><span class="dr-l">止损</span><span class="dr-v text-stock-up">{{ dailyReport.stop_loss_count }}</span></div><div class="dr-i"><span class="dr-l">止盈</span><span class="dr-v text-stock-down">{{ dailyReport.take_profit_count }}</span></div><div class="dr-i"><span class="dr-l">胜率</span><span class="dr-v">{{ dailyReport.win_rate }}%</span></div></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_profit?.length"><div class="dr-t">🏆 最赚</div><div v-for="p in dailyReport.positions.top_profit" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="up">+{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_loss?.length"><div class="dr-t">💀 最亏</div><div v-for="p in dailyReport.positions.top_loss" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="down">{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in dailyReport.positions.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.count }}只</span><span :class="(s.total_profit || s.total_pnl || 0) >= 0 ? 'up' : 'down'">¥{{ (s.total_profit || s.total_pnl || 0) >= 0 ? '+' : '' }}{{ (s.total_profit || s.total_pnl || 0).toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无复盘数据</div>
    </ElDialog>

    <!-- 周报弹窗 -->
    <ElDialog v-model="weeklyReportVisible" title="📊 周报 — 最近5个交易日" width="800px">
      <div v-if="weeklyReportData" class="wr">
        <div class="wr-sec"><div class="wr-t">💰 账户状态</div><div class="wr-g"><div class="wr-i"><span class="wr-l">总资产</span><span class="wr-v">{{ (weeklyReportData.account?.total_assets / 10000 || 0).toFixed(1) }}万</span></div><div class="wr-i"><span class="wr-l">累计盈亏</span><span class="wr-v" :class="weeklyReportData.account?.total_profit >= 0 ? 'up' : 'down'">{{ weeklyReportData.account?.total_profit >= 0 ? '+' : '' }}{{ (weeklyReportData.account?.total_profit || 0).toFixed(0) }}</span></div><div class="wr-i"><span class="wr-l">可用现金</span><span class="wr-v">{{ (weeklyReportData.account?.available_cash / 10000 || 0).toFixed(1) }}万</span></div></div></div>
        <div class="wr-sec"><div class="wr-t">📈 交易统计</div><div class="wr-g"><div class="wr-i"><span class="wr-l">交易日</span><span class="wr-v">{{ weeklyReportData.totals?.trading_days || 0 }}天</span></div><div class="wr-i"><span class="wr-l">买入</span><span class="wr-v">{{ weeklyReportData.totals?.total_buys || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">卖出</span><span class="wr-v">{{ weeklyReportData.totals?.total_sells || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">净流入</span><span class="wr-v" :class="weeklyReportData.totals?.net_flow >= 0 ? 'up' : 'down'">{{ (weeklyReportData.totals?.net_flow || 0).toFixed(0) }}</span></div></div></div>
        <div class="wr-sec" v-if="weeklyReportData.strategy_summary"><div class="wr-t">📋 策略汇总</div><div v-for="(s, k) in weeklyReportData.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.trades }}笔</span><span :class="s.amount >= 0 ? 'up' : 'down'">¥{{ s.amount >= 0 ? '+' : '' }}{{ s.amount.toFixed(0) }}</span></div></div>
        <div class="wr-sec" v-if="weeklyReportData.daily_stats"><div class="wr-t">📅 每日明细</div><div v-for="(stats, date) in weeklyReportData.daily_stats" class="wr-day"><span class="wr-date">{{ date }}</span><span>买{{ stats.buys }}卖{{ stats.sells }}</span><span :class="stats.sell_amount - stats.buy_amount >= 0 ? 'up' : 'down'">¥{{ (stats.sell_amount - stats.buy_amount).toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无周报数据</div>
    </ElDialog>
    <!-- ==================== 🌅 盘前竞价Tab ==================== -->
    <div v-if="activeTab === 'premarket'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 状态栏 -->
        <div class="pm-status-bar">
          <div class="pm-status-icon">{{ premarketStatus === 'active' ? '🔴' : premarketStatus === 'ended' ? '✅' : premarketStatus === 'waiting' ? '⏳' : premarketStatus === 'debug' ? '🧪' : '💤' }}</div>
          <div class="pm-status-text">
            <div class="pm-status-title">{{ {active: '竞价进行中', ended: '竞价已结束', waiting: '等待竞价(9:15)', debug: '🧪 调试预选模式', off: '非交易时间'}[premarketStatus] }} <span v-if="premarketDebugMode" class="pm-debug-badge">SIM</span></div>
            <div class="pm-status-sub">{{ premarketDebugMode ? '日级因子模拟 · 不影响实盘' : premarketCandidates.length + '只候选 · ' + premarketStrategyGroups.length + '个策略' }}</div>
          </div>
          <div class="pm-status-actions">
            <ElButton size="small" @click="fetchPremarketData">🔄</ElButton>
            <button :class="['pm-mode-btn', premarketDebugMode ? 'active' : '']" @click="premarketDebugMode = !premarketDebugMode; fetchPremarketData()" title="用日级因子模拟盘前预选(非交易时间可用)">🧪 调试</button>
            <button :class="['pm-mode-btn', premarketGroupMode === 'strategy' ? 'active' : '']" @click="premarketGroupMode = 'strategy'">按策略</button>
            <button :class="['pm-mode-btn', premarketGroupMode === 'list' ? 'active' : '']" @click="premarketGroupMode = 'list'">列表</button>
          </div>
        </div>

        <!-- 情绪+市场快照 -->
        <div class="pm-overview">
          <div class="pm-ov-card pm-sentiment">
            <div class="pm-ov-label">🌡️ 情绪周期</div>
            <div class="pm-ov-val" :class="premarketSentiment.score >= 55 ? 'up' : premarketSentiment.score < 40 ? 'down' : ''">
              {{ premarketSentiment.phase_name || '震荡' }}
              <span class="pm-ov-sub">{{ premarketSentiment.score }}分</span>
            </div>
            <div class="pm-ov-hint">仓位系数 {{ ((premarketSentiment.position_ratio || 0.5) * 100).toFixed(0) }}%</div>
          </div>
          <div class="pm-ov-card">
            <div class="pm-ov-label">📈 涨/跌</div>
            <div class="pm-ov-row">
              <span class="up">{{ premarketMarketSnapshot.up_count || 0 }}</span>
              <span class="pm-ov-sep">/</span>
              <span class="down">{{ premarketMarketSnapshot.down_count || 0 }}</span>
            </div>
            <div class="pm-ov-hint">均幅 {{ (premarketMarketSnapshot.avg_pct_chg || 0).toFixed(2) }}%<span v-if="premarketMarketSnapshot.data_date"> ({{ premarketMarketSnapshot.data_date.slice(4,6) }}/{{ premarketMarketSnapshot.data_date.slice(6,8) }}数据)</span></div>
          </div>
          <div class="pm-ov-card">
            <div class="pm-ov-label">🔴 涨停/跌停</div>
            <div class="pm-ov-row">
              <span class="up">{{ premarketMarketSnapshot.limit_up_count || 0 }}</span>
              <span class="pm-ov-sep">/</span>
              <span class="down">{{ premarketMarketSnapshot.limit_down_count || 0 }}</span>
            </div>
            <div class="pm-ov-hint">量比>2: {{ premarketMarketSnapshot.volume_ratio_gt2 || 0 }}只</div>
          </div>
          <div class="pm-ov-card">
            <div class="pm-ov-label">🎯 信号数</div>
            <div class="pm-ov-val">{{ premarketCandidates.length }}</div>
            <div class="pm-ov-hint">已执行 {{ premarketCandidates.filter(c => c.signal_status === 'executed').length }} | blocked {{ premarketCandidates.filter(c => c.signal_status === 'blocked' || c.signal_status === 'skipped').length }}</div>
          </div>
        </div>

        <!-- 漏斗+Blocked原因(调试模式) -->
        <div v-if="premarketDebugMode && (premarketFunnel.total_scanned || Object.keys(premarketBlockedReasons).length)" class="pm-debug-panel">
          <div class="pm-dp-title">📊 9层漏斗</div>
          <div class="pm-funnel">
            <div class="pm-funnel-step">
              <span class="pm-fs-label">全市场</span>
              <span class="pm-fs-val">{{ premarketFunnel.total_scanned || 0 }}</span>
            </div>
            <div class="pm-funnel-arrow">→</div>
            <div class="pm-funnel-step">
              <span class="pm-fs-label">策略候选</span>
              <span class="pm-fs-val">{{ premarketFunnel.strategy_candidates || 0 }}</span>
            </div>
            <div class="pm-funnel-arrow">→</div>
            <div class="pm-funnel-step">
              <span class="pm-fs-label">9层通过</span>
              <span class="pm-fs-val up">{{ premarketFunnel.after_pipeline || 0 }}</span>
            </div>
            <div class="pm-funnel-arrow">→</div>
            <div class="pm-funnel-step">
              <span class="pm-fs-label">blocked</span>
              <span class="pm-fs-val warn">{{ premarketFunnel.blocked || 0 }}</span>
            </div>
            <div class="pm-funnel-arrow">→</div>
            <div class="pm-funnel-step">
              <span class="pm-fs-label">已买</span>
              <span class="pm-fs-val" style="color:var(--el-color-success)">{{ premarketFunnel.executed || 0 }}</span>
            </div>
          </div>
          <div v-if="Object.keys(premarketBlockedReasons).length" class="pm-blocked-reasons">
            <div class="pm-dp-title">🚫 Blocked原因</div>
            <div v-for="(count, reason) in premarketBlockedReasons" :key="reason" class="pm-br-item">
              <span class="pm-br-reason">{{ reason }}</span>
              <span class="pm-br-count">{{ count }}笔</span>
            </div>
          </div>
        </div>

        <!-- 盘前综合分析 -->
        <div v-if="premarketAnalysis" class="pm-analysis">
          <div class="pm-analysis-head">
            <span class="pm-analysis-icon">🧠</span>
            <span class="pm-analysis-title">盘前综合研判</span>
            <span class="pm-analysis-date" v-if="premarketAnalysis.data_date">{{ premarketAnalysis.data_date.slice(4,6) }}/{{ premarketAnalysis.data_date.slice(6,8) }}数据</span>
          </div>
          <!-- 核心结论 -->
          <div class="pm-conclusion" :class="premarketAnalysis.verdict">
            <span class="pm-verdict-icon">{{ premarketAnalysis.verdict === 'bullish' ? '🟢' : premarketAnalysis.verdict === 'bearish' ? '🔴' : '🟡' }}</span>
            <span class="pm-verdict-text">{{ premarketAnalysis.conclusion }}</span>
          </div>
          <!-- 判断依据 -->
          <div class="pm-reasons">
            <div v-for="(r, i) in premarketAnalysis.reasons" :key="i" class="pm-reason-item">
              <span class="pm-reason-icon">{{ r.icon }}</span>
              <span class="pm-reason-text">{{ r.text }}</span>
            </div>
          </div>
          <!-- 操作建议 -->
          <div v-if="premarketAnalysis.suggestion" class="pm-suggestion">
            <span class="pm-sugg-label">💡 建议</span>
            <span class="pm-sugg-text">{{ premarketAnalysis.suggestion }}</span>
          </div>
        </div>

        <!-- 涨停池+连板分布+板块热力 -->
        <div class="pm-zt-section">
          <div class="pm-zt-header">
            <div class="st">🔴 涨停池 <span class="text-tertiary" style="font-size:10px">({{ premarketLimitPools.up_count || 0 }}只)</span></div>
            <div class="st">🟢 跌停池 <span class="text-tertiary" style="font-size:10px">({{ premarketLimitPools.down_count || 0 }}只)</span></div>
          </div>
          <div class="pm-zt-body">
            <!-- 连板分布 -->
            <div v-if="premarketLimitPools.continue_stats && Object.keys(premarketLimitPools.continue_stats).length" class="pm-continue-bar">
              <span class="pm-cb-label">连板</span>
              <template v-for="(count, boards) in premarketLimitPools.continue_stats" :key="boards">
                <span class="pm-cb-item" :class="Number(boards) >= 3 ? 'hot' : ''">{{ boards }}板×{{ count }}</span>
              </template>
            </div>
            <!-- 板块热力 -->
            <div v-if="premarketLimitPools.sector_heat && premarketLimitPools.sector_heat.length" class="pm-sector-heat">
              <span class="pm-sh-label">板块</span>
              <span v-for="s in premarketLimitPools.sector_heat.slice(0, 8)" :key="s.name" class="pm-sh-item" :class="s.count >= 3 ? 'hot' : ''">
                {{ s.name }}<sub>{{ s.count }}</sub>
              </span>
            </div>
            <!-- 涨停列表(折叠) -->
            <div v-if="premarketLimitPools.limit_up_list && premarketLimitPools.limit_up_list.length" class="pm-zt-list">
              <div class="pm-zt-toggle cp" @click="premarketGroupExpanded['limit_up'] = !premarketGroupExpanded['limit_up']">
                {{ premarketGroupExpanded['limit_up'] ? '▼' : '▶' }} 涨停明细 {{ premarketLimitPools.limit_up_list.length }}只
              </div>
              <div v-if="premarketGroupExpanded['limit_up']" class="pm-zt-items">
                <span v-for="z in premarketLimitPools.limit_up_list" :key="z.ts_code" class="pm-zt-tag" :class="z.open_times > 0 ? 'broken' : 'sealed'">
                  {{ z.name }}<sub v-if="z.open_times > 0">炸</sub>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 持仓竞价影响 -->
        <div v-if="premarketPositionGaps && premarketPositionGaps.length" class="pm-pos-gap-section">
          <div class="st">💼 持仓竞价影响</div>
          <div class="pm-pos-gaps">
            <div v-for="p in premarketPositionGaps" :key="p.ts_code" class="pm-pg-item" :class="p.gap_pct >= 0 ? 'gap-up' : 'gap-down'">
              <span class="pm-pg-name">{{ p.stock_name }}</span>
              <span class="pm-pg-gap" :class="p.gap_pct >= 0 ? 'up' : 'down'">{{ p.gap_pct >= 0 ? '⬆' : '⬇' }} {{ p.gap_pct >= 0 ? '+' : '' }}{{ p.gap_pct.toFixed(1) }}%</span>
              <span class="pm-pg-hint">{{ p.gap_pct > 3 ? '强势高开' : p.gap_pct < -2 ? '⚠️风险低开' : '正常' }}</span>
            </div>
          </div>
        </div>

        <!-- 策略分组模式 -->
        <div v-if="premarketGroupMode === 'strategy'" class="pm-groups">
          <div v-for="g in premarketStrategyGroups" :key="g.strategy" class="pm-group">
            <div class="pm-group-header cp" @click="premarketGroupExpanded[g.strategy] = !premarketGroupExpanded[g.strategy]">
              <span class="pm-group-toggle">{{ premarketGroupExpanded[g.strategy] ? '▼' : '▶' }}</span>
              <ElTag size="small" :color="strategyMeta[g.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(g.strategy) }}</ElTag>
              <span class="pm-group-stat">{{ g.count }}只</span>
              <span class="pm-group-stat" :class="g.avg_pct_chg >= 0 ? 'up' : 'down'">均幅 {{ g.avg_pct_chg >= 0 ? '+' : '' }}{{ g.avg_pct_chg.toFixed(1) }}%</span>
              <span v-if="g.executed" class="pm-group-stat executed">已买{{ g.executed }}</span>
              <span v-if="g.blocked" class="pm-group-stat warn">blocked {{ g.blocked }}</span>
              <span v-if="premarketHitRate[g.strategy]" class="pm-group-stat hit-rate" :class="premarketHitRate[g.strategy].win_rate >= 60 ? 'up' : 'warn'">
                历史 {{ premarketHitRate[g.strategy].win_rate }}%胜 / {{ premarketHitRate[g.strategy].total }}笔
              </span>
              <span class="pm-group-preview">{{ g.candidates.slice(0, 3).map(c => (c.stock_name || c.ts_code?.slice(0,6)) + ' ' + (c.pct_chg >= 0 ? '+' : '') + c.pct_chg.toFixed(1) + '%').join(' · ') }}{{ g.count > 3 ? ' ...' : '' }}</span>
            </div>
            <div v-if="premarketGroupExpanded[g.strategy]" class="pm-group-list">
              <div v-for="c in g.candidates" :key="c.ts_code + c.strategy" class="pm-item">
                <span class="pm-item-code">{{ c.ts_code?.slice(0,6) }}</span>
                <span class="pm-item-name">{{ c.stock_name }}</span>
                <span :class="c.pct_chg >= 0 ? 'up' : 'down'" class="pm-item-pct">{{ c.pct_chg >= 0 ? '+' : '' }}{{ (c.pct_chg || 0).toFixed(1) }}%</span>
                <span v-if="c.volume_ratio" class="pm-item-factor">量比{{ c.volume_ratio.toFixed(1) }}</span>
                <span v-if="c.turnover_rate" class="pm-item-factor">换手{{ c.turnover_rate.toFixed(1) }}%</span>
                <ElTag v-if="c.signal_status === 'executed'" size="small" type="success" style="font-size:9px">已买</ElTag>
                <ElTag v-else-if="c.signal_status === 'skipped'" size="small" type="warning" style="font-size:9px">跳过</ElTag>
                <ElTag v-else-if="c.signal_status === 'preview'" size="small" type="info" style="font-size:9px">预览</ElTag>
                <ElButton v-if="c.signal_status === 'new' && !dryRun" size="small" type="danger" plain class="btn-xs" @click="quickBuy(c)">买</ElButton>
                <span v-if="c.reason" class="pm-item-reason">{{ c.reason }}</span>
              </div>
            </div>
          </div>
          <div v-if="!premarketStrategyGroups.length" class="pm-empty-state">
            <div class="pm-empty-icon">📋</div>
            <div class="pm-empty-text">{{ premarketDebugMode ? '无日级因子数据，请启动扫描器后再试' : '9:00后自动生成盘前预选' }}</div>
            <div class="pm-empty-hint">{{ premarketDebugMode ? '调试模式使用daily_factors_df模拟策略扫描' : 'Scanner启动后，竞价阶段自动扫描全市场候选' }}</div>
          </div>
        </div>

        <!-- 列表模式 -->
        <div v-if="premarketGroupMode === 'list'" class="pm-list-mode">
          <div class="pm-table-header">
            <span>代码</span><span>名称</span><span>策略</span><span>涨幅</span><span>量比</span><span>换手</span><span>状态</span><span>操作</span>
          </div>
          <div v-for="c in premarketCandidates" :key="c.ts_code + c.strategy" class="pm-table-row">
            <span class="code">{{ c.ts_code?.slice(0,6) }}</span>
            <span class="name">{{ c.stock_name }}</span>
            <ElTag size="small" :color="strategyMeta[c.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:9px">{{ strategyCN(c.strategy) }}</ElTag>
            <span :class="c.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (c.pct_chg || 0) >= 0 ? '+' : '' }}{{ (c.pct_chg || 0).toFixed(1) }}%</span>
            <span :class="(c.volume_ratio || 0) >= 2 ? 'up' : ''">{{ (c.volume_ratio || 0).toFixed(1) }}</span>
            <span :class="(c.turnover_rate || 0) >= 3 ? 'up' : ''">{{ (c.turnover_rate || 0).toFixed(1) }}%</span>
            <ElTag v-if="c.signal_status === 'executed'" size="small" type="success" style="font-size:9px">已买</ElTag>
            <ElTag v-else-if="c.signal_status === 'skipped'" size="small" type="warning" style="font-size:9px">跳过</ElTag>
            <ElTag v-else-if="c.signal_status === 'new'" size="small" type="danger" style="font-size:9px">新</ElTag>
            <span v-else class="text-tertiary" style="font-size:10px">{{ c.signal_status }}</span>
            <ElButton v-if="c.signal_status === 'new' && !dryRun" size="small" type="danger" plain class="btn-xs" @click="quickBuy(c)">买</ElButton>
          </div>
          <div v-if="!premarketCandidates.length" class="pm-empty-state">
            <div class="pm-empty-icon">📋</div>
            <div class="pm-empty-text">9:00后自动生成盘前预选</div>
          </div>
        </div>

        <!-- 竞价异动 -->
        <div v-if="auctionTopGainers.length" class="pm-auction-section">
          <div class="st">⚡ 竞价涨幅TOP <span class="text-tertiary" style="font-size:10px">({{ auctionTopGainers.length }}只)</span></div>
          <div class="pm-auction-grid">
            <div v-for="g in auctionTopGainers" :key="g.ts_code" class="pm-auction-item">
              <span class="code">{{ g.ts_code?.slice(0,6) }}</span>
              <span class="name">{{ g.name }}</span>
              <span :class="g.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:700;font-size:14px">{{ g.pct_chg >= 0 ? '+' : '' }}{{ g.pct_chg.toFixed(1) }}%</span>
              <span v-if="g.volume_ratio" class="pm-item-factor">量比{{ g.volume_ratio.toFixed(1) }}</span>
            </div>
          </div>
        </div>

        <!-- 竞价信号 -->
        <div v-if="premarketSignals.length" class="pm-signal-section">
          <div class="st">🎯 竞价过滤信号 <span class="text-tertiary" style="font-size:10px">(通过竞价筛选)</span></div>
          <div class="pm-signal-list">
            <div v-for="s in premarketSignals" :key="s.ts_code" class="pm-signal-item">
              <ElTag size="small" :color="strategyMeta[s.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(s.strategy) }}</ElTag>
              <span class="code">{{ s.ts_code?.slice(0,6) }}</span>
              <span class="name">{{ s.stock_name }}</span>
              <span :class="s.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ s.pct_chg >= 0 ? '+' : '' }}{{ s.pct_chg.toFixed(1) }}%</span>
              <span v-if="s.volume_ratio" class="pm-item-factor">量比{{ s.volume_ratio.toFixed(1) }}</span>
              <ElTag v-if="s.signal_status === 'executed'" size="small" type="success">已买</ElTag>
              <ElButton v-else-if="!dryRun" size="small" type="danger" plain class="btn-xs" @click="quickBuy(s)">买</ElButton>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 🔍 扫描追踪Tab ==================== -->
    <div v-if="activeTab === 'scan-trace'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 顶部: 扫描历史列表(单行紧凑) -->
        <div class="st">📡 扫描历史
          <ElDatePicker v-model="scanTraceDate" type="date" placeholder="选择日期查看" size="small" value-format="YYYY-MM-DD" style="width:130px;margin-left:8px" :disabled-date="(d: Date) => d > new Date()" :cell-class-name="scanDateCellClass" :teleported="false" @change="fetchScanHistory" />
          <ElButton v-if="scanTraceDate" size="small" @click="scanTraceDate='';scanHistory=[];scanTraceDetail=null" :loading="scanHistoryLoading">✕ 清除</ElButton>
          <span class="text-tertiary" style="font-size:11px;margin-left:auto">扫描5分钟 · 持仓30秒 · <span style="opacity:0.7">全市场扫→策略候选→通过筛选</span> · <span style="color:var(--el-color-primary)">●</span>交易日 <span style="color:#e6a23c">●</span>调试</span>
        </div>
        <div v-if="!scanTraceDate" class="empty" style="padding:12px 0;color:var(--text-tertiary)">📅 请在上方选择日期查看扫描记录（高亮日期有数据）</div>
        <div v-else-if="scanHistoryLoading" class="empty" style="padding:8px 0">加载中...</div>
        <div v-else-if="!scanHistory.length" class="empty" style="padding:8px 0">该日暂无扫描记录</div>
        <div v-else>
          <div style="font-size:12px;color:var(--el-color-primary);font-weight:600;margin-bottom:4px">📅 {{ scanTraceDate }} 的扫描记录（共{{ scanHistory.length }}条）</div>
          <div class="scan-hours">
            <div v-for="(group, gi) in scanHistoryByHour" :key="gi" class="sc-hour-group">
              <div class="sc-hour-header" @click="toggleScanHour(group.hour)">
                <span class="sc-hour-toggle">{{ group.collapsed ? '▶' : '▽' }}</span>
                <span class="sc-hour-label">{{ group.hour }}:00</span>
                <span class="sc-hour-count">{{ group.items.length }}条</span>
                <span v-if="group.collapsed" class="sc-hour-summary">最新 {{ group.items[group.items.length-1]?.summary?.passed || 0 }}只通过</span>
              </div>
              <div v-show="!group.collapsed" class="scan-strip">
                <div v-for="(s, i) in group.items" :key="group.hour + '-' + i" class="scan-chip" :class="{ active: selectedScanIdx === scanHistory.indexOf(s), debug: s.is_debug }" @click="selectedScanIdx = scanHistory.indexOf(s); fetchScanTrace(s.scan_id || '')">
                  <span class="sc-time">{{ (s.scan_time || s.time || '').substring(11, 19) || '--:--' }}</span>
                  <span v-if="s.is_debug" class="sc-debug-tag">调试</span>
                  <span class="sc-stats" :title="`全市场扫描${s.summary?.total_candidates || s.candidates || 0}只 → 通过9层筛选${s.summary?.passed || s.signals || 0}只 → 实际买入${s.buys || 0}只`">
                    <span class="ss-all">{{ s.summary?.total_candidates || s.candidates || 0 }}</span><span class="ss-arr">▶</span><span class="ss-pass">{{ s.summary?.passed || s.signals || 0 }}</span><span class="ss-arr">▶</span><span class="ss-buy" :class="(s.buys || 0) > 0 ? 'has-buy' : ''">{{ s.buys || 0 }}</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="scanTraceDetail" class="scan-funnel">
          <template v-for="(layerData, layerName, idx) in scanTraceDetail.summary || {}">
            <div v-if="layerName !== 'total_candidates' && layerName !== 'passed' && layerName !== 'rejected' && typeof layerData === 'object'" :key="layerName" class="fn-row" :class="{ 'fn-filter': layerData.rejected > 0, 'fn-pass': !layerData.rejected && (layerData.input || 0) > 0 }">
              <span class="fn-tag">{{ layerLabel(layerName) }}</span>
              <span class="fn-flow">{{ (layerData.input || 0) === 0 && (layerData.output || 0) === 0 && !layerData.rejected ? '—' : (layerData.input || 0) + '→' + (layerData.output || 0) }}</span>
              <span v-if="layerData.rejected" class="fn-rej">淘汰{{ layerData.rejected }}</span>
              <span class="fn-desc">{{ scanTraceDetail.layer_details?.[layerName] || layerDesc(layerName, layerData) || '' }}</span>
            </div>
          </template>
          <div v-if="scanTraceDetail._pagination" class="fn-total">✅ 通过{{ scanTraceDetail._pagination.passed_count }} / ❌ 淘汰{{ scanTraceDetail._pagination.rejected_count }}</div>
        </div>

        <!-- 底部: 候选追踪(主区域) -->
        <div v-if="scanTraceDetail" style="margin-top:8px">
          <div class="st" style="display:flex;align-items:center;gap:8px">
            <span>🎯 候选追踪</span>
            <div style="display:flex;gap:4px;margin-left:auto">
              <button :class="['tab-btn-sm', scanTraceFilter === 'passed' ? 'active' : '']" @click="switchScanTraceFilter('passed')" :disabled="scanTraceLoadingMore">✅ 通过({{ scanTraceDetail._pagination?.passed_count || 0 }})</button>
              <button :class="['tab-btn-sm', scanTraceFilter === 'rejected' ? 'active' : '']" @click="switchScanTraceFilter('rejected')" :disabled="scanTraceLoadingMore">❌ 淘汰({{ scanTraceDetail._pagination?.rejected_count || 0 }})</button>
              <button :class="['tab-btn-sm', scanTraceFilter === 'summary' ? 'active' : '']" @click="switchScanTraceFilter('summary')">📊 统计</button>
            </div>
          </div>

          <!-- 淘汰统计视图 -->
          <div v-if="scanTraceFilter === 'summary' && scanTraceDetail.rejected_layer_stats" class="rejected-stats">
            <div v-for="(count, layer) in scanTraceDetail.rejected_layer_stats" :key="layer" class="rs-row">
              <span class="rs-label">{{ rejectionLayerCN[layer] || layer }}</span>
              <div class="rs-bar-track"><div class="rs-bar-fill" :style="{ width: Math.min(count / (scanTraceDetail._pagination?.rejected_count || 1) * 100, 100) + '%' }"></div></div>
              <span class="rs-count">{{ count }}只</span>
            </div>
          </div>

          <!-- 候选列表 -->
          <div v-if="scanTraceFilter !== 'summary'">
            <div v-if="scanTraceLoadingMore" class="empty">加载中...</div>
            <div v-else-if="!scanTraceDetail.candidates?.length" class="empty">{{ scanTraceFilter === 'passed' ? '本轮无通过候选' : '无淘汰候选' }}</div>
            <div class="et-wrap">
              <div v-for="sig in scanTraceDetail.candidates || []" :key="sig.ts_code + sig.strategy" class="et-item" :class="sig.final_status === 'passed' ? 'et-pass' : 'et-fail'">
                <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:9px;min-width:28px;padding:0 2px">{{ strategyCN(sig.strategy) }}</ElTag>
                <span class="code">{{ sig.ts_code }}</span>
                <span class="name">{{ sig.stock_name }}</span>
                <span :class="sig.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ (sig.pct_chg || 0).toFixed(1) }}%</span>
                <span v-if="sig.final_status === 'passed'" class="et-ok">✅</span>
                <span v-else class="et-no">❌{{ rejectionLayerCN[sig.rejection_layer] || sig.rejection_layer }}</span>
              </div>
            </div>
            <div v-if="scanTraceDetail._pagination && (scanTraceDetail._pagination.has_more_passed || scanTraceDetail._pagination.has_more_rejected)" class="load-more-hint">
              <span class="text-tertiary" style="font-size:11px">已显示{{ scanTraceDetail._pagination.returned_count }}条 / 共{{ scanTraceFilter === 'passed' ? scanTraceDetail._pagination.passed_count : scanTraceDetail._pagination.rejected_count }}条</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 📋 复盘Tab (专业版) ==================== -->
    <div v-if="activeTab === 'review'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 日期/周期选择 -->
        <div class="review-header">
          <div class="review-tabs">
            <button :class="['review-tab', reviewTab === 'daily' ? 'active' : '']" @click="reviewTab = 'daily'; fetchReviewData()">📊 日复盘</button>
            <button :class="['review-tab', reviewTab === 'weekly' ? 'active' : '']" @click="reviewTab = 'weekly'; fetchReviewData()">📅 周复盘</button>
            <button :class="['review-tab', reviewTab === 'monthly' ? 'active' : '']" @click="reviewTab = 'monthly'; fetchReviewData()">📆 月复盘</button>
          </div>
          <ElDatePicker v-model="reviewDate" type="date" size="small" value-format="YYYY-MM-DD" @change="fetchReviewData" />
          <ElButton size="small" @click="fetchReviewData" :loading="reviewLoading">🔄</ElButton>
        </div>

        <!-- ============ 第1层: Hero Banner ============ -->
        <div v-if="reviewHero" class="hero-banner" :class="reviewHero.conclusion_type">
          <div class="hero-conclusion">{{ reviewHero.conclusion }}</div>
          <div class="hero-meta">
            <span v-if="reviewHero.benchmark" class="hero-bench">📊 {{ reviewHero.benchmark.name }} {{ reviewHero.benchmark.pct_chg >= 0 ? '+' : '' }}{{ reviewHero.benchmark.pct_chg }}%</span>
            <span class="hero-alpha" :class="reviewHero.benchmark?.alpha >= 0 ? 'up' : 'down'">{{ reviewHero.benchmark?.alpha >= 0 ? '跑赢' : '落后' }} {{ Math.abs(reviewHero.benchmark?.alpha || 0) }}%</span>
            <span class="hero-sentiment">🌡️ {{ reviewHero.sentiment?.period }} {{ reviewHero.sentiment?.score }}分</span>
          </div>
        </div>

        <!-- ============ 第2层: 核心仪表盘 ============ -->
        <div v-if="reviewHero" class="review-scorecard">
          <div class="rsc"><div class="rsc-label">收益</div><div class="rsc-value" :class="reviewHero.metrics.total_pct >= 0 ? 'up' : 'down'">{{ reviewHero.metrics.total_pct >= 0 ? '+' : '' }}{{ reviewHero.metrics.total_pct }}%</div></div>
          <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ reviewHero.metrics.win_rate }}%</div></div>
          <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ reviewHero.metrics.trades }}笔</div></div>
          <div class="rsc"><div class="rsc-label">期望值</div><div class="rsc-value" :class="reviewHero.metrics.expectancy >= 0 ? 'up' : 'down'">{{ reviewHero.metrics.expectancy }}</div></div>
          <div class="rsc"><div class="rsc-label">纪律分</div><div class="rsc-value" :class="reviewHero.metrics.discipline_score >= 80 ? 'up' : reviewHero.metrics.discipline_score >= 60 ? '' : 'down'">{{ reviewHero.metrics.discipline_score }}</div></div>
          <div class="rsc"><div class="rsc-label">盈亏比</div><div class="rsc-value">{{ reviewHero.metrics.profit_loss_ratio }}</div></div>
          <div class="rsc"><div class="rsc-label">止损</div><div class="rsc-value down">{{ reviewHero.metrics.stop_loss_count }}</div></div>
          <div class="rsc"><div class="rsc-label">止盈</div><div class="rsc-value up">{{ reviewHero.metrics.take_profit_count }}</div></div>
          <div class="rsc"><div class="rsc-label">连亏</div><div class="rsc-value" :class="reviewHero.metrics.max_consecutive_loss >= 3 ? 'down' : ''">{{ reviewHero.metrics.max_consecutive_loss }}笔</div></div>
        </div>

        <!-- ============ 第3层: 归因分析 ============ -->
        <template v-if="reviewTab === 'daily' && dailyReportData">
          <!-- 策略贡献 -->
          <div class="st" style="margin-top:12px">🎯 策略贡献</div>
          <div class="strategy-contrib">
            <div v-for="(data, key) in dailyReportData.positions?.strategy_summary || {}" :key="key" class="strat-card">
              <div class="strat-header">
                <ElTag size="small" :color="strategyMeta[key]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(key) }}</ElTag>
                <span class="strat-pnl" :class="(data.closed_profit || data.total_pnl || 0) >= 0 ? 'up' : 'down'">{{ (data.closed_profit || data.total_pnl || 0) >= 0 ? '+' : '' }}¥{{ (data.closed_profit || data.total_pnl || 0).toFixed(0) }}</span>
              </div>
              <div class="strat-metrics">
                <div class="strat-m"><span class="strat-ml">已平</span><span class="strat-mv">{{ data.closed_count || data.sell_count || 0 }}笔</span></div>
                <div class="strat-m"><span class="strat-ml">胜率</span><span class="strat-mv" :class="(data.closed_win_rate || data.win_rate || 0) >= 50 ? 'up' : 'down'">{{ (data.closed_win_rate || data.win_rate || 0).toFixed(0) }}%</span></div>
                <div class="strat-m" v-if="data.avg_win_pct"><span class="strat-ml">均盈</span><span class="strat-mv up">+{{ data.avg_win_pct }}%</span></div>
                <div class="strat-m" v-if="data.avg_loss_pct"><span class="strat-ml">均亏</span><span class="strat-mv down">{{ data.avg_loss_pct }}%</span></div>
                <div class="strat-m" v-if="data.stop_loss_count"><span class="strat-ml">止损</span><span class="strat-mv down">{{ data.stop_loss_count }}笔</span></div>
              </div>
            </div>
          </div>

          <!-- 逐笔归因 -->
          <div class="st" style="margin-top:12px">📝 逐笔归因 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">({{ tradeAttributions.length }}笔)</span></div>
          <div v-if="!tradeAttributions.length" class="empty">暂无交易数据</div>
          <div v-for="t in tradeAttributions" :key="t.ts_code + t.sell_time" class="attribution-card" :class="t.profit_pct >= 0 ? 'attr-profit' : 'attr-loss'">
            <div class="attr-top">
              <ElTag size="small" :color="strategyMeta[t.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(t.strategy) }}</ElTag>
              <span class="code">{{ t.ts_code }}</span>
              <span class="name">{{ t.stock_name }}</span>
              <span :class="t.profit_pct >= 0 ? 'up' : 'down'" class="pct ml-auto">{{ t.profit_pct >= 0 ? '+' : '' }}{{ t.profit_pct.toFixed(1) }}%</span>
            </div>
            <div class="attr-detail">
              <div class="attr-row"><span>买入</span><span>¥{{ t.buy_price?.toFixed(2) }} {{ t.buy_time }}</span></div>
              <div class="attr-row"><span>卖出</span><span>¥{{ t.sell_price?.toFixed(2) }} {{ t.sell_time }}</span></div>
              <div class="attr-row"><span>原因</span><span>{{ t.sell_reason }}</span></div>
              <div class="attr-row" v-if="t.why_profit"><span class="up">赚在哪</span><span>{{ t.why_profit }}</span></div>
              <div class="attr-row" v-if="t.why_loss"><span class="down">亏在哪</span><span>{{ t.why_loss }}</span></div>
            </div>
          </div>

          <!-- 扫描漏斗 -->
          <div class="st" style="margin-top:12px">📡 扫描漏斗</div>
          <div v-if="dailyReportData?.scanner_stats" class="review-scan-stats">
            <div class="rss-row"><span class="rss-label">扫描次数</span><span class="rss-value">{{ dailyReportData.scanner_stats.scan_count || 0 }}次</span></div>
            <div class="rss-row"><span class="rss-label">发现信号</span><span class="rss-value up">{{ dailyReportData.scanner_stats.total_signals || 0 }}只</span></div>
            <div class="rss-row"><span class="rss-label">实际买入</span><span class="rss-value">{{ dailyReportData.scanner_stats.buy_count || 0 }}笔</span></div>
            <div class="rss-row"><span class="rss-label">实际卖出</span><span class="rss-value">{{ dailyReportData.scanner_stats.sell_count || 0 }}笔</span></div>
          </div>
          <div v-if="dailyReportData?.sentiment_snapshot" class="review-sentiment-snap">
            <span style="font-weight:600">🌡️ 情绪快照</span>
            <span>{{ dailyReportData.sentiment_snapshot }}</span>
          </div>
        </template>

        <!-- 周复盘 -->
        <template v-if="reviewTab === 'weekly' && weeklyReportData">
          <div class="review-summary-cards">
            <div class="rsc"><div class="rsc-label">周收益</div><div class="rsc-value" :class="weeklyReportData.weekly_profit >= 0 ? 'up' : 'down'">¥{{ weeklyReportData.weekly_profit?.toFixed(0) }}</div></div>
            <div class="rsc"><div class="rsc-label">周胜率</div><div class="rsc-value">{{ weeklyReportData.win_rate }}%</div></div>
            <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ weeklyReportData.total_trades }}笔</div></div>
          </div>
          <div v-if="weeklyReportData.daily_breakdown" class="st" style="margin-top:12px">📅 逐日明细</div>
          <div v-if="weeklyReportData.daily_breakdown" class="weekly-daily-table">
            <div class="wdt-header"><span>日期</span><span>盈亏</span><span>交易</span><span>胜率</span><span>情绪</span></div>
            <div v-for="d in weeklyReportData.daily_breakdown" :key="d.date" class="wdt-row">
              <span>{{ d.date }}</span>
              <span :class="d.profit >= 0 ? 'up' : 'down'">{{ d.profit >= 0 ? '+' : '' }}¥{{ d.profit?.toFixed(0) }}</span>
              <span>{{ d.trades }}笔</span>
              <span>{{ d.win_rate }}%</span>
              <span>{{ d.sentiment || '-' }}</span>
            </div>
          </div>
        </template>

        <!-- 月复盘 -->
        <template v-if="reviewTab === 'monthly'">
          <!-- === 月复盘主区块 === -->
          <template v-if="monthlyReviewData">
            <div class="st" style="margin-top:12px">🔬 系统偏差 ({{ monthlyReviewData.period }})</div>
            <div class="review-scorecard" style="grid-template-columns:repeat(4,1fr)">
              <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ monthlyReviewData.summary?.trades || 0 }}笔</div></div>
              <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ monthlyReviewData.summary?.win_rate || 0 }}%</div></div>
              <div class="rsc"><div class="rsc-label">盈亏</div><div class="rsc-value" :class="monthlyReviewData.summary?.pnl >= 0 ? 'up' : 'down'">{{ monthlyReviewData.summary?.pnl >= 0 ? '+' : '' }}{{ monthlyReviewData.summary?.pnl || 0 }}%</div></div>
              <div class="rsc"><div class="rsc-label">连亏</div><div class="rsc-value">-</div></div>
            </div>

            <!-- 📈 偏差趋势折线(用weekly_trend数据绘制) -->
            <div class="st" style="margin-top:12px">📈 偏差趋势(近4周)</div>
            <div v-if="monthlyReviewData.weekly_trend?.length" class="deviation-trend-chart">
              <div class="trend-axis">
                <div v-for="w in monthlyReviewData.weekly_trend" :key="w.week" class="trend-col">
                  <div class="trend-bar" :style="{height: Math.min(w.win_rate, 100) + '%', background: w.win_rate >= 60 ? 'var(--color-up)' : w.win_rate >= 40 ? 'var(--color-warn, #e6a23c)' : 'var(--color-down)'}">
                    <span class="trend-val">{{ w.win_rate }}%</span>
                  </div>
                  <div class="trend-label">{{ w.week }}</div>
                  <div class="trend-sub">{{ w.trades }}笔</div>
                </div>
              </div>
            </div>
            <div v-else class="empty">无周度数据</div>

            <!-- ⚡ 行为漂移检测 -->
            <div class="st" style="margin-top:12px">⚡ 行为漂移检测</div>
            <div class="review-2col">
              <div class="dev-card">
                <div class="dev-title">🛡️ 止损执行率</div>
                <div class="dev-row"><span>亏损止损/总亏损</span><span :class="monthlyReviewData.behavior_drift?.stop_loss_execution_rate >= 90 ? 'up' : 'down'">{{ monthlyReviewData.behavior_drift?.stop_loss_execution_rate || 0 }}%</span></div>
                <div class="dev-row" style="font-size:11px;color:var(--text-tertiary)"><span>亏损止损{{ monthlyReviewData.behavior_drift?.stop_loss_at_loss || 0 }}笔 / 盈利止损{{ monthlyReviewData.behavior_drift?.stop_loss_at_profit || 0 }}笔</span></div>
              </div>
              <div class="dev-card">
                <div class="dev-title">❄️ 冰点期开仓率</div>
                <div class="dev-row"><span>冰点买入占比</span><span :class="monthlyReviewData.behavior_drift?.bearish_period_buy_ratio >= 30 ? 'down' : 'up'">{{ monthlyReviewData.behavior_drift?.bearish_period_buy_ratio || 0 }}%</span></div>
                <div class="dev-row"><span>冰点/总买入</span><span>{{ monthlyReviewData.behavior_drift?.bearish_buys || 0 }}/{{ monthlyReviewData.behavior_drift?.total_buys || 0 }}笔</span></div>
              </div>
            </div>

            <!-- 🗓️ 日历热力图(月度盈亏) -->
            <div class="st" style="margin-top:12px">🗓️ 日历热力图</div>
            <div v-if="monthlyReviewData.daily_breakdown?.length" class="calendar-heatmap">
              <div v-for="d in monthlyReviewData.daily_breakdown" :key="d.date" class="cal-cell" :class="d.pnl > 0 ? 'cal-up' : d.pnl < 0 ? 'cal-down' : 'cal-neutral'">
                <div class="cal-date">{{ d.date?.slice(-2) }}</div>
                <div class="cal-pnl">{{ d.pnl >= 0 ? '+' : '' }}{{ d.pnl }}%</div>
                <div class="cal-trades">{{ d.trades }}笔</div>
              </div>
            </div>
            <div v-else class="empty">无逐日数据</div>

            <!-- 🎯 策略贡献堆积图 -->
            <div class="st" style="margin-top:12px">🎯 策略月度贡献</div>
            <div class="strategy-stacked">
              <div v-for="(data, key) in monthlyReviewData.strategy_stats || {}" :key="key" class="stacked-bar" :style="{width: Math.max(Math.abs(data.pnl), 5) + '%', background: data.pnl >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
                <span class="stacked-label">{{ strategyCN(key) }}</span>
                <span class="stacked-val">{{ data.pnl >= 0 ? '+' : '' }}{{ data.pnl }}%</span>
              </div>
            </div>

            <!-- 🔧 参数漂移检测 -->
            <div class="st" style="margin-top:12px">🔧 参数漂移检测
              <ElButton size="small" @click="saveParamSnapshot" style="margin-left:8px">📸 保存当前快照</ElButton>
            </div>
            <div v-if="paramDriftData?.drifts?.length" class="violations-list">
              <div v-for="(d, i) in paramDriftData.drifts" :key="i" class="violation-item" :class="d.severity === 'high' ? 'sev-high' : 'sev-medium'">
                <span class="v-icon">{{ d.severity === 'high' ? '🔴' : '🟡' }}</span>
                <span class="v-type">{{ d.strategy || d.level }}</span>
                <span class="v-detail">{{ d.key }}: {{ d.old }} → {{ d.new }}</span>
              </div>
            </div>
            <div v-else class="empty">无参数漂移(快照基线: {{ paramDriftData?.start_date || '无' }})</div>
          </template>
          <div v-else class="empty">选择日期后查看月复盘</div>

          <!-- 📊 因子效果跟踪 -->
          <div class="st" style="margin-top:12px">📊 因子效果跟踪 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">(市场漂移检测)</span></div>
          <div v-if="factorEffectData" class="factor-effect-section">
            <div v-if="factorEffectData.drift_alerts?.length" class="violations-list" style="margin-bottom:8px">
              <div v-for="(a, i) in factorEffectData.drift_alerts" :key="i" class="violation-item sev-medium">
                <span class="v-icon">⚠️</span>
                <span class="v-type">{{ a.factor }}/{{ a.bucket }}</span>
                <span class="v-detail">{{ a.alert }}</span>
              </div>
            </div>
            <div v-for="(periods, fname) in factorEffectData.factor_stats || {}" :key="fname" class="factor-group">
              <div class="factor-name">{{ fname }}</div>
              <div v-for="(items, period) in periods" :key="period" class="factor-period">
                <div class="factor-period-label">{{ period }}</div>
                <div class="factor-bars">
                  <div v-for="it in items?.slice(0, 5)" :key="it.name" class="factor-bar-row">
                    <span class="fb-name">{{ it.name }}</span>
                    <div class="fb-bar-bg">
                      <div class="fb-bar-fill" :style="{width: it.total > 0 ? Math.min(it.win_rate, 100) + '%' : '0%'}" :class="it.win_rate >= 60 ? 'fb-up' : it.win_rate >= 40 ? 'fb-mid' : 'fb-down'"></div>
                    </div>
                    <span class="fb-wr" :class="it.win_rate >= 60 ? 'up' : 'down'">{{ it.win_rate }}%</span>
                    <span class="fb-cnt">({{ it.total }})</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty">无因子数据</div>

          <!-- 💡 闭环建议 -->
          <div class="st" style="margin-top:12px">💡 闭环建议 <span v-if="closedLoopData" style="font-weight:normal;font-size:11px;margin-left:6px" :class="closedLoopData.summary?.high > 0 ? 'down' : 'up'">{{ closedLoopData.summary?.high || 0 }}高 / {{ closedLoopData.summary?.medium || 0 }}中 / {{ closedLoopData.summary?.low || 0 }}低</span></div>
          <div v-if="closedLoopData?.suggestions?.length" class="closed-loop-list">
            <div v-for="(s, i) in closedLoopData.suggestions" :key="i" class="cl-card" :class="'cl-' + s.severity">
              <div class="cl-header">
                <span class="cl-sev">{{ s.severity === 'high' ? '🔴' : s.severity === 'medium' ? '🟡' : '🔵' }}</span>
                <span class="cl-type">{{ s.type }}</span>
              </div>
              <div class="cl-diagnosis">{{ s.diagnosis }}</div>
              <div class="cl-action">👉 {{ s.action }}</div>
              <div class="cl-verify">✅ 验证: {{ s.verification }}</div>
              <div v-if="s.worst_cases?.length" class="cl-cases">
                最差案例: <span v-for="w in s.worst_cases" :key="w.ts_code">{{ w.name }}({{ w.pnl }}%) </span>
              </div>
            </div>
          </div>
          <div v-else class="empty">无闭环建议</div>
        </template>

        <!-- ============ 第4层: 纪律检查 + 执行质量 ============ -->
        <!-- ===== 日复盘: 执行偏差(纪律+滑点) ===== -->
        <template v-if="reviewTab === 'daily' && deviationData">
          <div class="st" style="margin-top:12px">🔍 执行偏差归因 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">({{ deviationData.period }})</span></div>
          <div class="review-2col">
            <div class="dev-card">
              <div class="dev-title">📊 滑点偏差</div>
              <div class="dev-row"><span>平均滑点</span><span :class="deviationData.deviations?.slippage?.avg_pct > 0 ? 'down' : 'up'">{{ deviationData.deviations?.slippage?.avg_pct || 0 }}%</span></div>
              <div class="dev-row"><span>影响笔数</span><span>{{ deviationData.deviations?.slippage?.count || 0 }}笔</span></div>
              <div class="dev-row"><span>影响幅度</span><span class="down">{{ deviationData.deviations?.slippage?.impact || 0 }}%</span></div>
            </div>
            <div class="dev-card">
              <div class="dev-title">🚨 纪律偏差 <span v-if="deviationData.deviations?.discipline?.violations" class="down">（主因）</span></div>
              <div class="dev-row"><span>违规笔数</span><span class="down">{{ deviationData.deviations?.discipline?.violations || 0 }}笔</span></div>
              <div class="dev-row"><span>违规胜率</span><span class="down">{{ deviationData.deviations?.discipline?.violation_wr || 0 }}%</span></div>
              <div class="dev-row"><span>影响幅度</span><span class="down">{{ deviationData.deviations?.discipline?.impact || 0 }}%</span></div>
            </div>
          </div>
          <div v-if="deviationData.details?.discipline?.length" class="violations-list" style="margin-top:6px">
            <div v-for="v in deviationData.details.discipline.slice(0,5)" :key="v.ts_code" class="violation-item sev-high">
              <span class="v-icon">🔴</span>
              <span class="v-type">{{ v.type }}</span>
              <span class="v-detail">{{ v.period }}期{{ v.strategy }} {{ v.stock_name }}</span>
            </div>
          </div>
        </template>

        <!-- ===== 周复盘: 策略偏差 + 偏差趋势 ===== -->
        <template v-if="reviewTab === 'weekly' && weeklyReviewData">
          <div class="st" style="margin-top:12px">📊 策略效能 ({{ weeklyReviewData.period }})</div>
          <div class="review-scorecard" style="grid-template-columns:repeat(4,1fr)">
            <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ weeklyReviewData.summary?.trades || 0 }}笔</div></div>
            <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ weeklyReviewData.summary?.win_rate || 0 }}%</div></div>
            <div class="rsc"><div class="rsc-label">盈亏</div><div class="rsc-value" :class="weeklyReviewData.summary?.pnl >= 0 ? 'up' : 'down'">{{ weeklyReviewData.summary?.pnl >= 0 ? '+' : '' }}{{ weeklyReviewData.summary?.pnl || 0 }}%</div></div>
            <div class="rsc"><div class="rsc-label">情绪</div><div class="rsc-value">{{ Object.values(weeklyReviewData.sentiments || {})[0]?.period || '-' }}</div></div>
          </div>
          <!-- 策略统计 -->
          <div class="strategy-contrib">
            <div v-for="(data, key) in weeklyReviewData.strategy_stats || {}" :key="key" class="strat-card">
              <div class="strat-header">
                <ElTag size="small" class="tag-solid">{{ strategyCN(key) }}</ElTag>
                <span class="strat-pnl" :class="data.pnl >= 0 ? 'up' : 'down'">{{ data.pnl >= 0 ? '+' : '' }}{{ data.pnl }}%</span>
              </div>
              <div class="strat-metrics">
                <div class="strat-m"><span class="strat-ml">笔数</span><span class="strat-mv">{{ data.trades }}笔</span></div>
                <div class="strat-m"><span class="strat-ml">胜率</span><span class="strat-mv" :class="data.win_rate >= 50 ? 'up' : 'down'">{{ data.win_rate }}%</span></div>
              </div>
            </div>
          </div>
          <!-- 偏差趋势 -->
          <div class="st" style="margin-top:12px">📈 偏差趋势(近4周)</div>
          <div class="eq-grid-mini">
            <div v-for="w in weeklyReviewData.weekly_trend || []" :key="w.week" class="eq-row">
              <span>{{ w.week }}({{ w.start }})</span>
              <span>{{ w.trades }}笔 WR={{ w.win_rate }}%</span>
            </div>
          </div>
          <!-- 逐日 -->
          <div class="st" style="margin-top:12px">📋 逐日明细</div>
          <div class="eq-grid-mini">
            <div v-for="d in weeklyReviewData.daily_breakdown || []" :key="d.date" class="eq-row">
              <span>{{ d.date }}</span>
              <span>买{{ d.buys }} 卖{{ d.sells }} WR={{ d.win_rate }}% PnL={{ d.pnl }}%</span>
            </div>
          </div>
        </template>

        <!-- (月复盘内容已在上方reviewTab==='monthly'区块中) -->
        <div class="review-2col" style="margin-top:12px">
          <!-- 纪律检查 -->
          <div class="sentiment-panel">
            <div class="st">🔍 纪律检查
              <span v-if="disciplineCheck" style="font-weight:normal;font-size:11px;margin-left:6px" :class="disciplineCheck.execution_rate >= 80 ? 'up' : disciplineCheck.execution_rate >= 60 ? '' : 'down'">
                执行正确率 {{ disciplineCheck.execution_rate }}%
              </span>
            </div>
            <div v-if="disciplineCheck && disciplineCheck.violations.length" class="violations-list">
              <div v-for="(v, i) in disciplineCheck.violations" :key="i" class="violation-item" :class="'sev-' + v.severity">
                <span class="v-icon">{{ v.severity === 'high' ? '🔴' : '🟡' }}</span>
                <span class="v-type">{{ v.violation }}</span>
                <span class="v-detail">{{ v.detail }}</span>
              </div>
            </div>
            <div v-else-if="disciplineCheck" class="empty" style="padding:8px 0;color:#67c23a">✅ 无违规交易</div>
            <div v-else class="empty" style="padding:8px 0">无数据</div>
          </div>
          <!-- 执行质量 -->
          <div class="sentiment-panel">
            <div class="st">🎯 执行质量</div>
            <div v-if="executionQuality" class="eq-grid-mini">
              <div class="eq-row"><span>平均滑点</span><span :class="Math.abs(executionQuality.avg_slippage_pct || 0) > 0.5 ? 'down' : ''">{{ (executionQuality.avg_slippage_pct || 0).toFixed(3) }}%</span></div>
              <div class="eq-row"><span>最大滑点</span><span>{{ (executionQuality.max_slippage_pct || 0).toFixed(3) }}%</span></div>
              <div class="eq-row"><span>成交率</span><span :class="(executionQuality.fill_rate_pct || 0) < 90 ? 'down' : 'up'">{{ (executionQuality.fill_rate_pct || 0).toFixed(1) }}%</span></div>
              <div class="eq-row"><span>下单/成交</span><span>{{ executionQuality.total_orders || 0 }}/{{ executionQuality.filled_orders || 0 }}</span></div>
            </div>
            <div v-else class="empty" style="padding:8px 0">无数据</div>
          </div>
        </div>

        <!-- 实盘vs回测 -->
        <div class="st" style="margin-top:12px">📊 实盘 vs 回测偏差
          <ElButton v-if="!liveBacktestDiff.length" size="small" type="primary" @click="runBacktest" :loading="backtestRunning" style="margin-left:8px">▶️ 运行回测</ElButton>
        </div>
        <div v-if="liveBacktestDiff.length" class="lb-table">
          <div class="lb-header"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>回测胜率</span><span>偏差</span></div>
          <div v-for="c in liveBacktestDiff" :key="c.strategy" class="lb-row">
            <span class="code">{{ strategyCN(c.strategy) }}</span>
            <span>{{ c.live_trades }}笔</span>
            <span>{{ c.live_win_rate }}%</span>
            <span>{{ c.bt_win_rate }}%</span>
            <span :class="Math.abs(c.live_win_rate - c.bt_win_rate) > 15 ? 'down' : 'up'">{{ (c.live_win_rate - c.bt_win_rate).toFixed(1) }}%</span>
          </div>
        </div>
        <div v-else class="empty">暂无对比数据</div>

        <!-- ============ 第5层: 前瞻建议 ============ -->
        <div class="st" style="margin-top:12px">💡 前瞻建议</div>
        <div v-if="reviewForward" class="forward-section">
          <!-- 操作建议 -->
          <div class="fw-card fw-advice">
            <div class="fw-title">📌 明日操作</div>
            <div class="fw-content">{{ reviewForward.advice }}</div>
          </div>
          <!-- 策略开关 -->
          <div v-if="reviewForward.strategy_recommendations?.length || reviewForward.strategy_switches?.length" class="fw-switches">
            <div v-for="r in reviewForward.strategy_recommendations" :key="'o'+r.strategy" class="fw-card fw-open">
              <span class="fw-icon">🟢</span>
              <span><strong>{{ strategyCN(r.strategy) }}</strong> 可开仓 (历史WR {{ r.win_rate }}%)</span>
            </div>
            <div v-for="s in reviewForward.strategy_switches" :key="'c'+s.strategy" class="fw-card fw-close">
              <span class="fw-icon">🔴</span>
              <span><strong>{{ strategyCN(s.strategy) }}</strong> {{ s.reason }}</span>
            </div>
          </div>
        </div>
        <div v-else class="empty">选择日期后查看前瞻建议</div>

      </div>
    </div>

    <!-- ==================== 🛡️ 风控Tab ==================== -->
    <div v-if="activeTab === 'risk'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <PositionRiskMatrix />
      </div>
    </div>

    <!-- ==================== 🌡️ 情绪Tab ==================== -->
    <div v-if="activeTab === 'sentiment'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 头部: 模式切换 + 日期 -->
        <div class="review-header">
          <button :class="['review-tab', sentimentMode === 'intraday' ? 'active' : '']" @click="sentimentMode = 'intraday'; fetchSentimentData()">📈 日内</button>
          <button :class="['review-tab', sentimentMode === 'daily' ? 'active' : '']" @click="sentimentMode = 'daily'; fetchSentimentData()">📊 日线</button>
          <button :class="['review-tab', sentimentMode === 'weekly' ? 'active' : '']" @click="sentimentMode = 'weekly'; fetchSentimentData()">📅 周线</button>
          <button :class="['review-tab', sentimentMode === 'monthly' ? 'active' : '']" @click="sentimentMode = 'monthly'; fetchSentimentData()">📆 月线</button>
          <ElDatePicker v-model="sentimentDate" type="date" size="small" value-format="YYYY-MM-DD" @change="fetchSentimentData" :teleported="false" />
          <ElButton size="small" @click="fetchSentimentData" :loading="sentimentLoading">🔄</ElButton>
        </div>

        <!-- ============ 区块1: 情绪时间线 ============ -->
        <div class="st">📈 情绪时间线
          <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary);margin-left:8px">
            {{ isIntradayFallback ? '（Scanner未运行，显示日线数据）' : `（${displayTimeline.length}个数据点）` }}
          </span>
        </div>
        <div v-if="sentimentMode === 'intraday' && !sentimentTimeline.length && !isIntradayFallback" class="empty" style="padding:16px 0;text-align:center">
          <div style="font-size:32px;margin-bottom:8px">📡</div>
          <div>日内模式需要扫描器运行中才能采集数据</div>
          <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px">请先启动扫描器，或在日线/周线/月线模式下查看历史情绪</div>
        </div>
        <div v-else-if="!displayTimeline.length" class="empty" style="padding:12px 0">暂无情绪数据</div>
        <div v-else class="sentiment-chart">
          <div class="sc-chart-row">
            <div class="sc-y-axis"><span>100</span><span>70</span><span>55</span><span>40</span><span>0</span></div>
            <div class="sc-chart-body">
              <template v-if="sentimentMode !== 'intraday' || isIntradayFallback">
                <div class="sc-band" style="height:30%;background:rgba(245,108,108,0.08)" title="高潮 ≥70"></div>
                <div class="sc-band" style="height:15%;background:rgba(64,158,255,0.08)" title="分化 55-70"></div>
                <div class="sc-band" style="height:15%;background:rgba(230,162,60,0.08)" title="震荡 40-55"></div>
                <div class="sc-band" style="height:40%;background:rgba(103,194,58,0.08)" title="冰点 <40"></div>
              </template>
              <template v-if="sentimentMode === 'intraday' && !isIntradayFallback && intradayMaxCand > 0">
                <svg class="sc-svg" :viewBox="`0 0 ${Math.max(displayTimeline.length - 1, 1) * 20} 100`" preserveAspectRatio="none">
                  <polyline :points="displayTimeline.map((p, i) => `${i * 20},${100 - Math.round((p.candidates || 0) / intradayMaxCand * 90)}`).join(' ')" fill="none" stroke="#409eff" stroke-width="1.5" />
                  <polyline :points="displayTimeline.map((p, i) => `${i * 20},${100 - Math.round((p.passed || 0) / intradayMaxCand * 90)}`).join(' ')" fill="none" stroke="#67c23a" stroke-width="1.5" />
                </svg>
                <template v-for="(p, i) in displayTimeline" :key="i">
                  <div class="sc-dot" :style="{ left: `${i / Math.max(displayTimeline.length - 1, 1) * 100}%`, bottom: `${Math.round((p.candidates || 0) / intradayMaxCand * 90)}%` }" @mouseenter="hoveredPoint = p" @mouseleave="hoveredPoint = null"></div>
                </template>
                <div style="position:absolute;top:4px;right:8px;font-size:10px;z-index:5"><span style="color:#409eff">● 候选</span> <span style="color:#67c23a;margin-left:6px">● 通过</span></div>
              </template>
              <template v-else>
                <svg class="sc-svg" :viewBox="`0 0 ${Math.max(displayTimeline.filter(p => p.score != null).length - 1, 1) * 20} 100`" preserveAspectRatio="none">
                  <polyline :points="displayTimeline.filter(p => p.score != null).map((p, i) => `${i * 20},${100 - (p.score || 0)}`).join(' ')" fill="none" stroke="var(--el-color-primary)" stroke-width="1.5" />
                </svg>
                <template v-for="(p, i) in displayTimeline" :key="i">
                  <div v-if="p.score != null" class="sc-dot" :style="{ left: `${i / Math.max(displayTimeline.length - 1, 1) * 100}%`, bottom: `${(p.score || 0)}%` }" :class="p.period === '高潮' ? 'hot' : p.period === '冰点' ? 'cold' : p.missing_data ? 'missing' : ''" @mouseenter="hoveredPoint = p" @mouseleave="hoveredPoint = null"></div>
                </template>
              </template>
              <div v-if="hoveredPoint" class="sc-hover-card" :style="{ left: `${Math.min(displayTimeline.findIndex(p => p === hoveredPoint) / Math.max(displayTimeline.length - 1, 1) * 100, 75)}%`, bottom: `${Math.min((hoveredPoint.score || 30) + 8, 85)}%` }">
                <template v-if="sentimentMode === 'intraday' && !isIntradayFallback">
                  <div class="sc-hover-date">{{ hoveredPoint.time?.substring(11, 16) }}</div>
                  <div class="sc-hover-detail" style="font-size:13px">候选 <strong style="color:#409eff">{{ hoveredPoint.candidates }}</strong> 通过 <strong style="color:#67c23a">{{ hoveredPoint.passed }}</strong></div>
                </template>
                <template v-else>
                  <div class="sc-hover-date">{{ hoveredPoint.date }}</div>
                  <div class="sc-hover-score" :class="hoveredPoint.period === '高潮' ? 'hot' : hoveredPoint.period === '冰点' ? 'cold' : ''">{{ hoveredPoint.score?.toFixed(1) }} {{ hoveredPoint.period }}</div>
                  <div class="sc-hover-detail">涨停{{ hoveredPoint.limit_up || 0 }} 跌停{{ hoveredPoint.limit_down || 0 }} 连板{{ hoveredPoint.max_continue || 0 }}</div>
                  <div v-if="hoveredPoint.missing_data" class="sc-hover-warn">⚠ 数据不完整</div>
                </template>
              </div>
              <template v-for="(t, i) in sentimentTrades" :key="'t'+i">
                <div v-if="sentimentMode === 'intraday'" class="sc-trade-marker" :class="t.side" :style="{ left: `${displayTimeline.length ? displayTimeline.findIndex(p => p.time >= t.time) / Math.max(displayTimeline.length - 1, 1) * 100 : 50}%`, bottom: '2%' }">{{ t.side === 'buy' ? '▲' : '▼' }}</div>
                <div v-else class="sc-trade-marker" :class="t.side" :style="{ left: `${displayTimeline.findIndex(p => p.date >= t.date) / Math.max(displayTimeline.length - 1, 1) * 100}%`, bottom: '2%' }">{{ t.side === 'buy' ? '▲' : '▼' }}</div>
              </template>
            </div>
          </div>
          <div class="sc-x-labels"><span v-for="(lbl, i) in xAxisLabels" :key="i">{{ lbl }}</span></div>
        </div>

        <!-- ============ 区块2: 情绪全貌(当前状态+市场全景+得分拆解) ============ -->
        <div class="sentiment-3col" style="margin-top:12px">
          <!-- 当前状态 -->
          <div class="sentiment-panel">
            <div class="st">🔄 当前状态</div>
            <div v-if="sentimentLive" class="sl-content">
              <div class="sl-gauge">
                <div class="sl-gauge-bar">
                  <div class="sl-gauge-fill" :style="{ width: sentimentLive.score + '%', background: sentimentLive.score >= 70 ? '#f56c6c' : sentimentLive.score >= 55 ? '#409eff' : sentimentLive.score >= 40 ? '#e6a23c' : '#67c23a' }"></div>
                </div>
                <div class="sl-score-labels"><span>0 冰点</span><span>40 震荡</span><span>55 分化</span><span>70 高潮</span><span>100</span></div>
              </div>
              <div class="sl-row"><span>情绪分</span><span class="sl-val" :style="{ color: sentimentLive.score >= 70 ? '#f56c6c' : sentimentLive.score >= 55 ? '#409eff' : sentimentLive.score >= 40 ? '#e6a23c' : '#67c23a' }">{{ sentimentLive.score?.toFixed(0) }}</span></div>
              <div class="sl-row"><span>周期</span><span class="sl-val">{{ sentimentLive.period_label }}</span></div>
              <div class="sl-row"><span>仓位系数</span><span class="sl-val">{{ (sentimentLive.position_ratio * 100).toFixed(0) }}%</span></div>
              <div class="sl-row"><span>允许开仓</span><span class="sl-val" :style="{ color: sentimentLive.position_ratio > 0 ? '#67c23a' : '#f56c6c' }">{{ sentimentLive.position_ratio > 0 ? '✅ 是' : '❌ 否' }}</span></div>
            </div>
            <div v-else class="empty" style="padding:8px 0">无数据</div>
          </div>
          <!-- 市场全景 -->
          <div class="sentiment-panel">
            <div class="st">📊 市场全景</div>
            <div v-if="sentimentLive" class="sl-content">
              <div class="sl-row"><span>涨停</span><span class="sl-val up">{{ sentimentLive.limit_up_count }}</span></div>
              <div class="sl-row"><span>跌停</span><span class="sl-val down">{{ sentimentLive.limit_down_count }}</span></div>
              <div class="sl-row"><span>炸板率</span><span class="sl-val" :style="{ color: sentimentLive.broken_rate > 30 ? '#f56c6c' : 'var(--text-primary)' }">{{ sentimentLive.broken_rate?.toFixed(1) }}%</span></div>
              <div class="sl-row"><span>炸板数</span><span class="sl-val">{{ sentimentLive.broken_count }}</span></div>
              <div v-if="sentimentLive.board_distribution && Object.keys(sentimentLive.board_distribution).length" class="sl-board">
                <span style="color:var(--text-tertiary);font-size:11px">连板分布</span>
                <div v-for="(cnt, times) in sentimentLive.board_distribution" :key="times" class="sl-board-item">
                  <span class="sl-board-n">{{ times }}板</span><span class="sl-board-c">{{ cnt }}</span>
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding:8px 0">无数据</div>
          </div>
          <!-- 得分拆解 -->
          <div class="sentiment-panel">
            <div class="st">🧮 得分拆解</div>
            <div v-if="sentimentLive" class="sl-content">
              <div class="sl-row"><span>涨停贡献</span><span class="sl-val">{{ Math.min(30, sentimentLive.limit_up_count) }}/30</span></div>
              <div class="sl-row"><span>跌停扣分</span><span class="sl-val">{{ Math.max(0, 20 - sentimentLive.limit_down_count * 2) }}/20</span></div>
              <div class="sl-row"><span>连板高度</span><span class="sl-val">—/20</span></div>
              <div class="sl-row"><span>涨跌比</span><span class="sl-val">—/15</span></div>
              <div class="sl-row"><span>涨停溢价</span><span class="sl-val">—/15</span></div>
              <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-default)">
                <div style="font-size:10px;color:var(--text-quaternary);line-height:1.4">
                  满分100 = 涨停30 + 跌停20 + 连板20 + 涨跌比15 + 溢价15<br>
                  ≥70高潮 | 55-70分化 | 40-55震荡 | &lt;40冰点
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding:8px 0">无数据</div>
          </div>
        </div>

        <!-- ============ 区块3: 情绪阶段说明与建议 ============ -->
        <div class="st" style="margin-top:12px">📖 阶段说明与建议</div>
        <div class="phase-guide">
          <div v-for="p in phaseGuide" :key="p.name" class="phase-card" :class="p.active ? 'active' : ''" :style="{ borderColor: p.color }">
            <div class="phase-header" :style="{ background: p.color + '18' }">
              <span class="phase-icon">{{ p.icon }}</span>
              <span class="phase-name" :style="{ color: p.color }">{{ p.name }}</span>
              <span class="phase-range">{{ p.range }}</span>
            </div>
            <div class="phase-body">
              <div class="phase-row"><span class="phase-label">仓位</span><span class="phase-val">{{ p.position }}</span></div>
              <div class="phase-row"><span class="phase-label">开仓</span><span class="phase-val">{{ p.canOpen }}</span></div>
              <div class="phase-row"><span class="phase-label">策略</span><span class="phase-val">{{ p.strategy }}</span></div>
              <div class="phase-row"><span class="phase-label">建议</span><span class="phase-val">{{ p.advice }}</span></div>
            </div>
          </div>
        </div>

        <!-- ============ 区块4: 情绪降级调仓规则 ============ -->
        <div class="st" style="margin-top:12px">⚠️ 情绪降级调仓规则</div>
        <div class="downgrade-rules">
          <div v-for="r in downgradeRules" :key="r.from+r.to" class="dg-rule">
            <span class="dg-from" :style="{ color: phaseColors[r.from] }">{{ r.from }}</span>
            <span class="dg-arrow">→</span>
            <span class="dg-to" :style="{ color: phaseColors[r.to] }">{{ r.to }}</span>
            <span class="dg-action">{{ r.action }}</span>
            <span class="dg-desc">{{ r.desc }}</span>
          </div>
        </div>

        <!-- ============ 区块5: 策略×情绪效果矩阵 ============ -->
        <div class="st" style="margin-top:12px">📋 策略×情绪 效果矩阵</div>
        <div v-if="sentimentMatrix && Object.keys(sentimentMatrix).length" class="matrix-table-wrap">
          <table class="matrix-table">
            <thead>
              <tr><th>策略</th><th>冰点</th><th>震荡</th><th>分化</th><th>高潮</th><th>合计</th></tr>
            </thead>
            <tbody>
              <tr v-for="(periods, strat) in sentimentMatrix" :key="strat">
                <td class="mt-strat">{{ strategyCN(strat) }}</td>
                <td v-for="col in ['冰点','震荡','分化','高潮']" :key="col" class="mt-cell">
                  <template v-if="periods[col]">
                    <div class="mt-count" :class="periods[col].total_pnl >= 0 ? 'up' : 'down'">{{ periods[col].count }}笔</div>
                    <div class="mt-wr" :class="periods[col].win_rate >= 50 ? 'up' : 'down'">WR {{ periods[col].win_rate }}%</div>
                    <div class="mt-pnl" :class="periods[col].total_pnl >= 0 ? 'up' : 'down'">¥{{ periods[col].total_pnl }}</div>
                  </template>
                  <span v-else class="mt-empty">-</span>
                </td>
                <td class="mt-total">{{ Object.values(periods).reduce((s: number, v: any) => s + v.count, 0) }}笔</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty" style="padding:8px 0">暂无策略×情绪数据</div>

        <!-- ============ 区块6: 推荐与警告 ============ -->
        <div class="st" style="margin-top:12px">💡 推荐与警告</div>
        <div v-if="sentimentLive" class="rec-warn-section">
          <!-- 基于当前情绪的推荐 -->
          <div class="rw-card rw-rec">
            <div class="rw-title">📌 当前建议</div>
            <div class="rw-content">{{ sentimentAdvice }}</div>
          </div>
          <!-- 基于策略矩阵的推荐 -->
          <div v-for="r in sentimentRecommendations" :key="r.strategy" class="rw-card rw-strat">
            <div class="rw-title">🏆 {{ strategyCN(r.strategy) }}</div>
            <div class="rw-content">在 <strong :style="{ color: phaseColors[r.best_period] || 'var(--text-primary)' }">{{ r.best_period }}</strong> 期表现最佳，{{ r.count }}笔 WR{{ r.win_rate }}%</div>
          </div>
          <!-- 风险警告 -->
          <div v-if="sentimentLive.score < 40" class="rw-card rw-warn">
            <div class="rw-title">⚠️ 风险警告</div>
            <div class="rw-content">当前情绪冰点，市场极度弱势。建议空仓观望，禁止新开仓。持仓应严格执行止损，亏损标的优先平仓。</div>
          </div>
          <div v-else-if="sentimentLive.score < 55" class="rw-card rw-caution">
            <div class="rw-title">⚡ 震荡提醒</div>
            <div class="rw-content">市场情绪震荡，涨跌分化明显。建议轻仓操作，仅做龙头股低吸，避免追高。严格止损3%。</div>
          </div>
        </div>
        <div v-else class="empty" style="padding:8px 0">选择日期后查看推荐</div>

        <!-- ============ 区块7: 算法说明 ============ -->
        <div class="st" style="margin-top:12px">🔬 算法与数据源</div>
        <div class="algo-info">
          <div class="algo-section">
            <div class="algo-title">📐 情绪得分算法</div>
            <div class="algo-body">
              综合得分满分100，由5个维度加权计算：<br>
              <strong>涨停数量(0-30分)</strong>：每只涨停+1分，50只以上满分。涨停越多市场越强。<br>
              <strong>跌停数量(0-20分)</strong>：0跌停满分20，每只跌停-2分。跌停反映恐慌程度。<br>
              <strong>最高连板(0-20分)</strong>：每层连板+2分，10板以上满分。连板高度代表赚钱效应。<br>
              <strong>涨跌家数比(0-15分)</strong>：上涨占比×15。反映市场广度。<br>
              <strong>昨日涨停溢价(0-15分)</strong>：昨日涨停股今日平均涨幅每1%+1分。反映打板盈亏。
            </div>
          </div>
          <div class="algo-section">
            <div class="algo-title">📊 数据来源</div>
            <div class="algo-body">
              <strong>实时数据</strong>：Scanner内存缓存(limit_pools/realtime_cache)，盘中最快5秒更新。<br>
              <strong>历史数据</strong>：MongoDB sentiment_scores集合(预计算缓存，494天)。<br>
              <strong>涨跌停</strong>：limit_list集合(Scanner收盘自动同步) 或 daily_basic(pct_chg推算)。<br>
              <strong>交易数据</strong>：broker_orders集合(含profit_pct真实盈亏)。<br>
              <strong style="color:var(--el-color-warning)">数据断档</strong>：5/12-5/30部分数据缺失(东财API网络不通)，标记为⚠。
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- ==================== 📜 历史Tab ==================== -->
    <div v-if="activeTab === 'history'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 交易时间线 -->
        <div class="st">⏱️ 交易时间线 <span class="text-tertiary" style="font-size:11px">({{ timeline.length }}笔)</span>
          <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span>
          <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit" style="margin-left:8px">🔍 审查</ElButton>
          <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="历史日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading">回放</ElButton><ElButton v-if="historyData.length" size="small" type="info" @click="historyData=[];historyDate=''">返回</ElButton></div>
        </div>
        <div v-if="historyData.length" class="history-tag" style="margin-bottom:6px">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-if="!historyData.length && !timeline.length" class="empty">暂无交易记录</div>
        <div class="ht-timeline">
          <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)">
            <span class="tl-time">{{ item.time }}</span>
            <span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span>
            <span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span>
            <span v-if="item.action === 'blocked'" class="tl-blocked-reason">{{ item.reason }}</span>
            <template v-else>
              <span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span>
              <span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span>
              <span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span>
              <span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span>
            </template>
          </div>
        </div>

        <!-- 历史订单 -->
        <div class="st" style="margin-top:16px">📋 历史订单 <span class="text-tertiary" style="font-size:11px">({{ orders.length }}笔)</span></div>
        <div v-if="!orders.length" class="empty">暂无订单</div>
        <div v-else class="ht-orders">
          <div class="ho-header"><span>时间</span><span>方向</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span></div>
          <div v-for="o in orders" :key="o.order_id" class="ho-row cp" @click="openTradeDetail(o.ts_code)">
            <span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span>
            <span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span>
            <span>{{ o.filled_qty }}股</span><span>¥{{ o.filled_price?.toFixed(2) || '0.00' }}</span>
            <span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span>
          </div>
        </div>

        <!-- 已平仓汇总 -->
        <div class="st" style="margin-top:16px">💰 已平仓汇总</div>
        <div v-if="!closedPositions.length" class="empty">暂无已平仓记录</div>
        <div v-else class="ht-closed">
          <div class="hc-header"><span>代码</span><span>名称</span><span>策略</span><span>买入价</span><span>卖出价</span><span>盈亏</span><span>盈亏%</span></div>
          <div v-for="cp in closedPositions" :key="cp.ts_code + cp.strategy" class="hc-row" @click="openTradeDetail(cp.ts_code)" :class="cp.profit_pct >= 0 ? 'hc-win' : 'hc-loss'">
            <span class="code">{{ cp.ts_code }}</span><span class="name">{{ cp.stock_name }}</span>
            <span><ElTag size="small" :color="strategyMeta[cp.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px">{{ strategyCN(cp.strategy) }}</ElTag></span>
            <span>¥{{ cp.buy_price?.toFixed(2) }}</span><span>¥{{ cp.sell_price?.toFixed(2) }}</span>
            <span :class="cp.profit_amount >= 0 ? 'up' : 'down'">{{ cp.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(cp.profit_amount).toFixed(0) }}</span>
            <span :class="cp.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ cp.profit_pct >= 0 ? '+' : '' }}{{ cp.profit_pct.toFixed(1) }}%</span>
          </div>
        </div>

        <!-- 审计日志 -->
        <div class="st" style="margin-top:16px">📝 审计日志 <ElButton size="small" @click="fetchAuditLog" :loading="auditLogLoading">🔄</ElButton></div>
        <div v-if="!auditLog.length" class="empty">暂无审计记录</div>
        <div v-else class="ht-audit">
          <div v-for="(log, i) in auditLog" :key="i" class="ha-row cp" @click="log.ts_code && openTradeDetail(log.ts_code)">
            <span class="tl-time">{{ log.time }}</span>
            <span class="ha-action">{{ log.action }}</span>
            <span class="ha-detail">{{ log.detail }}</span>
          </div>
        </div>

        <!-- 导出 -->
        <div class="st" style="margin-top:16px">📥 数据导出</div>
        <div class="ht-export">
          <ElButton size="small" @click="exportTradeLog">📥 导出交易日志(CSV)</ElButton>
          <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 交易审查</ElButton>
        </div>
      </div>
    </div>

    <!-- ==================== 运维Tab ==================== -->
    <div v-if="activeTab === 'ops'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 自动交易操作流 -->
        <div class="st">🤖 自动交易操作流 <ElButton size="small" @click="fetchAutoTrades">🔄</ElButton></div>
        <div v-if="!autoTrades.length" class="empty">暂无自动交易记录</div>
        <div v-else class="auto-trades-list">
          <div class="at-header"><span>时间</span><span>来源</span><span>操作</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span><span>原因</span></div>
          <div v-for="t in autoTrades" :key="t.order_id" class="at-row" :class="{ 'auto-trade': t.source === 'auto', 'manual-trade': t.source === 'manual' }">
            <span class="tl-time">{{ t.time }}</span>
            <span><ElTag size="small" :type="t.source === 'auto' ? 'primary' : 'warning'" style="font-size:10px">{{ t.source === 'auto' ? '🤖自动' : '✋手动' }}</ElTag></span>
            <span class="tl-action" :class="t.side === 'buy' ? 'buy' : 'sell'">{{ t.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ t.ts_code }}</span>
            <span class="name">{{ t.stock_name }}</span>
            <span>{{ t.quantity }}股</span>
            <span>¥{{ t.price?.toFixed(2) }}</span>
            <span v-if="t.strategy" class="tl-strat">{{ strategyCN(t.strategy) }}</span><span v-else>-</span>
            <span class="text-tertiary" style="font-size:11px">{{ t.reason }}</span>
          </div>
        </div>

        <!-- 扫描器配置 -->
        <div class="st" style="margin-top:16px">⏱️ 扫描器配置 <ElButton size="small" @click="fetchScanConfig" :loading="scanConfigLoading">🔄</ElButton></div>
        <div v-if="scanConfig" class="scan-config-grid">
          <div class="sc-item"><span class="sc-label">自动扫描间隔</span><span class="sc-value">{{ scanConfig.scan_interval_desc || scanConfig.scan_interval_sec + '秒' }}</span></div>
          <div class="sc-item"><span class="sc-label">持仓检查间隔</span><span class="sc-value">{{ scanConfig.position_check_interval_sec }}秒</span></div>
          <div class="sc-item"><span class="sc-label">持仓快速检查</span><span class="sc-value">{{ scanConfig.position_check_fast_sec }}秒(接近止损)</span></div>
          <div class="sc-item"><span class="sc-label">持仓紧急检查</span><span class="sc-value">{{ scanConfig.position_check_critical_sec }}秒(触及止损)</span></div>
          <div class="sc-item"><span class="sc-label">信号过期时间</span><span class="sc-value">{{ scanConfig.signal_expire_desc || scanConfig.signal_expire_sec + '秒' }}</span></div>
          <div class="sc-item"><span class="sc-label">最大持仓数</span><span class="sc-value">{{ scanConfig.max_positions }}只</span></div>
          <div class="sc-item"><span class="sc-label">最大仓位比例</span><span class="sc-value">{{ (scanConfig.max_position_ratio * 100).toFixed(0) }}%</span></div>
          <div class="sc-item" v-if="scanConfig.current_smart_interval"><span class="sc-label">当前智能检查间隔</span><span class="sc-value">{{ scanConfig.current_smart_interval }}秒</span></div>
          <div class="sc-item"><span class="sc-label">交易模式</span><span class="sc-value">{{ scanConfig.trade_mode === 'simulated' ? '模拟' : scanConfig.trade_mode === 'gm' ? '掘金' : scanConfig.trade_mode }}</span></div>
          <div class="sc-item"><span class="sc-label">运行状态</span><span class="sc-value" :style="{ color: scanConfig.is_running ? 'var(--el-color-success)' : 'var(--el-color-danger)' }">{{ scanConfig.is_running ? '🟢 运行中' : '🔴 未启动' }}</span></div>
        </div>
        <div v-else class="empty" style="padding:8px">点击刷新加载扫描配置</div>

        <!-- 系统健康 -->
        <div class="st" style="margin-top:16px">💻 系统健康</div>
        <SystemHealth />

        <!-- 快捷操作 -->
        <div class="st" style="margin-top:16px">⚡ 快捷操作</div>
        <div class="ops-grid">
          <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning">📡 扫描</ElButton>
          <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning">⚡ 强扫</ElButton>
          <ElButton size="small" @click="dailySettlement" :disabled="!isRunning">📅 日结</ElButton>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 审查</ElButton>
          <ElButton size="small" @click="fetchDailyReport(); dailyReportVisible = true">📈 复盘</ElButton>
          <ElButton size="small" @click="openWeeklyReport">📊 周报</ElButton>
          <ElButton size="small" @click="openLayerDebug" :loading="layerDebugLoading">🧪 9层调试</ElButton>
          <ElButton size="small" @click="loadCompare" :loading="compareLoading">📊 回测对比</ElButton>
          <ElButton size="small" @click="toggleDryRun">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
          <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker">🔓 解熔断</ElButton>
          <ElButton size="small" @click="exportTradeLog">📥 导出日志</ElButton>
          <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
          <ElButton size="small" type="warning" @click="resetAccount">🗑️ 清仓重置</ElButton>
          <ElButton size="small" @click="sellAllPositions">💰 一键清仓</ElButton>
        </div>

        <!-- 手动下单 -->
        <div class="st" style="margin-top:16px">🔧 手动下单</div>
        <div class="mf ops-mf">
          <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
          <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
          <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
          <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
          <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ manualQuote.pct_chg.toFixed(2) }}%</span></div>
        </div>

        <!-- 交易时间线 -->
        <div class="st" style="margin-top:16px">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span>
          <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading" style="padding:2px 8px;font-size:11px">回放</ElButton></div>
        </div>
        <div v-if="!timeline.length && !historyData.length" class="empty">暂无交易</div>
        <div v-else class="ops-timeline">
          <div v-if="historyData.length" class="history-tag">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
          <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><template v-if="item.action !== 'blocked'"><span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span><span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span></template><span v-else class="tl-blocked-reason">{{ item.reason }}</span></div>
        </div>

        <!-- 历史订单 -->
        <div v-if="orders.length" class="st" style="margin-top:16px">📋 历史订单 ({{ orders.length }})</div>
        <div v-if="orders.length" class="ops-timeline">
          <div v-for="o in orders.slice(0, 50)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
        </div>
      </div>
    </div>

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
      @toggle-strategy="(i) => { const keys = ['halfway_chase','first_limit_up','dragon_head','limit_down_qiao']; if (strategies[keys[i]]) toggleStrat(strategies[keys[i]].id) }"
      @focus-prev="() => { if (focusIndex > 0) focusIndex-- }"
      @focus-next="() => { if (focusIndex < sortedPositions.length - 1) focusIndex++ }"
      @show-detail="() => { if (focusIndex >= 0 && focusIndex < sortedPositions.length) openTradeDetail(sortedPositions[focusIndex].ts_code) }"
    />

  </div>
</template>
<style scoped lang="scss">
.mm { height: 100%; display: flex; flex-direction: column; background: var(--bg-base); overflow: hidden; min-width: 0; }
/* 顶部状态栏 */
.mm-header { display: flex; align-items: center; gap: 8px; padding: 5px 12px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; min-width: 0; overflow-x: auto; }
.cb-pause-btn { font-size: 12px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--warning); color: var(--warning); background: transparent; cursor: pointer; }
.cb-pause-btn:hover { background: var(--warning); color: var(--text-inverse); }
.hh-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }
.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }
.hh-status.running .dot { background: var(--stock-down); animation: pulse 1.5s infinite; }
.hh-status.stopped .dot { background: var(--text-tertiary); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.hh-account { display: flex; align-items: center; gap: 8px; flex: 1; justify-content: center; }
.ha { display: inline-flex; align-items: baseline; gap: 2px; font-size: 12px; }
.hl { color: var(--text-tertiary); font-size: 10px; }
.hv { font-weight: 600; }
.hl { font-size: 10px; color: var(--text-tertiary); }
.hv { font-size: 13px; font-weight: 600; }
.hh-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

/* 引导页 */
.mm-guide { flex: 1; overflow-y: auto; padding: 12px 16px; }
/* 横幅 */
.guide-banner { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-elevated); border-radius: 10px; margin-bottom: 12px; }
.gb-left { display: flex; align-items: center; gap: 14px; }
.gb-logo { font-size: 36px; }
.gb-title { font-size: 18px; font-weight: 700; }
.gb-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
/* 卡片网格 */
.guide-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.gg-card { background: var(--bg-elevated); border-radius: 10px; overflow: hidden; }
.gg-span2 { grid-column: span 2; }
.gg-head { padding: 8px 14px; font-size: 13px; font-weight: 600; background: var(--bg-normal); border-bottom: 1px solid var(--border-light); }
.gg-icon { margin-right: 6px; }
.gg-body { padding: 10px 14px; }
.gg-compact { display: flex; flex-direction: column; gap: 6px; }
.gg-line { font-size: 12px; color: var(--text-secondary); }
.gg-params { display: flex; gap: 10px; }
.gg-p { font-size: 12px; font-weight: 500; }
.gg-pl { color: var(--text-tertiary); font-weight: 400; margin-right: 3px; }
/* 架构流程 */
.gf-flow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.gf-tag { padding: 4px 10px; border-radius: 5px; font-size: 12px; font-weight: 500; background: var(--bg-normal); border: 1px solid var(--border-default); }
.gf-tag.gf-input { background: var(--el-color-primary-light-5); border-color: var(--el-color-primary-light-3); color: var(--el-color-primary-dark-2); }
.gf-tag.gf-output { background: rgba(0,180,42,0.1); border-color: rgba(0,180,42,0.3); color: #00b42a; }
.gf-arrow { color: var(--text-tertiary); font-size: 11px; }
/* 操作指南 */
.go-list { display: flex; flex-direction: column; gap: 6px; }
.go-row { display: flex; align-items: center; gap: 8px; font-size: 12px; line-height: 1.5; }
.sn { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary); color: var(--text-inverse); font-size: 10px; font-weight: 600; flex-shrink: 0; }
/* 风控 */
.gr-grid { display: flex; flex-direction: column; gap: 5px; }
.gr-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.gr-k { color: var(--text-tertiary); min-width: 56px; flex-shrink: 0; }
.gr-v { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
/* 快捷键 */
.gk-row { display: flex; flex-wrap: wrap; gap: 12px; }
.gk-g { font-size: 12px; display: flex; align-items: center; gap: 4px; }
.gk-g kbd { background: var(--bg-normal); border: 1px solid var(--border-default); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
/* 紧急平仓行内按钮 */
.emergency-btn-inline { font-size: 14px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--stock-up); color: var(--stock-up); background: transparent; cursor: pointer; }
.emergency-btn-inline:hover { background: var(--stock-up); color: var(--text-inverse); }
.emergency-btn-inline.disabled { opacity: 0.4; cursor: not-allowed; }

/* 3列主布局 */
.mm-trace { flex-shrink: 0; max-height: 45vh; overflow-y: auto; border-top: 1px solid var(--border-default); background: var(--bg-elevated); }
.mm-body { flex: 1; display: grid; grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr); gap: 0; overflow: hidden; min-width: 0; }
.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 10px; min-width: 0; min-height: 0; }
.mm-left { background: var(--bg-secondary); border-right: 1px solid var(--border-default); }
.mm-right { background: var(--bg-secondary); border-left: 1px solid var(--border-default); }

/* 区域标题 */
.st { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; }

/* 策略卡片 */
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

/* 快捷操作 */
.qa { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

/* 手动下单 */
.mf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.mf-row { display: flex; gap: 4px; min-width: 0; flex-wrap: wrap; }
.mf-q { font-size: 11px; color: var(--stock-down); padding: 2px 0; }
.mf-hint { font-size: 11px; color: var(--el-color-primary); cursor: pointer; padding: 0 4px; white-space: nowrap; }

/* 信号列表 */
.sl { overflow-y: auto; min-width: 0; }
.sl-sm { max-height: 200px; }
.sig-row { display: flex; align-items: center; gap: 5px; padding: 4px 8px; margin-bottom: 2px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); font-size: 12px; flex-wrap: wrap; min-width: 0; }
.sig-row:hover { border-color: var(--el-color-primary); }
.factor { font-size: 11px; color: var(--text-tertiary); background: var(--bg-tertiary); padding: 1px 4px; border-radius: 3px; white-space: nowrap; }
.reason { font-size: 11px; color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; min-width: 0; }
.sig-row .el-button { padding: 1px 6px; font-size: 11px; }

/* 涨停池 */
.limit-row { display: flex; align-items: center; gap: 6px; padding: 3px 8px; font-size: 12px; border-bottom: 1px solid var(--border-light); flex-wrap: wrap; min-width: 0; }
.lb-tag { font-size: 10px; color: var(--stock-up); background: var(--stock-up-bg); padding: 1px 4px; border-radius: 3px; }
.fd-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; }

/* 持仓卡片 */
.pos-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); min-width: 0; }
.pos-card:hover { border-color: var(--el-color-primary); }
.pos-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.pct { margin-left: auto; font-weight: 700; font-size: 14px; transition: transform 0.3s; }
.pos-card:hover .pct { transform: scale(1.05); }
.pos-info { display: flex; gap: 8px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; min-width: 0; }
.pos-risk-row { margin-top: 4px; }
.risk-track { height: 4px; background: var(--bg-muted); border-radius: 2px; overflow: hidden; }
.risk-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.risk-fill.safe { background: linear-gradient(90deg, var(--warning), var(--success)); }
.risk-fill.warning { background: linear-gradient(90deg, var(--warning), var(--stock-up)); }
.risk-fill.danger { background: var(--stock-up); animation: risk-pulse 1s infinite; }
.risk-labels-row { display: flex; justify-content: space-between; font-size: 10px; margin-top: 2px; }
@keyframes risk-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.t1-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; font-weight: 600; }
.rl { padding: 1px 5px; border-radius: 3px; font-weight: 500; }
.rl.stop { color: var(--stock-up); background: var(--stock-up-bg); }
.rl.stop-price { color: var(--stock-up); background: var(--stock-up-bg); font-weight: 700; }
.rl.profit { color: var(--stock-down); background: var(--stock-down-bg); }
.rl.profit-price { color: var(--stock-down); background: var(--stock-down-bg); font-weight: 700; }
.rd { color: var(--text-tertiary); }
.rd.danger { color: var(--stock-up); font-weight: 600; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.5; } }

/* 统计 */
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(60px, 1fr)); gap: 6px; }
.si { text-align: center; padding: 6px; background: var(--bg-elevated); border-radius: 6px; min-width: 0; }
.sv { font-size: 18px; font-weight: 700; }
.sl2 { font-size: 11px; color: var(--text-tertiary); }

/* 底部时间线 */
.mm-footer { flex-shrink: 0; border-top: 1px solid var(--border-default); padding: 6px 16px; background: var(--bg-elevated); min-width: 0; }
.tl-body { display: flex; gap: 16px; flex-wrap: wrap; min-width: 0; }
.tl-col { flex: 1 1 200px; overflow-y: auto; max-height: 260px; min-width: 0; }
.tl-col + .tl-col { border-left: 1px solid var(--border-default); padding-left: 16px; }
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
.tl-reason { font-size: 11px; color: var(--text-tertiary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.history-tag { font-size: 12px; color: var(--el-color-primary); background: var(--info-bg); padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

/* 通用 */
.code { font-size: 12px; font-weight: 600; color: var(--text-primary); font-family: monospace; }
.name { font-size: 12px; color: var(--text-secondary); }
.empty { text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px 0; }

/* 【P1-1】关键因子标签 */
.kf { color: var(--el-color-warning); background: var(--warning-bg); font-weight: 600; }

/* 【P1-2】持仓市值和盈亏金额 */
.mv { color: var(--text-tertiary); font-size: 11px; }
.pamt { font-weight: 700; font-size: 12px; }

/* 【P1-5】数据源健康指示器 */
.ds-indicator { display: inline-flex; gap: 4px; margin-left: 4px; }
.ds-dot { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: 600; cursor: help; }
.ds-dot.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.ds-dot.err { color: var(--stock-up); background: var(--stock-up-bg); }

/* 【P1-3】时间线盈亏金额 */
.tl-amt { font-size: 11px; font-weight: 700; min-width: 50px; text-align: right; }

/* 交易详情弹窗 */
.td { font-size: 13px; }
.td-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); min-width: 0; }
.td-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.td-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.td-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.td-l { font-size: 10px; color: var(--text-tertiary); }
.td-v { font-size: 13px; font-weight: 500; }
.td-r { font-size: 12px; color: var(--text-secondary); margin: 4px 0; padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); }
.td-c { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-top: 4px; }
.cl { font-size: 11px; color: var(--text-secondary); padding: 1px 0 1px 10px; font-family: monospace; }
.td-e { color: var(--text-muted); font-size: 12px; }

/* 审查弹窗 */
.al { max-height: 500px; overflow-y: auto; }
.ah { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.ar { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); cursor: pointer; overflow: hidden; }
.ar:hover { background: var(--bg-hover); }

/* 回测对比 */
.cl-table { max-height: 400px; overflow-y: auto; }
.cl-h { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.cl-r { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); overflow: hidden; }

/* 响应式 */
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

/* 【调试增强】9层调试弹窗 */
.layer-debug { font-size: 13px; }
.ld-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: var(--text-secondary); }
.ld-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.ld-pipeline { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 10px; }
.ld-layers { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px; margin-bottom: 6px; }
.ld-layer { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); }
.ld-on { color: var(--stock-down); }
.ld-off { color: var(--text-tertiary); }
.ld-name { color: var(--text-secondary); }
.ld-sentiment { font-size: 12px; color: var(--el-color-primary); padding: 4px 0; }
.ld-traces { max-height: 400px; overflow-y: auto; }
.ld-trace-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); }
.ld-trace-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ld-trace-layers { padding-left: 10px; }
.ld-trace-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }

/* 【调试增强】扫描Trace弹窗 */
.scan-trace { font-size: 13px; }
.st-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.st-reason { font-size: 12px; color: var(--text-secondary); padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); margin-bottom: 6px; }
.st-age { font-size: 11px; color: var(--text-tertiary); margin-bottom: 6px; }
.st-trace, .st-detail, .st-factors { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 8px; }
.st-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.st-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }
.st-fg { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 4px; }
.st-fi { display: flex; flex-direction: column; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; }
.st-fl { font-size: 10px; color: var(--text-tertiary); }
.st-fv { font-size: 13px; font-weight: 500; }

/* 【P1-4】信号过期倒计时 */
.expire-tag { font-size: 11px; color: var(--el-color-primary); background: var(--info-bg); padding: 1px 5px; border-radius: 3px; font-weight: 600; }
.expire-tag.urgent { color: var(--stock-up); background: var(--stock-up-bg); animation: blink 1s infinite; }

/* 【P1-6】复盘报告弹窗 */
.dr { font-size: 13px; }
.dr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.dr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.dr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.dr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.dr-l { font-size: 10px; color: var(--text-tertiary); }
.dr-v { font-size: 13px; font-weight: 500; }
.dr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }

/* 周报弹窗 */
.wr { font-size: 13px; }
.wr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.wr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.wr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.wr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.wr-l { font-size: 10px; color: var(--text-tertiary); }
.wr-v { font-size: 14px; font-weight: 600; }
.wr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-day { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-date { font-weight: 600; color: var(--text-primary); min-width: 80px; }

/* === Extracted utility classes === */
.w-full { width: 100%; }
.ml-auto { margin-left: auto; }
.mt-10 { margin-top: 10px; }
.cp { cursor: pointer; }
.btn-xs { padding: 1px 6px; font-size: 11px; }
.tag-solid { color: var(--text-inverse); border: none; }
.fs-10 { font-size: 10px; }

/* === Dark toggle button === */
.dark-toggle { font-size: 16px; cursor: pointer; padding: 0 4px; user-select: none; }

/* === Mini bar (PnL progress) === */
.mini-bar { display: inline-block; width: 40px; height: 4px; background: var(--border-default); border-radius: 2px; vertical-align: middle; margin-left: 4px; }
.mini-bar-fill { display: block; height: 100%; border-radius: 2px; transition: width 0.3s; }

/* === Quick action groups === */
.qa-group { margin-bottom: 2px; }
.qa-label { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; margin-bottom: 2px; padding-left: 2px; }


/* === Utility classes for inline style replacement === */
.text-stock-up { color: var(--stock-up) !important; }
.text-stock-down { color: var(--stock-down) !important; }
.text-tertiary { color: var(--text-tertiary); }
.text-tertiary-sm { font-size: 11px; color: var(--text-tertiary); }

/* === Mini bar fill variants === */
.mini-bar-fill.bar-up { background: var(--stock-up) !important; }
.mini-bar-fill.bar-down { background: var(--stock-down) !important; }

/* ============================================ */

/* 【V50.1】交易详情弹窗-结构化卡片 */
.td2 { font-size: 13px; }
.td2-sec { margin-bottom: 16px; padding: 12px; background: var(--bg-secondary); border-radius: 8px; }
.td2-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary, var(--text-primary)); }
.td2-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.td2-card { padding: 8px 10px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 6px; border: 1px solid var(--border-default); }
.td2-card.sm { padding: 6px 8px; }
.td2-label { font-size: 11px; color: var(--text-tertiary, var(--text-tertiary)); margin-bottom: 2px; }
.td2-val { font-size: 14px; font-weight: 600; color: var(--text-primary, var(--text-primary)); }
.td2-reason { padding: 8px 10px; margin: 8px 0; background: var(--bg-elevated, var(--text-inverse)); border-radius: 6px; border-left: 3px solid var(--el-color-primary); font-size: 13px; color: var(--text-secondary, var(--text-secondary)); }
.td2-chain { margin-top: 8px; }
.td2-chain-title { font-size: 12px; font-weight: 600; color: var(--text-secondary, var(--text-secondary)); margin: 8px 0 6px; padding-left: 4px; border-left: 2px solid var(--el-color-primary); }
.td2-pipeline { display: flex; flex-direction: column; gap: 3px; }
.td2-pipe-step { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 4px; font-size: 12px; }
.td2-pipe-step.passed { border-left: 2px solid var(--success); }
.td2-pipe-icon { font-size: 12px; flex-shrink: 0; }
.td2-pipe-name { font-weight: 500; min-width: 100px; color: var(--text-primary, var(--text-primary)); }
.td2-pipe-detail { color: var(--text-tertiary, var(--text-tertiary)); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td2-factors { display: flex; flex-wrap: wrap; gap: 6px; }
.td2-factor { padding: 4px 8px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 4px; font-size: 12px; }
.td2-fk { color: var(--text-tertiary, var(--text-tertiary)); margin-right: 4px; }
.td2-fv { font-weight: 500; color: var(--text-primary, var(--text-primary)); }
.td2-empty { text-align: center; padding: 16px; color: var(--text-tertiary, var(--text-tertiary)); font-size: 13px; }

/* 风控状态栏 */
.risk-bar { background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; transition: background 0.3s; }
.risk-bar.critical { background: rgba(245, 108, 108, 0.12); border-bottom-color: var(--stock-up); }
.risk-bar.warning { background: rgba(230, 162, 60, 0.08); border-bottom-color: var(--el-color-warning); }
.rb-main { display: flex; align-items: center; justify-content: space-between; padding: 6px 16px; gap: 12px; flex-wrap: wrap; }
.rb-left { display: flex; align-items: center; gap: 8px; }
.rb-right { display: flex; align-items: center; gap: 8px; }
.rb-light { font-size: 14px; line-height: 1; }
.rb-label { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.rb-metric { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.rb-ml { color: var(--text-tertiary); }
.rb-mv { font-weight: 600; color: var(--text-secondary); }
.rb-progress { display: inline-block; width: 60px; height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; vertical-align: middle; }
.rb-progress-fill { display: block; height: 100%; background: var(--stock-down); border-radius: 3px; transition: width 0.3s; }
.rb-progress-fill.danger { background: var(--stock-up); }
.rb-arrow { font-size: 10px; color: var(--text-tertiary); margin-left: 4px; }
.rb-ds { display: flex; gap: 4px; }
.rb-ds-dot { font-size: 10px; }
.rb-ds-dot.ok { color: var(--stock-down); }
.rb-ds-dot.err { color: var(--stock-up); }

/* 紧急平仓按钮 */
.emergency-btn { position: relative; display: inline-flex; align-items: center; justify-content: center; padding: 4px 14px; border: 2px solid var(--stock-up); border-radius: 6px; background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; color: var(--stock-up); transition: all 0.2s; }
.emergency-btn.active { animation: emergency-pulse 1.5s infinite; }
.emergency-btn.disabled { opacity: 0.4; cursor: not-allowed; animation: none; }
.emergency-btn:not(.disabled):hover { background: var(--stock-up); color: var(--text-inverse); }
.emergency-text { white-space: nowrap; }
@keyframes emergency-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.5); } 50% { box-shadow: 0 0 0 8px rgba(245, 108, 108, 0); } }

/* 风控详情 */
.rb-detail { padding: 8px 16px 10px; border-top: 1px solid var(--border-light); }
.rb-detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 6px; margin-bottom: 6px; }
.rb-di { display: flex; flex-direction: column; gap: 1px; }
.rb-dl { font-size: 10px; color: var(--text-tertiary); }
.rb-dv { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.rb-dv.ok { color: var(--stock-down); }
.rb-dv.warn { color: var(--el-color-warning); }
.rb-dv.crit { color: var(--stock-up); }
.rb-ds-detail { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; }
.rb-ds-item { padding: 1px 6px; border-radius: 3px; font-weight: 500; }
.rb-ds-item.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.rb-ds-item.err { color: var(--stock-up); background: var(--stock-up-bg); }

/* P1: 持仓价格行 */
.pos-prices-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; font-size: 11px; flex-wrap: wrap; }
.pp-sl { color: var(--stock-up); }
.pp-tp { color: var(--stock-down); }
.pp-trail { color: var(--el-color-warning); }
.pp-risk { font-weight: 600; }
.pp-risk.high { color: var(--stock-up); }
.pp-risk.elevated { color: var(--el-color-warning); }
.pp-risk.low { color: var(--stock-down); }
.risk-labels-row .rl.trail { color: var(--el-color-warning); font-size: 10px; }

/* P1: 快捷操作常用行 */
.qa-row2 { display: flex; gap: 4px; margin-bottom: 4px; }
.qa-row2 .ElButton, .qa-row2 > button { flex: 1; }
.qa-more { margin-top: 6px; }
.qa-more-toggle { cursor: pointer; font-size: 12px; color: var(--text-tertiary); padding: 4px 0; user-select: none; }
.qa-more-toggle:hover { color: var(--text-primary); }
.qa-more[open] .qa-more-toggle { color: var(--text-primary); margin-bottom: 4px; }

/* P1: 追踪止损区域 */
.td2-trail-section { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-default); }
.td2-trail-ctrl { display: flex; align-items: center; gap: 8px; margin-top: 8px; }

/* 盈亏曲线 */
.pnl-chart-wrap { background: var(--bg-elevated); border-radius: 6px; padding: 4px; margin-top: 4px; }
/* 【Phase4.1:数据新鲜度+健康分数】 */
.rb-freshness { font-size: 10px; margin: 0 4px; }
.rb-freshness.green { color: #52c41a; }
.rb-freshness.yellow { color: #faad14; }
.rb-freshness.red { color: #ff4d4f; }
.rb-score { font-size: 11px; font-weight: 600; color: var(--text-secondary); background: var(--bg-elevated); border-radius: 4px; padding: 1px 5px; margin-left: 4px; }

/* Tab导航栏 */
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

/* Tab内容区 */
.mm-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.mm-tab-scroll { flex: 1; overflow-y: auto; padding: 12px 16px; }

/* 历史Tab */
.ht-timeline { display: flex; flex-direction: column; gap: 2px; }
.ht-orders { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }
.ho-header { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }
.ho-row { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; }
.ho-row:hover { background: var(--bg-muted); }
.ht-closed { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }
.hc-header { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }
.hc-row { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; cursor: pointer; }
.hc-row:hover { background: var(--bg-muted); }
.hc-win { border-left: 3px solid var(--stock-up); }
.hc-loss { border-left: 3px solid var(--stock-down); }
.ht-audit { display: flex; flex-direction: column; gap: 2px; }
.ha-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }
.ha-action { color: var(--el-color-primary); font-weight: 600; min-width: 60px; }
.ha-detail { color: var(--text-secondary); }
.ht-export { display: flex; gap: 8px; flex-wrap: wrap; }
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

/* 绩效Tab */
.pnl-chart-wrap-lg {
  background: var(--bg-elevated);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 12px;
  border: 1px solid var(--border-default);
}

/* 风控Tab */
.risk-overview { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.ro-card { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--border-default); border-radius: 6px; font-size: 12px; background: var(--bg-normal); }
.ro-label { color: var(--text-tertiary); }
.ro-value { font-weight: 600; font-family: 'JetBrains Mono', monospace; }
.risk-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}
.risk-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 10px 12px;
}
.rc-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.rc-detail {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.rc-row {
  display: flex;
  justify-content: space-between;
}
.rc-row span:first-child { color: var(--text-tertiary); }

/* 复盘Tab */
.review-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-scan-stats { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 8px 12px; border-radius: 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); }
.rss-row { font-size: 12px; }
.rss-label { color: var(--text-tertiary); margin-right: 4px; }
.rss-value { font-weight: 600; }
.review-funnel-detail { margin-top: 6px; }
.rfd-row { display: flex; align-items: center; gap: 8px; font-size: 11px; padding: 2px 0; }
.rfd-layer { width: 70px; text-align: right; color: var(--text-tertiary); flex-shrink: 0; }
.rfd-bar-track { flex: 1; height: 12px; background: var(--bg-secondary); border-radius: 3px; overflow: hidden; }
.rfd-bar-fill { height: 100%; border-radius: 3px; background: var(--stock-up); opacity: 0.6; }
.rfd-rej { font-weight: 600; color: var(--stock-up); font-size: 10px; min-width: 50px; }
.review-sentiment-snap { margin-top: 8px; padding: 6px 12px; border-radius: 6px; background: rgba(22,93,255,0.05); border-left: 3px solid var(--el-color-primary); font-size: 12px; display: flex; gap: 8px; }

/* ==================== 情绪Tab ==================== */
.sentiment-chart { display: flex; flex-direction: column; height: 260px; position: relative; border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; background: var(--bg-elevated); }
.sc-y-axis { display: flex; flex-direction: column-reverse; justify-content: space-between; padding: 4px 6px; font-size: 10px; color: var(--text-tertiary); min-width: 32px; text-align: right; }
.sc-chart-row { display: flex; flex: 1; min-height: 0; }
.sc-chart-body { flex: 1; position: relative; display: flex; flex-direction: column-reverse; }
.sc-band { width: 100%; position: relative; z-index: 1; }
.sc-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; }
.sc-dot { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: var(--el-color-primary); transform: translate(-50%, 50%); z-index: 4; cursor: pointer; transition: transform 0.15s; }
.sc-dot:hover { transform: translate(-50%, 50%) scale(2); }
.sc-dot.hot { background: #f56c6c; }
.sc-dot.cold { background: #67c23a; }
.sc-dot-null { position: absolute; width: 4px; height: 4px; border-radius: 50%; background: var(--text-quaternary); transform: translate(-50%, 0); z-index: 4; top: 50%; opacity: 0.5; }
.sc-dot.missing { background: var(--el-color-warning); opacity: 0.6; }
.sc-hover-card { position: absolute; z-index: 10; background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 6px 10px; font-size: 12px; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,0.15); white-space: nowrap; }
.sc-hover-date { color: var(--text-secondary); margin-bottom: 2px; }
.sc-hover-score { font-weight: 600; font-size: 14px; }
.sc-hover-score.hot { color: #f56c6c; }
.sc-hover-score.cold { color: #67c23a; }
.sc-hover-detail { color: var(--text-tertiary); margin-top: 2px; }
.sc-hover-warn { color: var(--el-color-warning); margin-top: 2px; }
.sc-trade-marker { position: absolute; font-size: 10px; z-index: 5; font-weight: 700; }
.sc-trade-marker.buy { color: var(--stock-down); }
.sc-trade-marker.sell { color: var(--stock-up); }
.sc-x-labels { display: flex; justify-content: space-between; padding: 4px 8px 4px 40px; font-size: 11px; color: var(--text-tertiary); border-top: 1px solid var(--border-default); min-height: 22px; }

.sentiment-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sentiment-panel { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.sl-content { margin-top: 6px; }
.sl-gauge { margin-bottom: 8px; }
.sl-gauge-bar { height: 16px; background: var(--bg-secondary); border-radius: 8px; overflow: hidden; }
.sl-gauge-fill { height: 100%; border-radius: 8px; transition: width 0.5s; }
.sl-score-labels { display: flex; justify-content: space-between; font-size: 9px; color: var(--text-tertiary); margin-top: 2px; }
.sl-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
.sl-row span:first-child { color: var(--text-tertiary); }
.sl-val { font-weight: 600; }
.sl-board { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.sl-board-item { font-size: 11px; background: var(--bg-secondary); padding: 1px 6px; border-radius: 4px; }
.sl-board-n { color: var(--text-tertiary); }
.sl-board-c { font-weight: 600; margin-left: 2px; }

.matrix-table-wrap { overflow-x: auto; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.matrix-table th { padding: 6px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); }
.matrix-table td { padding: 6px 8px; text-align: center; border-bottom: 1px solid var(--border-default); }
.mt-strat { font-weight: 600; text-align: left !important; white-space: nowrap; }
.mt-cell { min-width: 80px; }
.mt-count { font-weight: 600; }
.mt-wr { font-size: 10px; }
.mt-pnl { font-size: 10px; font-weight: 600; }
.mt-empty { color: var(--text-quaternary); }
.mt-total { font-weight: 600; color: var(--text-secondary); }

.rec-card { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; margin-bottom: 6px; font-size: 12px; }
.rec-strat { font-weight: 600; min-width: 70px; }
.rec-stat { color: var(--text-tertiary); margin-left: auto; }
.rec-pnl { font-weight: 700; }
.review-tabs { display: flex; gap: 2px; }
.review-tab { padding: 6px 14px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 13px; cursor: pointer; transition: all 0.2s; }
.review-tab:hover { background: var(--bg-hover); }
.review-tab.active { background: var(--el-color-primary); color: var(--text-inverse); border-color: var(--el-color-primary); }
.review-summary-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
.rsc { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; text-align: center; }
.rsc-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.rsc-value { font-size: 16px; font-weight: 600; }
.strategy-contrib { display: flex; flex-direction: column; gap: 8px; }
.strat-card { padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-default); background: var(--bg-elevated); }
.strat-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.strat-pnl { font-weight: 700; font-size: 14px; margin-left: auto; }
.strat-pnl.up { color: var(--stock-down); }
.strat-pnl.down { color: var(--stock-up); }
.strat-metrics { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.strat-m { font-size: 11px; }
.strat-ml { color: var(--text-tertiary); margin-right: 4px; }
.strat-mv { font-weight: 600; }
.attribution-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; margin-bottom: 6px; }
.attr-top { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.attr-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; font-size: 12px; }
.attr-row { display: flex; justify-content: space-between; }
.attr-row span:first-child { color: var(--text-tertiary); }
.attr-scan { margin-top: 6px; padding: 6px 8px; border-radius: 4px; background: rgba(22,93,255,0.05); border-left: 3px solid var(--el-color-primary); }
.attr-scan-title { font-size: 11px; font-weight: 600; color: var(--el-color-primary); margin-bottom: 4px; }
.weekly-daily-table { font-size: 12px; }
.wdt-header, .wdt-row { display: grid; grid-template-columns: 90px 1fr 60px 60px 80px; gap: 8px; padding: 4px 0; }
.wdt-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.eq-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.eq-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; text-align: center; }
.eq-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.eq-value { font-size: 15px; font-weight: 600; }
.eq-value.ok { color: var(--stock-down); }
.eq-value.warn { color: var(--stock-up); }
.lb-table { font-size: 12px; }
.lb-header, .lb-row { display: grid; grid-template-columns: 70px 60px 60px 60px 60px 70px 60px 60px; gap: 4px; padding: 3px 0; }
.lb-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.suggestions { display: flex; flex-direction: column; gap: 6px; }
.suggestion { padding: 8px 12px; border-radius: 6px; font-size: 12px; }
.suggestion.warn { background: rgba(250,173,20,0.1); border: 1px solid rgba(250,173,20,0.3); }
.suggestion.info { background: rgba(22,119,255,0.1); border: 1px solid rgba(22,119,255,0.3); }

/* 盘前竞价Tab */
.pm-status-bar { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--bg-elevated); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 10px; }
.pm-status-icon { font-size: 28px; }
.pm-status-title { font-size: 15px; font-weight: 600; }
.pm-status-sub { font-size: 11px; color: var(--text-tertiary); }
.pm-status-actions { margin-left: auto; display: flex; align-items: center; gap: 4px; }
.pm-mode-btn { padding: 2px 8px; font-size: 11px; border-radius: 4px; border: 1px solid var(--border-default); background: var(--bg-elevated); cursor: pointer; color: var(--text-secondary); }
.pm-mode-btn.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.pm-debug-badge { display: inline-block; font-size: 9px; background: var(--el-color-warning); color: #fff; padding: 0 4px; border-radius: 2px; margin-left: 4px; vertical-align: middle; }

.pm-debug-panel { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.pm-dp-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.pm-funnel { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.pm-funnel-step { display: flex; flex-direction: column; align-items: center; background: var(--bg-muted); border-radius: 6px; padding: 4px 10px; min-width: 56px; }
.pm-fs-label { font-size: 9px; color: var(--text-tertiary); }
.pm-fs-val { font-size: 16px; font-weight: 700; }
.pm-fs-val.up { color: var(--el-color-success); }
.pm-fs-val.warn { color: var(--el-color-warning); }
.pm-funnel-arrow { color: var(--text-tertiary); font-size: 14px; }
.pm-blocked-reasons { margin-top: 8px; }
.pm-br-item { display: flex; justify-content: space-between; padding: 2px 0; font-size: 11px; border-bottom: 1px solid var(--border-default); }
.pm-br-reason { color: var(--text-secondary); }
.pm-br-count { font-weight: 600; color: var(--el-color-warning); }

/* 涨停池+连板+板块 */
.pm-zt-section { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.pm-zt-header { display: flex; gap: 16px; margin-bottom: 6px; }
.pm-zt-body { font-size: 12px; }
.pm-continue-bar { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.pm-cb-label { font-size: 10px; color: var(--text-tertiary); font-weight: 600; }
.pm-cb-item { background: var(--bg-muted); padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.pm-cb-item.hot { background: #f56c6c18; color: var(--el-color-danger); font-weight: 600; }
.pm-sector-heat { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; flex-wrap: wrap; }
.pm-sh-label { font-size: 10px; color: var(--text-tertiary); font-weight: 600; }
.pm-sh-item { background: var(--bg-muted); padding: 1px 5px; border-radius: 3px; font-size: 11px; }
.pm-sh-item.hot { background: #e6a23c18; color: var(--el-color-warning); font-weight: 600; }
.pm-sh-item sub { font-size: 9px; color: var(--el-color-danger); }
.pm-zt-list { margin-top: 4px; }
.pm-zt-toggle { font-size: 11px; color: var(--text-secondary); padding: 2px 0; }
.pm-zt-toggle:hover { color: var(--text-primary); }
.pm-zt-items { display: flex; flex-wrap: wrap; gap: 4px; padding-top: 4px; }
.pm-zt-tag { font-size: 11px; padding: 1px 5px; border-radius: 3px; }
.pm-zt-tag.sealed { background: #f56c6c18; color: var(--el-color-danger); }
.pm-zt-tag.broken { background: #e6a23c18; color: var(--el-color-warning); }
.pm-zt-tag sub { font-size: 8px; }

/* 持仓竞价影响 */
.pm-pos-gap-section { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.pm-pos-gaps { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.pm-pg-item { display: flex; align-items: center; gap: 8px; padding: 4px 8px; border-radius: 6px; font-size: 12px; }
.pm-pg-item.gap-up { background: #f56c6c08; border-left: 3px solid var(--el-color-danger); }
.pm-pg-item.gap-down { background: #67c23a08; border-left: 3px solid var(--el-color-success); }
.pm-pg-name { font-weight: 600; min-width: 60px; }
.pm-pg-gap { font-weight: 700; font-size: 14px; min-width: 60px; }
.pm-pg-hint { font-size: 10px; color: var(--text-tertiary); }

.pm-overview { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.pm-ov-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.pm-ov-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 4px; }
.pm-ov-val { font-size: 16px; font-weight: 700; }
.pm-ov-sub { font-size: 11px; font-weight: 400; color: var(--text-secondary); margin-left: 4px; }
.pm-ov-row { display: flex; align-items: baseline; gap: 2px; font-size: 18px; font-weight: 700; }
.pm-ov-sep { color: var(--text-tertiary); font-weight: 400; margin: 0 2px; }
.pm-ov-hint { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }
.pm-ov-card.pm-sentiment { border-left: 3px solid var(--el-color-warning); }

/* 盘前综合分析 */
.pm-analysis { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.pm-analysis-head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.pm-analysis-icon { font-size: 18px; }
.pm-analysis-title { font-size: 13px; font-weight: 600; }
.pm-analysis-date { font-size: 10px; color: var(--text-tertiary); margin-left: auto; }
.pm-conclusion { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-radius: 6px; margin-bottom: 8px; font-size: 14px; font-weight: 700; }
.pm-conclusion.bullish { background: #67c23a10; color: var(--el-color-success); }
.pm-conclusion.bearish { background: #f56c6c10; color: var(--el-color-danger); }
.pm-conclusion.neutral { background: #e6a23c10; color: var(--el-color-warning); }
.pm-verdict-icon { font-size: 18px; }
.pm-reasons { display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; }
.pm-reason-item { display: flex; align-items: baseline; gap: 4px; font-size: 12px; color: var(--text-secondary); }
.pm-reason-icon { font-size: 12px; flex-shrink: 0; }
.pm-suggestion { display: flex; align-items: baseline; gap: 4px; padding: 6px 8px; background: var(--bg-muted); border-radius: 4px; font-size: 12px; }
.pm-sugg-label { font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.pm-sugg-text { color: var(--text-secondary); }

.pm-groups { display: flex; flex-direction: column; gap: 8px; }
.pm-group { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.pm-group-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--border-default); background: var(--bg-muted); }
.pm-group-header.cp { cursor: pointer; }
.pm-group-header.cp:hover { background: var(--bg-hover); }
.pm-group-toggle { font-size: 9px; color: var(--text-tertiary); min-width: 10px; }
.pm-group-preview { margin-left: auto; font-size: 10px; color: var(--text-tertiary); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-group-stat { font-size: 11px; color: var(--text-secondary); }
.pm-group-stat.executed { color: var(--el-color-success); }
.pm-group-stat.hit-rate { margin-left: auto; font-size: 10px; }
.pm-group-stat.warn { color: var(--el-color-warning); }
.pm-group-list { padding: 4px 12px; }
.pm-item { display: flex; align-items: center; gap: 6px; padding: 5px 0; font-size: 12px; border-bottom: 1px solid var(--border-default); }
.pm-item:last-child { border-bottom: none; }
.pm-item-code { font-family: monospace; font-size: 10px; color: var(--text-tertiary); min-width: 50px; }
.pm-item-name { font-size: 12px; min-width: 60px; }
.pm-item-pct { font-weight: 600; min-width: 48px; }
.pm-item-factor { font-size: 10px; color: var(--text-tertiary); background: var(--bg-muted); padding: 0 4px; border-radius: 2px; }
.pm-item-reason { font-size: 10px; color: var(--text-tertiary); margin-left: auto; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.pm-list-mode { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.pm-table-header { display: grid; grid-template-columns: 56px 72px 72px 56px 44px 52px 48px 40px; gap: 4px; padding: 6px 12px; font-size: 10px; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); background: var(--bg-muted); }
.pm-table-row { display: grid; grid-template-columns: 56px 72px 72px 56px 44px 52px 48px 40px; gap: 4px; padding: 5px 12px; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-default); }
.pm-table-row:hover { background: var(--bg-hover); }

.pm-auction-section { margin-top: 12px; }
.pm-auction-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 6px; margin-top: 6px; }
.pm-auction-item { display: flex; align-items: center; gap: 4px; padding: 6px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; font-size: 12px; }

.pm-signal-section { margin-top: 12px; }
.pm-signal-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.pm-signal-item { display: flex; align-items: center; gap: 6px; padding: 6px 10px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; font-size: 12px; }

.pm-empty-state { text-align: center; padding: 32px 16px; }
.pm-empty-icon { font-size: 36px; margin-bottom: 8px; }
.pm-empty-text { font-size: 14px; color: var(--text-secondary); margin-bottom: 4px; }
.pm-empty-hint { font-size: 11px; color: var(--text-tertiary); }

/* 扫描追踪Tab */
.scan-hours { display: flex; flex-direction: column; gap: 4px; }
.sc-hour-group { margin-bottom: 2px; }
.sc-hour-header { display: flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; background: var(--bg-elevated); border: 1px solid var(--border-default); }
.sc-hour-header:hover { background: var(--bg-hover); }
.sc-hour-toggle { font-size: 9px; color: var(--text-tertiary); }
.sc-hour-label { font-weight: 600; color: var(--text-primary); }
.sc-hour-count { color: var(--text-tertiary); font-size: 10px; }
.sc-hour-summary { color: var(--el-color-primary); font-size: 10px; margin-left: auto; }
.scan-strip { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0 0 16px; }
.scan-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; border: 1px solid var(--border-default); background: var(--bg-elevated); transition: all 0.15s; }
.scan-chip:hover { background: var(--bg-hover); border-color: var(--el-color-primary-light-5); }
.scan-chip.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary); }
.sc-time { color: var(--text-tertiary); font-family: 'JetBrains Mono', monospace; }
.sc-type { font-weight: 600; padding: 1px 5px; border-radius: 3px; font-size: 10px; }
.sc-type.full { background: rgba(0,180,42,0.12); color: #00b42a; }
.sc-type.quick { background: rgba(22,93,255,0.12); color: #165dff; }
.sc-stats { display: inline-flex; align-items: center; gap: 2px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
.ss-all { color: var(--text-tertiary); font-size: 10px; }
.ss-arr { color: var(--text-tertiary); font-size: 9px; margin: 0 1px; }
.ss-pass { color: var(--el-color-primary); font-weight: 600; }
.ss-buy { color: var(--text-tertiary); font-weight: 600; }
.ss-buy.has-buy { color: #f56c6c; }

.scan-funnel { padding: 8px 0; }
.fn-row { display: flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 5px; font-size: 11px; margin-bottom: 2px; }
.fn-row.fn-filter { background: rgba(245,63,63,0.04); }
.fn-row.fn-pass { background: rgba(0,180,42,0.03); }
.fn-tag { font-weight: 600; min-width: 56px; flex-shrink: 0; }
.fn-flow { font-family: 'JetBrains Mono', monospace; font-weight: 600; flex-shrink: 0; }
.fn-rej { color: var(--stock-down); flex-shrink: 0; font-size: 10px; }
.fn-desc { color: var(--text-tertiary); font-size: 10px; line-height: 1.4; flex: 1; min-width: 0; }
.fn-total { padding: 6px 8px 0; font-size: 12px; font-weight: 600; border-top: 1px solid var(--border-default); margin-top: 4px; }
.funnel { display: flex; flex-direction: column; gap: 2px; }
.funnel-step { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 6px; font-size: 12px; border: 1px solid var(--border-default); }
.funnel-step.passed { background: rgba(0,180,42,0.06); border-color: rgba(0,180,42,0.2); }
.funnel-step.rejected { background: rgba(245,63,63,0.06); border-color: rgba(245,63,63,0.2); }
.fn-label { font-weight: 600; width: 80px; }
.fn-count { flex: 1; }
.fn-reject { color: var(--stock-up); font-size: 11px; }
.fn-arrow { text-align: center; color: var(--text-tertiary); font-size: 12px; }
.et-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 2px; }
.et-item { display: flex; align-items: center; gap: 3px; padding: 2px 5px; font-size: 11px; border-radius: 3px; }
.et-item.et-pass { background: rgba(0,180,42,0.05); }
.et-item.et-fail { background: rgba(245,63,63,0.04); }
.et-ok { color: var(--stock-up); flex-shrink: 0; }
.et-no { color: var(--stock-down); font-size: 9px; flex-shrink: 0; }
/* 【v2.9.7: 候选过滤按钮+淘汰统计+加载更多 */
.tab-btn-sm { padding: 2px 10px; border-radius: 4px; border: 1px solid var(--border-default); background: transparent; font-size: 11px; cursor: pointer; color: var(--text-secondary); transition: all 0.15s; }
.tab-btn-sm:hover { border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); }
.tab-btn-sm.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); font-weight: 600; }
.tab-btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.rejected-stats { padding: 8px 0; }
.rs-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
.rs-label { min-width: 72px; color: var(--text-secondary); }
.rs-bar-track { flex: 1; height: 16px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.rs-bar-fill { height: 100%; background: rgba(245,63,63,0.25); border-radius: 3px; transition: width 0.3s; }
.rs-count { min-width: 40px; text-align: right; font-weight: 600; }
.load-more-hint { text-align: center; padding: 8px 0; }
.et-strat { line-height: 1; }
.et-result { font-size: 10px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 情绪Tab */
.limit-pool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 6px;
}
.limit-pool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-elevated);
  border-radius: 6px;
  border: 1px solid var(--border-default);
  font-size: 12px;
}

/* 运维Tab */
.auto-trades-list { font-size: 12px; }
.at-header, .at-row { display: grid; grid-template-columns: 52px 50px 28px 72px 56px 50px 60px 56px 1fr; gap: 4px; padding: 3px 0; align-items: center; }
.at-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); font-size: 11px; }
.at-row { border-bottom: 1px solid var(--border-default); }
.at-row:last-child { border-bottom: none; }
.at-row.auto-trade { background: rgba(22,119,255,0.03); }
.at-row.manual-trade { background: rgba(250,173,20,0.03); }

/* 参数对比 */
.param-compare { display: flex; flex-direction: column; gap: 8px; }
.pc-strategy { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.pc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.pc-name { font-weight: 600; font-size: 13px; }
.pc-params { display: flex; flex-direction: column; gap: 2px; }
.pc-diff-row { display: grid; grid-template-columns: 140px 1fr 1fr; gap: 8px; padding: 3px 6px; border-radius: 4px; font-size: 12px; background: rgba(245,63,63,0.06); }
.pc-same-row { display: grid; grid-template-columns: 140px 1fr; gap: 8px; padding: 2px 6px; font-size: 11px; color: var(--text-tertiary); }
.pc-key { font-weight: 500; }
.pc-live { color: var(--el-color-primary); }
.pc-bt { color: var(--stock-up); }

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

.pos-focused {
  border: 2px solid var(--el-color-primary) !important;
  box-shadow: 0 0 8px var(--el-color-primary-light-5);
}
/* 日期选择器: 交易日有数据 */
:deep(.el-date-table td.has-scan-data) {
  .el-date-table-cell__text {
    background: var(--el-color-primary);
    color: #fff;
    font-weight: 600;
    border-radius: 50%;
  }
}
/* 日期选择器: 调试数据(非交易日) */
:deep(.el-date-table td.has-scan-debug) {
  .el-date-table-cell__text {
    background: #e6a23c;
    color: #fff;
    font-weight: 600;
    border-radius: 50%;
  }
}
/* 扫描记录: 调试标记 */
.scan-chip.debug { border-style: dashed; opacity: 0.85; }
.sc-debug-tag { font-size: 9px; padding: 1px 4px; border-radius: 3px; background: rgba(230,162,60,0.15); color: #e6a23c; font-weight: 600; }
/* 情绪Tab - 新增样式 */
.sentiment-3col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.phase-guide { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.phase-card { border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; transition: all 0.2s; opacity: 0.65; }
.phase-card.active { opacity: 1; box-shadow: 0 0 0 2px var(--el-color-primary); transform: translateY(-1px); }
.phase-header { display: flex; align-items: center; gap: 4px; padding: 6px 8px; font-size: 12px; }
.phase-icon { font-size: 16px; }
.phase-name { font-weight: 700; font-size: 13px; }
.phase-range { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.phase-body { padding: 6px 8px; }
.phase-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.phase-label { color: var(--text-tertiary); }
.phase-val { color: var(--text-primary); font-weight: 500; }
.downgrade-rules { display: flex; flex-direction: column; gap: 4px; }
.dg-rule { display: flex; align-items: center; gap: 6px; padding: 4px 10px; font-size: 11px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); }
.dg-from, .dg-to { font-weight: 700; min-width: 28px; }
.dg-arrow { color: var(--text-quaternary); }
.dg-action { color: var(--el-color-warning); font-weight: 600; min-width: 60px; }
.dg-desc { color: var(--text-tertiary); }
.rec-warn-section { display: flex; flex-direction: column; gap: 8px; }
.rw-card { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border-default); }
.rw-card.rw-rec { background: rgba(64,158,255,0.06); border-color: rgba(64,158,255,0.2); }
.rw-card.rw-strat { background: rgba(103,194,58,0.06); border-color: rgba(103,194,58,0.2); }
.rw-card.rw-warn { background: rgba(245,108,108,0.06); border-color: rgba(245,108,108,0.2); }
.rw-card.rw-caution { background: rgba(230,162,60,0.06); border-color: rgba(230,162,60,0.2); }
.rw-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.rw-content { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.algo-info { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.algo-section { border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; }
.algo-title { font-weight: 700; font-size: 12px; padding: 6px 10px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); }
.algo-body { padding: 8px 10px; font-size: 11px; color: var(--text-secondary); line-height: 1.6; }

/* 复盘Tab - 5层架构 */
.hero-banner { padding: 14px 16px; border-radius: 10px; margin-bottom: 8px; }
.hero-banner.profit { background: linear-gradient(135deg, rgba(103,194,58,0.12), rgba(103,194,58,0.04)); border: 1px solid rgba(103,194,58,0.25); }
.hero-banner.slight_profit { background: linear-gradient(135deg, rgba(103,194,58,0.08), rgba(230,162,60,0.04)); border: 1px solid rgba(103,194,58,0.15); }
.hero-banner.slight_loss { background: linear-gradient(135deg, rgba(230,162,60,0.12), rgba(245,108,108,0.04)); border: 1px solid rgba(230,162,60,0.25); }
.hero-banner.loss { background: linear-gradient(135deg, rgba(245,108,108,0.12), rgba(245,108,108,0.04)); border: 1px solid rgba(245,108,108,0.25); }
.hero-banner.neutral { background: var(--bg-elevated); border: 1px solid var(--border-default); }
.hero-conclusion { font-size: 15px; font-weight: 700; line-height: 1.5; margin-bottom: 4px; }
.hero-meta { display: flex; gap: 12px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; }
.hero-bench { }
.hero-alpha { font-weight: 600; }
.hero-sentiment { }
.review-scorecard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.review-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.violations-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.violation-item { display: flex; align-items: flex-start; gap: 6px; padding: 5px 8px; border-radius: 6px; font-size: 11px; line-height: 1.4; }
.violation-item.sev-high { background: rgba(245,108,108,0.08); border: 1px solid rgba(245,108,108,0.15); }
.violation-item.sev-medium { background: rgba(230,162,60,0.08); border: 1px solid rgba(230,162,60,0.15); }
.v-icon { flex-shrink: 0; }
.v-type { font-weight: 600; min-width: 64px; color: var(--text-primary); }
.v-detail { color: var(--text-secondary); }
.attr-profit { border-left: 3px solid rgba(103,194,58,0.4); }
.attr-loss { border-left: 3px solid rgba(245,108,108,0.4); }
.eq-grid-mini { display: flex; flex-direction: column; gap: 4px; }
.eq-row { display: flex; justify-content: space-between; font-size: 11px; padding: 3px 0; border-bottom: 1px solid var(--border-default); }
.forward-section { display: flex; flex-direction: column; gap: 8px; }

/* 偏差趋势图 */
.deviation-trend-chart { background: var(--bg-elevated); border-radius: 8px; padding: 12px; }
.trend-axis { display: flex; align-items: flex-end; gap: 8px; height: 120px; padding-top: 20px; }
.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.trend-bar { width: 100%; border-radius: 4px 4px 0 0; min-height: 20px; position: relative; transition: height 0.3s; }
.trend-val { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-size: 11px; font-weight: 600; white-space: nowrap; }
.trend-label { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
.trend-sub { font-size: 10px; color: var(--text-tertiary); }

/* 日历热力图 */
.calendar-heatmap { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; padding: 8px; background: var(--bg-elevated); border-radius: 8px; }
.cal-cell { border-radius: 6px; padding: 4px 2px; text-align: center; font-size: 10px; min-height: 48px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.cal-up { background: rgba(207, 48, 48, 0.15); color: var(--color-up, #f56c6c); }
.cal-down { background: rgba(103, 194, 58, 0.15); color: var(--color-down, #67c23a); }
.cal-neutral { background: var(--bg-elevated); color: var(--text-tertiary); }
.cal-date { font-weight: 600; }
.cal-pnl { font-size: 10px; font-weight: 600; }
.cal-trades { font-size: 9px; color: var(--text-tertiary); }

/* 策略贡献堆积图 */
.strategy-stacked { display: flex; flex-direction: column; gap: 4px; padding: 8px; background: var(--bg-elevated); border-radius: 8px; }
.stacked-bar { display: flex; align-items: center; justify-content: space-between; border-radius: 4px; padding: 4px 8px; min-width: 80px; }
.stacked-label { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }
.stacked-val { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }

/* 因子效果跟踪 */
.factor-effect-section { display: flex; flex-direction: column; gap: 8px; }
.factor-group { background: var(--bg-elevated); border-radius: 8px; padding: 8px; }
.factor-name { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.factor-period { margin-bottom: 6px; }
.factor-period-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 2px; }
.factor-bars { display: flex; flex-direction: column; gap: 2px; }
.factor-bar-row { display: flex; align-items: center; gap: 6px; }
.fb-name { width: 60px; font-size: 10px; text-align: right; color: var(--text-secondary); }
.fb-bar-bg { flex: 1; height: 14px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; }
.fb-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.fb-up { background: var(--color-up, #f56c6c); }
.fb-mid { background: var(--color-warn, #e6a23c); }
.fb-down { background: var(--color-down, #67c23a); }
.fb-wr { width: 36px; font-size: 10px; font-weight: 600; text-align: right; }
.fb-cnt { width: 28px; font-size: 9px; color: var(--text-tertiary); }

/* 闭环建议 */
.closed-loop-list { display: flex; flex-direction: column; gap: 6px; }
.cl-card { border-radius: 8px; padding: 8px 10px; border-left: 3px solid; }
.cl-high { background: rgba(245,108,108,0.08); border-color: #f56c6c; }
.cl-medium { background: rgba(230,162,60,0.08); border-color: #e6a23c; }
.cl-low { background: rgba(144,147,153,0.08); border-color: #909399; }
.cl-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.cl-sev { font-size: 14px; }
.cl-type { font-weight: 600; font-size: 12px; }
.cl-diagnosis { font-size: 11px; color: var(--text-secondary); margin-bottom: 2px; }
.cl-action { font-size: 11px; font-weight: 600; margin-bottom: 2px; }
.cl-verify { font-size: 10px; color: var(--text-tertiary); }
.cl-cases { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }
.fw-card { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border-default); font-size: 12px; }
.fw-card.fw-advice { background: rgba(64,158,255,0.06); border-color: rgba(64,158,255,0.2); }
.fw-card.fw-open { background: rgba(103,194,58,0.06); border-color: rgba(103,194,58,0.15); }
.fw-card.fw-close { background: rgba(245,108,108,0.06); border-color: rgba(245,108,108,0.15); }
.fw-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.fw-content { color: var(--text-secondary); line-height: 1.5; }
.fw-switches { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.fw-icon { margin-right: 4px; }

.dev-card { padding: 10px 12px; border-radius: 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); }
.dev-title { font-weight: 700; font-size: 13px; margin-bottom: 6px; }
.dev-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }

</style>
