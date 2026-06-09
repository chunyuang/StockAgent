<script setup lang="ts">
/**
 * ScanTraceTab — 扫描追踪Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(86行)】
 */
import { computed, unref, onMounted } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElTag } from 'element-plus'

const m = useScannerMonitorInject()

const {
  scanTraceDate, scanTraceFilter, scanTraceLoadingMore, selectedScanIdx,
  scanDateCellClass, scanHistory, scanHistoryByHour, scanHistoryLoading,
  switchScanTraceFilter, fetchScanHistory, fetchScanTrace, toggleScanHour,
  scanTraceDetail, layerLabel, layerDesc, rejectionLayerCN,
  strategyCN, strategyMeta,
  // v2.9.75: 补齐模板使用但未解构的变量
  layerDebugVisible, layerDebugData, scanTraceVisible, scanTraceData,
  signalStatusTag, formatLayerTrace, formatDecisionDetail, factorLabel,
  fetchScanTraceDates,
} = m

// scanTraceCode accessed from inject, used in template via {{ scanTraceCode }}
// @ts-expect-error vue-tsc TS6133 false positive — used in template
const scanTraceCode = computed(() => unref((m as any).scanTraceCode))

// 挂载时自动加载日期数据(用于日期选择器高亮)
// 并自动选择最近有数据的日期加载扫描历史
onMounted(async () => {
  const dates = await fetchScanTraceDates()
  if (!scanTraceDate.value && dates?.length) {
    // scan-dates返回降序(最新在前), 取第一个作为最新交易日
    const latestDate = dates[0]?.date || dates[0]
    scanTraceDate.value = String(latestDate).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
    fetchScanHistory()
  }
})
</script>

<template>
  <div class="mm-tab-content">
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
              <span v-if="group.collapsed" class="sc-hour-summary">最新 {{ group.items[0]?.summary?.passed || 0 }}只通过</span>
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
      <div v-if="scanTraceDetail?.summary" class="scan-funnel">
        <template v-for="(layerData, layerName) in scanTraceDetail.summary" :key="layerName">
          <div v-if="String(layerName) !== 'total_candidates' && String(layerName) !== 'passed' && String(layerName) !== 'rejected' && layerData && typeof layerData === 'object'" class="fn-row" :class="{ 'fn-filter': layerData.rejected > 0, 'fn-pass': !layerData.rejected && (layerData.input || 0) > 0 }">
            <span class="fn-tag">{{ layerLabel(layerName) }}</span>
            <span class="fn-flow">{{ (layerData.input || 0) === 0 && (layerData.output || 0) === 0 && !layerData.rejected ? '—' : (layerData.input || 0) + '→' + (layerData.output || 0) }}</span>
            <span v-if="layerData.rejected" class="fn-rej">淘汰{{ layerData.rejected }}</span>
            <span class="fn-desc">{{ scanTraceDetail.layer_details?.[layerName] || layerDesc(layerName, layerData) || '' }}</span>
          </div>
        </template>
        <div v-if="scanTraceDetail?._pagination" class="fn-total">✅ 通过{{ scanTraceDetail._pagination.passed_count }} / ❌ 淘汰{{ scanTraceDetail._pagination.rejected_count }}</div>
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
            <span class="rs-label">{{ rejectionLayerCN(String(layer)) || layer }}</span>
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
              <span :class="(sig.pct_chg ?? 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (sig.pct_chg ?? 0) >= 0 ? '+' : '' }}{{ (sig.pct_chg ?? 0).toFixed(1) }}%</span>
              <span v-if="sig.final_status === 'passed'" class="et-ok">✅</span>
              <span v-else class="et-no">❌{{ rejectionLayerCN(String(sig.rejection_layer)) || sig.rejection_layer }}</span>
            </div>
          </div>
          <div v-if="scanTraceDetail._pagination && (scanTraceDetail._pagination.has_more_passed || scanTraceDetail._pagination.has_more_rejected)" class="load-more-hint">
            <span class="text-tertiary" style="font-size:11px">已显示{{ scanTraceDetail._pagination.returned_count }}条 / 共{{ scanTraceFilter === 'passed' ? scanTraceDetail._pagination.passed_count : scanTraceDetail._pagination.rejected_count }}条</span>
          </div>
        </div>
      </div>
    </div>

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
      <div class="ld-sentiment" v-if="layerDebugData.pipeline_config?.sentiment">
        情绪: {{ layerDebugData.pipeline_config.sentiment?.score ?? '-' }} → {{ layerDebugData.pipeline_config.sentiment?.period ?? '-' }} | 仓位系数: {{ ((layerDebugData.pipeline_config?.position_ratio || 0) * 100).toFixed(0) }}%
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
        <span :class="(scanTraceData.pct_chg || 0) >= 0 ? 'up' : 'down'" style="font-weight:600">{{ (scanTraceData.pct_chg || 0) >= 0 ? '+' : '' }}{{ Number(scanTraceData.pct_chg || 0).toFixed(1) }}%</span>
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
          <div v-for="(v, k) in scanTraceData.factors" :key="k" class="st-fi"><span class="st-fl">{{ factorLabel(String(k)) }}</span><span class="st-fv">{{ typeof v === 'number' && isFinite(v) ? v.toFixed(2) : v }}</span></div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="empty">加载中...</div>
