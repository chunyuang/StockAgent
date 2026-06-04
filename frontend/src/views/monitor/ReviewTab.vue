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
import { ElDatePicker, ElButton, ElTag } from 'element-plus'

defineProps<{
  visible: boolean
  strategyCN: (s: string | number) => string | number
  strategyMeta: Record<string, any>
  reviewTab: 'daily' | 'weekly' | 'monthly'
  reviewLoading: boolean
  reviewDate: string
  reviewHero: any
  reviewForward: any
  dailyReportData: any
  weeklyReportData: any
  weeklyReviewData: any
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
        <ElDatePicker :modelValue="reviewDate" type="date" size="small" value-format="YYYY-MM-DD" @update:modelValue="emit('update:reviewDate', $event); emit('fetchReviewData')" />
        <ElButton size="small" @click="emit('fetchReviewData')" :loading="reviewLoading">🔄</ElButton>
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
        <div class="st" style="margin-top:8px">🎯 策略贡献</div>
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

        <div class="st" style="margin-top:8px">📝 逐笔归因 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">({{ (tradeAttributions?.length || 0) }}笔)</span></div>
        <div v-if="!(tradeAttributions?.length || 0)" class="empty">暂无交易数据</div>
        <div v-for="t in tradeAttributions" :key="t.ts_code + t.sell_time" class="attribution-card" :class="t.profit_pct >= 0 ? 'attr-profit' : 'attr-loss'">
          <div class="attr-top">
            <ElTag size="small" :color="strategyMeta[t.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(t.strategy) }}</ElTag>
            <span class="code">{{ t.ts_code }}</span>
            <span class="name">{{ t.stock_name }}</span>
            <span :class="(t.profit_pct || 0) >= 0 ? 'up' : 'down'" class="pct ml-auto">{{ (t.profit_pct || 0) >= 0 ? '+' : '' }}{{ (t.profit_pct || 0).toFixed(1) }}%</span>
          </div>
          <div class="attr-detail">
            <div class="attr-row"><span>买入</span><span>¥{{ t.buy_price?.toFixed(2) }} {{ t.buy_time }}</span></div>
            <div class="attr-row"><span>卖出</span><span>¥{{ t.sell_price?.toFixed(2) }} {{ t.sell_time }}</span></div>
            <div class="attr-row"><span>原因</span><span>{{ t.sell_reason }}</span></div>
            <div class="attr-row" v-if="t.why_profit"><span class="up">赚在哪</span><span>{{ t.why_profit }}</span></div>
            <div class="attr-row" v-if="t.why_loss"><span class="down">亏在哪</span><span>{{ t.why_loss }}</span></div>
          </div>
        </div>

        <div class="st" style="margin-top:8px">📡 扫描漏斗</div>
        <div v-if="dailyReportData?.scanner_stats" class="review-scan-stats">
          <div class="rss-row"><span class="rss-label">扫描次数</span><span class="rss-value">{{ (dailyReportData?.scanner_stats?.scan_count || 0) || 0 }}次</span></div>
          <div class="rss-row"><span class="rss-label">发现信号</span><span class="rss-value up">{{ (dailyReportData?.scanner_stats?.total_signals || 0) || 0 }}只</span></div>
          <div class="rss-row"><span class="rss-label">实际买入</span><span class="rss-value">{{ (dailyReportData?.scanner_stats?.buy_count || 0) || 0 }}笔</span></div>
          <div class="rss-row"><span class="rss-label">实际卖出</span><span class="rss-value">{{ (dailyReportData?.scanner_stats?.sell_count || 0) || 0 }}笔</span></div>
        </div>
        <div v-if="dailyReportData?.sentiment_snapshot" class="review-sentiment-snap">
          <span style="font-weight:600">🌡️ 情绪快照</span>
          <span>{{ (dailyReportData?.sentiment_snapshot || "") }}</span>
        </div>
      </template>

      <!-- 周复盘 -->
      <!-- 周复盘 -->
      <template v-if="reviewTab === 'monthly'">
        <template v-if="monthlyReviewData">
          <div class="st" style="margin-top:8px">🔬 系统偏差 ({{ monthlyReviewData.period }})</div>
          <div class="review-scorecard" style="grid-template-columns:repeat(4,1fr)">
            <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ monthlyReviewData.summary?.trades || 0 }}笔</div></div>
            <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ monthlyReviewData.summary?.win_rate || 0 }}%</div></div>
            <div class="rsc"><div class="rsc-label">盈亏</div><div class="rsc-value" :class="monthlyReviewData.summary?.pnl >= 0 ? 'up' : 'down'">{{ monthlyReviewData.summary?.pnl >= 0 ? '+' : '' }}{{ monthlyReviewData.summary?.pnl || 0 }}%</div></div>
            <div class="rsc"><div class="rsc-label">连亏</div><div class="rsc-value">-</div></div>
          </div>
          <div class="st" style="margin-top:8px">📈 偏差趋势(近4周)</div>
          <div v-if="(monthlyReviewData?.weekly_trend?.length || 0)" class="deviation-trend-chart">
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
          <div v-else class="empty">无周度数据</div>
          <div class="st" style="margin-top:8px">⚡ 行为漂移检测</div>
          <div class="review-2col">
            <div class="dev-card"><div class="dev-title">🛡️ 止损执行率</div><div class="dev-row"><span>亏损止损/总亏损</span><span :class="monthlyReviewData.behavior_drift?.stop_loss_execution_rate >= 90 ? 'up' : 'down'">{{ monthlyReviewData.behavior_drift?.stop_loss_execution_rate || 0 }}%</span></div><div class="dev-row" style="font-size:11px;color:var(--text-tertiary)"><span>亏损止损{{ monthlyReviewData.behavior_drift?.stop_loss_at_loss || 0 }}笔 / 盈利止损{{ monthlyReviewData.behavior_drift?.stop_loss_at_profit || 0 }}笔</span></div></div>
            <div class="dev-card"><div class="dev-title">❄️ 冰点期开仓率</div><div class="dev-row"><span>冰点买入占比</span><span :class="monthlyReviewData.behavior_drift?.bearish_period_buy_ratio >= 30 ? 'down' : 'up'">{{ monthlyReviewData.behavior_drift?.bearish_period_buy_ratio || 0 }}%</span></div><div class="dev-row"><span>冰点/总买入</span><span>{{ monthlyReviewData.behavior_drift?.bearish_buys || 0 }}/{{ monthlyReviewData.behavior_drift?.total_buys || 0 }}笔</span></div></div>
          </div>
          <div class="st" style="margin-top:8px">🗓️ 日历热力图</div>
          <div v-if="(monthlyReviewData?.daily_breakdown?.length || 0)" class="calendar-heatmap">
            <div v-for="d in monthlyReviewData.daily_breakdown" :key="d.date" class="cal-cell" :class="d.pnl > 0 ? 'cal-up' : d.pnl < 0 ? 'cal-down' : 'cal-neutral'">
              <div class="cal-date">{{ d.date?.slice(-2) }}</div>
              <div class="cal-pnl">{{ d.pnl >= 0 ? '+' : '' }}{{ d.pnl }}%</div>
              <div class="cal-trades">{{ d.trades }}笔</div>
            </div>
          </div>
          <div v-else class="empty">无逐日数据</div>
          <div class="st" style="margin-top:8px">🎯 策略月度贡献</div>
          <div class="strategy-stacked">
            <div v-for="(data, key) in (monthlyReviewData?.strategy_stats) || {}" :key="key" class="stacked-bar" :style="{width: Math.max(Math.abs(data.pnl), 5) + '%', background: data.pnl >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
              <span class="stacked-label">{{ strategyCN(key) }}</span>
              <span class="stacked-val">{{ data.pnl >= 0 ? '+' : '' }}{{ data.pnl }}%</span>
            </div>
          </div>
          <div class="st" style="margin-top:8px">🔧 参数漂移检测
            <ElButton size="small" @click="emit('saveParamSnapshot')" style="margin-left:8px">📸 保存当前快照</ElButton>
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
        <div class="st" style="margin-top:8px">📊 因子效果跟踪 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">(市场漂移检测)</span></div>
        <div v-if="factorEffectData" class="factor-effect-section">
          <div v-if="factorEffectData.drift_alerts?.length" class="violations-list" style="margin-bottom:8px">
            <div v-for="(a, i) in factorEffectData.drift_alerts" :key="i" class="violation-item sev-medium">
              <span class="v-icon">⚠️</span><span class="v-type">{{ a.factor }}/{{ a.bucket }}</span><span class="v-detail">{{ a.alert }}</span>
            </div>
          </div>
          <div v-for="(periods, fname) in factorEffectData.factor_stats || {}" :key="fname" class="factor-group">
            <div class="factor-name">{{ fname }}</div>
            <div v-for="(items, period) in periods" :key="period" class="factor-period">
              <div class="factor-period-label">{{ period }}</div>
              <div class="factor-bars">
                <div v-for="it in items?.slice(0, 5)" :key="it.name" class="factor-bar-row">
                  <span class="fb-name">{{ it.name }}</span>
                  <div class="fb-bar-bg"><div class="fb-bar-fill" :style="{width: it.total > 0 ? Math.min(it.win_rate, 100) + '%' : '0%'}" :class="it.win_rate >= 60 ? 'fb-up' : it.win_rate >= 40 ? 'fb-mid' : 'fb-down'"></div></div>
                  <span class="fb-wr" :class="it.win_rate >= 60 ? 'up' : 'down'">{{ it.win_rate }}%</span>
                  <span class="fb-cnt">({{ it.total }})</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty">无因子数据</div>
        <div class="st" style="margin-top:8px">💡 闭环建议 <span v-if="closedLoopData" style="font-weight:normal;font-size:11px;margin-left:6px" :class="closedLoopData.summary?.high > 0 ? 'down' : 'up'">{{ closedLoopData.summary?.high || 0 }}高 / {{ closedLoopData.summary?.medium || 0 }}中 / {{ closedLoopData.summary?.low || 0 }}低</span></div>
        <div v-if="closedLoopData?.suggestions?.length" class="closed-loop-list">
          <div v-for="(s, i) in closedLoopData.suggestions" :key="i" class="cl-card" :class="'cl-' + s.severity">
            <div class="cl-header"><span class="cl-sev">{{ s.severity === 'high' ? '🔴' : s.severity === 'medium' ? '🟡' : '🔵' }}</span><span class="cl-type">{{ s.type }}</span></div>
            <div class="cl-diagnosis">{{ s.diagnosis }}</div>
            <div class="cl-action">👉 {{ s.action }}</div>
            <div class="cl-verify">✅ 验证: {{ s.verification }}</div>
            <div v-if="s.worst_cases?.length" class="cl-cases">最差案例: <span v-for="w in s.worst_cases" :key="w.ts_code">{{ w.name }}({{ w.pnl }}%) </span></div>
          </div>
        </div>
        <div v-else class="empty">无闭环建议</div>
      </template>

      <!-- 第4层: 纪律检查 + 执行质量 -->
      <template v-if="reviewTab === 'daily' && deviationData">
        <div class="st" style="margin-top:8px">🔍 执行偏差归因 <span style="font-weight:normal;font-size:11px;color:var(--text-tertiary)">({{ deviationData.period }})</span></div>
        <div class="review-2col">
          <div class="dev-card"><div class="dev-title">📊 滑点偏差</div><div class="dev-row"><span>平均滑点</span><span :class="deviationData.deviations?.slippage?.avg_pct > 0 ? 'down' : 'up'">{{ deviationData.deviations?.slippage?.avg_pct || 0 }}%</span></div><div class="dev-row"><span>影响笔数</span><span>{{ deviationData.deviations?.slippage?.count || 0 }}笔</span></div><div class="dev-row"><span>影响幅度</span><span class="down">{{ deviationData.deviations?.slippage?.impact || 0 }}%</span></div></div>
          <div class="dev-card"><div class="dev-title">🚨 纪律偏差 <span v-if="deviationData.deviations?.discipline?.violations" class="down">（主因）</span></div><div class="dev-row"><span>违规笔数</span><span class="down">{{ deviationData.deviations?.discipline?.violations || 0 }}笔</span></div><div class="dev-row"><span>违规胜率</span><span class="down">{{ deviationData.deviations?.discipline?.violation_wr || 0 }}%</span></div><div class="dev-row"><span>影响幅度</span><span class="down">{{ deviationData.deviations?.discipline?.impact || 0 }}%</span></div></div>
        </div>
        <div v-if="deviationData.details?.discipline?.length" class="violations-list" style="margin-top:6px">
          <div v-for="v in deviationData.details.discipline.slice(0,5)" :key="v.ts_code" class="violation-item sev-high"><span class="v-icon">🔴</span><span class="v-type">{{ v.type }}</span><span class="v-detail">{{ v.period }}期{{ v.strategy }} {{ v.stock_name }}</span></div>
        </div>
      </template>

      <template v-if="reviewTab === 'weekly' && weeklyReviewData">
        <div class="st" style="margin-top:8px">📊 策略效能 ({{ weeklyReviewData.period }})</div>
        <div class="review-scorecard" style="grid-template-columns:repeat(4,1fr)">
          <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ weeklyReviewData.summary?.trades || 0 }}笔</div></div>
          <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ weeklyReviewData.summary?.win_rate || 0 }}%</div></div>
          <div class="rsc"><div class="rsc-label">盈亏</div><div class="rsc-value" :class="weeklyReviewData.summary?.pnl >= 0 ? 'up' : 'down'">{{ weeklyReviewData.summary?.pnl >= 0 ? '+' : '' }}{{ weeklyReviewData.summary?.pnl || 0 }}%</div></div>
          <div class="rsc"><div class="rsc-label">情绪</div><div class="rsc-value">{{ (Object.values(weeklyReviewData.sentiments || {}) as any[])[0]?.period || '-' }}</div></div>
        </div>
        <div class="strategy-contrib">
          <div v-for="(data, key) in weeklyReviewData.strategy_stats || {}" :key="key" class="strat-card">
            <div class="strat-header"><ElTag size="small" class="tag-solid">{{ strategyCN(key) }}</ElTag><span class="strat-pnl" :class="data.pnl >= 0 ? 'up' : 'down'">{{ data.pnl >= 0 ? '+' : '' }}{{ data.pnl }}%</span></div>
            <div class="strat-metrics"><div class="strat-m"><span class="strat-ml">笔数</span><span class="strat-mv">{{ data.trades }}笔</span></div><div class="strat-m"><span class="strat-ml">胜率</span><span class="strat-mv" :class="data.win_rate >= 50 ? 'up' : 'down'">{{ data.win_rate }}%</span></div></div>
          </div>
        </div>
        <div class="st" style="margin-top:8px">📈 偏差趋势(近4周)</div>
        <div class="deviation-trend-chart">
          <div class="trend-axis">
            <div v-for="w in weeklyReviewData.weekly_trend || []" :key="w.week" class="trend-col">
              <div class="trend-bar" :style="{height: w.trades > 0 ? Math.max(Math.min(w.win_rate, 100), 8) + '%' : '8px', background: w.trades === 0 ? 'var(--border-default)' : w.win_rate >= 60 ? 'var(--color-up)' : w.win_rate >= 40 ? 'var(--color-warn, #e6a23c)' : 'var(--color-down)'}">
                <span v-if="w.trades > 0" class="trend-val">{{ w.win_rate }}%</span>
              </div>
              <div class="trend-label">{{ w.week }}</div>
              <div class="trend-sub">{{ w.trades }}笔</div>
            </div>
          </div>
        </div>
        <div class="st" style="margin-top:8px">📋 逐日明细</div>
        <div v-if="weeklyReviewData?.daily_breakdown?.length" class="weekly-daily-table">
          <div class="wdt-header"><span>日期</span><span>买入</span><span>卖出</span><span>胜率</span><span>盈亏</span><span>情绪</span></div>
          <div v-for="d in weeklyReviewData.daily_breakdown" :key="d.date" class="wdt-row wdt-6col">
            <span>{{ d.date?.length >= 8 ? d.date.slice(4,6)+'/'+d.date.slice(6,8) : d.date }}</span>
            <span>{{ d.buys || 0 }}</span>
            <span>{{ d.sells || 0 }}</span>
            <span :class="d.win_rate >= 50 ? 'up' : 'down'">{{ d.win_rate }}%</span>
            <span :class="d.pnl >= 0 ? 'up' : 'down'" style="font-weight:600">{{ d.pnl >= 0 ? '+' : '' }}{{ d.pnl }}%</span>
            <span style="font-size:11px">{{ weeklyReviewData.sentiments?.[d.date]?.period || '-' }}</span>
          </div>
        </div>
      </template>

      <div class="review-2col" style="margin-top:8px">
        <div class="sentiment-panel">
          <div class="st">🔍 纪律检查<span v-if="disciplineCheck" style="font-weight:normal;font-size:11px;margin-left:6px" :class="(disciplineCheck?.execution_rate || 0) >= 80 ? 'up' : (disciplineCheck?.execution_rate || 0) >= 60 ? '' : 'down'"> 执行正确率 {{ (disciplineCheck?.execution_rate || 0) }}%</span></div>
          <div v-if="disciplineCheck && (disciplineCheck?.violations?.length || 0)" class="violations-list"><div v-for="(v, i) in disciplineCheck.violations" :key="i" class="violation-item" :class="'sev-' + v.severity"><span class="v-icon">{{ v.severity === 'high' ? '🔴' : '🟡' }}</span><span class="v-type">{{ v.violation }}</span><span class="v-detail">{{ v.detail }}</span></div></div>
          <div v-else-if="disciplineCheck" class="empty" style="padding:8px 0;color:#67c23a">✅ 无违规交易</div>
          <div v-else class="empty" style="padding:8px 0">无数据</div>
        </div>
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

      <div class="st" style="margin-top:8px">📊 实盘 vs 回测偏差
        <ElButton v-if="!(liveBacktestDiff?.length || 0)" size="small" type="primary" @click="emit('runBacktest')" :loading="backtestRunning" style="margin-left:8px">▶️ 运行回测</ElButton>
      </div>
      <div v-if="(liveBacktestDiff?.length || 0)" class="lb-table">
        <div class="lb-header"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>回测胜率</span><span>偏差</span></div>
        <div v-for="c in liveBacktestDiff" :key="c.strategy" class="lb-row"><span class="code">{{ strategyCN(c.strategy) }}</span><span>{{ c.live_trades }}笔</span><span>{{ c.live_win_rate }}%</span><span>{{ c.bt_win_rate }}%</span><span :class="Math.abs(c.live_win_rate - c.bt_win_rate) > 15 ? 'down' : 'up'">{{ ((c.live_win_rate || 0) - (c.bt_win_rate || 0)).toFixed(1) }}%</span></div>
      </div>
      <div v-else class="empty">暂无对比数据</div>

      <div class="st" style="margin-top:8px">💡 前瞻建议</div>
      <div v-if="reviewForward" class="forward-section">
        <div class="fw-card fw-advice"><div class="fw-title">📌 明日操作</div><div class="fw-content">{{ reviewForward.advice }}</div></div>
        <div v-if="reviewForward.strategy_recommendations?.length || reviewForward.strategy_switches?.length" class="fw-switches">
          <div v-for="r in reviewForward.strategy_recommendations" :key="'o'+r.strategy" class="fw-card fw-open"><span class="fw-icon">🟢</span><span><strong>{{ strategyCN(r.strategy) }}</strong> 可开仓 (历史WR {{ r.win_rate }}%)</span></div>
          <div v-for="s in reviewForward.strategy_switches" :key="'c'+s.strategy" class="fw-card fw-close"><span class="fw-icon">🔴</span><span><strong>{{ strategyCN(s.strategy) }}</strong> {{ s.reason }}</span></div>
        </div>
      </div>
      <div v-else class="empty">选择日期后查看前瞻建议</div>
    </div>
  </div>


    <!-- 回测对比弹窗 -->
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
    <div class="dr-sec"><div class="dr-t">💰 账户概览</div><div class="dr-g"><div class="dr-i"><span class="dr-l">总资产</span><span class="dr-v">{{ (dailyReport.account.total_assets / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">可用</span><span class="dr-v">{{ (dailyReport.account.available_cash / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">仓位</span><span class="dr-v">{{ dailyReport.account.position_ratio }}%</span></div><div class="dr-i"><span class="dr-l">今日盈亏</span><span class="dr-v" :class="dailyReport.account.today_profit >= 0 ? 'up' : 'down'">{{ dailyReport.account.today_profit >= 0 ? '+' : '' }}{{ dailyReport.account.today_profit.toFixed(0) }}</span></div></div></div>
    <div class="dr-sec"><div class="dr-t">📊 持仓概况</div><div class="dr-g"><div class="dr-i"><span class="dr-l">持仓数</span><span class="dr-v">{{ dailyReport.positions.count }}</span></div><div class="dr-i"><span class="dr-l">止损</span><span class="dr-v text-stock-up">{{ dailyReport.stop_loss_count }}</span></div><div class="dr-i"><span class="dr-l">止盈</span><span class="dr-v text-stock-down">{{ dailyReport.take_profit_count }}</span></div><div class="dr-i"><span class="dr-l">胜率</span><span class="dr-v">{{ dailyReport.win_rate }}%</span></div></div></div>
    <div class="dr-sec" v-if="dailyReport.positions.top_profit?.length"><div class="dr-t">🏆 最赚</div><div v-for="p in dailyReport.positions.top_profit" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="up">+{{ p.pct }}%</span></div></div>
    <div class="dr-sec" v-if="dailyReport.positions.top_loss?.length"><div class="dr-t">💀 最亏</div><div v-for="p in dailyReport.positions.top_loss" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="down">{{ p.pct }}%</span></div></div>
    <div class="dr-sec" v-if="dailyReport.positions.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in dailyReport.positions.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.count }}只</span><span :class="(s.total_profit || s.total_pnl || 0) >= 0 ? 'up' : 'down'">¥{{ (s.total_profit || s.total_pnl || 0) >= 0 ? '+' : '' }}{{ (s.total_profit || s.total_pnl || 0).toFixed(0) }}</span></div></div>
  </div>
  <div v-else class="empty">暂无复盘数据</div>
</ElDialog>


    <!-- 周报弹窗 -->
<ElDialog :model-value="weeklyReportVisible" @update:model-value="emit('update:weeklyReportVisible', $event)" title="📊 周报 — 最近5个交易日" width="800px">
  <div v-if="weeklyReportData" class="wr">
    <div class="wr-sec"><div class="wr-t">💰 账户状态</div><div class="wr-g"><div class="wr-i"><span class="wr-l">总资产</span><span class="wr-v">{{ (weeklyReportData.account?.total_assets / 10000 || 0).toFixed(1) }}万</span></div><div class="wr-i"><span class="wr-l">累计盈亏</span><span class="wr-v" :class="(weeklyReportData.account?.total_profit || 0) >= 0 ? 'up' : 'down'">{{ (weeklyReportData.account?.total_profit || 0) >= 0 ? '+' : '' }}{{ (weeklyReportData.account?.total_profit || 0).toFixed(0) }}</span></div><div class="wr-i"><span class="wr-l">可用现金</span><span class="wr-v">{{ (weeklyReportData.account?.available_cash / 10000 || 0).toFixed(1) }}万</span></div></div></div>
    <div class="wr-sec"><div class="wr-t">📈 交易统计</div><div class="wr-g"><div class="wr-i"><span class="wr-l">交易日</span><span class="wr-v">{{ weeklyReportData.totals?.trading_days || 0 }}天</span></div><div class="wr-i"><span class="wr-l">买入</span><span class="wr-v">{{ weeklyReportData.totals?.total_buys || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">卖出</span><span class="wr-v">{{ weeklyReportData.totals?.total_sells || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">净流入</span><span class="wr-v" :class="weeklyReportData.totals?.net_flow >= 0 ? 'up' : 'down'">{{ (weeklyReportData.totals?.net_flow || 0).toFixed(0) }}</span></div></div></div>
    <div class="wr-sec" v-if="weeklyReportData.strategy_summary"><div class="wr-t">📋 策略汇总</div><div v-for="(s, k) in weeklyReportData.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.trades }}笔</span><span :class="s.amount >= 0 ? 'up' : 'down'">¥{{ s.amount >= 0 ? '+' : '' }}{{ (s.amount || 0).toFixed(0) }}</span></div></div>
    <div class="wr-sec" v-if="weeklyReportData.daily_stats"><div class="wr-t">📅 每日明细</div><div v-for="(stats, date) in weeklyReportData.daily_stats" class="wr-day"><span class="wr-date">{{ date }}</span><span>买{{ stats.buys }}卖{{ stats.sells }}</span><span :class="stats.sell_amount - stats.buy_amount >= 0 ? 'up' : 'down'">¥{{ ((stats.sell_amount || 0) - (stats.buy_amount || 0)).toFixed(0) }}</span></div></div>
  </div>
  <div v-else class="empty">暂无周报数据</div>
</ElDialog>
</template>

<style scoped lang="scss">
.review-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }

.review-scan-stats { display: flex; gap: 12px; padding: 6px 10px; border-radius: 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); font-size: 11px; }

.rss-row { font-size: 12px; }

.rss-label { color: var(--text-tertiary); margin-right: 4px; }

.rss-value { font-weight: 600; }

.review-sentiment-snap { margin-top: 8px; padding: 6px 12px; border-radius: 6px; background: rgba(22,93,255,0.05); border-left: 3px solid var(--el-color-primary); font-size: 12px; display: flex; gap: 8px; }

.review-tabs { display: flex; gap: 2px; }

.review-tab { padding: 6px 14px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 13px; cursor: pointer; transition: all 0.2s; }

.review-tab:hover { background: var(--bg-hover); }

.review-tab.active { background: var(--el-color-primary); color: var(--text-inverse); border-color: var(--el-color-primary); }

.review-summary-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }

.rsc { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; padding: 6px 8px; text-align: center; }

.rsc-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 2px; }

.rsc-value { font-size: 14px; font-weight: 600; }

.strategy-contrib { display: flex; flex-direction: column; gap: 8px; }

.strat-card { padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border-default); background: var(--bg-elevated); }

