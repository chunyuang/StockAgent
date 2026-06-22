<script setup lang="ts">
/**
 * ScanTraceTab — 扫描追踪Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(86行)】
 */
import { computed, unref, onMounted, ref } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElTag } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'

const m = useScannerMonitorInject()

const {
  scanTraceDate, scanTraceFilter, scanTraceLoadingMore, selectedScanIdx,
  scanHistory, scanHistoryByHour, scanHistoryLoading,
  scanTraceDebugMode,
  switchScanTraceFilter, fetchScanHistory, fetchScanTrace, toggleScanHour,
  scanTraceDetail, layerLabel, layerDesc, rejectionLayerCN,
  strategyCN, strategyMeta,
  // v2.9.75: 补齐模板使用但未解构的变量
  layerDebugVisible, layerDebugData, scanTraceVisible, scanTraceData,
  signalStatusTag, formatLayerTrace, formatDecisionDetail, factorLabel,
  fetchScanTraceDates,
  // v2.9.95: 全天执行摘要
  executionSummary,
} = m

const showSummaryReasons = ref(false)
const expandedReasonGroup = ref('')

const blockRuleCatalog = [
  { category: '集中度', rules: ['同行业集中度超限'] },
  { category: '信号状态', rules: ['已有持仓/重复信号', '异动信号仅观察', '调试模式不下单'] },
  { category: '行情条件', rules: ['盘前预选过滤(ST/退市/次新/低流动)', '极端竞价', '换手率不足/过高', '流通市值不在区间', '龙头回调幅度不符', '流动性不足', '价格异常', '停牌/无实时行情', '涨停未成交'] },
  { category: '仓位资金', rules: ['最大持仓数已满', '可用资金不足', '单票仓位超限', '总仓位超限', '科创板资金不足200股'] },
  { category: '情绪风控', rules: ['强制空仓', '特殊时期降仓', '冰点期暂停半路追涨', '风控熔断', '非交易时间不下单', '大盘跌破MA60降仓'] },
  { category: '其他原因', rules: ['撮合失败', '执行质量检查拒绝', '下单失败/券商拒单'] },
]

const inactiveBlockRules = computed(() => {
  const groups = execSummaryDisplay.value?.groups || []
  const activeCats = new Set(groups.map((g: any) => g.label))
  return blockRuleCatalog
    .map(g => ({ ...g, active: activeCats.has(g.category), color: reasonGroupColor(g.category) }))
    .filter(g => !g.active)
})

function normalizeBlockReason(reason: string) {
  const r = String(reason || '')
  let m = r.match(/过滤·换手([\d.]+)%<下限([\d.]+)%/)
  if (m) return { reason: `首板打板：换手不足（<${m[2]}%）`, sample: r }
  m = r.match(/换手率([\d.]+)%<([\d.]+)%/)
  if (m) return { reason: `跌停翘板：换手不足（<${m[2]}%）`, sample: r }
  m = r.match(/过滤·换手([\d.]+)%>上限([\d.]+)%/)
  if (m) return { reason: `首板打板：换手过高（>${m[2]}%）`, sample: r }
  m = r.match(/流通市值[\d.]+亿<([\d.]+)亿/)
  if (m) return { reason: `流通市值过小（<${m[1]}亿）`, sample: r }
  m = r.match(/流通市值[\d.]+亿>([\d.]+)亿/)
  if (m) return { reason: `流通市值过大（>${m[1]}亿）`, sample: r }
  m = r.match(/流动性不足\(成交额[\d.]+万<([\d.]+)万\)/)
  if (m) return { reason: `流动性不足（成交额<${m[1]}万）`, sample: r }
  m = r.match(/回调[\d.]+%<([\d.]+)%/)
  if (m) return { reason: `龙头低吸：回调不足（<${m[1]}%）`, sample: r }
  m = r.match(/回调[\d.]+%>([\d.]+)%/)
  if (m) return { reason: `龙头低吸：回调过深（>${m[1]}%）`, sample: r }
  if (/已有持仓|已持仓/.test(r)) return { reason: '已有持仓/重复信号', sample: r }
  if (/持仓已满|最大持仓/.test(r)) return { reason: '最大持仓数已满', sample: r }
  if (/非交易时间/.test(r)) return { reason: '非交易时间不下单', sample: r }
  return { reason: r, sample: r }
}

