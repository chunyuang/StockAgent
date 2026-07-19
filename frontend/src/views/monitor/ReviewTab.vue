<script setup lang="ts">
/**
 * ReviewTab — 📋 复盘Tab (专业版)
 * 
 * 从MarketMonitorView.vue提取【v2.9.70】
 * 所有状态由父组件通过props传入, 避免重复实例化composable。
 * 
 * Props: review composable的展开状态 + 策略映射
 * Emits: fetchReviewData, runBacktest, saveParamSnapshot
 */
import { computed, ref } from 'vue'
import { ElButton, ElTag } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { formatTradeDate, formatFullDate } from '@/utils/scanner'
import FactorEffectSection from './components/FactorEffectSection.vue'

const props = defineProps<{
  visible: boolean
  strategyCN: (s: string | number) => string | number
  strategyMeta: Record<string, any>
  reviewTab: 'daily' | 'weekly' | 'monthly'
  reviewLoading: boolean
  reviewDate: string
  reviewHero: any
  reviewForward: any
  dailyReportData: any
  // ⚠️ 命名区分: weeklyReportData=周报弹窗(/weekly-report API), weeklyReviewData=周复盘内容(/review-weekly API)
  weeklyReportData: any    // 周报弹窗数据: account/totals/strategy_summary/daily_stats
  weeklyReviewData: any   // 周复盘审查数据: summary/strategy_stats/daily_breakdown/weekly_trend
  monthlyReviewData: any
  deviationData: any
  closedLoopData: any
  tradeAttributions: any[]
  paramDriftData: any
  factorEffectData: any
  disciplineCheck: any
  executionQuality: any
  liveBacktestDiff: any[]
  backtestRunning: boolean
  // v2.9.75: 补齐模板使用但缺失的props
  compareVisible: boolean
  compareData: any[]
  dailyReportVisible: boolean
  dailyReport: any
  weeklyReportVisible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:reviewTab', val: string): void
  (e: 'update:reviewDate', val: string): void
  (e: 'update:compareVisible', val: boolean): void
  (e: 'update:dailyReportVisible', val: boolean): void
  (e: 'update:weeklyReportVisible', val: boolean): void
  (e: 'fetchReviewData'): void
  (e: 'runBacktest'): void
  (e: 'saveParamSnapshot'): void
}>()

// 折叠状态
const tradeDetailExpanded = ref(false)
const slippageDetailExpanded = ref(false)
const disciplineExpanded = ref(false)
const backtestDiffExpanded = ref(false)
const weeklyStrategyExpanded = ref(false)
const weeklyTrendExpanded = ref(false)
const weeklyDailyExpanded = ref(false)
const monthlyTrendExpanded = ref(false)
const monthlyBehaviorExpanded = ref(false)
const monthlyCalendarExpanded = ref(false)
const monthlyStrategyExpanded = ref(false)
const monthlyStrategyCount = computed(() => Object.keys(props.monthlyReviewData?.strategy_stats || {}).length)
const monthlyStrategyPnl = computed(() => (Object.values(props.monthlyReviewData?.strategy_stats || ({} as any)) as any[]).reduce((s: number, d: any) => s + (d.pnl || 0), 0))
const monthlyParamExpanded = ref(false)
const monthlyFactorExpanded = ref(false)
const monthlyClosedLoopExpanded = ref(false)
</script>

