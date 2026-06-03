<script setup lang="ts">
/**
 * SentimentTab — 情绪分析Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(237行)】
 * 【v2.9.75: 提取chart计算属性, 消除10个TS7006隐式any错误】
 */
import { computed } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker } from 'element-plus'

const m = useScannerMonitorInject()

const {
  sentimentMode, sentimentDate, hoveredPoint, sentimentTimeline,
  sentimentTrades, displayTimeline, isIntradayFallback, intradayMaxCand,
  xAxisLabels, sentimentMatrix, sentimentRecommendations, sentimentLoading,
  sentimentLive, phaseGuide, downgradeRules, phaseColors, sentimentAdvice,
  fetchSentimentData, strategyCN,
} = m

// ===== v2.9.75: 类型化chart计算属性, 消除模板内隐式any回调 =====

/** 日内SVG折线: candidates + passed */
const intradayCandidatePoints = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  const maxC = intradayMaxCand.value as number
  if (!maxC) return ''
  return tl.map((p: Record<string, any>, i: number) =>
    `${i * 20},${100 - Math.round(((p.candidates || 0) as number) / maxC * 90)}`
  ).join(' ')
})
const intradayPassedPoints = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  const maxC = intradayMaxCand.value as number
  if (!maxC) return ''
  return tl.map((p: Record<string, any>, i: number) =>
    `${i * 20},${100 - Math.round(((p.passed || 0) as number) / maxC * 90)}`
  ).join(' ')
})

/** 日线SVG折线 */
const dailyScorePoints = computed(() => {
  const tl = (displayTimeline.value as Array<Record<string, any>>).filter(
    (p: Record<string, any>) => p.score != null
  )
  return tl.map((p: Record<string, any>, i: number) =>
    `${i * 20},${100 - (p.score || 0)}`
  ).join(' ')
})

/** 日线有score的数据点 */
const scoredTimeline = computed(() =>
  (displayTimeline.value as Array<Record<string, any>>).filter(
    (p: Record<string, any>) => p.score != null
  )
)

/** 交易标记定位 - 日内 */
const intradayTradeMarkers = computed(() =>
  (sentimentTrades.value as Array<Record<string, any>>).map(
    (t: Record<string, any>) => ({
      ...t,
      leftPct: (() => {
        const tl = displayTimeline.value as Array<Record<string, any>>
        const idx = tl.findIndex((p: Record<string, any>) => (p.time as string) >= (t.time as string))
        return tl.length ? idx / Math.max(tl.length - 1, 1) * 100 : 50
      })(),
    })
  )
)

/** 交易标记定位 - 日线 */
const dailyTradeMarkers = computed(() =>
  (sentimentTrades.value as Array<Record<string, any>>).map(
    (t: Record<string, any>) => ({
      ...t,
      leftPct: (() => {
        const tl = displayTimeline.value as Array<Record<string, any>>
        const idx = tl.findIndex((p: Record<string, any>) => (p.date as string) >= (t.date as string))
        return tl.length ? idx / Math.max(tl.length - 1, 1) * 100 : 50
      })(),
    })
  )
)

/** 策略×情绪矩阵合计行 */
function matrixTotal(periods: Record<string, any>): number {
  return Object.values(periods).reduce(
    (s: number, v: any) => s + ((v as Record<string, any>).count as number || 0), 0
  )
}

/** 日内dot的bottom百分比 */
function intradayDotBottom(p: Record<string, any>): number {
  return Math.round(((p.candidates || 0) as number) / (intradayMaxCand.value as number) * 90)
}

/** 日线dot的bottom百分比 */
function dailyDotBottom(p: Record<string, any>): number {
  return (p.score || 0) as number
}

/** 日内hover card定位 */
function intradayHoverLeft(): number {
  const tl = displayTimeline.value as Array<Record<string, any>>
  const hp = hoveredPoint.value as Record<string, any> | null
  if (!hp) return 0
  const idx = tl.findIndex((p: Record<string, any>) => p === hp)
  return Math.min(idx / Math.max(tl.length - 1, 1) * 100, 75)
}
function intradayHoverBottom(): number {
  const hp = hoveredPoint.value as Record<string, any> | null
  return Math.min(((hp?.score || 30) as number) + 8, 85)
}

