<script setup lang="ts">
/**
 * PremarketTab — 盘前竞价Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(254行)】
 * 【v2.9.75: 提取计算属性, 消除TS7006/TS7053错误】
 */
import { computed, onMounted } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElTag, ElDatePicker } from 'element-plus'

const m = useScannerMonitorInject()

// 解构需要的变量
const {
  premarketStatus, premarketCandidates, premarketSignals,
  premarketDebugMode, premarketDebugUserToggled, premarketDate, premarketGroupMode, premarketGroupExpanded,
  premarketAnalysis, premarketBlockedReasons, premarketFunnel,
  premarketHitRate, premarketLimitPools, premarketMarketSnapshot,
  premarketPositionGaps, premarketSentiment, premarketStrategyGroups,
  auctionTopGainers,
  dryRun, strategyCN, strategyMeta,
  fetchPremarketData, quickBuy,
} = m

// v2.9.75: 类型化计算属性, 消除模板内隐式any回调
const executedCount = computed(() =>
  (premarketCandidates.value as any[]).filter((c: any) => c.signal_status === 'executed').length
)
const blockedCount = computed(() =>
  (premarketCandidates.value as any[]).filter((c: any) => c.signal_status === 'blocked' || c.signal_status === 'skipped').length
)

// 非交易时间自动加载最近交易日盘前数据
onMounted(() => {
  if (premarketStatus.value === 'off' && !premarketDebugMode.value) {
    fetchPremarketData()
  }
})
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 状态栏 -->
      <div class="pm-status-bar">
        <div class="pm-status-icon">{{ premarketStatus === 'active' ? '🔴' : premarketStatus === 'ended' ? '✅' : premarketStatus === 'waiting' ? '⏳' : premarketStatus === 'debug' ? '🧪' : '💤' }}</div>
        <div class="pm-status-text">
          <div class="pm-status-title">{{ ({active: '竞价进行中', ended: '竞价已结束 · 查看当日预选', waiting: '等待竞价(9:15)', debug: '🧪 调试预选模式', off: '非交易时间'} as Record<string, string>)[premarketStatus as string] }} <span v-if="premarketDebugMode" class="pm-debug-badge">SIM</span></div>
          <div class="pm-status-sub">{{ premarketDebugMode ? '最近交易日数据 · 不影响实盘' : premarketCandidates.length + '只候选 · ' + premarketStrategyGroups.length + '个策略' }}</div>
        </div>
        <div class="pm-status-actions">
          <ElDatePicker v-model="premarketDate" type="date" size="small" value-format="YYYY-MM-DD" style="width:130px" @change="fetchPremarketData" />
          <ElButton size="small" @click="fetchPremarketData">🔄</ElButton>
          <button :class="['pm-mode-btn', premarketDebugMode ? 'active' : '']" @click="premarketDebugMode = !premarketDebugMode; premarketDebugUserToggled = true; fetchPremarketData()" title="用日级因子模拟盘前预选(非交易时间可用)">🧪 调试</button>
          <button :class="['pm-mode-btn', premarketGroupMode === 'strategy' ? 'active' : '']" @click="premarketGroupMode = 'strategy'">按策略</button>
          <button :class="['pm-mode-btn', premarketGroupMode === 'list' ? 'active' : '']" @click="premarketGroupMode = 'list'">列表</button>
        </div>
      </div>

      <!-- 情绪+市场快照 -->
      <div class="pm-overview">
        <div class="pm-ov-card pm-sentiment">
          <div class="pm-ov-label">🌡️ 情绪周期</div>
          <div class="pm-ov-val" :class="(premarketSentiment?.score ?? 0) >= 55 ? 'up' : (premarketSentiment?.score ?? 0) < 40 ? 'down' : ''">
            {{ (premarketSentiment?.phase_name) || '震荡' }}
            <span class="pm-ov-sub">{{ premarketSentiment?.score ?? '-' }}分</span>
          </div>
          <div class="pm-ov-hint">仓位系数 {{ ((Number(premarketSentiment?.position_ratio) || 0.5) * 100).toFixed(0) }}%</div>
        </div>
        <div class="pm-ov-card">
          <div class="pm-ov-label">📈 涨/跌</div>
          <div class="pm-ov-row">
            <span class="up">{{ (premarketMarketSnapshot?.up_count) || 0 }}</span>
            <span class="pm-ov-sep">/</span>
            <span class="down">{{ (premarketMarketSnapshot?.down_count) || 0 }}</span>
          </div>
          <div class="pm-ov-hint">均幅 {{ (Number(premarketMarketSnapshot?.avg_pct_chg) || 0).toFixed(2) }}%<span v-if="premarketMarketSnapshot?.data_date"> ({{ String(premarketMarketSnapshot.data_date).slice(4,6) }}/{{ String(premarketMarketSnapshot.data_date).slice(6,8) }}数据)</span></div>
        </div>
        <div class="pm-ov-card">
          <div class="pm-ov-label">🔴 涨停/跌停</div>
          <div class="pm-ov-row">
            <span class="up">{{ (premarketMarketSnapshot?.limit_up_count) || 0 }}</span>
            <span class="pm-ov-sep">/</span>
            <span class="down">{{ (premarketMarketSnapshot?.limit_down_count) || 0 }}</span>
          </div>
          <div class="pm-ov-hint">量比>2: {{ (premarketMarketSnapshot?.volume_ratio_gt2) || 0 }}只</div>
        </div>
        <div class="pm-ov-card">
          <div class="pm-ov-label">🎯 信号数</div>
          <div class="pm-ov-val">{{ premarketCandidates.length }}</div>
          <div class="pm-ov-hint">已执行 {{ executedCount }} | blocked {{ blockedCount }}</div>
        </div>
      </div>

      <!-- 漏斗+Blocked原因(调试模式) -->
      <div v-if="premarketDebugMode && ((premarketFunnel?.total_scanned) || Object.keys(premarketBlockedReasons || {}).length)" class="pm-debug-panel">
        <div class="pm-dp-title">📊 9层漏斗</div>
        <div class="pm-funnel">
          <div class="pm-funnel-step"><span class="pm-fs-label">全市场</span><span class="pm-fs-val">{{ (premarketFunnel?.total_scanned) || 0 }}</span></div>
          <div class="pm-funnel-arrow">→</div>
          <div class="pm-funnel-step"><span class="pm-fs-label">策略候选</span><span class="pm-fs-val">{{ (premarketFunnel?.strategy_candidates) || 0 }}</span></div>
          <div class="pm-funnel-arrow">→</div>
          <div class="pm-funnel-step"><span class="pm-fs-label">9层通过</span><span class="pm-fs-val up">{{ (premarketFunnel?.after_pipeline) || 0 }}</span></div>
          <div class="pm-funnel-arrow">→</div>
          <div class="pm-funnel-step"><span class="pm-fs-label">blocked</span><span class="pm-fs-val warn">{{ (premarketFunnel?.blocked) || 0 }}</span></div>
          <div class="pm-funnel-arrow">→</div>
          <div class="pm-funnel-step"><span class="pm-fs-label">已买</span><span class="pm-fs-val" style="color:var(--el-color-success)">{{ (premarketFunnel?.executed) || 0 }}</span></div>
        </div>
        <div v-if="Object.keys(premarketBlockedReasons || {}).length" class="pm-blocked-reasons">
          <div class="pm-dp-title">🚫 Blocked原因</div>
          <div v-for="(count, reason) in premarketBlockedReasons" :key="reason" class="pm-br-item">
            <span class="pm-br-reason">{{ reason }}</span><span class="pm-br-count">{{ count }}笔</span>
          </div>
        </div>
      </div>

      <!-- 盘前综合分析 -->
      <div v-if="premarketAnalysis" class="pm-analysis">
        <div class="pm-analysis-head">
          <span class="pm-analysis-icon">🧠</span>
          <span class="pm-analysis-title">盘前综合研判</span>
          <span class="pm-analysis-date" v-if="premarketAnalysis.data_date">{{ premarketAnalysis.data_date?.slice(4,6) }}/{{ premarketAnalysis.data_date?.slice(6,8) }}数据</span>
        </div>
        <div class="pm-conclusion" :class="premarketAnalysis.verdict">
          <span class="pm-verdict-icon">{{ premarketAnalysis.verdict === 'bullish' ? '🟢' : premarketAnalysis.verdict === 'bearish' ? '🔴' : '🟡' }}</span>
          <span class="pm-verdict-text">{{ premarketAnalysis.conclusion }}</span>
        </div>
        <div class="pm-reasons">
          <div v-for="(r, i) in premarketAnalysis.reasons" :key="i" class="pm-reason-item">
            <span class="pm-reason-icon">{{ r.icon }}</span><span class="pm-reason-text">{{ r.text }}</span>
          </div>
        </div>
        <div v-if="premarketAnalysis.suggestion" class="pm-suggestion">
          <span class="pm-sugg-label">💡 建议</span><span class="pm-sugg-text">{{ premarketAnalysis.suggestion }}</span>
        </div>
      </div>

      <!-- 涨停池+连板分布+板块热力 -->
      <div class="pm-zt-section">
        <div class="pm-zt-header">
          <div class="st">🔴 涨停池 <span class="text-tertiary" style="font-size:10px">({{ (premarketLimitPools?.up_count) || 0 }}只)</span></div>
          <div class="st">🟢 跌停池 <span class="text-tertiary" style="font-size:10px">({{ (premarketLimitPools?.down_count) || 0 }}只)</span></div>
        </div>
        <div class="pm-zt-body">
          <div v-if="(premarketLimitPools?.continue_stats) && Object.keys((premarketLimitPools?.continue_stats)).length" class="pm-continue-bar">
            <span class="pm-cb-label">连板</span>
            <template v-for="(count, boards) in (premarketLimitPools?.continue_stats)" :key="boards">
              <span class="pm-cb-item" :class="Number(boards) >= 3 ? 'hot' : ''">{{ boards }}板×{{ count }}</span>
            </template>
          </div>
          <div v-if="(premarketLimitPools?.sector_heat) && (premarketLimitPools?.sector_heat).length" class="pm-sector-heat">
            <span class="pm-sh-label">板块</span>
            <span v-for="s in (premarketLimitPools?.sector_heat || []).slice(0, 8)" :key="s.name" class="pm-sh-item" :class="s.count >= 3 ? 'hot' : ''">
              {{ s.name }}<sub>{{ s.count }}</sub>
            </span>
          </div>
          <div v-if="(premarketLimitPools?.limit_up_list) && (premarketLimitPools?.limit_up_list).length" class="pm-zt-list">
            <div class="pm-zt-toggle cp" @click="premarketGroupExpanded = { ...premarketGroupExpanded, limit_up: !premarketGroupExpanded['limit_up'] }">
              {{ premarketGroupExpanded['limit_up'] ? '▼' : '▶' }} 涨停明细 {{ (premarketLimitPools?.limit_up_list).length }}只
            </div>
            <div v-if="premarketGroupExpanded['limit_up']" class="pm-zt-items">
              <span v-for="z in (premarketLimitPools?.limit_up_list)" :key="z.ts_code" class="pm-zt-tag" :class="z.open_times > 0 ? 'broken' : 'sealed'">
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
          <div v-for="p in premarketPositionGaps" :key="p.ts_code" class="pm-pg-item" :class="(p.gap_pct || 0) >= 0 ? 'gap-up' : 'gap-down'">
            <span class="pm-pg-name">{{ p.stock_name }}</span>
            <span class="pm-pg-gap" :class="(p.gap_pct || 0) >= 0 ? 'up' : 'down'">{{ (p.gap_pct || 0) >= 0 ? '⬆' : '⬇' }} {{ (p.gap_pct || 0) >= 0 ? '+' : '' }}{{ (p.gap_pct || 0).toFixed(1) }}%</span>
            <span class="pm-pg-hint">{{ (p.gap_pct || 0) > 3 ? '强势高开' : (p.gap_pct || 0) < -2 ? '⚠️风险低开' : '正常' }}</span>
          </div>
        </div>
      </div>

      <!-- 策略分组模式 -->
      <div v-if="premarketGroupMode === 'strategy'" class="pm-groups">
        <div v-for="g in premarketStrategyGroups" :key="g.strategy" class="pm-group">
          <div class="pm-group-header cp" @click="premarketGroupExpanded = { ...premarketGroupExpanded, [g.strategy]: !premarketGroupExpanded[g.strategy] }">
            <span class="pm-group-toggle">{{ premarketGroupExpanded[g.strategy] ? '▼' : '▶' }}</span>
            <ElTag size="small" :color="strategyMeta[g.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(g.strategy) }}</ElTag>
            <span class="pm-group-stat">{{ g.count }}只</span>
            <span class="pm-group-stat" :class="(g.avg_pct_chg || 0) >= 0 ? 'up' : 'down'">均幅 {{ (g.avg_pct_chg || 0) >= 0 ? '+' : '' }}{{ (g.avg_pct_chg || 0).toFixed(1) }}%</span>
            <span v-if="g.executed" class="pm-group-stat executed">已买{{ g.executed }}</span>
            <span v-if="g.blocked" class="pm-group-stat warn">blocked {{ g.blocked }}</span>
            <span v-if="premarketHitRate?.[g.strategy]" class="pm-group-stat hit-rate" :class="(premarketHitRate?.[g.strategy])?.win_rate >= 60 ? 'up' : 'warn'">
              历史 {{ (premarketHitRate?.[g.strategy])?.win_rate ?? '-' }}%胜 / {{ (premarketHitRate?.[g.strategy])?.total ?? '-' }}笔
            </span>
            <span class="pm-group-preview">{{ (g.candidates || []).slice(0, 3).map((c: any) => (c.stock_name || c.ts_code?.slice(0,6)) + ' ' + ((c.pct_chg || 0) >= 0 ? '+' : '') + (c.pct_chg || 0).toFixed(1) + '%').join(' · ') }}{{ g.count > 3 ? ' ...' : '' }}</span>
          </div>
          <div v-if="premarketGroupExpanded[g.strategy]" class="pm-group-list">
            <div v-for="c in g.candidates" :key="c.ts_code + c.strategy" class="pm-item">
              <span class="pm-item-code">{{ c.ts_code?.slice(0,6) }}</span>
              <span class="pm-item-name">{{ c.stock_name }}</span>
              <span :class="(c.pct_chg || 0) >= 0 ? 'up' : 'down'" class="pm-item-pct">{{ (c.pct_chg || 0) >= 0 ? '+' : '' }}{{ (c.pct_chg || 0).toFixed(1) }}%</span>
              <span v-if="c.volume_ratio" class="pm-item-factor">量比{{ (c.volume_ratio || 0).toFixed(1) }}</span>
              <span v-if="c.turnover_rate" class="pm-item-factor">换手{{ (c.turnover_rate || 0).toFixed(1) }}%</span>
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
          <div class="pm-empty-text">{{ premarketDebugMode ? '无日级因子数据，请启动扫描器后再试' : '非交易时间自动显示最近交易日盘前数据' }}</div>
          <div class="pm-empty-hint">{{ premarketMarketSnapshot?.error ? `⚠️ ${premarketMarketSnapshot.error}` : (premarketDebugMode ? '调试模式使用daily_factors_df模拟策略扫描' : '竞价期间(9:15-9:25)自动切换为实时数据') }}</div>
        </div>
      </div>

      <!-- 列表模式 -->
      <div v-if="premarketGroupMode === 'list'" class="pm-list-mode">
        <div class="pm-table-header"><span>代码</span><span>名称</span><span>策略</span><span>涨幅</span><span>量比</span><span>换手</span><span>状态</span><span>操作</span></div>
        <div v-for="c in premarketCandidates" :key="c.ts_code + c.strategy" class="pm-table-row">
          <span class="code">{{ c.ts_code?.slice(0,6) }}</span>
          <span class="name">{{ c.stock_name }}</span>
          <ElTag size="small" :color="strategyMeta[c.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:9px">{{ strategyCN(c.strategy) }}</ElTag>
          <span :class="(c.pct_chg || 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (c.pct_chg || 0) >= 0 ? '+' : '' }}{{ (c.pct_chg || 0).toFixed(1) }}%</span>
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
            <span :class="(g.pct_chg || 0) >= 0 ? 'up' : 'down'" style="font-weight:700;font-size:14px">{{ (g.pct_chg || 0) >= 0 ? '+' : '' }}{{ (g.pct_chg || 0).toFixed(1) }}%</span>
            <span v-if="g.volume_ratio" class="pm-item-factor">量比{{ (g.volume_ratio || 0).toFixed(1) }}</span>
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
            <span :class="(s.pct_chg || 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (s.pct_chg || 0) >= 0 ? '+' : '' }}{{ (s.pct_chg || 0).toFixed(1) }}%</span>
            <span v-if="s.volume_ratio" class="pm-item-factor">量比{{ (s.volume_ratio || 0).toFixed(1) }}</span>
            <ElTag v-if="s.signal_status === 'executed'" size="small" type="success">已买</ElTag>
            <ElButton v-else-if="!dryRun" size="small" type="danger" plain class="btn-xs" @click="quickBuy(s)">买</ElButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
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
</style>