.strat-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }

.strat-pnl { font-weight: 700; font-size: 14px; margin-left: auto; }

.strat-pnl.up { color: var(--stock-down); }

.strat-pnl.down { color: var(--stock-up); }

.strat-metrics { display: flex; flex-wrap: wrap; gap: 4px 12px; }

.strat-m { font-size: 11px; }

.strat-ml { color: var(--text-tertiary); margin-right: 4px; }

.strat-mv { font-weight: 600; }

.attribution-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 6px; padding: 6px 10px; margin-bottom: 4px; }

.attr-top { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }

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

.hero-banner { padding: 10px 14px; border-radius: 8px; margin-bottom: 6px; }

.hero-banner.profit { background: linear-gradient(135deg, rgba(103,194,58,0.12), rgba(103,194,58,0.04)); border: 1px solid rgba(103,194,58,0.25); }

.hero-banner.slight_profit { background: linear-gradient(135deg, rgba(103,194,58,0.08), rgba(230,162,60,0.04)); border: 1px solid rgba(103,194,58,0.15); }

.hero-banner.slight_loss { background: linear-gradient(135deg, rgba(230,162,60,0.12), rgba(245,108,108,0.04)); border: 1px solid rgba(230,162,60,0.25); }

.hero-banner.loss { background: linear-gradient(135deg, rgba(245,108,108,0.12), rgba(245,108,108,0.04)); border: 1px solid rgba(245,108,108,0.25); }