</ElDialog>
  </div>
</template>

<style scoped lang="scss">
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

.fn-reject { color: var(--stock-up); font-size: 11px; }

.et-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 2px; }

.et-item { display: flex; align-items: center; gap: 3px; padding: 2px 5px; font-size: 11px; border-radius: 3px; }

.et-item.et-pass { background: rgba(0,180,42,0.05); }

.et-item.et-fail { background: rgba(245,63,63,0.04); }

.et-ok { color: var(--stock-up); flex-shrink: 0; }

.et-no { color: var(--stock-down); font-size: 9px; flex-shrink: 0; }

.rejected-stats { padding: 8px 0; }

.rs-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }

.rs-label { min-width: 72px; color: var(--text-secondary); }

.rs-bar-track { flex: 1; height: 16px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }

.rs-bar-fill { height: 100%; background: rgba(245,63,63,0.25); border-radius: 3px; transition: width 0.3s; }

.rs-count { min-width: 40px; text-align: right; font-weight: 600; }

.load-more-hint { text-align: center; padding: 8px 0; }

.scan-chip.debug { border-style: dashed; opacity: 0.85; }

.sc-debug-tag { font-size: 9px; padding: 1px 4px; border-radius: 3px; background: rgba(230,162,60,0.15); color: #e6a23c; font-weight: 600; }

/* ========== 弹窗样式(v2.9.75死CSS清理误删补回) ========== */

/* 9层筛选调试弹窗 */
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
.layer-debug { font-size: 13px; }

/* 单只股票扫描链路弹窗 */
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

/* ========== 日期选择器高亮(teleported=false所以scoped生效) ========== */
:deep(.has-scan-data) { position: relative; }
:deep(.has-scan-data .el-date-table-cell) { color: var(--el-color-primary) !important; font-weight: 600; }
:deep(.has-scan-data .el-date-table-cell::after) { content: ''; position: absolute; bottom: 2px; left: 50%; transform: translateX(-50%); width: 4px; height: 4px; border-radius: 50%; background: var(--el-color-primary); }
:deep(.has-scan-debug) { position: relative; }
:deep(.has-scan-debug .el-date-table-cell) { color: #e6a23c !important; font-weight: 600; }
:deep(.has-scan-debug .el-date-table-cell::after) { content: ''; position: absolute; bottom: 2px; left: 50%; transform: translateX(-50%); width: 4px; height: 4px; border-radius: 50%; background: #e6a23c; }
</style>
