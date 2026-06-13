<script setup lang="ts">
/**
 * AnalysisTab — 市场监听结果分析
 * 参考回测结果分析，对实盘交易数据进行综合KPI、策略贡献、卖出原因、月度收益分析
 * v2.9.92g
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElTag, ElEmpty } from 'element-plus'
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const m = useScannerMonitorInject()
const { activeTab } = m

const loading = ref(false)
const dateRange = ref<[string, string] | null>(null)
const analysisData = ref<any>(null)

async function fetchAnalysis() {
  loading.value = true
  try {
    let url = '/scanner/analysis'
    if (dateRange.value) {
      const [s, e] = dateRange.value
      url += `?start_date=${s.replace(/-/g, '')}&end_date=${e.replace(/-/g, '')}`
    }
    const r = await api.get(url)
    const p = parseResponse(r)
    if (p.success) analysisData.value = p.data
  } catch (e) { console.error('[Analysis]', e) }
  finally { loading.value = false }
}

onMounted(() => { if (activeTab.value === 'analysis') fetchAnalysis() })
watch(activeTab, (t) => { if (t === 'analysis' && !analysisData.value) fetchAnalysis() })

const kpi = computed(() => analysisData.value?.kpi || {})
const strategies = computed(() => analysisData.value?.strategy_contrib || [])
const sellReasons = computed(() => analysisData.value?.sell_reasons || [])
const monthly = computed(() => analysisData.value?.monthly || [])
const positions = computed(() => analysisData.value?.positions || [])

const totalReasonCount = computed(() => sellReasons.value.reduce((s: number, r: any) => s + r.count, 0) || 1)
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll ana-wrap">
      <!-- 工具栏 -->
      <div class="ana-toolbar">
        <span class="ana-title">📊 结果分析</span>
        <ElDatePicker v-model="dateRange" type="daterange" start-placeholder="开始" end-placeholder="结束" size="small" value-format="YYYY-MM-DD" style="width:220px" :disabled-date="(d: Date) => d > new Date()" />
        <ElButton size="small" type="primary" @click="fetchAnalysis" :loading="loading">刷新</ElButton>
        <span class="ana-note">数据来自scanner_timeline已平仓记录</span>
      </div>

      <div v-if="!analysisData && !loading" class="ana-empty">
        <ElEmpty description="暂无分析数据，点击刷新加载" />
      </div>

      <template v-if="analysisData">
        <!-- KPI 指标卡 -->
        <div class="ana-kpis">
          <div class="kpi-card" :class="kpi.total_profit >= 0 ? 'kpi-up' : 'kpi-down'">
            <div class="kpi-label">累计盈亏</div>
            <div class="kpi-val">¥{{ (kpi.total_profit || 0).toLocaleString() }}</div>
          </div>
          <div class="kpi-card" :class="(kpi.win_rate || 0) >= 50 ? 'kpi-up' : 'kpi-down'">
            <div class="kpi-label">胜率</div>
            <div class="kpi-val">{{ (kpi.win_rate || 0).toFixed(1) }}%</div>
          </div>
          <div class="kpi-card kpi-neutral">
            <div class="kpi-label">交易笔数</div>
            <div class="kpi-val">{{ kpi.total_trades || 0 }}</div>
          </div>
          <div class="kpi-card" :class="(kpi.profit_loss_ratio || 0) >= 2 ? 'kpi-up' : 'kpi-warn'">
            <div class="kpi-label">盈亏比</div>
            <div class="kpi-val">{{ (kpi.profit_loss_ratio || 0).toFixed(2) }}</div>
          </div>
          <div class="kpi-card kpi-warn">
            <div class="kpi-label">最大回撤</div>
            <div class="kpi-val">{{ (kpi.max_drawdown || 0).toFixed(1) }}%</div>
          </div>
          <div class="kpi-card kpi-neutral">
            <div class="kpi-label">平均盈亏%</div>
            <div class="kpi-val" :class="(kpi.avg_profit_pct || 0) >= 0 ? 'up' : 'down'">{{ (kpi.avg_profit_pct || 0).toFixed(2) }}%</div>
          </div>
        </div>

        <div class="ana-grid">
          <!-- 左: 策略贡献 + 卖出原因 -->
          <div class="ana-col">
            <!-- 策略贡献 -->
            <div class="ana-panel">
              <div class="ana-sec">🔄 策略贡献</div>
              <div v-if="!strategies.length" class="ana-empty-sm">暂无数据</div>
              <div class="ana-table">
                <div class="at-header"><span>策略</span><span>笔数</span><span>胜率</span><span>盈亏</span><span>均盈亏%</span></div>
                <div v-for="s in strategies" :key="s.strategy" class="at-row" :class="s.profit >= 0 ? 'row-up' : 'row-down'">
                  <span class="at-strat">{{ s.strategy }}</span>
                  <span>{{ s.trades }}</span>
                  <span :class="s.win_rate >= 50 ? 'up' : 'down'">{{ s.win_rate.toFixed(1) }}%</span>
                  <span :class="s.profit >= 0 ? 'up' : 'down'">¥{{ s.profit.toLocaleString() }}</span>
                  <span :class="s.avg_profit_pct >= 0 ? 'up' : 'down'">{{ s.avg_profit_pct.toFixed(2) }}%</span>
                </div>
              </div>
            </div>

            <!-- 卖出原因 -->
            <div class="ana-panel">
              <div class="ana-sec">📤 卖出原因</div>
              <div v-if="!sellReasons.length" class="ana-empty-sm">暂无数据</div>
              <div class="reason-bars">
                <div v-for="r in sellReasons" :key="r.reason" class="reason-row">
                  <span class="reason-name">{{ r.reason }}</span>
                  <div class="reason-bar-wrap">
                    <div class="reason-bar" :class="r.profit >= 0 ? 'bar-up' : 'bar-down'" :style="{ width: (r.count / totalReasonCount * 100) + '%' }"></div>
                  </div>
                  <span class="reason-count">{{ r.count }}笔</span>
                  <span class="reason-profit" :class="r.profit >= 0 ? 'up' : 'down'">¥{{ r.profit.toLocaleString() }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 右: 月度收益 + 持仓 -->
          <div class="ana-col">
            <!-- 月度收益 -->
            <div class="ana-panel">
              <div class="ana-sec">📅 月度收益</div>
              <div v-if="!monthly.length" class="ana-empty-sm">暂无数据</div>
              <div class="monthly-list">
                <div class="ml-header"><span>月份</span><span>盈亏</span><span>累计</span><span>笔数</span><span>胜率</span></div>
                <div v-for="m in monthly" :key="m.month" class="ml-row" :class="m.profit >= 0 ? 'row-up' : 'row-down'">
                  <span>{{ m.month }}</span>
                  <span :class="m.profit >= 0 ? 'up' : 'down'">¥{{ m.profit.toLocaleString() }}</span>
                  <span :class="m.cum_profit >= 0 ? 'up' : 'down'">¥{{ m.cum_profit.toLocaleString() }}</span>
                  <span>{{ m.trades }}</span>
                  <span :class="m.win_rate >= 50 ? 'up' : 'down'">{{ m.win_rate }}%</span>
                </div>
              </div>
            </div>

            <!-- 当前持仓 -->
            <div class="ana-panel">
              <div class="ana-sec">💼 当前持仓 <span class="ana-stat">{{ positions.length }}只</span></div>
              <div v-if="!positions.length" class="ana-empty-sm">空仓</div>
              <div class="pos-list">
                <div class="pos-header"><span>代码</span><span>名称</span><span>策略</span><span>盈亏%</span><span>市值</span></div>
                <div v-for="p in positions" :key="p.ts_code" class="pos-row" :class="p.profit_pct >= 0 ? 'row-up' : 'row-down'">
                  <span class="pos-code">{{ p.ts_code?.slice(0,6) }}</span>
                  <span class="pos-name">{{ p.stock_name }}</span>
                  <span class="pos-strat">{{ p.strategy }}</span>
                  <span :class="p.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct.toFixed(1) }}%</span>
                  <span>¥{{ (p.market_value || 0).toLocaleString() }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 每日盈亏明细 -->
        <div class="ana-panel" style="margin-top:8px" v-if="analysisData?.daily_detail">
          <div class="ana-sec">📋 每日明细</div>
          <div class="daily-list">
            <div class="dl-header"><span>日期</span><span>笔数</span><span>胜率</span><span>盈亏</span></div>
            <div v-for="d in analysisData.daily_detail" :key="d.date" class="dl-row" :class="d.profit >= 0 ? 'row-up' : 'row-down'">
              <span>{{ d.date }}</span>
              <span>{{ d.trades }}</span>
              <span :class="d.win_rate >= 50 ? 'up' : 'down'">{{ d.win_rate }}%</span>
              <span :class="d.profit >= 0 ? 'up' : 'down'">¥{{ d.profit.toLocaleString() }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ana-wrap { display: flex; flex-direction: column; gap: 8px; }
.ana-toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-default); }
.ana-title { font-size: 14px; font-weight: 700; }
.ana-note { font-size: 10px; color: var(--text-tertiary); margin-left: auto; }
.ana-empty { padding: 60px 0; text-align: center; }
.ana-empty-sm { padding: 16px 0; text-align: center; color: var(--text-tertiary); font-size: 11px; }

/* KPI 卡片 */
.ana-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.kpi-card { background: var(--bg-muted); border-radius: 6px; padding: 10px 12px; text-align: center; }
.kpi-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 4px; }
.kpi-val { font-size: 16px; font-weight: 700; }
.kpi-up { border-left: 3px solid var(--stock-up); }
.kpi-down { border-left: 3px solid var(--stock-down); }
.kpi-warn { border-left: 3px solid var(--el-color-warning); }
.kpi-neutral { border-left: 3px solid var(--text-tertiary); }