<template>
  <div v-if="visible" class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 日期/周期选择 -->
      <div class="review-header">
        <div class="review-tabs">
          <button :class="['review-tab', reviewTab === 'daily' ? 'active' : '']" @click="emit('update:reviewTab', 'daily'); emit('fetchReviewData')">📊 日复盘</button>
          <button :class="['review-tab', reviewTab === 'weekly' ? 'active' : '']" @click="emit('update:reviewTab', 'weekly'); emit('fetchReviewData')">📅 周复盘</button>
          <button :class="['review-tab', reviewTab === 'monthly' ? 'active' : '']" @click="emit('update:reviewTab', 'monthly'); emit('fetchReviewData')">📆 月复盘</button>
        </div>
        <UnifiedDateBar @change="(_d: string) => { emit('update:reviewDate', _d); emit('fetchReviewData') }" />
        <ElButton size="small" @click="emit('fetchReviewData')" :loading="reviewLoading">🔄</ElButton>
      </div>

      <!-- ============ Hero: 一行结论+收益+基准+情绪 ============ -->
      <div v-if="reviewTab === 'daily' && reviewHero" class="hero-banner" :class="reviewHero.conclusion_type">
        <div class="hero-conclusion">{{ reviewHero.conclusion }}</div>
        <div class="hero-big-pct" :class="(reviewHero.metrics?.total_pct || 0) >= 0 ? 'up' : 'down'">
          {{ reviewHero.metrics?.total_pct != null ? ((reviewHero.metrics.total_pct >= 0 ? '+' : '') + reviewHero.metrics.total_pct + '%') : '--' }}
        </div>
        <div class="hero-meta">
          <span v-if="reviewHero.benchmark">{{ reviewHero.benchmark.name }} {{ (reviewHero.benchmark.pct_chg || 0) >= 0 ? '+' : '' }}{{ reviewHero.benchmark.pct_chg || 0 }}%</span>
          <span v-if="reviewHero.benchmark" :class="(reviewHero.benchmark.alpha || 0) >= 0 ? 'up' : 'down'">{{ (reviewHero.benchmark.alpha || 0) >= 0 ? '跑赢' : '落后' }}{{ Math.abs(reviewHero.benchmark.alpha || 0) }}%</span>
          <span>🌡{{ reviewHero.sentiment?.period }}{{ reviewHero.sentiment?.score }}</span>
        </div>
      </div>

      <!-- ============ 指标条 (单行紧凑) ============ -->
      <div v-if="reviewTab === 'daily' && reviewHero" class="metric-strip">
        <span class="ms">胜率(闭环) <b>{{ reviewHero.metrics?.win_rate != null ? reviewHero.metrics.win_rate + '%' : '--' }}</b></span>
        <span class="ms">今日交易 <b>{{ reviewHero.metrics?.trades ?? '--' }}</b></span>
        <span class="ms">期望值(笔均) <b :class="reviewHero.metrics?.expectancy != null ? ((reviewHero.metrics.expectancy || 0) >= 0 ? 'up' : 'down') : ''">{{ reviewHero.metrics?.expectancy ?? '--' }}</b></span>
        <span class="ms">纪律评分 <b :class="(reviewHero.metrics?.discipline_score || 0) >= 80 ? 'up' : (reviewHero.metrics?.discipline_score || 0) < 60 ? 'down' : ''">{{ reviewHero.metrics?.discipline_score ?? '--' }}</b></span>
        <span class="ms">盈亏比 <b>{{ reviewHero.metrics?.profit_loss_ratio ?? '--' }}</b></span>
        <span class="ms">止损触发 <b class="down">{{ reviewHero.metrics?.stop_loss_count ?? 0 }}</b></span>
        <span class="ms">止盈触发 <b class="up">{{ reviewHero.metrics?.take_profit_count ?? 0 }}</b></span>
        <span class="ms">最大连亏 <b :class="(reviewHero.metrics?.max_consecutive_loss || 0) >= 3 ? 'down' : ''">{{ reviewHero.metrics?.max_consecutive_loss ?? 0 }}</b></span>
        <span class="ms">闭环进度 <b>{{ reviewHero.metrics?.closed_trades ?? 0 }}/{{ reviewHero.metrics?.buys ?? 0 }}</b></span>
      </div>

      <!-- ============ 双栏: 策略贡献 + 扫描漏斗 ============ -->
      <template v-if="reviewTab === 'daily' && dailyReportData">
        <!-- 🎯策略贡献 -->
        <div v-if="Object.keys(dailyReportData.positions?.strategy_summary || {}).length" class="review-section" style="margin-top:4px">
          <span class="section-title title-red">🎯 策略贡献</span>
          <span class="section-detail">
            <template v-for="(data, key) in dailyReportData.positions?.strategy_summary" :key="key">
              <span class="ir-strat" :style="{borderColor: strategyMeta[key]?.color || 'var(--text-tertiary)'}">
                {{ strategyCN(key) }}<b>{{ data.count || 0 }}</b>只持仓
                <span :class="(Number(data.closed_profit || data.total_profit || 0)) >= 0 ? 'up' : 'down'">{{ (Number(data.closed_profit || data.total_profit || 0)) >= 0 ? '+' : '' }}¥{{ Number(data.closed_profit || data.total_profit || 0).toFixed(0) }}</span>
                <span class="ir-dim">| 闭环胜率{{ Number(data.closed_win_rate || data.win_rate || 0).toFixed(0) }}%</span>
                <span v-if="data.market_value" class="ir-dim">| 市值¥{{ (Number(data.market_value ?? 0) / 10000).toFixed(1) }}万</span>
              </span>
            </template>
          </span>
        </div>

        <!-- 📡扫描漏斗 -->
        <div v-if="dailyReportData?.scanner_stats" class="review-section">
          <span class="section-title title-blue">📡 扫描漏斗</span>
          <span class="section-detail">扫描<b>{{ dailyReportData.scanner_stats.scan_count || 0 }}</b>次 | 发现信号<b>{{ dailyReportData.scanner_stats.total_signals || 0 }}</b>只(均次<b>{{ ((dailyReportData.scanner_stats.total_signals || 0) / Math.max(dailyReportData.scanner_stats.scan_count || 1, 1)).toFixed(0) }}</b>) | 买入<b>{{ dailyReportData.scanner_stats.buy_count || 0 }}</b>笔(信号转化<b>{{ ((dailyReportData.scanner_stats.buy_count || 0) / Math.max(dailyReportData.scanner_stats.total_signals || 1, 1) * 100).toFixed(1) }}%</b>) | 卖出<b>{{ dailyReportData.scanner_stats.sell_count || 0 }}</b>笔 | 止损<b class="down">{{ dailyReportData.scanner_stats.stop_losses || 0 }}</b>笔 | 止盈<b class="up">{{ dailyReportData.scanner_stats.take_profits || 0 }}</b>笔</span>
        </div>

        <!-- 🎯执行质量 -->
        <div v-if="executionQuality" class="review-section">
          <span class="section-title title-green">🎯 执行质量</span>
          <span class="section-detail">平均滑点<b :class="Math.abs(executionQuality.avg_slippage_pct || 0) > 0.5 ? 'down' : ''">{{ (executionQuality.avg_slippage_pct || 0).toFixed(2) }}%</b> | 最大滑点<b>{{ (executionQuality.max_slippage_pct || 0).toFixed(2) }}%</b> | 成交率<b :class="(executionQuality.fill_rate_pct || 0) < 90 ? 'down' : 'up'">{{ (executionQuality.fill_rate_pct || 0).toFixed(0) }}%</b> | 下单<b>{{ executionQuality.total_orders || 0 }}</b>笔/成交<b>{{ executionQuality.filled_orders || 0 }}</b>笔</span>
        </div>

        <!-- 🌡情绪+💰账户：拆成两行避免拥挤 -->
        <div class="review-section" v-if="dailyReportData?.sentiment_snapshot">
          <span class="section-title title-cyan">🌡 情绪状态</span>
          <span class="section-detail">{{ dailyReportData.sentiment_snapshot }}</span>
        </div>
        <div class="review-section" v-if="dailyReportData?.account">
          <span class="section-title title-orange">💰 账户概览</span>
          <span class="section-detail">总资产<b>{{ (Number(dailyReportData.account.total_assets || 0) / 10000).toFixed(1) }}</b>万 | 仓位<b>{{ dailyReportData.account.position_ratio || 0 }}%</b></span>
        </div>

        <!-- 逐笔归因 — 折叠 -->
        <div class="review-section" style="margin-top:4px">
          <span class="section-title title-red" style="cursor:pointer" @click="tradeDetailExpanded = !tradeDetailExpanded">📝 逐笔归因 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ tradeDetailExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!tradeDetailExpanded"><b>{{ tradeAttributions?.length || 0 }}</b>笔交易 | 持仓<b>{{ tradeAttributions?.filter(t => t.status === 'open').length || 0 }}</b>笔 | 已平<b>{{ tradeAttributions?.filter(t => t.status !== 'open').length || 0 }}</b>笔 | 总盈亏<b :class="tradeAttributions?.reduce((s,t) => s + (t.profit_amount || 0), 0) >= 0 ? 'up' : 'down'">¥{{ (tradeAttributions?.reduce((s,t) => s + (t.profit_amount || 0), 0) || 0).toFixed(0) }}</b></span>
        </div>
        <div v-if="tradeDetailExpanded && (tradeAttributions?.length || 0)" class="review-section" style="margin-top:1px">
          <div class="attr-compact">
            <div v-for="t in tradeAttributions" :key="t.ts_code + (t.sell_time || t.buy_time)" class="attr-line" :class="t.status === 'open' ? 'tr-open' : ((t.profit_pct || 0) >= 0 ? 'tr-profit' : 'tr-loss')">
              <span class="mono">{{ t.ts_code }}</span>
              <span class="attr-name">{{ t.stock_name }}</span>
              <ElTag size="small" class="tag-solid tag-xs" :color="strategyMeta[t.strategy]?.color || 'var(--text-tertiary)'">{{ strategyCN(t.strategy) }}</ElTag>
              <span v-if="t.buy_price" class="ir-dim">买入价¥{{ Number(t.buy_price ?? 0).toFixed(2) }}</span>
              <span v-if="t.sell_price" class="ir-dim">卖出价¥{{ Number(t.sell_price ?? 0).toFixed(2) }}</span>
              <span v-if="t.signal_price" class="ir-dim">信号价¥{{ Number(t.signal_price ?? 0).toFixed(2) }}</span>
              <span class="attr-pct" :class="(t.profit_pct || 0) >= 0 ? 'up' : 'down'">{{ t.status === 'open' ? '持仓' : ((t.profit_pct || 0) >= 0 ? '+' : '') + (t.profit_pct || 0).toFixed(1) + '%' }}</span>
              <span v-if="t.profit_amount" class="ir-dim">盈亏¥{{ Number(t.profit_amount ?? 0).toFixed(0) }}</span>
              <span v-if="t.hold_days" class="ir-dim">持有{{ t.hold_days }}日</span>
              <span v-if="t.sell_reason" class="attr-reason">{{ t.sell_reason }}</span>
            </div>
          </div>
        </div>

        <!-- 逐笔滑点明细 — 折叠, 底部 -->
        <div v-if="deviationData?.details?.slippage?.length" class="review-section" style="margin-top:4px">
          <span class="section-title title-blue" style="cursor:pointer" @click="slippageDetailExpanded = !slippageDetailExpanded">📋 逐笔滑点 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ slippageDetailExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!slippageDetailExpanded"><b>{{ deviationData.details.slippage.length }}</b>笔 | 最大滑点<b :class="Math.max(...deviationData.details.slippage.map((s: any) => Math.abs(s.slippage_pct || 0))) > 0.5 ? 'down' : ''">{{ Math.max(...deviationData.details.slippage.map((s: any) => Math.abs(s.slippage_pct || 0))).toFixed(2) }}%</b></span>
        </div>
        <div v-if="slippageDetailExpanded && deviationData?.details?.slippage?.length" class="review-section" style="margin-top:1px">
          <span class="section-detail">
            <div v-for="s in deviationData.details.slippage" :key="s.ts_code" class="v-item" :class="Math.abs(s.slippage_pct || 0) > 0.3 ? 'sev-high' : 'sev-medium'">
              {{ s.ts_code }} {{ s.stock_name }} | 信号价¥{{ s.signal_price?.toFixed(2) }}→成交价¥{{ s.filled_price?.toFixed(2) }} | 滑点<b :class="Math.abs(s.slippage_pct || 0) > 0.3 ? 'down' : ''">{{ s.slippage_pct?.toFixed(2) }}%</b> | {{ strategyCN(s.strategy) }}
            </div>
          </span>
        </div>

        <!-- 纪律检查 — 折叠, 底部 -->
        <div v-if="disciplineCheck" class="review-section" style="margin-top:4px">
          <span class="section-title title-orange" style="cursor:pointer" @click="disciplineExpanded = !disciplineExpanded">🔍 纪律检查 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ disciplineExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!disciplineExpanded">执行正确率<b :class="(disciplineCheck?.execution_rate || 0) >= 80 ? 'up' : (disciplineCheck?.execution_rate || 0) < 60 ? 'down' : ''">{{ disciplineCheck.execution_rate || 0 }}%</b><span v-if="disciplineCheck?.violations?.length" class="down">({{ disciplineCheck.violations.length }}笔违规)</span><span v-else class="up">(无违规)</span></span>
        </div>
        <div v-if="disciplineExpanded && disciplineCheck?.violations?.length" class="review-section" style="margin-top:1px">
          <span class="section-detail">
            <div v-for="(v, i) in disciplineCheck.violations" :key="i" class="v-item" :class="'sev-' + v.severity">
              {{ v.severity === 'high' ? '🔴' : '🟡' }}{{ v.violation }}: {{ v.detail }}
            </div>
          </span>
        </div>

        <!-- 回测偏差 — 列表折叠, 底部 -->
        <div v-if="(liveBacktestDiff?.length || 0)" class="review-section" style="margin-top:4px">
          <span class="section-title title-purple" style="cursor:pointer" @click="backtestDiffExpanded = !backtestDiffExpanded">📊 回测偏差 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ backtestDiffExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!backtestDiffExpanded"><b>{{ liveBacktestDiff.length }}</b>个策略 | 最大偏差<b :class="Math.max(...liveBacktestDiff.map(c => Math.abs((Number(c.live_win_rate) || 0) - (Number(c.bt_win_rate) || 0)))) > 15 ? 'down' : 'up'">{{ Math.max(...liveBacktestDiff.map(c => Math.abs((Number(c.live_win_rate) || 0) - (Number(c.bt_win_rate) || 0)))).toFixed(1) }}%</b></span>
        </div>
        <div v-if="backtestDiffExpanded && (liveBacktestDiff?.length || 0)" class="review-section" style="margin-top:1px">
          <div class="attr-compact">
            <div v-for="c in liveBacktestDiff" :key="c.strategy" class="attr-line">
              <ElTag size="small" class="tag-solid tag-xs" :color="strategyMeta[c.strategy]?.color || 'var(--text-tertiary)'">{{ strategyCN(c.strategy) }}</ElTag>
              <span>实盘<b>{{ c.live_trades || 0 }}</b>笔</span>
              <span>胜率<b :class="(c.live_win_rate || 0) >= 50 ? 'up' : 'down'">{{ c.live_win_rate || 0 }}%</b></span>
              <span class="ir-dim">回测胜率<b>{{ c.bt_win_rate || 0 }}%</b></span>
              <span>偏差<b :class="Math.abs((c.live_win_rate || 0) - (c.bt_win_rate || 0)) > 15 ? 'down' : 'up'">{{ ((Number(c.live_win_rate) || 0) - (Number(c.bt_win_rate) || 0)).toFixed(1) }}%</b></span>
            </div>
          </div>
        </div>
        <div v-else-if="!(liveBacktestDiff?.length || 0)" class="review-section" style="margin-top:4px">
          <span class="section-title title-purple" style="cursor:pointer" @click="backtestDiffExpanded = !backtestDiffExpanded">📊 回测偏差 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ backtestDiffExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail ir-dim">暂无数据 <ElButton size="small" type="primary" @click="emit('runBacktest')" :loading="backtestRunning" style="font-size:10px;padding:0 6px;height:20px;margin-left:4px">▶️运行回测</ElButton></span>
        </div>
      </template>

      <!-- 月复盘：参考日复盘风格，顶部指标 + 底部折叠明细 -->
      <template v-if="reviewTab === 'monthly'">
        <template v-if="monthlyReviewData">
          <div class="review-section" style="margin-top:4px">
            <span class="section-title title-purple">🔬 系统偏差</span>
            <span class="section-detail">{{ monthlyReviewData.period }} | 交易<b>{{ monthlyReviewData.summary?.trades || 0 }}</b>笔 | 胜率<b :class="(monthlyReviewData.summary?.win_rate || 0) >= 50 ? 'up' : 'down'">{{ monthlyReviewData.summary?.win_rate || 0 }}%</b> | 盈亏<b :class="(monthlyReviewData.summary?.pnl || 0) >= 0 ? 'up' : 'down'">{{ (monthlyReviewData.summary?.pnl || 0) >= 0 ? '+' : '' }}{{ monthlyReviewData.summary?.pnl || 0 }}%</b></span>
          </div>
          <div class="metric-strip">
            <span class="ms">交易 <b>{{ monthlyReviewData.summary?.trades || 0 }}</b>笔</span>
            <span class="ms">胜率 <b :class="(monthlyReviewData.summary?.win_rate || 0) >= 50 ? 'up' : 'down'">{{ monthlyReviewData.summary?.win_rate || 0 }}%</b></span>
            <span class="ms">盈亏 <b :class="(monthlyReviewData.summary?.pnl || 0) >= 0 ? 'up' : 'down'">{{ (monthlyReviewData.summary?.pnl || 0) >= 0 ? '+' : '' }}{{ monthlyReviewData.summary?.pnl || 0 }}%</b></span>
            <span class="ms">参数漂移 <b :class="(paramDriftData?.drifts?.length || 0) > 0 ? 'down' : 'up'">{{ paramDriftData?.drifts?.length || 0 }}</b>项</span>
            <span class="ms">闭环建议 <b>{{ closedLoopData?.suggestions?.length || 0 }}</b>条</span>
            <span class="ms">策略数 <b>{{ monthlyStrategyCount }}</b></span>
          </div>

          <div v-if="monthlyReviewData?.weekly_trend?.length" class="review-section" style="margin-top:4px">
            <span class="section-title title-blue" style="cursor:pointer" @click="monthlyTrendExpanded = !monthlyTrendExpanded">📈 偏差趋势 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyTrendExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyTrendExpanded"><b>{{ monthlyReviewData.weekly_trend.length }}</b>周 | 最近胜率<b>{{ monthlyReviewData.weekly_trend[monthlyReviewData.weekly_trend.length - 1]?.win_rate || 0 }}%</b></span>
          </div>
          <div v-if="monthlyTrendExpanded && monthlyReviewData?.weekly_trend?.length" class="deviation-trend-chart">
            <div class="trend-axis">
              <div v-for="w in monthlyReviewData.weekly_trend" :key="w.week" class="trend-col">
                <div class="trend-bar" :style="{height: w.trades > 0 ? Math.max(Math.min(w.win_rate, 100), 8) + '%' : '8px', background: w.trades === 0 ? 'var(--border-default)' : w.win_rate >= 60 ? 'var(--color-up)' : w.win_rate >= 40 ? 'var(--color-warn, #e6a23c)' : 'var(--color-down)'}">
                  <span v-if="w.trades > 0" class="trend-val">{{ w.win_rate }}%</span>
                </div>
                <div class="trend-label">{{ w.week }}</div>
                <div class="trend-sub">{{ w.trades }}笔</div>
              </div>
            </div>
          </div>

          <div class="review-section" style="margin-top:4px">
            <span class="section-title title-orange" style="cursor:pointer" @click="monthlyBehaviorExpanded = !monthlyBehaviorExpanded">⚡ 行为漂移 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyBehaviorExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyBehaviorExpanded">止损执行<b :class="monthlyReviewData.behavior_drift?.stop_loss_execution_rate >= 90 ? 'up' : 'down'">{{ monthlyReviewData.behavior_drift?.stop_loss_execution_rate || 0 }}%</b> | 冰点买入<b :class="monthlyReviewData.behavior_drift?.bearish_period_buy_ratio >= 30 ? 'down' : 'up'">{{ monthlyReviewData.behavior_drift?.bearish_period_buy_ratio || 0 }}%</b></span>
          </div>
          <div v-if="monthlyBehaviorExpanded" class="review-2col" style="margin-top:2px">
            <div class="dev-card"><div class="dev-title">🛡️ 止损执行率</div><div class="dev-row"><span>执行率(止损触发中真亏损)</span><span :class="monthlyReviewData.behavior_drift?.stop_loss_execution_rate >= 90 ? 'up' : 'down'">{{ monthlyReviewData.behavior_drift?.stop_loss_execution_rate || 0 }}%</span></div><div class="dev-row" style="font-size:11px;color:var(--text-tertiary)"><span>亏损走止损{{ monthlyReviewData.behavior_drift?.stop_loss_at_loss || 0 }}笔 / 止损触发{{ monthlyReviewData.behavior_drift?.stop_loss_triggered || 0 }}笔 / 全部亏损{{ monthlyReviewData.behavior_drift?.loss_sells || 0 }}笔</span></div><div v-if="monthlyReviewData.behavior_drift?.stop_loss_coverage_rate" class="dev-row"><span>止损覆盖(亏损走止损率)</span><span>{{ monthlyReviewData.behavior_drift?.stop_loss_coverage_rate || 0 }}%</span></div></div>
            <div class="dev-card"><div class="dev-title">❄️ 冰点期开仓率</div><div class="dev-row"><span>冰点买入占比</span><span :class="monthlyReviewData.behavior_drift?.bearish_period_buy_ratio >= 30 ? 'down' : 'up'">{{ monthlyReviewData.behavior_drift?.bearish_period_buy_ratio || 0 }}%</span></div><div class="dev-row"><span>冰点/总买入</span><span>{{ monthlyReviewData.behavior_drift?.bearish_buys || 0 }}/{{ monthlyReviewData.behavior_drift?.total_buys || 0 }}笔</span></div></div>
          </div>

          <div v-if="monthlyReviewData?.daily_breakdown?.length" class="review-section" style="margin-top:4px">
            <span class="section-title title-cyan" style="cursor:pointer" @click="monthlyCalendarExpanded = !monthlyCalendarExpanded">🗓️ 日历热力 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyCalendarExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyCalendarExpanded"><b>{{ monthlyReviewData.daily_breakdown.length }}</b>个交易日 | 盈利日<b class="up">{{ monthlyReviewData.daily_breakdown.filter((d: any) => (d.pnl || 0) > 0).length }}</b>天 | 亏损日<b class="down">{{ monthlyReviewData.daily_breakdown.filter((d: any) => (d.pnl || 0) < 0).length }}</b>天</span>
          </div>
          <div v-if="monthlyCalendarExpanded && monthlyReviewData?.daily_breakdown?.length" class="calendar-heatmap">
            <div v-for="d in monthlyReviewData.daily_breakdown" :key="d.date" class="cal-cell" :class="(d.pnl || 0) > 0 ? 'cal-up' : (d.pnl || 0) < 0 ? 'cal-down' : 'cal-neutral'">
              <div class="cal-date">{{ formatTradeDate(d.date) }}</div>
              <div class="cal-pnl">{{ (d.pnl || 0) >= 0 ? '+' : '' }}{{ d.pnl || 0 }}%</div>
              <div class="cal-trades">{{ d.trades || 0 }}笔</div>
            </div>
          </div>

          <div v-if="monthlyStrategyCount" class="review-section" style="margin-top:4px">
            <span class="section-title title-red" style="cursor:pointer" @click="monthlyStrategyExpanded = !monthlyStrategyExpanded">🎯 策略贡献 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyStrategyExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyStrategyExpanded"><b>{{ monthlyStrategyCount }}</b>个策略 | 总盈亏<b :class="(monthlyStrategyPnl ?? 0) >= 0 ? 'up' : 'down'">{{ (monthlyStrategyPnl || 0).toFixed(1) }}%</b></span>
          </div>
          <div v-if="monthlyStrategyExpanded && monthlyStrategyCount" class="strategy-stacked">
            <div v-for="(data, key) in (monthlyReviewData?.strategy_stats as any) || {}" :key="key" class="stacked-bar" :style="{width: Math.max(Math.abs(data.pnl || 0), 5) + '%', background: (data.pnl || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
              <span class="stacked-label">{{ strategyCN(key) }}</span>
              <span class="stacked-val">{{ (data.pnl || 0) >= 0 ? '+' : '' }}{{ data.pnl || 0 }}%</span>
            </div>
          </div>

          <div class="review-section" style="margin-top:4px">
            <span class="section-title title-orange" style="cursor:pointer" @click="monthlyParamExpanded = !monthlyParamExpanded">🔧 参数漂移 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyParamExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyParamExpanded"><b :class="(paramDriftData?.drifts?.length || 0) > 0 ? 'down' : 'up'">{{ paramDriftData?.drifts?.length || 0 }}</b>项漂移 | 基线{{ formatFullDate(paramDriftData?.start_date) || '无' }} <ElButton size="small" @click="emit('saveParamSnapshot')" style="font-size:10px;padding:0 6px;height:20px;margin-left:4px">📸 保存快照</ElButton></span>
          </div>
          <div v-if="monthlyParamExpanded && paramDriftData?.drifts?.length" class="violations-list">
            <div v-for="(d, i) in paramDriftData.drifts" :key="i" class="violation-item" :class="d.severity === 'high' ? 'sev-high' : 'sev-medium'">
              <span class="v-icon">{{ d.severity === 'high' ? '🔴' : '🟡' }}</span>
              <span class="v-type">{{ d.strategy || d.level }}</span>
              <span class="v-detail">{{ d.key }}: {{ d.old }} → {{ d.new }}</span>
            </div>
          </div>

          <div class="review-section" style="margin-top:4px">
            <span class="section-title title-green" style="cursor:pointer" @click="monthlyFactorExpanded = !monthlyFactorExpanded">🧪 因子效果 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyFactorExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyFactorExpanded">点击展开查看因子效果与市场漂移</span>
          </div>
          <FactorEffectSection v-if="monthlyFactorExpanded" :factorEffectData="factorEffectData" />

          <div class="review-section" style="margin-top:4px">
            <span class="section-title title-blue" style="cursor:pointer" @click="monthlyClosedLoopExpanded = !monthlyClosedLoopExpanded">💡 闭环建议 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ monthlyClosedLoopExpanded ? '▼' : '▶' }}</span></span>
            <span class="section-detail" v-if="!monthlyClosedLoopExpanded"><span v-if="closedLoopData"><b :class="closedLoopData.summary?.high > 0 ? 'down' : 'up'">{{ closedLoopData.summary?.high || 0 }}</b>高 / <b>{{ closedLoopData.summary?.medium || 0 }}</b>中 / <b>{{ closedLoopData.summary?.low || 0 }}</b>低</span><span v-else>暂无建议</span></span>
          </div>
          <div v-if="monthlyClosedLoopExpanded && closedLoopData?.suggestions?.length" class="closed-loop-list">
            <div v-for="(s, i) in closedLoopData.suggestions" :key="i" class="cl-card" :class="'cl-' + s.severity">
              <div class="cl-header"><span class="cl-sev">{{ s.severity === 'high' ? '🔴' : s.severity === 'medium' ? '🟡' : '🔵' }}</span><span class="cl-type">{{ s.type }}</span></div>
              <div class="cl-diagnosis">{{ s.diagnosis }}</div>
              <div class="cl-action">👉 {{ s.action }}</div>
              <div class="cl-verify">✅ 验证: {{ s.verification }}</div>
              <div v-if="s.worst_cases?.length" class="cl-cases">最差案例: <span v-for="w in s.worst_cases" :key="w.ts_code">{{ w.name }}({{ w.pnl }}%) </span></div>
            </div>
          </div>
          <div v-else-if="monthlyClosedLoopExpanded" class="empty">无闭环建议</div>
        </template>
        <div v-else class="empty">选择日期后查看月复盘</div>
      </template>

      <!-- 第4层: 纪律检查 + 执行质量 -->
      <template v-if="reviewTab === 'daily' && deviationData">
        <!-- 📊滑点偏差 -->
        <div class="review-section" style="margin-top:4px">
          <span class="section-title title-blue">📊 滑点偏差</span>
          <span class="section-detail">平均滑点<b :class="deviationData.deviations?.slippage?.avg_pct > 0 ? 'down' : 'up'">{{ deviationData.deviations?.slippage?.avg_pct || 0 }}%</b> | 影响笔数<b>{{ deviationData.deviations?.slippage?.count || 0 }}</b>笔 | 影响幅度<b class="down">{{ deviationData.deviations?.slippage?.impact || 0 }}%</b></span>
        </div>
        <!-- 🚨纪律偏差 -->
        <div class="review-section">
          <span class="section-title title-orange">🚨 纪律偏差</span>
          <span class="section-detail">违规笔数<b class="down">{{ deviationData.deviations?.discipline?.violations || 0 }}</b>笔 | 违规交易胜率<b class="down">{{ deviationData.deviations?.discipline?.violation_wr || 0 }}%</b> | 影响幅度<b class="down">{{ deviationData.deviations?.discipline?.impact || 0 }}%</b><span v-if="deviationData.deviations?.discipline?.violations" class="down">（主因）</span></span>
        </div>
        <!-- 纪律违规明细已移至底部折叠的「纪律检查」区域，避免顶部摘要被列表撑开 -->
      </template>

      <template v-if="reviewTab === 'weekly' && weeklyReviewData">
        <!-- 周复盘：参考日复盘风格，顶部摘要 + 底部折叠明细 -->
        <div class="review-section" style="margin-top:4px">
          <span class="section-title title-blue">📅 周复盘</span>
          <span class="section-detail">交易<b>{{ weeklyReviewData.summary?.trades || 0 }}</b>笔 | 胜率<b :class="(weeklyReviewData.summary?.win_rate || 0) >= 50 ? 'up' : 'down'">{{ weeklyReviewData.summary?.win_rate || 0 }}%</b> | 盈亏<b :class="(weeklyReviewData.summary?.pnl ?? 0) >= 0 ? 'up' : 'down'">{{ (weeklyReviewData.summary?.pnl ?? 0) >= 0 ? '+' : '' }}{{ weeklyReviewData.summary?.pnl ?? 0 }}%</b> | 情绪<b>{{ (Object.values(weeklyReviewData.sentiments || {}) as any[])[0]?.period || '-' }}</b></span>
        </div>
        <div class="metric-strip">
          <span class="ms">交易 <b>{{ weeklyReviewData.summary?.trades || 0 }}</b>笔</span>
          <span class="ms">胜率 <b :class="(weeklyReviewData.summary?.win_rate || 0) >= 50 ? 'up' : 'down'">{{ weeklyReviewData.summary?.win_rate || 0 }}%</b></span>
          <span class="ms">盈亏 <b :class="(weeklyReviewData.summary?.pnl ?? 0) >= 0 ? 'up' : 'down'">{{ (weeklyReviewData.summary?.pnl ?? 0) >= 0 ? '+' : '' }}{{ weeklyReviewData.summary?.pnl ?? 0 }}%</b></span>
          <span class="ms">策略数 <b>{{ Object.keys(weeklyReviewData.strategy_stats || {}).length }}</b></span>
          <span class="ms">逐日 <b>{{ weeklyReviewData?.daily_breakdown?.length || 0 }}</b>天</span>
          <span class="ms">趋势 <b>{{ weeklyReviewData?.weekly_trend?.length || 0 }}</b>周</span>
        </div>

        <div v-if="Object.keys(weeklyReviewData.strategy_stats || {}).length" class="review-section" style="margin-top:4px">
          <span class="section-title title-red" style="cursor:pointer" @click="weeklyStrategyExpanded = !weeklyStrategyExpanded">🎯 策略表现 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ weeklyStrategyExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!weeklyStrategyExpanded"><b>{{ Object.keys(weeklyReviewData.strategy_stats || {}).length }}</b>个策略 | 点击展开查看各策略交易/胜率/盈亏</span>
        </div>
        <div v-if="weeklyStrategyExpanded && Object.keys(weeklyReviewData.strategy_stats || {}).length" class="review-section" style="margin-top:1px">
          <span class="section-detail">
            <template v-for="(data, key) in weeklyReviewData.strategy_stats || {}" :key="key">
              <span class="ir-strat" :style="{borderColor: strategyMeta[key]?.color || 'var(--text-tertiary)'}">{{ strategyCN(key) }}<b>{{ data.trades || 0 }}</b>笔 <b :class="(data.win_rate || 0) >= 50 ? 'up' : 'down'">{{ data.win_rate || 0 }}%</b> <span :class="(data.pnl || 0) >= 0 ? 'up' : 'down'">{{ (data.pnl || 0) >= 0 ? '+' : '' }}{{ data.pnl || 0 }}%</span></span>
            </template>
          </span>
        </div>

        <div v-if="weeklyReviewData?.weekly_trend?.length" class="review-section" style="margin-top:4px">
          <span class="section-title title-purple" style="cursor:pointer" @click="weeklyTrendExpanded = !weeklyTrendExpanded">📈 偏差趋势 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ weeklyTrendExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!weeklyTrendExpanded"><b>{{ weeklyReviewData.weekly_trend.length }}</b>周 | 最近胜率<b>{{ weeklyReviewData.weekly_trend[weeklyReviewData.weekly_trend.length - 1]?.win_rate || 0 }}%</b></span>
        </div>
        <div v-if="weeklyTrendExpanded && weeklyReviewData?.weekly_trend?.length" class="deviation-trend-chart" style="margin-top:2px;height:60px">
          <div class="trend-axis" style="height:60px">
            <div v-for="w in weeklyReviewData.weekly_trend || []" :key="w.week" class="trend-col">
              <div class="trend-bar" :style="{height: w.trades > 0 ? Math.max(Math.min(w.win_rate, 100), 8) + '%' : '8px', background: w.trades === 0 ? 'var(--border-default)' : w.win_rate >= 60 ? 'var(--color-up)' : w.win_rate >= 40 ? 'var(--color-warn, #e6a23c)' : 'var(--color-down)'}">
                <span v-if="w.trades > 0" class="trend-val">{{ w.win_rate }}%</span>
              </div>
              <div class="trend-label">{{ w.week }}</div>
              <div class="trend-sub">{{ w.trades }}笔</div>
            </div>
          </div>
        </div>

        <div class="review-section" style="margin-top:4px">
          <span class="section-title title-cyan" style="cursor:pointer" @click="weeklyDailyExpanded = !weeklyDailyExpanded">📋 逐日明细 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ weeklyDailyExpanded ? '▼' : '▶' }}</span></span>
          <span class="section-detail" v-if="!weeklyDailyExpanded"><b>{{ weeklyReviewData?.daily_breakdown?.length || 0 }}</b>天 | 点击展开查看买卖/胜率/盈亏/情绪</span>
        </div>
        <div v-if="weeklyDailyExpanded && weeklyReviewData?.daily_breakdown?.length" class="rv-card" style="margin-top:2px">
          <div class="attr-compact">
            <div v-for="d in weeklyReviewData.daily_breakdown" :key="d.date" class="attr-line">
              <span class="mono">{{ formatTradeDate(d.date) }}</span>
              <span>买{{ d.buys || 0 }}卖{{ d.sells || 0 }}</span>
              <span class="attr-pct" :class="(d.win_rate || 0) >= 50 ? 'up' : 'down'">{{ d.win_rate || 0 }}%</span>
              <span :class="(d.pnl || 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (d.pnl || 0) >= 0 ? '+' : '' }}{{ d.pnl || 0 }}%</span>
              <span class="attr-reason">{{ weeklyReviewData.sentiments?.[d.date]?.period || '-' }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- 💡明日操作建议 -->
      <div v-if="reviewForward" class="review-section" style="margin-top:4px">
        <span class="section-title title-blue">💡 明日操作建议</span>
        <span class="section-detail">{{ reviewForward.advice }}</span>
      </div>

      <!-- 🌡情绪研判+策略开关 -->
      <div v-if="reviewForward" class="review-section" style="margin-top:2px">
        <span class="section-title title-cyan">🌡 情绪研判与策略开关</span>
        <span class="section-detail">
          <span v-if="reviewForward.sentiment">当前情绪<b>{{ reviewForward.sentiment.period }}</b>(<b>{{ reviewForward.sentiment.score }}</b>分)→{{ reviewForward.sentiment.raw_period }}</span>
          <template v-if="reviewForward.strategy_recommendations?.length">
            <span v-for="r in reviewForward.strategy_recommendations" :key="'o'+r.strategy" style="color:var(--stock-up);margin-left:6px">🟢{{ strategyCN(r.strategy) }}可开仓(历史胜率{{ r.win_rate || 0 }}%，{{ r.count || 0 }}笔候选)</span>
          </template>
          <template v-if="reviewForward.strategy_switches?.length">
            <span v-for="s in reviewForward.strategy_switches" :key="'c'+s.strategy" style="color:var(--stock-down);margin-left:6px">🔴{{ strategyCN(s.strategy) }}{{ s.reason }}</span>
          </template>
          <span v-if="reviewForward.drift_warnings?.length" class="down" style="margin-left:6px">⚠{{ reviewForward.drift_warnings.length }}项参数漂移告警</span>
        </span>
      </div>
<ElDialog :model-value="compareVisible" @update:model-value="emit('update:compareVisible', $event)" title="📊 实盘 vs 回测对比" width="700px">
  <div v-if="compareData.length" class="cl-table">
    <div class="cl-h"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>实盘盈亏</span><span>回测收益</span><span>回测胜率</span><span>回测回撤</span><span>回测夏普</span></div>
    <div v-for="c in compareData" :key="c.strategy" class="cl-r">
      <span class="code">{{ strategyCN(c.strategy) }}</span>
      <span>{{ c.live_trades }}笔</span>
      <span :class="c.live_win_rate >= 50 ? 'up' : 'down'">{{ c.live_win_rate }}%</span>
      <span :class="(c.live_pnl || 0) >= 0 ? 'up' : 'down'">{{ (c.live_pnl || 0) >= 0 ? '+' : '' }}{{ (c.live_pnl || 0).toFixed(0) }}</span>
      <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
      <span>{{ c.bt_win_rate }}%</span>
      <span class="text-stock-up">{{ c.bt_drawdown }}%</span>
      <span>{{ c.bt_sharpe }}</span>
    </div>
  </div>
  <div v-else class="empty">暂无对比数据（需先运行回测）</div>
</ElDialog>


    <!-- 复盘报告弹窗 -->
<ElDialog :model-value="dailyReportVisible" @update:model-value="emit('update:dailyReportVisible', $event)" title="📈 每日复盘报告" width="750px">
  <div v-if="dailyReport" class="dr">
    <div class="dr-sec"><div class="dr-t">💰 账户概览</div><div class="dr-g"><div class="dr-i"><span class="dr-l">总资产</span><span class="dr-v">{{ (Number(dailyReport?.account?.total_assets || 0) / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">可用</span><span class="dr-v">{{ (Number(dailyReport?.account?.available_cash || 0) / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">仓位</span><span class="dr-v">{{ dailyReport?.account?.position_ratio || 0 }}%</span></div><div class="dr-i"><span class="dr-l">今日盈亏</span><span class="dr-v" :class="(dailyReport?.account?.today_profit || 0) >= 0 ? 'up' : 'down'">{{ (dailyReport?.account?.today_profit || 0) >= 0 ? '+' : '' }}{{ Number(dailyReport?.account?.today_profit || 0).toFixed(0) }}</span></div></div></div>
    <div class="dr-sec"><div class="dr-t">📊 持仓概况</div><div class="dr-g"><div class="dr-i"><span class="dr-l">持仓数</span><span class="dr-v">{{ dailyReport?.positions?.count ?? '-' }}</span></div><div class="dr-i"><span class="dr-l">止损</span><span class="dr-v text-stock-up">{{ dailyReport?.stop_loss_count ?? '-' }}</span></div><div class="dr-i"><span class="dr-l">止盈</span><span class="dr-v text-stock-down">{{ dailyReport?.take_profit_count ?? '-' }}</span></div><div class="dr-i"><span class="dr-l">胜率</span><span class="dr-v">{{ dailyReport?.win_rate ?? '-' }}%</span></div></div></div>
    <div class="dr-sec" v-if="dailyReport?.positions?.top_profit?.length"><div class="dr-t">🏆 最赚</div><div v-for="p in dailyReport.positions.top_profit" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="up">+{{ p.pct }}%</span></div></div>
    <div class="dr-sec" v-if="dailyReport?.positions?.top_loss?.length"><div class="dr-t">💀 最亏</div><div v-for="p in dailyReport.positions.top_loss" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="down">{{ p.pct }}%</span></div></div>
    <div class="dr-sec" v-if="dailyReport?.positions?.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in dailyReport.positions.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.count }}只</span><span :class="(s.total_profit || s.total_pnl || 0) >= 0 ? 'up' : 'down'">¥{{ (s.total_profit || s.total_pnl || 0) >= 0 ? '+' : '' }}{{ Number(s.total_profit || s.total_pnl || 0).toFixed(0) }}</span></div></div>
  </div>
  <div v-else class="empty">暂无复盘数据</div>
</ElDialog>


    <!-- 周报弹窗 -->
<ElDialog :model-value="weeklyReportVisible" @update:model-value="emit('update:weeklyReportVisible', $event)" title="📊 周报 — 最近5个交易日" width="800px">
  <div v-if="weeklyReportData" class="wr">
    <div class="wr-sec"><div class="wr-t">💰 账户状态</div><div class="wr-g"><div class="wr-i"><span class="wr-l">总资产</span><span class="wr-v">{{ (Number(weeklyReportData?.account?.total_assets || 0) / 10000).toFixed(1) }}万</span></div><div class="wr-i"><span class="wr-l">累计盈亏</span><span class="wr-v" :class="(weeklyReportData?.account?.total_profit || 0) >= 0 ? 'up' : 'down'">{{ (weeklyReportData?.account?.total_profit || 0) >= 0 ? '+' : '' }}{{ Number(weeklyReportData?.account?.total_profit || 0).toFixed(0) }}</span></div><div class="wr-i"><span class="wr-l">可用现金</span><span class="wr-v">{{ (Number(weeklyReportData?.account?.available_cash || 0) / 10000).toFixed(1) }}万</span></div></div></div>
    <div class="wr-sec"><div class="wr-t">📈 交易统计</div><div class="wr-g"><div class="wr-i"><span class="wr-l">交易日</span><span class="wr-v">{{ weeklyReportData.totals?.trading_days || 0 }}天</span></div><div class="wr-i"><span class="wr-l">买入</span><span class="wr-v">{{ weeklyReportData.totals?.total_buys || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">卖出</span><span class="wr-v">{{ weeklyReportData.totals?.total_sells || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">净流入</span><span class="wr-v" :class="(weeklyReportData.totals?.net_flow || 0) >= 0 ? 'up' : 'down'">{{ Number(weeklyReportData.totals?.net_flow || 0).toFixed(0) }}</span></div></div></div>
    <div class="dr-sec" v-if="weeklyReportData.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in weeklyReportData.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.trades }}笔</span><span :class="(s.amount || 0) >= 0 ? 'up' : 'down'">¥{{ (s.amount || 0) >= 0 ? '+' : '' }}{{ Number(s.amount || 0).toFixed(0) }}</span></div></div>
    <div class="dr-sec" v-if="weeklyReportData.daily_stats"><div class="dr-t">📅 每日明细</div><div v-for="(stats, date) in weeklyReportData.daily_stats" class="wr-day"><span class="wr-date">{{ formatTradeDate(date) }}</span><span>买{{ stats.buys }}卖{{ stats.sells }}</span><span :class="((stats.sell_amount || 0) - (stats.buy_amount || 0)) >= 0 ? 'up' : 'down'">¥{{ Number((stats.sell_amount || 0) - (stats.buy_amount || 0)).toFixed(0) }}</span></div></div>
  </div>
  <div v-else class="empty">暂无周报数据</div>
</ElDialog>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* ========== v2.9.97m 分区布局+彩色标题 ========== */

/* 分区块 */
.review-section { padding: 3px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 4px; margin-bottom: 2px; display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px; }

/* 分区标题 — 内联,大粗字+颜色左边框, 等宽对齐 */
.section-title { font-size: 13px; font-weight: 800; color: var(--text-primary); line-height: 1.4; padding: 1px 6px; border-left: 3px solid var(--el-color-primary); white-space: nowrap; flex-shrink: 0; min-width: 96px; display: inline-block; text-align: left; }
.title-red { border-left-color: #e6363a; color: #e6363a; }
.title-green { border-left-color: #18a058; color: #18a058; }
.title-orange { border-left-color: #e6a23c; color: #e6a23c; }
.title-blue { border-left-color: #409eff; color: #409eff; }
.title-purple { border-left-color: #9b59b6; color: #9b59b6; }
.title-cyan { border-left-color: #36cfc9; color: #36cfc9; }

/* 分区详情行 — 内联 */
.section-detail { font-size: 11px; color: var(--text-secondary); line-height: 1.6; }
.section-detail b { font-weight: 600; color: var(--text-primary); font-size: 12px; margin: 0 1px; }
.section-detail b.up { color: var(--stock-up); }
.section-detail b.down { color: var(--stock-down); }
.section-detail .ir-dim { color: var(--text-tertiary); }
.section-detail .ir-strat { border-left: 2px solid; padding-left: 3px; margin-right: 6px; font-size: 11px; color: var(--text-primary); }
.section-detail .ir-section { white-space: nowrap; margin-right: 6px; }
.section-detail .v-item { font-size: 10px; padding: 1px 4px; border-radius: 2px; }
.section-detail .v-item.sev-high { background: rgba(242,54,69,0.06); }
.section-detail .v-item.sev-medium { background: rgba(230,162,60,0.06); }

/* 指标条 — 单行内联, 极致紧凑 */
.metric-strip { display: flex; flex-wrap: wrap; gap: 2px 6px; margin-top: 2px; padding: 2px 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; font-size: 10px; color: var(--text-tertiary); }
.metric-strip .ms b { font-weight: 600; color: var(--text-primary); font-size: 11px; margin-left: 2px; }

/* 信息行 — 策略/漏斗/纪律/执行 一行内联 */
.info-row { display: flex; flex-wrap: wrap; gap: 2px 8px; padding: 2px 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; font-size: 10px; color: var(--text-tertiary); }
.ir-section { white-space: nowrap; }
.ir-section b { font-weight: 600; color: var(--text-primary); font-size: 11px; margin-left: 1px; }
.ir-strat { border-left: 2px solid; padding-left: 3px; margin-right: 2px; font-size: 10px; color: var(--text-primary); }
.ir-dim { color: var(--text-tertiary); }

/* 纪律违规紧凑 */
.violations-compact { display: flex; flex-direction: column; gap: 1px; }
.v-item { font-size: 10px; padding: 1px 4px; border-radius: 2px; }
.v-item.sev-high { background: rgba(242,54,69,0.06); }
.v-item.sev-medium { background: rgba(230,162,60,0.06); }

/* 卡片 — 紧凑 */
.rv-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; padding: 3px 5px; }
.rv-card-title { font-size: 10px; font-weight: 700; margin-bottom: 1px; display: flex; align-items: center; gap: 3px; line-height: 1.2; }
.rv-count { font-weight: 400; font-size: 11px; color: var(--text-tertiary); }
.rv-badge { font-size: 11px; font-weight: 600; padding: 0 5px; border-radius: 3px; line-height: 1.5; }
.rv-badge.up { background: rgba(242,54,69,0.1); color: var(--stock-up); }
.rv-badge.down { background: rgba(8,153,129,0.1); color: var(--stock-down); }

/* 策略贡献行式 */
.strat-rows { display: flex; flex-direction: column; gap: 1px; }
.strat-row { display: flex; align-items: center; gap: 4px; padding: 2px 0; border-bottom: 1px solid var(--border-light); font-size: 11px; }
.strat-row:last-child { border-bottom: none; }
.strat-cnt { color: var(--text-secondary); font-size: 10px; }
.strat-val { font-weight: 600; margin-left: auto; font-size: 11px; }
.strat-wr { font-weight: 600; min-width: 32px; text-align: right; font-size: 11px; }

/* 漏斗 */
.funnel-rows { display: flex; flex-direction: column; gap: 1px; }
.funnel-row { display: flex; align-items: center; gap: 4px; }
.fun-l { font-size: 10px; color: var(--text-tertiary); min-width: 24px; }
.fun-bar { flex: 1; height: 14px; background: var(--bg-muted); border-radius: 2px; position: relative; overflow: hidden; }
.fun-fill { height: 100%; border-radius: 2px; background: var(--el-color-primary); opacity: 0.5; transition: width 0.3s; }
.fun-fill.full { width: 100%; }
.fun-fill.buy { background: var(--stock-up); opacity: 0.6; }
.fun-v { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); font-size: 9px; font-weight: 600; }
.sent-snap { margin-top: 2px; padding: 2px 6px; border-radius: 3px; background: rgba(22,93,255,0.05); border-left: 2px solid var(--el-color-primary); font-size: 10px; }

/* 逐笔归因 — 行式, 不用表格 */
.attr-compact { display: flex; flex-direction: column; gap: 1px; }
.attr-line { display: flex; align-items: center; gap: 4px; padding: 1px 0; font-size: 10px; border-bottom: 1px solid var(--border-light); }
.attr-line:last-child { border-bottom: none; }
.attr-name { max-width: 40px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attr-pct { font-weight: 600; min-width: 32px; text-align: right; }
.attr-line.tr-profit { border-left: 2px solid rgba(242,54,69,0.4); padding-left: 3px; }
.attr-line.tr-loss { border-left: 2px solid rgba(8,153,129,0.4); padding-left: 3px; }
.attr-line.tr-open { border-left: 2px solid rgba(230,162,60,0.5); padding-left: 3px; }
.attr-reason { color: var(--text-tertiary); margin-left: auto; font-size: 9px; }
.mono { font-family: monospace; font-size: 10px; }
.tag-xs { font-size: 9px !important; padding: 0 3px !important; height: 16px !important; line-height: 16px !important; }

.review-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; flex-wrap: nowrap; }

.review-scan-stats { display: flex; gap: 8px; padding: 3px 8px; border-radius: 4px; background: var(--bg-elevated); border: 1px solid var(--border-default); font-size: 10px; }

.rss-row { font-size: 11px; }

.rss-label { color: var(--text-tertiary); margin-right: 2px; }

.rss-value { font-weight: 600; }

.review-sentiment-snap { margin-top: 4px; padding: 3px 8px; border-radius: 4px; background: rgba(22,93,255,0.05); border-left: 2px solid var(--el-color-primary); font-size: 11px; display: flex; gap: 6px; }

.review-tabs { display: flex; gap: 2px; }

.review-tab { padding: 3px 8px; border: 1px solid var(--border-default); border-radius: 4px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 11px; cursor: pointer; transition: all 0.2s; }

.review-tab:hover { background: var(--bg-hover); }

.review-tab.active { background: var(--el-color-primary); color: var(--text-inverse); border-color: var(--el-color-primary); }

.review-summary-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 4px; }

.rsc { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 4px; padding: 2px 4px; text-align: center; }

.rsc-label { font-size: 9px; color: var(--text-tertiary); margin-bottom: 1px; line-height: 1.2; }

.rsc-value { font-size: 12px; font-weight: 600; line-height: 1.3; }

.strategy-contrib { display: flex; flex-direction: column; gap: 8px; }

.strat-card { padding: 5px 8px; border-radius: 6px; border: 1px solid var(--border-default); background: var(--bg-elevated); }

.strat-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }

.strat-pnl { font-weight: 700; font-size: 13px; margin-left: auto; }

.strat-pnl.up { color: var(--stock-up); }

.strat-pnl.down { color: var(--stock-down); }

.strat-metrics { display: flex; flex-wrap: wrap; gap: 4px 12px; }

.strat-m { font-size: 11px; }

.strat-ml { color: var(--text-tertiary); margin-right: 4px; }

.strat-mv { font-weight: 600; }

.attribution-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; padding: 5px 8px; margin-bottom: 3px; }

.attr-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }

.attr-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 12px; font-size: 11px; }

.attr-row { display: flex; justify-content: space-between; }

.attr-row span:first-child { color: var(--text-tertiary); }

.attr-scan { margin-top: 6px; padding: 6px 8px; border-radius: 4px; background: rgba(22,93,255,0.05); border-left: 3px solid var(--el-color-primary); }

.attr-scan-title { font-size: 11px; font-weight: 600; color: var(--el-color-primary); margin-bottom: 4px; }

.weekly-daily-table { font-size: 12px; }

.wdt-header, .wdt-row { display: grid; grid-template-columns: 50px 40px 40px 50px 60px 50px; gap: 4px; padding: 3px 0; }
.wdt-6col { grid-template-columns: 50px 40px 40px 50px 60px 50px; }

.wdt-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }

.lb-table { font-size: 12px; }

.lb-header, .lb-row { display: grid; grid-template-columns: 70px 60px 60px 60px 60px 70px 60px 60px; gap: 4px; padding: 3px 0; }

.lb-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }

.hero-banner { padding: 3px 6px; border-radius: 3px; margin-bottom: 1px; display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.hero-conclusion { font-size: 11px; font-weight: 700; line-height: 1.2; }
.hero-big-pct { font-size: 16px; font-weight: 800; letter-spacing: -0.5px; }
.hero-big-pct.up { color: var(--stock-up); }
.hero-big-pct.down { color: var(--stock-down); }
.hero-meta { display: flex; gap: 6px; font-size: 10px; color: var(--text-secondary); margin-left: auto; }
.hero-banner.profit { background: linear-gradient(135deg, rgba(242,54,69,0.10), rgba(242,54,69,0.03)); border: 1px solid rgba(242,54,69,0.20); }
.hero-banner.slight_profit { background: linear-gradient(135deg, rgba(242,54,69,0.06), rgba(230,162,60,0.03)); border: 1px solid rgba(242,54,69,0.12); }
.hero-banner.slight_loss { background: linear-gradient(135deg, rgba(230,162,60,0.10), rgba(8,153,129,0.03)); border: 1px solid rgba(230,162,60,0.20); }
.hero-banner.loss { background: linear-gradient(135deg, rgba(8,153,129,0.10), rgba(8,153,129,0.03)); border: 1px solid rgba(8,153,129,0.20); }
.hero-banner.neutral { background: var(--bg-elevated); border: 1px solid var(--border-default); }

.review-scorecard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }

.review-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }

.violations-list { display: flex; flex-direction: column; gap: 2px; margin-top: 3px; }

.violation-item { display: flex; align-items: flex-start; gap: 3px; padding: 2px 4px; border-radius: 3px; font-size: 10px; line-height: 1.3; }

.violation-item.sev-high { background: rgba(242,54,69,0.06); border: 1px solid rgba(242,54,69,0.12); }

.violation-item.sev-medium { background: rgba(230,162,60,0.06); border: 1px solid rgba(230,162,60,0.12); }

.v-icon { flex-shrink: 0; }

.v-type { font-weight: 600; min-width: 64px; color: var(--text-primary); }

.v-detail { color: var(--text-secondary); }

.attr-profit { border-left: 3px solid rgba(242,54,69,0.35); }

.attr-loss { border-left: 3px solid rgba(8,153,129,0.35); }

.attr-open { border-left: 3px solid rgba(230,162,60,0.45); }

/* 执行质量 — 行内标签式 */
.eq-compact { display: flex; gap: 8px; font-size: 10px; color: var(--text-tertiary); }
.eq-compact span { white-space: nowrap; }
.eq-compact b { font-weight: 600; color: var(--text-primary); margin-left: 2px; font-size: 11px; }

.forward-section { display: flex; flex-direction: column; gap: 8px; }

.deviation-trend-chart { background: var(--bg-elevated); border-radius: 6px; padding: 8px; }

.trend-axis { display: flex; align-items: flex-end; gap: 8px; height: 100px; padding-top: 16px; }

.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }

.trend-bar { width: 100%; border-radius: 4px 4px 0 0; min-height: 20px; position: relative; transition: height 0.3s; }

.trend-val { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-size: 11px; font-weight: 600; white-space: nowrap; }

.trend-label { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

.trend-sub { font-size: 10px; color: var(--text-tertiary); }

.calendar-heatmap { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; padding: 6px; background: var(--bg-elevated); border-radius: 6px; }

.cal-cell { border-radius: 6px; padding: 4px 2px; text-align: center; font-size: 10px; min-height: 40px; display: flex; flex-direction: column; align-items: center; justify-content: center; }

.cal-up { background: rgba(242,54,69,0.12); color: var(--stock-up); }

.cal-down { background: rgba(8,153,129,0.12); color: var(--stock-down); }

.cal-neutral { background: var(--bg-elevated); color: var(--text-tertiary); }

.cal-date { font-weight: 600; }

.cal-pnl { font-size: 10px; font-weight: 600; }

.cal-trades { font-size: 9px; color: var(--text-tertiary); }

.strategy-stacked { display: flex; flex-direction: column; gap: 3px; padding: 6px; background: var(--bg-elevated); border-radius: 6px; }

.stacked-bar { display: flex; align-items: center; justify-content: space-between; border-radius: 4px; padding: 4px 8px; min-width: 80px; }

.stacked-label { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }

.stacked-val { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }

.closed-loop-list { display: flex; flex-direction: column; gap: 6px; }

.cl-card { border-radius: 6px; padding: 6px 8px; border-left: 3px solid; }

.cl-high { background: rgba(245,108,108,0.08); border-color: var(--stock-up); }

.cl-medium { background: rgba(230,162,60,0.08); border-color: #e6a23c; }

.cl-low { background: rgba(144,147,153,0.08); border-color: #909399; }

.cl-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }

.cl-sev { font-size: 14px; }

.cl-type { font-weight: 600; font-size: 12px; }

.cl-diagnosis { font-size: 11px; color: var(--text-secondary); margin-bottom: 2px; }

.cl-action { font-size: 11px; font-weight: 600; margin-bottom: 2px; }

.cl-verify { font-size: 10px; color: var(--text-tertiary); }

.cl-cases { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }

.fw-card { padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border-default); font-size: 12px; }

.fw-card.fw-advice { background: rgba(64,158,255,0.06); border-color: rgba(64,158,255,0.2); }

.fw-card.fw-open { background: rgba(103,194,58,0.06); border-color: rgba(103,194,58,0.15); }

.fw-card.fw-close { background: rgba(245,108,108,0.06); border-color: rgba(245,108,108,0.15); }

.fw-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }

.fw-content { color: var(--text-secondary); line-height: 1.5; }

.fw-switches { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }

.fw-icon { margin-right: 4px; }

.dev-card { padding: 8px 10px; border-radius: 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); }

.dev-title { font-weight: 700; font-size: 12px; margin-bottom: 4px; }

.dev-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }

/* ========== 弹窗样式(v2.9.75死CSS清理误删补回) ========== */

/* 回测对比弹窗 */
.cl-table { max-height: 400px; overflow-y: auto; }
.cl-h { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.cl-r { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); overflow: hidden; }

/* 复盘报告弹窗 */
.dr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.dr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.dr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.dr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.dr-l { font-size: 10px; color: var(--text-tertiary); }
.dr-v { font-size: 13px; font-weight: 500; }
.dr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }

/* 周报弹窗 */
.wr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.wr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.wr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.wr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.wr-l { font-size: 10px; color: var(--text-tertiary); }
.wr-v { font-size: 14px; font-weight: 600; }
.wr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-day { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-date { font-weight: 600; color: var(--text-primary); min-width: 80px; }
</style>
