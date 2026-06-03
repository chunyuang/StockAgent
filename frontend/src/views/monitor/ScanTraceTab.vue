<script setup lang="ts">
/**
 * ScanTraceTab — 扫描追踪Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(86行)】
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElTag } from 'element-plus'

const m = useScannerMonitorInject()

const {
  scanTraceDate, scanTraceFilter, scanTraceLoadingMore, selectedScanIdx,
  scanDateCellClass, scanHistory, scanHistoryByHour, scanHistoryLoading,
  switchScanTraceFilter, fetchScanHistory, fetchScanTrace, toggleScanHour,
  scanTraceDetail, layerLabel, layerDesc, rejectionLayerCN,
  strategyCN, strategyMeta,
} = m
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
        <template v-for="(layerData, layerName) in scanTraceDetail.summary || {}">
          <div v-if="String(layerName) !== 'total_candidates' && String(layerName) !== 'passed' && String(layerName) !== 'rejected' && typeof layerData === 'object'" :key="layerName" class="fn-row" :class="{ 'fn-filter': layerData.rejected > 0, 'fn-pass': !layerData.rejected && (layerData.input || 0) > 0 }">
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
              <span :class="sig.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ (sig.pct_chg || 0).toFixed(1) }}%</span>
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
  </div>
</template>