/* 双栏 */
.ana-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ana-col { display: flex; flex-direction: column; gap: 8px; }

/* 面板 */
.ana-panel { background: var(--bg-base, var(--bg-muted)); border: 1px solid var(--border-default); border-radius: 6px; padding: 8px 10px; }
.ana-sec { font-size: 12px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.ana-stat { font-size: 10px; color: var(--text-tertiary); font-weight: 400; }

/* 表格 */
.ana-table, .monthly-list, .pos-list, .daily-list { font-size: 11px; }
.at-header, .ml-header, .pos-header, .dl-header { display: flex; gap: 4px; padding: 4px 0; font-size: 10px; color: var(--text-tertiary); font-weight: 600; border-bottom: 1px solid var(--border-light); }
.at-row, .ml-row, .pos-row, .dl-row { display: flex; gap: 4px; padding: 3px 0; border-bottom: 1px solid var(--border-light); align-items: center; }
.at-row:hover, .ml-row:hover, .pos-row:hover, .dl-row:hover { background: var(--bg-muted); }
.row-up { border-left: 2px solid var(--stock-up); }
.row-down { border-left: 2px solid var(--stock-down); }

/* 策略表列宽 */
.at-header span, .at-row span { min-width: 48px; }
.at-strat { flex: 1; font-weight: 600; min-width: 60px; }
.at-row span:not(.at-strat) { text-align: right; }

/* 月度列宽 */
.ml-header span, .ml-row span { flex: 1; text-align: right; }
.ml-header span:first-child, .ml-row span:first-child { flex: 1.2; text-align: left; }

/* 持仓列宽 */
.pos-code { font-family: 'JetBrains Mono', monospace; min-width: 48px; }
.pos-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pos-strat { font-size: 9px; color: var(--el-color-primary); min-width: 48px; }

/* 卖出原因条 */
.reason-bars { display: flex; flex-direction: column; gap: 4px; }
.reason-row { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.reason-name { min-width: 48px; font-weight: 600; }
.reason-bar-wrap { flex: 1; height: 8px; background: var(--bg-muted); border-radius: 4px; overflow: hidden; min-width: 60px; }
.reason-bar { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-up { background: var(--stock-up); opacity: 0.7; }
.bar-down { background: var(--stock-down); opacity: 0.7; }
.reason-count { font-size: 10px; color: var(--text-tertiary); min-width: 32px; }
.reason-profit { font-weight: 600; min-width: 60px; text-align: right; }

/* 每日明细列宽 */
.dl-header span, .dl-row span { flex: 1; text-align: right; }
.dl-header span:first-child, .dl-row span:first-child { text-align: left; }

/* 通用 */
.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

@media (max-width: 900px) {
  .ana-kpis { grid-template-columns: repeat(3, 1fr); }
  .ana-grid { grid-template-columns: 1fr; }
}
</style>
