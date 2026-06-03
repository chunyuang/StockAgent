<script setup lang="ts">
/**
 * SentimentTab — 情绪分析Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(237行)】
 */
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
        <div class="rw-card rw-rec">
          <div class="rw-title">📌 当前建议</div>
          <div class="rw-content">{{ sentimentAdvice }}</div>
        </div>
        <div v-for="r in sentimentRecommendations" :key="r.strategy" class="rw-card rw-strat">
          <div class="rw-title">🏆 {{ strategyCN(r.strategy) }}</div>
          <div class="rw-content">在 <strong :style="{ color: phaseColors[r.best_period] || 'var(--text-primary)' }">{{ r.best_period }}</strong> 期表现最佳，{{ r.count }}笔 WR{{ r.win_rate }}%</div>
        </div>
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
</template>