.hero-banner.neutral { background: var(--bg-elevated); border: 1px solid var(--border-default); }

.hero-conclusion { font-size: 14px; font-weight: 700; line-height: 1.4; margin-bottom: 2px; }

.hero-meta { display: flex; gap: 12px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; }

.hero-bench { }

.hero-alpha { font-weight: 600; }

.hero-sentiment { }

.review-scorecard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }

.review-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }

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

.deviation-trend-chart { background: var(--bg-elevated); border-radius: 6px; padding: 8px; }

.trend-axis { display: flex; align-items: flex-end; gap: 8px; height: 100px; padding-top: 16px; }

.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }

.trend-bar { width: 100%; border-radius: 4px 4px 0 0; min-height: 20px; position: relative; transition: height 0.3s; }

.trend-val { position: absolute; top: -18px; left: 50%; transform: translateX(-50%); font-size: 11px; font-weight: 600; white-space: nowrap; }

.trend-label { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

.trend-sub { font-size: 10px; color: var(--text-tertiary); }

.calendar-heatmap { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; padding: 6px; background: var(--bg-elevated); border-radius: 6px; }

.cal-cell { border-radius: 6px; padding: 4px 2px; text-align: center; font-size: 10px; min-height: 40px; display: flex; flex-direction: column; align-items: center; justify-content: center; }

.cal-up { background: rgba(207, 48, 48, 0.15); color: var(--color-up, #f56c6c); }

.cal-down { background: rgba(103, 194, 58, 0.15); color: var(--color-down, #67c23a); }

.cal-neutral { background: var(--bg-elevated); color: var(--text-tertiary); }

.cal-date { font-weight: 600; }

.cal-pnl { font-size: 10px; font-weight: 600; }

.cal-trades { font-size: 9px; color: var(--text-tertiary); }

.strategy-stacked { display: flex; flex-direction: column; gap: 3px; padding: 6px; background: var(--bg-elevated); border-radius: 6px; }

.stacked-bar { display: flex; align-items: center; justify-content: space-between; border-radius: 4px; padding: 4px 8px; min-width: 80px; }

.stacked-label { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }

.stacked-val { font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }

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

.closed-loop-list { display: flex; flex-direction: column; gap: 6px; }

.cl-card { border-radius: 6px; padding: 6px 8px; border-left: 3px solid; }

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