/** 日线hover card定位 */
function dailyHoverLeft(): number {
  const tl = displayTimeline.value as Array<Record<string, any>>
  const hp = hoveredPoint.value as Record<string, any> | null
  if (!hp) return 0
  const idx = tl.findIndex((p: Record<string, any>) => p === hp)
  return Math.min(idx / Math.max(tl.length - 1, 1) * 100, 75)
}
function dailyHoverBottom(): number {
  const hp = hoveredPoint.value as Record<string, any> | null
  return Math.min(((hp?.score || 30) as number) + 8, 85)
}
</script>

<template>
  <div class="mm-tab-content">
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
              <svg class="sc-svg" :viewBox="`0 0 ${Math.max((displayTimeline as any[]).length - 1, 1) * 20} 100`" preserveAspectRatio="none">
                <polyline :points="intradayCandidatePoints" fill="none" stroke="#409eff" stroke-width="1.5" />
                <polyline :points="intradayPassedPoints" fill="none" stroke="#67c23a" stroke-width="1.5" />
              </svg>
              <template v-for="(p, i) in (displayTimeline as any[])" :key="i">
                <div class="sc-dot" :style="{ left: `${i / Math.max((displayTimeline as any[]).length - 1, 1) * 100}%`, bottom: `${intradayDotBottom(p)}%` }" @mouseenter="hoveredPoint = p" @mouseleave="hoveredPoint = null"></div>
              </template>
              <div style="position:absolute;top:4px;right:8px;font-size:10px;z-index:5"><span style="color:#409eff">● 候选</span> <span style="color:#67c23a;margin-left:6px">● 通过</span></div>
            </template>
            <template v-else>
              <svg class="sc-svg" :viewBox="`0 0 ${Math.max(scoredTimeline.length - 1, 1) * 20} 100`" preserveAspectRatio="none">
                <polyline :points="dailyScorePoints" fill="none" stroke="var(--el-color-primary)" stroke-width="1.5" />
              </svg>
              <template v-for="(p, i) in (displayTimeline as any[])" :key="i">
                <div v-if="p.score != null" class="sc-dot" :style="{ left: `${i / Math.max((displayTimeline as any[]).length - 1, 1) * 100}%`, bottom: `${dailyDotBottom(p)}%` }" :class="p.period === '高潮' ? 'hot' : p.period === '冰点' ? 'cold' : p.missing_data ? 'missing' : ''" @mouseenter="hoveredPoint = p" @mouseleave="hoveredPoint = null"></div>
              </template>
            </template>
            <div v-if="hoveredPoint" class="sc-hover-card" :style="{ left: `${sentimentMode === 'intraday' && !isIntradayFallback ? intradayHoverLeft() : dailyHoverLeft()}%`, bottom: `${sentimentMode === 'intraday' && !isIntradayFallback ? intradayHoverBottom() : dailyHoverBottom()}%` }">
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
              <div v-if="sentimentMode === 'intraday'" class="sc-trade-marker" :class="t.side" :style="{ left: `${intradayTradeMarkers[i]?.leftPct || 50}%`, bottom: '2%' }">{{ (t as any).side === 'buy' ? '▲' : '▼' }}</div>
              <div v-else class="sc-trade-marker" :class="t.side" :style="{ left: `${dailyTradeMarkers[i]?.leftPct || 50}%`, bottom: '2%' }">{{ (t as any).side === 'buy' ? '▲' : '▼' }}</div>
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
                <div class="sl-gauge-fill" :style="{ width: (sentimentLive?.score || 0) + '%', background: (sentimentLive?.score || 0) >= 70 ? '#f56c6c' : (sentimentLive?.score || 0) >= 55 ? '#409eff' : (sentimentLive?.score || 0) >= 40 ? '#e6a23c' : '#67c23a' }"></div>
              </div>
              <div class="sl-score-labels"><span>0 冰点</span><span>40 震荡</span><span>55 分化</span><span>70 高潮</span><span>100</span></div>
            </div>
            <div class="sl-row"><span>情绪分</span><span class="sl-val" :style="{ color: (sentimentLive?.score || 0) >= 70 ? '#f56c6c' : (sentimentLive?.score || 0) >= 55 ? '#409eff' : (sentimentLive?.score || 0) >= 40 ? '#e6a23c' : '#67c23a' }">{{ (sentimentLive?.score || 0)?.toFixed(0) }}</span></div>
            <div class="sl-row"><span>周期</span><span class="sl-val">{{ (sentimentLive?.period_label || "") }}</span></div>
            <div class="sl-row"><span>仓位系数</span><span class="sl-val">{{ ((sentimentLive?.position_ratio || 0) * 100).toFixed(0) }}%</span></div>
            <div class="sl-row"><span>允许开仓</span><span class="sl-val" :style="{ color: (sentimentLive?.position_ratio || 0) > 0 ? '#67c23a' : '#f56c6c' }">{{ (sentimentLive?.position_ratio || 0) > 0 ? '✅ 是' : '❌ 否' }}</span></div>
          </div>
          <div v-else class="empty" style="padding:8px 0">无数据</div>
        </div>
        <!-- 市场全景 -->
        <div class="sentiment-panel">
          <div class="st">📊 市场全景</div>
          <div v-if="sentimentLive" class="sl-content">
            <div class="sl-row"><span>涨停</span><span class="sl-val up">{{ (sentimentLive?.limit_up_count || 0) }}</span></div>
            <div class="sl-row"><span>跌停</span><span class="sl-val down">{{ (sentimentLive?.limit_down_count || 0) }}</span></div>
            <div class="sl-row"><span>炸板率</span><span class="sl-val" :style="{ color: sentimentLive.broken_rate > 30 ? '#f56c6c' : 'var(--text-primary)' }">{{ sentimentLive.broken_rate?.toFixed(1) }}%</span></div>
            <div class="sl-row"><span>炸板数</span><span class="sl-val">{{ (sentimentLive?.broken_count || 0) }}</span></div>
            <div v-if="(sentimentLive?.board_distribution || {}) && Object.keys((sentimentLive?.board_distribution || {})).length" class="sl-board">
              <span style="color:var(--text-tertiary);font-size:11px">连板分布</span>
              <div v-for="(cnt, times) in (sentimentLive?.board_distribution || {})" :key="times" class="sl-board-item">
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
            <div class="sl-row"><span>涨停贡献</span><span class="sl-val">{{ Math.min(30, (sentimentLive?.limit_up_count || 0)) }}/30</span></div>
            <div class="sl-row"><span>跌停扣分</span><span class="sl-val">{{ Math.max(0, 20 - (sentimentLive?.limit_down_count || 0) * 2) }}/20</span></div>
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
              <td class="mt-total">{{ matrixTotal(periods) }}笔</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty" style="padding:8px 0">暂无策略×情绪数据</div>

      <!-- ============ 区块6: 推荐与警告 ============ -->
      <div class="st" style="margin-top:12px">💡 推荐与警告</div>
      <div v-if="sentimentLive" class="rec-warn-section">
        <div class="rw-card rw-rec">
          <div class="rw-title">📌 当前建议</div>
          <div class="rw-content">{{ sentimentAdvice }}</div>
        </div>
        <div v-for="r in sentimentRecommendations" :key="r.strategy" class="rw-card rw-strat">
          <div class="rw-title">🏆 {{ strategyCN(r.strategy) }}</div>
          <div class="rw-content">在 <strong :style="{ color: phaseColors[r.best_period] || 'var(--text-primary)' }">{{ r.best_period }}</strong> 期表现最佳，{{ r.count }}笔 WR{{ r.win_rate }}%</div>
        </div>
        <div v-if="(sentimentLive?.score || 0) < 40" class="rw-card rw-warn">
          <div class="rw-title">⚠️ 风险警告</div>
          <div class="rw-content">当前情绪冰点，市场极度弱势。建议空仓观望，禁止新开仓。持仓应严格执行止损，亏损标的优先平仓。</div>
        </div>
        <div v-else-if="(sentimentLive?.score || 0) < 55" class="rw-card rw-caution">
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
</template>

<style scoped lang="scss">
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
</style>