// v2.9.95: 执行摘要格式化 — 顶部只保留数字，原因改为可展开Top列表，避免长文本挤爆
const execSummaryDisplay = computed(() => {
  const es = unref(executionSummary)
  if (!es) return null
  const reasonMap = Object.entries(es.block_reasons || {}).reduce((acc: Record<string, any>, [rawReason, rawCount]) => {
    const count = Number(rawCount) || 0
    const n = normalizeBlockReason(String(rawReason))
    if (!acc[n.reason]) acc[n.reason] = { reason: n.reason, count: 0, examples: [] }
    acc[n.reason].count += count
    if (n.sample && acc[n.reason].examples.length < 3 && !acc[n.reason].examples.includes(n.sample)) acc[n.reason].examples.push(n.sample)
    return acc
  }, {})
  const reasons = Object.values(reasonMap).sort((a: any, b: any) => b.count - a.count)
  const totalBlocked = Number(es.blocked || reasons.reduce((s, r) => s + r.count, 0) || 1)
  const groups = reasons.reduce((acc: Record<string, { label: string; count: number; reasons: any[] }>, r) => {
    const label = reasonCategory(r.reason)
    if (!acc[label]) acc[label] = { label, count: 0, reasons: [] }
    acc[label].count += r.count
    acc[label].reasons.push({ ...r, pct: r.count / totalBlocked * 100 })
    return acc
  }, {})
  const sortedGroups = Object.values(groups).sort((a, b) => b.count - a.count)
    .map((g, i) => ({ ...g, pct: g.count / totalBlocked * 100, color: reasonGroupColor(g.label, i) }))
  let cursor = 0
  const pieSegments = sortedGroups.map((g) => {
    const start = cursor
    cursor += g.pct
    return `${g.color} ${start}% ${cursor}%`
  }).join(', ')
  return {
    buys: es.buys || 0,
    blocked: es.blocked || 0,
    totalBlocked,
    reasons: reasons.map(r => ({ ...r, pct: r.count / totalBlocked * 100 })),
    groups: sortedGroups,
    pieStyle: { background: pieSegments ? `conic-gradient(${pieSegments})` : 'var(--bg-hover)' },
  }
})

function scanKind(s: any): 'full' | 'quick' | 'blocked' | 'other' {
  const total = Number(s?.summary?.total_candidates || 0)
  const passed = Number(s?.summary?.passed || 0)
  if (total >= 1000) return 'full'
  if (total > 0 && total <= 300) return 'quick'
  if (total > 0 && passed === 0) return 'blocked'
  return 'other'
}

function scanKindLabel(s: any): string {
  const k = scanKind(s)
  if (k === 'full') return '全市场主扫'
  if (k === 'quick') return '异动快扫'
  if (k === 'blocked') return '风控拦截'
  return '扫描'
}

function scanKindTitle(s: any): string {
  const total = Number(s?.summary?.total_candidates || 0)
  const passed = Number(s?.summary?.passed || 0)
  const bought = Number(s?.exec?.bought || 0)
  const blocked = Number(s?.exec?.blocked || 0)
  const label = scanKindLabel(s)
  if (scanKind(s) === 'full') {
    return `${label}: 策略展开记录${total}条，不等于股票数；通过排序/仓位后${passed}条，成交${bought}条，执行拦截${blocked}次`
  }
  if (scanKind(s) === 'quick') {
    return `${label}: 只扫描盘中异动/候选池${total}条；通过${passed}条，成交${bought}条，执行拦截${blocked}次`
  }
  return `${label}: 输入${total}条，通过${passed}条，成交${bought}条，执行拦截${blocked}次`
}

function scanHourTypeSummary(items: any[]) {
  const full = items.filter(s => scanKind(s) === 'full').length
  const quick = items.filter(s => scanKind(s) === 'quick').length
  const blocked = items.filter(s => scanKind(s) === 'blocked').length
  return [full ? `全市场${full}轮` : '', quick ? `异动${quick}轮` : '', blocked ? `拦截${blocked}轮` : ''].filter(Boolean).join(' · ')
}

function reasonGroupColor(label: string, index = 0): string {
  const map: Record<string, string> = {
    '集中度': '#6C8CFF',
    '信号状态': '#67C23A',
    '行情条件': '#E6A23C',
    '仓位资金': '#F56C6C',
    '情绪风控': '#9B7BFF',
    '排序评分': '#36CFC9',
    '其他原因': '#A8ABB2',
  }
  const fallback = ['#6C8CFF', '#67C23A', '#E6A23C', '#F56C6C', '#9B7BFF', '#36CFC9', '#A8ABB2']
  return map[label] || fallback[index % fallback.length]
}

function reasonCategory(reason: string): string {
  if (/仓位|资金|现金|持仓|已持有|满仓|可用/.test(reason)) return '仓位资金'
  if (/情绪|周期|冰点|高潮|分化|熔断|风控|风险|空仓/.test(reason)) return '情绪风控'
  if (/行业|集中度|板块|同业/.test(reason)) return '集中度'
  if (/排名|评分|分数|综合|概率/.test(reason)) return '排序评分'
  if (/竞价|量比|换手|封单|涨停|跌停|开板|价格|涨幅/.test(reason)) return '行情条件'
  if (/重复|过期|已在进行|信号/.test(reason)) return '信号状态'
  return '其他原因'
}

function shortReason(reason: string): string {
  return reason
    .replace(/同行业「(.+?)」已选\d+只信号,本只被集中度过滤剔除/g, '行业集中度：$1')
    .replace(/同行业「(.+?)」已选\d+只信号,本只被集中度过滤剔/g, '行业集中度：$1')
    .replace(/本只被集中度过滤剔除/g, '集中度过滤')
}

function emotionRiskTrigger(rule: string): string {
  const map: Record<string, string> = {
    '强制空仓': '极端风险闸门：跌停≥80；或涨停≤10且有跌停；或大盘跌≥3%。触发后候选清空/仓位归零。',
    '特殊时期降仓': '日历风控：月末/季末/年末/节前/周五等特殊时期降低仓位系数，不一定淘汰候选。',
    '冰点期暂停半路追涨': '情绪分<40时暂停半路追涨策略，属于情绪层直接过滤。',
    '风控熔断': '账户级闸门：连续亏损、日内回撤、手动暂停等触发后停止新增买入。',
    '非交易时间不下单': '执行闸门：盘前/盘后/午休等非真实交易时段，只记录信号，不执行真实买入。',
    '大盘跌破MA60降仓': '指数趋势风控：上证跌破MA60时仓位系数减半，通常表现为降仓而不是候选淘汰。',
  }
  return map[rule] || '系统风控规则。'
}

function emotionRiskState(rule: string): string {
  const d = unref(scanTraceDetail) as any
  if (!d?.layer_details) return '当前未选中具体扫描，点击某条扫描记录后可看本轮状态。'
  if (rule === '强制空仓') return d.layer_details.L1_force_empty || '本轮未返回强制空仓状态。'
  if (rule === '特殊时期降仓') return d.layer_details.L2_special_period || '本轮未返回特殊时期状态。'
  if (rule === '冰点期暂停半路追涨') return d.layer_details.L3_sentiment || '本轮未返回情绪状态。'
  if (rule === '大盘跌破MA60降仓') return d.layer_details.L8_ma60 || '本轮未返回MA60状态。'
  if (rule === '非交易时间不下单') return '若本轮发生，会出现在执行拦截原因中；当前成交/拦截统计可在候选追踪里查看。'
  if (rule === '风控熔断') return '若账户已暂停交易，会出现在执行拦截原因中；当前未在本轮详情中看到熔断拦截。'
  return ''
}

function toggleScanDetail(s: any) {
  const idx = scanHistory.value.indexOf(s)
  if (selectedScanIdx.value === idx) {
    selectedScanIdx.value = -1
    scanTraceDetail.value = null
    return
  }
  selectedScanIdx.value = idx
  fetchScanTrace(s.scan_id || '')
}

// scanTraceCode accessed from inject, used in template via {{ scanTraceCode }}
// @ts-expect-error vue-tsc TS6133 false positive — used in template
const scanTraceCode = computed(() => unref((m as any).scanTraceCode))

// 挂载时自动加载日期数据(用于日期选择器高亮)
// 并自动选择最近有数据的日期加载扫描历史
// 【v2.9.97h-v14】优先选今天(如果今天有数据), 再 fallback 到 dates[0]
onMounted(async () => {
  const dates = await fetchScanTraceDates()
  if (!scanTraceDate.value && dates?.length) {
    // 先找今天(20260622 格式)
    const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' }).replace(/-/g, '')
    const bestDateObj = dates.find((d: any) => String(d.date || d) === todayStr)
    let bestDateStr: string
    if (bestDateObj) {
      // bestDateObj 是 {date, count, is_debug} 对象, 取 .date
      bestDateStr = bestDateObj.date || String(bestDateObj)
    } else {
      // dates[0] 同样可能是对象或字符串
      bestDateStr = dates[0]?.date || String(dates[0])
    }
    scanTraceDate.value = String(bestDateStr).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
    fetchScanHistory()
  }
})
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 顶部: 扫描历史列表(单行紧凑) -->
      <div class="st scan-trace-toolbar">
        <span class="st-title">📡 扫描历史</span>
        <button :class="['mode-toggle', scanTraceDebugMode ? 'debug' : 'prod']" @click="scanTraceDebugMode = !scanTraceDebugMode; fetchScanHistory()">
          {{ scanTraceDebugMode ? '调试审计模式' : '生产模式' }}
        </button>
        <span class="scan-trace-help">当前显示实盘有效扫描；点小时行展开查看每轮漏斗、成交和拦截。</span>
        <div class="scan-date-actions">
          <span class="scan-debug-hint">排查盘前/非交易记录时切换调试模式</span>
          <UnifiedDateBar @change="(_d: string) => { scanTraceDate = _d; fetchScanHistory() }" />
          <ElButton size="small" @click="fetchScanHistory" :loading="scanHistoryLoading">🔄</ElButton>
        </div>
      </div>
      <div v-if="!scanTraceDate" class="empty" style="padding:12px 0;color:var(--text-tertiary)">📅 请在上方选择日期查看扫描记录（高亮日期有数据）</div>
      <div v-else-if="scanHistoryLoading" class="empty" style="padding:8px 0">加载中...</div>
      <div v-else-if="!scanHistory.length" class="empty" style="padding:8px 0">该日暂无扫描记录</div>
      <div v-else>
        <div style="font-size:12px;color:var(--el-color-primary);font-weight:600;margin-bottom:4px">📅 {{ scanTraceDate }} 的扫描记录（共{{ scanHistory.length }}条）</div>
        <div class="scan-readme">
          <span><b>小时行</b>：汇总该小时所有扫描，显示“扫描次数 / 通过候选 / 实际成交 / 执行拦截”。</span>
          <span><b>单次扫描</b>：分为“全市场主扫”和“异动快扫”。一万多条是策略展开记录，不等于股票数；几十条通常是盘中异动候选池快扫。🚫 表示通过筛选后又被仓位、资金、熔断等执行规则挡住。</span>
          <span><b>查看明细</b>：点某个时间 chip 后，下方会展开扫描漏斗和候选追踪。</span>
        </div>
        <!-- 【v2.9.95】全天执行摘要横幅 -->
        <div v-if="execSummaryDisplay" class="exec-summary-banner">
          <div class="es-main">
            <span class="es-label">今日执行</span>
            <span class="es-item es-buy">{{ execSummaryDisplay.buys }}成交</span>
            <span class="es-item es-block">{{ execSummaryDisplay.blocked }}拦截</span>
            <button v-if="execSummaryDisplay.reasons.length" class="es-toggle" @click="showSummaryReasons = !showSummaryReasons">
              {{ showSummaryReasons ? '收起拦截分析' : `查看完整拦截分析（${execSummaryDisplay.reasons.length}类）` }}
            </button>
          </div>
          <div v-if="showSummaryReasons && execSummaryDisplay.reasons.length" class="es-analysis">
            <div class="es-distribution">
              <div class="es-pie" :style="execSummaryDisplay.pieStyle"><span>{{ execSummaryDisplay.blocked }}<em>拦截</em></span></div>
              <div class="es-group-grid">
                <button v-for="g in execSummaryDisplay.groups" :key="g.label" class="es-group-card" :class="{ active: expandedReasonGroup === g.label }" :style="{ '--group-color': g.color }" @click="expandedReasonGroup = expandedReasonGroup === g.label ? '' : g.label">
                  <span class="es-group-dot"></span>
                  <span class="es-group-name">{{ g.label }}</span>
                  <span class="es-group-count">{{ g.count }}次</span>
                  <span class="es-group-pct">{{ Number(g.pct ?? 0).toFixed(0) }}%</span>
                </button>
              </div>
            </div>
            <div v-if="expandedReasonGroup" class="es-reason-table">
              <div class="es-reason-table-title">{{ expandedReasonGroup }}明细</div>
              <div v-for="r in execSummaryDisplay.groups.find((g: any) => g.label === expandedReasonGroup)?.reasons || []" :key="r.reason" class="es-reason-row" :title="r.examples?.length ? `原始样例：\n${r.examples.join('\n')}` : r.reason">
                <span class="es-reason-name">{{ shortReason(r.reason) }}</span>
                <div class="es-reason-bar"><div class="es-reason-fill" :style="{ width: Math.max(3, r.pct) + '%' }"></div></div>
                <span class="es-reason-num">{{ r.count }}次</span>
                <span class="es-reason-pct">{{ Number(r.pct ?? 0).toFixed(1) }}%</span>
              </div>
            </div>
            <div v-else class="es-detail-hint">
              点击上方分类卡片查看该类全部执行拦截原因。图中只包含今日执行阶段实际触发过的拦截。
              排序淘汰在选中某条扫描后，看下面的“扫描漏斗”或点这里：
              <button class="es-inline-link" @click="switchScanTraceFilter('summary')" :disabled="!scanTraceDetail">打开筛选统计</button>
            </div>
            <details v-if="inactiveBlockRules.length" class="es-rule-catalog">
              <summary>今日未触发的执行/系统闸门规则（{{ inactiveBlockRules.length }}类）</summary>
              <div class="es-rule-grid">
                <div v-for="g in inactiveBlockRules" :key="g.category" class="es-rule-card" :style="{ '--group-color': g.color }">
                  <span class="es-rule-title"><i></i>{{ g.category }}</span>
                  <div v-if="g.category === '情绪风控'" class="es-rule-detail-list">
                    <div v-for="rule in g.rules" :key="rule" class="es-rule-detail-item">
                      <b>{{ rule }}</b>
                      <span>{{ emotionRiskTrigger(rule) }}</span>
                      <em>{{ emotionRiskState(rule) }}</em>
                    </div>
                  </div>
                  <span v-else class="es-rule-list">{{ g.rules.join('、') }}</span>
                </div>
              </div>
            </details>
          </div>
        </div>
        <div class="scan-hours">
          <div v-for="(group, gi) in scanHistoryByHour" :key="gi" class="sc-hour-group">
            <div class="sc-hour-header" :class="{ 'has-buy': group.items.reduce((a:any,s:any) => a + (s.exec?.bought || 0), 0) > 0 }" @click="toggleScanHour(group.hour)">
              <span class="sc-hour-toggle">{{ group.collapsed ? '▶' : '▽' }}</span>
              <span class="sc-hour-label">{{ group.hour }}:00</span>
              <span class="sc-hour-count">{{ group.items.length }}轮</span>
              <span class="sc-hour-types">{{ scanHourTypeSummary(group.items) }}</span>
              <span class="sc-hour-summary">{{ group.items.reduce((a:any,s:any) => a + (s.summary?.passed || 0), 0) }}通过 → <b>{{ group.items.reduce((a:any,s:any) => a + (s.exec?.bought || 0), 0) }}成交</b> · {{ group.items.reduce((a:any,s:any) => a + (s.exec?.blocked || 0), 0) }}拦截</span>
            </div>
            <div v-show="!group.collapsed" class="scan-strip">
              <div v-for="(s, i) in group.items" :key="group.hour + '-' + i" class="scan-chip" :class="{ active: selectedScanIdx === scanHistory.indexOf(s), debug: s.is_debug, 'has-buy': (s.exec?.bought || 0) > 0, full: scanKind(s) === 'full', quick: scanKind(s) === 'quick' }" @click="toggleScanDetail(s)">
                <span class="sc-time">{{ (s.scan_time || s.time || '').substring(11, 19) || '--:--' }}</span>
                <span class="sc-kind" :class="scanKind(s)">{{ scanKindLabel(s) }}</span>
                <span v-if="s.is_debug" class="sc-debug-tag">调试</span>
                <span class="sc-stats" :title="scanKindTitle(s)">
                  <span class="ss-all">{{ s.summary?.total_candidates || 0 }}</span><span class="ss-arr">▶</span><span class="ss-pass">{{ s.summary?.passed || 0 }}</span><span class="ss-arr">▶</span><span class="ss-buy" :class="(s.exec?.bought || 0) > 0 ? 'has-buy' : ''">{{ s.exec?.bought || 0 }}</span><span v-if="(s.exec?.blocked || 0) > 0" class="ss-block">🚫{{ s.exec?.blocked }}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="scanTraceDetail?.summary" class="scan-funnel">
        <div class="funnel-readme">
          <b>扫描漏斗读法</b>
          <span>每一行代表一层规则：左侧是层名，中间是“进入该层 → 通过该层”，右侧“淘汰N”表示这一层挡掉的候选。最后的“成交/执行拦截”是通过筛选后是否真正买入。</span>
        </div>
        <template v-for="(layerData, layerName) in scanTraceDetail.summary" :key="layerName">
          <div v-if="String(layerName) !== 'total_candidates' && String(layerName) !== 'passed' && String(layerName) !== 'rejected' && layerData && typeof layerData === 'object'" class="fn-row" :class="{ 'fn-filter': layerData.rejected > 0, 'fn-pass': !layerData.rejected && (layerData.input || 0) > 0 }">
            <span class="fn-tag">{{ layerLabel(layerName) }}</span>
            <span class="fn-flow">{{ (layerData.input || 0) === 0 && (layerData.output || 0) === 0 && !layerData.rejected ? '—' : (layerData.input || 0) + '→' + (layerData.output || 0) }}</span>
            <span v-if="layerData.rejected" class="fn-rej">淘汰{{ layerData.rejected }}</span>
            <span class="fn-desc">{{ scanTraceDetail.layer_details?.[layerName] || layerDesc(layerName, layerData) || '' }}</span>
          </div>
        </template>
        <div v-if="scanTraceDetail?._pagination" class="fn-total">✅ 通过{{ scanTraceDetail._pagination.passed_count }} / 💰 成交{{ scanTraceDetail._pagination.bought_count || 0 }} / 🚫 执行拦截{{ scanTraceDetail._pagination.blocked_count || 0 }} / ❌ 淘汰{{ scanTraceDetail._pagination.rejected_count }}</div>
      </div>

      <!-- 底部: 候选追踪(主区域) -->
      <div v-if="scanTraceDetail" style="margin-top:8px">
        <div class="st" style="display:flex;align-items:center;gap:8px">
          <span>🎯 候选追踪</span>
          <span class="candidate-readme">通过候选=进入买入池；成交候选=真实买入；淘汰候选=筛选阶段被挡住；统计=按层汇总。</span>
          <div style="display:flex;gap:4px;margin-left:auto">
            <button :class="['tab-btn-sm', scanTraceFilter === 'passed' ? 'active' : '']" @click="switchScanTraceFilter('passed')" :disabled="scanTraceLoadingMore">✅ 通过候选({{ scanTraceDetail._pagination?.passed_count || 0 }})</button>
            <button :class="['tab-btn-sm', scanTraceFilter === 'bought' ? 'active buy' : '']" @click="switchScanTraceFilter('bought')" :disabled="scanTraceLoadingMore">💰 成交候选({{ scanTraceDetail._pagination?.bought_count || 0 }})</button>
            <button :class="['tab-btn-sm', scanTraceFilter === 'rejected' ? 'active' : '']" @click="switchScanTraceFilter('rejected')" :disabled="scanTraceLoadingMore">❌ 淘汰候选({{ scanTraceDetail._pagination?.rejected_count || 0 }})</button>
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
            <div v-for="sig in scanTraceDetail.candidates || []" :key="sig.ts_code + sig.strategy" class="et-item" :class="[sig.final_status === 'passed' ? 'et-pass' : 'et-fail', sig.execution_status ? 'et-' + sig.execution_status : '']">
              <!-- 【v2.9.95c】两行布局: 上行=股票信息, 下行=执行状态 -->
              <div class="et-row1">
                <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid et-strategy" effect="dark">{{ strategyCN(sig.strategy) }}</ElTag>
                <span class="et-code">{{ sig.ts_code }}</span>
                <span class="et-name">{{ sig.stock_name || '-' }}</span>
                <span class="et-pct" :class="(Number(sig.pct_chg) || 0) >= 0 ? 'up' : 'down'">{{ (Number(sig.pct_chg) || 0) >= 0 ? '+' : '' }}{{ Number(sig.pct_chg ?? 0).toFixed(2) }}%</span>
                <span v-if="sig.price" class="et-price">¥{{ Number(sig.price).toFixed(2) }}</span>
              </div>
              <div class="et-row2">
                <span v-if="sig.execution_status === 'bought'" class="et-exec et-bought">
                  <span class="et-icon">✅</span><span class="et-text">已成交 · {{ sig.execution_desc || '买入成功' }}</span>
                </span>
                <span v-else-if="sig.execution_status === 'blocked'" class="et-exec et-blocked">
                  <span class="et-icon">🚫</span><span class="et-text">未成交 · {{ sig.execution_desc || '被拦截' }}</span>
                </span>
                <span v-else-if="sig.execution_status === 'pending'" class="et-exec et-pending">
                  <span class="et-icon">⏳</span><span class="et-text">未触发 · {{ sig.execution_desc || '通过筛选但未买入' }}</span>
                </span>
                <span v-else-if="sig.final_status === 'passed'" class="et-exec et-pending">
                  <span class="et-icon">✅</span><span class="et-text">通过筛选</span>
                </span>
                <span v-else class="et-exec et-rejected">
                  <span class="et-icon">❌</span><span class="et-text">被淘汰于第{{ String(sig.rejection_layer || '?').replace(/^L/, 'L') }}层 · {{ rejectionLayerCN(String(sig.rejection_layer)) || sig.rejection_layer }}<span v-if="sig.rejection_reason"> · {{ sig.rejection_reason }}</span></span>
                </span>
              </div>
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
.scan-trace-toolbar { display: flex; align-items: center; gap: 8px; }
.scan-trace-toolbar .st-title { flex-shrink: 0; }
.scan-trace-help { color: var(--text-tertiary); font-size: 11px; }
.scan-date-actions { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; }
.scan-debug-hint { color: var(--text-tertiary); font-size: 11px; opacity: 0.8; }

.tab-btn-sm.active.buy { background: rgba(245,108,108,0.12); color: var(--stock-up, #f56c6c); border-color: rgba(245,108,108,0.45); }

.scan-readme, .funnel-readme { display: flex; flex-wrap: wrap; gap: 6px 12px; padding: 6px 8px; margin-bottom: 6px; border-radius: 7px; background: rgba(64,158,255,0.06); border: 1px solid rgba(64,158,255,0.14); color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.scan-readme b, .funnel-readme b { color: var(--text-primary); }
.funnel-readme { margin-bottom: 8px; background: rgba(103,194,58,0.055); border-color: rgba(103,194,58,0.15); }
.funnel-readme span { color: var(--text-secondary); }
.candidate-readme { color: var(--text-tertiary); font-size: 11px; }

.scan-hours { display: flex; flex-direction: column; gap: 4px; }

.sc-hour-group { margin-bottom: 2px; }

.sc-hour-header { display: flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; background: var(--bg-elevated); border: 1px solid var(--border-default); }

.sc-hour-header:hover { background: var(--bg-hover); }
.sc-hour-header.has-buy { background: rgba(230, 162, 60, 0.16); border-color: rgba(230, 162, 60, 0.75); box-shadow: 0 0 0 1px rgba(230, 162, 60, 0.12) inset; }
.sc-hour-header.has-buy:hover { background: rgba(230, 162, 60, 0.24); border-color: #e6a23c; }

.sc-hour-toggle { font-size: 9px; color: var(--text-tertiary); }

.sc-hour-label { font-weight: 600; color: var(--text-primary); }

.sc-hour-count { color: var(--text-tertiary); font-size: 10px; }
.sc-hour-types { color: var(--text-secondary); font-size: 10px; background: var(--bg-muted); padding: 1px 6px; border-radius: 999px; }

.sc-hour-summary { color: var(--el-color-primary); font-size: 10px; margin-left: auto; }
.sc-hour-header.has-buy .sc-hour-summary b { color: #e6a23c; font-weight: 800; }

.scan-strip { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0 0 16px; }

.scan-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; border: 1px solid var(--border-default); background: var(--bg-elevated); transition: all 0.15s; }

.scan-chip:hover { background: var(--bg-hover); border-color: var(--el-color-primary-light-5); }

.scan-chip.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary); }

.scan-chip.has-buy { background: rgba(230, 162, 60, 0.22); border-color: rgba(230, 162, 60, 0.75); box-shadow: 0 0 0 1px rgba(230, 162, 60, 0.18) inset; }
.scan-chip.has-buy:hover { background: rgba(230, 162, 60, 0.32); border-color: #e6a23c; }
.scan-chip.has-buy.active { background: rgba(230, 162, 60, 0.38); border-color: #e6a23c; box-shadow: 0 0 0 2px rgba(230, 162, 60, 0.22) inset; }
.scan-chip.full { border-left: 3px solid var(--el-color-primary); }
.scan-chip.quick { border-left: 3px solid #67c23a; }

.sc-time { color: var(--text-tertiary); font-family: 'JetBrains Mono', monospace; }
.sc-kind { font-size: 10px; padding: 1px 5px; border-radius: 999px; background: var(--bg-muted); color: var(--text-secondary); }
.sc-kind.full { background: rgba(64,158,255,.12); color: var(--el-color-primary); }
.sc-kind.quick { background: rgba(103,194,58,.12); color: #67c23a; }
.sc-kind.blocked { background: rgba(245,108,108,.12); color: #f56c6c; }

.sc-stats { display: inline-flex; align-items: center; gap: 2px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }

.ss-all { color: var(--text-tertiary); font-size: 10px; }

.ss-arr { color: var(--text-tertiary); font-size: 9px; margin: 0 1px; }

.ss-pass { color: var(--el-color-primary); font-weight: 600; }

.ss-buy { color: var(--text-tertiary); font-weight: 600; }

.ss-buy.has-buy { color: #b77900; background: rgba(255, 255, 255, 0.55); border-radius: 4px; padding: 0 3px; }

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

.et-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 4px; }

/* 【v2.9.95c】候选追踪卡片: 两行布局，股票信息 + 执行状态 */
.et-item { display: flex; flex-direction: column; gap: 3px; padding: 6px 10px; font-size: 12px; border-radius: 5px; border: 1px solid transparent; transition: background 0.15s; }
.et-item:hover { background: var(--bg-hover); }
.et-item.et-pass { background: rgba(0,180,42,0.04); border-color: rgba(0,180,42,0.15); }
.et-item.et-fail { background: rgba(245,63,63,0.03); border-color: rgba(245,63,63,0.12); opacity: 0.85; }
.et-item.et-bought { background: rgba(230,162,60,0.18); border-color: rgba(230,162,60,0.75); border-left: 4px solid #e6a23c; box-shadow: 0 0 0 1px rgba(230,162,60,0.12) inset; }
.et-item.et-blocked { background: rgba(230,162,60,0.06); border-color: rgba(230,162,60,0.2); }

.et-row1 { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; }
.et-row2 { padding-left: 4px; }
.et-strategy { font-size: 10px !important; min-width: 56px; padding: 0 4px !important; height: 18px !important; line-height: 18px !important; flex-shrink: 0; }
.et-code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 11px; color: var(--text-secondary); flex-shrink: 0; }
.et-name { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.et-pct { font-weight: 700; flex-shrink: 0; min-width: 56px; text-align: right; }
.et-pct.up { color: var(--stock-up, #f56c6c); }
.et-pct.down { color: var(--stock-down, #67c23a); }
.et-price { font-size: 11px; color: var(--text-tertiary); flex-shrink: 0; }

.et-exec { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; line-height: 1.4; }
.et-exec .et-icon { flex-shrink: 0; }
.et-exec .et-text { color: var(--text-primary); }
.et-exec.et-bought .et-text { color: #b77900; font-weight: 700; }
.et-exec.et-blocked .et-text { color: #e6a23c; font-weight: 500; }
.et-exec.et-pending .et-text { color: var(--text-secondary); }
.et-exec.et-rejected .et-text { color: var(--text-tertiary); }

.et-ok { color: var(--stock-up); flex-shrink: 0; }

.et-no { color: var(--stock-down); font-size: 9px; flex-shrink: 0; }

.rejected-stats { padding: 8px 0; }

.rs-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }

.rs-label { min-width: 72px; color: var(--text-secondary); }

.rs-bar-track { flex: 1; height: 16px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }

.rs-bar-fill { height: 100%; background: rgba(245,63,63,0.25); border-radius: 3px; transition: width 0.3s; }

.rs-count { min-width: 40px; text-align: right; font-weight: 600; }

.load-more-hint { text-align: center; padding: 8px 0; }

/* ========== v2.9.95 执行摘要 + 状态标签 ========== */
.exec-summary-banner {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px 10px;
  margin-bottom: 6px;
  border-radius: 6px;
  font-size: 11px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}
.es-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.es-label { font-weight: 600; color: var(--text-secondary); }
.es-item { font-weight: 700; }
.es-buy { color: var(--stock-up, #f56c6c); }
.es-block { color: #e6a23c; }
.es-toggle { border: 1px solid rgba(108,140,255,0.28); background: rgba(108,140,255,0.09); color: #6c8cff; border-radius: 999px; padding: 2px 9px; font-size: 11px; cursor: pointer; margin-left: auto; }
.es-toggle:hover { background: rgba(108,140,255,0.15); border-color: rgba(108,140,255,0.45); }
.es-analysis { display: flex; flex-direction: column; gap: 8px; padding-top: 2px; }
.es-distribution { display: grid; grid-template-columns: 112px 1fr; gap: 10px; align-items: center; }
.es-pie { width: 92px; height: 92px; border-radius: 50%; margin: 0 auto; display: grid; place-items: center; box-shadow: inset 0 0 0 12px rgba(255,255,255,0.18); }
.es-pie span { width: 54px; height: 54px; border-radius: 50%; background: var(--bg-elevated); display: flex; flex-direction: column; align-items: center; justify-content: center; font-weight: 800; color: var(--text-primary); border: 1px solid var(--border-light); }
.es-pie em { font-style: normal; font-size: 10px; color: var(--text-tertiary); font-weight: 500; }
.es-group-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 6px; }
.es-group-card { --group-color: #6c8cff; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 2px 6px; padding: 6px 8px; border-radius: 8px; background: color-mix(in srgb, var(--group-color) 10%, var(--bg-secondary)); border: 1px solid color-mix(in srgb, var(--group-color) 28%, transparent); cursor: pointer; text-align: left; color: var(--text-primary); }
.es-group-card:hover, .es-group-card.active { background: color-mix(in srgb, var(--group-color) 16%, var(--bg-secondary)); border-color: color-mix(in srgb, var(--group-color) 55%, transparent); }
.es-group-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--group-color); }
.es-group-name { font-weight: 700; color: var(--text-primary); }
.es-group-count { font-weight: 800; color: var(--group-color); }
.es-group-pct { grid-column: 2 / -1; color: var(--text-tertiary); font-size: 10px; }
.es-reason-table { display: flex; flex-direction: column; gap: 4px; max-height: 260px; overflow-y: auto; padding-right: 2px; }
.es-reason-table-title { font-weight: 700; color: var(--text-primary); margin: 2px 0; }
.es-reason-row { display: grid; grid-template-columns: minmax(150px, 1.8fr) minmax(120px, 2fr) 48px 48px; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 5px; background: var(--bg-secondary); border: 1px solid var(--border-light); }
.es-reason-name { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--text-secondary); }
.es-reason-bar { height: 8px; border-radius: 999px; overflow: hidden; background: var(--bg-hover); }
.es-reason-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, rgba(230,162,60,0.45), rgba(230,162,60,0.9)); }
.es-reason-num { text-align: right; color: #e6a23c; font-weight: 800; }
.es-reason-pct { text-align: right; color: var(--text-tertiary); font-size: 10px; }
.es-detail-hint { color: var(--text-tertiary); font-size: 11px; padding: 4px 2px; }
.es-rule-catalog { margin-top: 2px; color: var(--text-secondary); }
.es-rule-catalog summary { cursor: pointer; font-size: 11px; color: var(--text-tertiary); user-select: none; }
.es-rule-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 6px; margin-top: 6px; }
.es-rule-card { --group-color: #a8abb2; padding: 6px 8px; border-radius: 7px; background: color-mix(in srgb, var(--group-color) 7%, var(--bg-secondary)); border: 1px dashed color-mix(in srgb, var(--group-color) 28%, transparent); }
.es-rule-title { display: flex; align-items: center; gap: 5px; font-weight: 700; color: var(--text-primary); margin-bottom: 3px; }
.es-rule-title i { width: 7px; height: 7px; border-radius: 50%; background: var(--group-color); }
.es-rule-list { font-size: 10px; color: var(--text-tertiary); line-height: 1.5; }
.es-inline-link { margin-left: 4px; border: 1px solid rgba(108,140,255,0.28); background: rgba(108,140,255,0.08); color: #6c8cff; border-radius: 999px; padding: 1px 7px; font-size: 10px; cursor: pointer; }
.es-inline-link:disabled { opacity: 0.45; cursor: not-allowed; }
.es-rule-detail-list { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.es-rule-detail-item { display: grid; gap: 2px; padding: 5px 6px; border-radius: 6px; background: rgba(255,255,255,0.035); }
.es-rule-detail-item b { color: var(--text-primary); font-size: 11px; }
.es-rule-detail-item span { color: var(--text-secondary); font-size: 10px; line-height: 1.45; }
.es-rule-detail-item em { color: var(--text-tertiary); font-style: normal; font-size: 10px; line-height: 1.45; }
.ss-block { color: #e6a23c; font-size: 10px; font-weight: 600; margin-left: 2px; }
.et-exec { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; flex-shrink: 0; font-weight: 500; }
/* 老样式保留作为 fallback (.et-bought/.et-blocked/.et-pending 类名在有些地方还被调用) */

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
.mode-toggle {
  margin-left: 6px;
  padding: 3px 8px;
  border-radius: 10px;
  border: 1px solid var(--border-secondary);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}
.mode-toggle.prod { border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); }
.mode-toggle.debug { border-color: #e6a23c; color: #e6a23c; background: rgba(230, 162, 60, 0.08); }

</style>
