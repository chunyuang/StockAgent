<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useSignalTrace, PIPELINE_LAYERS, FLOW_LAYERS } from './useSignalTrace'
import { ElCard, ElSelect, ElOption, ElButton, ElEmpty, ElTooltip } from 'element-plus'
import { Refresh, CaretRight, CaretBottom } from '@element-plus/icons-vue'
import UnifiedDateBar from '@/components/UnifiedDateBar.vue'

const trace = useSignalTrace()
const dateValue = ref('')
function onDateChange(d: string) { trace.fetchSignalTrace(d) }
onMounted(() => { trace.fetchSignalTrace() })

const showAll = ref(false)
const expandedRow = ref('')
const flowFilterLayer = ref('all')

function strategyCN(s: string): string {
  const m: Record<string, string> = { halfway_chase: '半路追涨', first_limit_up: '首板打板', limit_up_open: '涨停开板', dragon_head: '龙头低吸', limit_down_qiao: '跌停翘板', anomaly_strong: '强势涨停', anomaly_surge: '放量异动' }
  return m[s] || s
}
function strategyColor(s: string): string {
  const m: Record<string, string> = { halfway_chase: '#e6a23c', first_limit_up: '#f56c6c', limit_up_open: '#f56c6c', dragon_head: '#409eff', limit_down_qiao: '#909399', anomaly_strong: '#67c23a', anomaly_surge: '#67c23a' }
  return m[s] || '#909399'
}

function getFactorDetails(stock: any) {
  const f = stock.factors || {}
  const mv = (f.circ_mv || 0) / 10000, pb = (f.pullback_pct || 0) * 100, opPct = f.opening_pct_chg || 0
  return [
    { label: '涨幅', value: `${f.pct_chg?.toFixed(1)||'-'}%`, cls: (f.pct_chg||0)>0?'up':'down' },
    { label: '量比', value: `${f.volume_ratio?.toFixed(1)||'-'}x`, cls: (f.volume_ratio||0)>5?'warn':'' },
    { label: '换手率', value: `${f.turnover_rate?.toFixed(1)||'-'}%`, cls: (f.turnover_rate||0)>5?'warn':'' },
    { label: '流通市值', value: `${mv.toFixed(0)}亿` },
    { label: 'MA5偏离', value: `${pb.toFixed(1)}%`, cls: pb<-3?'down':'' },
    { label: 'RSI6', value: `${f.rsi_6?.toFixed(0)||'-'}`, cls: (f.rsi_6||50)>80?'warn':'' },
    { label: '开盘涨幅', value: `${opPct.toFixed(1)}%`, cls: opPct>2?'warn':opPct<0?'up':'', desc: opPct>2?'高开追高风险':opPct<-1?'低开冲高较优':'' },
    { label: '恐贪指数', value: f.fear_greed_index!=null?f.fear_greed_index.toFixed(1):'-', cls: (f.fear_greed_index||5)<3?'up':'' },
    { label: '开盘价', value: `¥${f.open?.toFixed(2)||'-'}` }, { label: '最高价', value: `¥${f.high?.toFixed(2)||'-'}` },
    { label: '最低价', value: `¥${f.low?.toFixed(2)||'-'}` }, { label: '昨收价', value: `¥${f.pre_close?.toFixed(2)||'-'}` },
    { label: 'MA5', value: `¥${f.ma5?.toFixed(2)||'-'}` }, { label: 'ATR', value: f.atr?.toFixed(2)||'-' },
    { label: 'MACD', value: f.macd?.toFixed(3)||'-' }, { label: '连板数', value: `${f.limit_up_count||0}` },
    { label: '是否涨停', value: f.is_limit_up?'是':'否' },
  ].filter(i => i.value && i.value!=='¥-' && i.value!=='-')
}

function clickFilterLayer(l: string) { trace.filterLayer.value = trace.filterLayer.value===l?'all':l }
function clickFilterResult(r: string) { trace.filterResult.value = trace.filterResult.value===r?'all':r }

interface FlowCell { status: 'pass'|'reject'|'skip'|'none'; reason: string; layerKey: string; layerLabel: string }

const mainRows = computed(() => {
  const base = trace.filteredStockTraces.value
  const src = flowFilterLayer.value==='all' ? base : base.filter(s => flowFilterLayer.value==='execution'?s.rejectionType==='execution':s.rejectionLayer===flowFilterLayer.value)
  return src.map(stock => {
    const cells: FlowCell[] = [], lr = stock.layerResults||{}
    let stopped = false
    for (const layer of FLOW_LAYERS) {
      if (stopped) { cells.push({status:'none',reason:'',layerKey:layer.key,layerLabel:layer.label}); continue }
      if (layer.key==='execution') {
        if (stock.finalStatus==='bought') cells.push({status:'pass',reason:stock.executionDesc||'成交',layerKey:'execution',layerLabel:'执行结果'})
        else if (stock.rejectionType==='execution') { cells.push({status:'reject',reason:stock.rejectionReason||stock.executionDesc||'',layerKey:'execution',layerLabel:'执行结果'}); stopped=true }
        else if (stock.executionStatus==='pending') { cells.push({status:'skip',reason:stock.executionDesc||'待执行',layerKey:'execution',layerLabel:'执行结果'}); stopped=true }
        else cells.push({status:'none',reason:'',layerKey:'execution',layerLabel:'执行结果'})
        continue
      }
      const result = lr[layer.key]
      if (!result) { cells.push({status:'skip',reason:'',layerKey:layer.key,layerLabel:layer.label}); continue }
      if (result.passed===false) { cells.push({status:'reject',reason:result.reason||'',layerKey:layer.key,layerLabel:layer.label}); stopped=true }
      else cells.push({status:'pass',reason:result.reason||'',layerKey:layer.key,layerLabel:layer.label})
    }
    return { stock, cells }
  })
})
const displayRows = computed(() => showAll.value ? mainRows.value : mainRows.value.slice(0,15))

const funnelRows = computed(() => {
  const s = trace.summary.value, lc = s.layerCounts||{}, maxVal = Math.max(s.total,1)
  const rows: any[] = [
    {layer:'',icon:'🎯',label:'策略筛选',val:s.total,cls:'total',barPct:100},
    ...PIPELINE_LAYERS.filter(l=>l.key!=='L9_execute').map(l=>{const v=lc[l.key]||0;return{layer:l.key,icon:l.icon,label:l.label,val:v,barPct:Math.round(v/maxVal*100),pct:v>0?`${Math.round(v/maxVal*100)}%`:''}}),
    {layer:'',icon:'✅',label:'通过管道',val:s.bought+s.passedNotBought,cls:'passed',barPct:Math.round((s.bought+s.passedNotBought)/maxVal*100),pct:s.total>0?`${Math.round((s.bought+s.passedNotBought)/s.total*100)}%`:''},
    {layer:'execution',icon:'📋',label:'未成交',val:s.passedNotBought,barPct:Math.round(s.passedNotBought/maxVal*100)},
    {layer:'',icon:'💵',label:'成交',val:s.bought,cls:'final',barPct:Math.round(s.bought/maxVal*100),pct:s.total>0?`${Math.round(s.bought/s.total*100)}%`:''},
  ]
  return rows.filter(r=>r.val>0||r.cls==='total'||r.cls==='passed'||r.cls==='final'||r.layer==='execution')
})

function barHeight(v:number,m:number):number{return !m||!v?2:Math.max(2,Math.round(v/m*48))}

// 评分排行(独立于主表格, 快速看高分股)
const rankShowAll = ref(false)
const rankedList = computed(() => {
  const list = [...trace.filteredStockTraces.value].filter(s=>s.score>0).sort((a,b)=>(b.score||0)-(a.score||0))
  return rankShowAll.value ? list : list.slice(0,10)
})
const rankedListFull = computed(() => trace.filteredStockTraces.value.filter(s=>s.score>0).length)
</script>

<template>
  <div class="signal-trace-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <UnifiedDateBar v-model="dateValue" @change="onDateChange" />
        <ElButton :icon="Refresh" size="small" @click="trace.fetchSignalTrace()" :loading="trace.loading.value">刷新</ElButton>
        <span class="toolbar-hint" v-if="trace.filteredStockTraces.value.length!==trace.stockTraces.value.length">
          筛选: {{trace.filteredStockTraces.value.length}}/{{trace.stockTraces.value.length}}
          <ElButton size="small" link type="primary" @click="trace.filterLayer.value='all';trace.filterResult.value='all';trace.filterStrategy.value='all';trace.filterScore.value='all';trace.filterCap.value='all'">清除</ElButton>
        </span>
      </div>
      <div class="toolbar-right">
        <ElSelect v-model="trace.filterStrategy.value" size="small" style="width:130px" clearable placeholder="全部策略">
          <ElOption value="all" label="全部策略" /><ElOption v-for="s in trace.strategyList.value" :key="s" :value="s" :label="strategyCN(s)" />
        </ElSelect>
        <ElSelect v-model="trace.filterResult.value" size="small" style="width:110px">
          <ElOption value="all" label="全部状态" /><ElOption value="bought" label="💰 成交" /><ElOption value="passed" label="📋 未成交" /><ElOption value="rejected" label="❌ 被拦" />
        </ElSelect>
        <ElSelect v-model="trace.filterScore.value" size="small" style="width:130px" clearable placeholder="评分区间">
          <ElOption value="all" label="全部评分" /><ElOption value="high" label="🟢 ≥70 建议" /><ElOption value="mid" label="🟡 50-69 观察" /><ElOption value="low" label="🔴 <50 不建议" />
        </ElSelect>
        <ElSelect v-model="trace.filterCap.value" size="small" style="width:120px" clearable placeholder="市值">
          <ElOption value="all" label="全部市值" /><ElOption value="small" label="<30亿 小盘" /><ElOption value="mid" label="30-100亿 中盘" /><ElOption value="large" label="100-300亿 大盘" /><ElOption value="mega" label="≥300亿 超大" />
        </ElSelect>
        <ElSelect v-model="trace.filterLayer.value" size="small" style="width:140px" clearable placeholder="全部层级">
          <ElOption v-for="l in trace.layerList" :key="l.key" :value="l.key" :label="l.label" />
        </ElSelect>
      </div>
    </div>

    <!-- KPI卡片行 -->
    <div class="kpi-row">
      <div class="kpi-card" @click="clickFilterResult('all')" :class="{active:!trace.filterResult.value||trace.filterResult.value==='all'}"><div class="kpi-value">{{trace.kpi.value.total}}</div><div class="kpi-label">候选</div></div>
      <div class="kpi-card bought" @click="clickFilterResult('bought')" :class="{active:trace.filterResult.value==='bought'}"><div class="kpi-value">{{trace.kpi.value.boughtCount}}</div><div class="kpi-label">💰 成交</div></div>
      <div class="kpi-card"><div class="kpi-value">{{trace.kpi.value.winRate?.toFixed(0) ?? '-'}}%</div><div class="kpi-label">胜率</div></div>
      <div class="kpi-card"><div class="kpi-value" :class="trace.kpi.value.avgPct>0?'up':'down'">{{trace.kpi.value.avgPct>0?'+':''}}{{trace.kpi.value.avgPct?.toFixed(1) ?? '-'}}%</div><div class="kpi-label">均涨幅</div></div>
      <div class="kpi-card"><div class="kpi-value">{{trace.kpi.value.avgVR?.toFixed(1) ?? '-'}}x</div><div class="kpi-label">均量比</div></div>
      <div class="kpi-card"><div class="kpi-value">{{trace.kpi.value.avgScore?.toFixed(0) ?? '-'}}</div><div class="kpi-label">均评分</div></div>
      <div class="kpi-card rejected" @click="clickFilterResult('rejected')" :class="{active:trace.filterResult.value==='rejected'}"><div class="kpi-value">{{trace.kpi.value.rejected}}</div><div class="kpi-label">❌ 被拦</div></div>
      <div class="kpi-card" v-if="trace.summary.value.maxLayer!=='-'"><div class="kpi-value clickable" @click="clickFilterLayer(trace.summary.value.maxLayerKey||'all')">{{trace.summary.value.maxLayer}}</div><div class="kpi-label">最大拦截</div></div>
    </div>

    <!-- 主表格 -->
    <!-- 评分排行 -->
    <ElCard shadow="never" class="rank-card">
      <template #header>
        <div class="card-header">
          <span>🏆 综合评分排行</span>
          <div class="header-right">
            <span class="header-hint">🟢≥70建议关注 · 🟡50-69观察 · 🔴<50不建议</span>
            <ElButton size="small" @click="rankShowAll=!rankShowAll">{{rankShowAll?'显示前10':'显示全部'}}<span v-if="!rankShowAll" class="rank-count">({{rankedListFull}}只)</span></ElButton>
          </div>
        </div>
      </template>
      <div class="rank-list" v-if="rankedList.length>0">
        <div v-for="(stock,i) in rankedList" :key="stock.tsCode+stock.strategy" class="rank-item" :class="'ri-'+stock.finalStatus">
          <div class="ri-rank" :class="i<3?'top3':''">{{i+1}}</div>
          <div class="ri-score"><span class="score-bar" :class="stock.score>=70?'high':stock.score>=50?'mid':'low'">{{stock.score}}</span></div>
          <div class="ri-stock"><span class="ri-code">{{stock.tsCode}}</span><span class="ri-name">{{stock.stockName}}</span></div>
          <div class="ri-strat"><span class="strat-tag" :style="{borderColor:strategyColor(stock.strategy),color:strategyColor(stock.strategy)}">{{strategyCN(stock.strategyName||stock.strategy)}}</span></div>
          <div class="ri-pct" :class="stock.pctChg>0?'up':'down'">{{stock.pctChg>0?'+':''}}{{stock.pctChg?.toFixed(1)}}%</div>
          <div class="ri-vr">{{stock.factors?.volume_ratio?.toFixed(1)||'-'}}x</div>
          <div class="ri-tr">{{stock.factors?.turnover_rate?.toFixed(1)||'-'}}%</div>
          <div class="ri-mv">{{((stock.factors?.circ_mv||0)/10000).toFixed(0)}}亿</div>
          <div class="ri-result">
            <span v-if="stock.finalStatus==='bought'" class="result-badge bought">💰 成交</span>
            <span v-else-if="stock.rejectionType==='execution'" class="result-badge exec-block">🛡 拦截</span>
            <span v-else class="result-badge rejected">✗ 被拦</span>
          </div>
          <div class="ri-reason">{{stock.rejectionReason||stock.executionDesc||'-'}}</div>
        </div>
      </div>
      <ElEmpty v-else description="暂无评分数据" :image-size="40" />
    </ElCard>

    <ElCard shadow="never" class="main-card">
      <template #header>
        <div class="card-header">
          <span>🏆 候选信号全链路追踪</span>
          <div class="header-right">
            <div class="header-legend">
              <span class="legend-item"><span class="lg pass">✓</span>通过</span>
              <span class="legend-item"><span class="lg reject">✗</span>拦截</span>
              <span class="legend-item"><span class="lg skip">·</span>未到达</span>
              <span class="legend-sep">|</span>
              <span class="legend-hint">🟢≥70建议 · 🟡50-69观察 · 🔴<50不建议 · 点击行展开 · 点击红格筛选</span>
            </div>
            <ElButton size="small" @click="showAll=!showAll">{{showAll?'显示前15':'显示全部'}}<span v-if="!showAll" class="rank-count">({{mainRows.length}}只)</span></ElButton>
          </div>
        </div>
      </template>
      <div class="main-table" v-if="displayRows.length>0">
        <div class="mt-header">
          <div class="mh-rank">#</div><div class="mh-score">评分</div><div class="mh-stock">股票</div><div class="mh-strat">策略</div><div class="mh-pct">涨幅</div><div class="mh-vr">量比</div><div class="mh-tr">换手</div><div class="mh-mv">市值</div>
          <div class="mh-pipeline">
            <div v-for="layer in FLOW_LAYERS" :key="layer.key" class="mh-cell" :class="{active:flowFilterLayer===layer.key}" @click="flowFilterLayer=flowFilterLayer===layer.key?'all':layer.key">
              <ElTooltip :content="layer.short+': '+layer.desc" placement="top"><span class="mh-label">{{layer.label}}</span></ElTooltip>
            </div>
          </div>
          <div class="mh-result">结果</div><div class="mh-reason">拦截原因</div>
        </div>
        <template v-for="({stock,cells},i) in displayRows" :key="stock.tsCode+'|'+stock.strategy">
          <div class="mt-row" :class="['row-'+stock.finalStatus,{expanded:expandedRow===stock.tsCode+'|'+stock.strategy}]" @click="expandedRow=expandedRow===stock.tsCode+'|'+stock.strategy?'':stock.tsCode+'|'+stock.strategy">
            <div class="mr-rank" :class="i<3?'top3':''">{{i+1}}</div>
            <div class="mr-score"><ElTooltip :content="`评分${stock.score}: 涨幅${stock.factors?.pct_chg?.toFixed(1)}% 量比${stock.factors?.volume_ratio?.toFixed(1)}x 换手${stock.factors?.turnover_rate?.toFixed(1)}% 市值${((stock.factors?.circ_mv||0)/10000).toFixed(0)}亿`" placement="top"><span class="score-bar" :class="stock.score>=70?'high':stock.score>=50?'mid':'low'">{{stock.score}}</span></ElTooltip></div>
            <div class="mr-stock"><component :is="expandedRow===stock.tsCode+'|'+stock.strategy?CaretBottom:CaretRight" class="expand-icon" /><span class="mr-code">{{stock.tsCode}}</span><span class="mr-name">{{stock.stockName}}</span></div>
            <div class="mr-strat"><span class="strat-tag" :style="{borderColor:strategyColor(stock.strategy),color:strategyColor(stock.strategy)}">{{strategyCN(stock.strategyName||stock.strategy)}}</span></div>
            <div class="mr-pct" :class="stock.pctChg>0?'up':'down'">{{stock.pctChg>0?'+':''}}{{stock.pctChg?.toFixed(1)}}%</div>
            <div class="mr-vr">{{stock.factors?.volume_ratio?.toFixed(1)||'-'}}</div>
            <div class="mr-tr">{{stock.factors?.turnover_rate?.toFixed(1)||'-'}}</div>
            <div class="mr-mv">{{((stock.factors?.circ_mv||0)/10000).toFixed(0)}}亿</div>
            <div class="mr-pipeline">
              <template v-for="(cell,ci) in cells" :key="ci">
                <ElTooltip v-if="cell.status!=='none'" :content="cell.layerLabel+(cell.reason?': '+cell.reason:(cell.status==='pass'?' — 通过':''))" placement="top" :show-after="200">
                  <div class="mr-cell" :class="cell.status" @click.stop="cell.status==='reject'&&(flowFilterLayer=flowFilterLayer===cell.layerKey?'all':cell.layerKey)">
                    <span v-if="cell.status==='pass'">✓</span><span v-else-if="cell.status==='reject'">✗</span><span v-else-if="cell.status==='skip'">·</span>
                  </div>
                </ElTooltip>
                <div v-else class="mr-cell none"></div>
              </template>
            </div>
            <div class="mr-result">
              <span v-if="stock.finalStatus==='bought'" class="result-badge bought">💰 成交</span>
              <span v-else-if="stock.executionStatus==='pending'" class="result-badge pending">👁 观察</span>
              <span v-else-if="stock.rejectionType==='execution'" class="result-badge exec-block">🛡 拦截</span>
              <span v-else class="result-badge rejected">✗ 被拦</span>
            </div>
            <div class="mr-reason">
              <template v-if="stock.finalStatus==='bought'"><span class="reason-bought">¥{{stock.boughtPrice?.toFixed(2)}} × {{stock.boughtShares}}股</span></template>
              <span v-else-if="stock.rejectionReason" class="reason-reject">{{stock.rejectionReason}}</span>
              <span v-else-if="stock.executionDesc" class="reason-exec">{{stock.executionDesc}}</span>
              <span v-else class="reason-dim">-</span>
            </div>
          </div>
          <!-- 展开详情 -->
          <div v-if="expandedRow===stock.tsCode+'|'+stock.strategy" class="row-detail">
            <div class="rd-section"><div class="rd-title">📊 因子详情</div><div class="rd-factors"><div class="rd-fact" v-for="fact in getFactorDetails(stock)" :key="fact.label"><span class="rd-fact-label">{{fact.label}}</span><span class="rd-fact-value" :class="fact.cls||''">{{fact.value}}</span><span v-if="fact.desc" class="rd-fact-desc">{{fact.desc}}</span></div></div></div>
            <div class="rd-section"><div class="rd-title">🔗 逐层追踪</div><div class="rd-pipeline"><div v-for="(cell,ci) in cells" :key="'p'+ci" class="rd-pipe-cell" v-if="cell.status!=='none'"><div class="rd-pipe-status" :class="cell.status">{{cell.status==='pass'?'✓':cell.status==='reject'?'✗':'·'}}</div><div class="rd-pipe-label">{{FLOW_LAYERS[ci]?.label||''}}</div><div v-if="cell.reason" class="rd-pipe-reason">{{cell.reason}}</div></div></div></div>
            <div class="rd-section" v-if="stock.executionDesc"><div class="rd-title">📝 执行信息</div><div class="rd-exec">{{stock.executionDesc}}</div></div>
            <div class="rd-section" v-if="stock.rejectionReason"><div class="rd-title">🚫 拦截原因</div><div class="rd-reject">{{stock.rejectionReason}}</div></div>
            <div class="rd-section" v-if="stock.reason"><div class="rd-title">📋 信号描述</div><div class="rd-signal">{{stock.reason}}</div></div>
          </div>
        </template>
      </div>
      <ElEmpty v-else description="暂无候选数据" :image-size="60" />
    </ElCard>

    <!-- 底部 -->
    <div class="bottom-row">
      <ElCard shadow="never" class="funnel-card">
        <template #header><div class="card-header"><span>📊 漏斗概览</span><span class="header-hint">点击筛选</span></div></template>
        <div class="funnel-body" v-if="trace.scanTraces.value.length>0">
          <div v-for="row in funnelRows" :key="row.label" class="funnel-row" :class="[row.cls||'',{clickable:!!row.layer,active:trace.filterLayer.value===row.layer}]" @click="row.layer&&clickFilterLayer(row.layer)">
            <div class="fn-left"><span class="fn-icon">{{row.icon}}</span><span class="fn-label">{{row.label}}</span></div>
            <div class="fn-right"><div class="fn-bar-wrap"><div class="fn-bar" :class="row.cls||''" :style="{width:row.barPct+'%'}" /></div><span class="fn-count" :class="{zero:row.val===0}">{{row.val}}</span><span class="fn-pct" v-if="row.pct">{{row.pct}}</span></div>
          </div>
        </div>
        <ElEmpty v-else description="暂无数据" :image-size="40" />
      </ElCard>
      <ElCard shadow="never" class="timeline-card">
        <template #header><span>🕐 时间线</span></template>
        <div class="timeline-body" v-if="trace.timelineNodes.value.length>0">
          <div v-for="slot in trace.timelineNodes.value" :key="slot.label" class="tl-slot">
            <div class="tl-slot-header"><span class="tl-slot-tag" :class="slot.type">{{slot.label}}</span><span class="tl-slot-range">{{slot.range}}</span><span class="tl-slot-stats"><span class="tl-ss-cand">{{slot.totalCand}}</span>→<span class="tl-ss-pass">{{slot.totalPassed}}</span><span v-if="slot.totalBuys>0" class="tl-ss-buy">💰{{slot.totalBuys}}</span></span></div>
            <div class="tl-bars">
              <div v-for="node in slot.nodes" :key="node.time" class="tl-bar-group">
                <ElTooltip :content="`${node.time} 候选${node.candidates||0} 通过${node.passed||0}${node.buys?' 成交'+node.buys:''}`" placement="top">
                  <div class="tl-bar-stack"><div class="tl-bar-cand" :style="{height:barHeight(node.candidates,slot.maxCand)+'px'}" /><div class="tl-bar-pass" :style="{height:barHeight(node.passed,slot.maxCand)+'px'}" /></div>
                </ElTooltip>
                <span class="tl-bar-time">{{node.time}}</span><span v-if="node.buys>0" class="tl-bar-buy">💰</span>
              </div>
            </div>
          </div>
        </div>
        <ElEmpty v-else description="暂无数据" :image-size="40" />
      </ElCard>
    </div>
  </div>
</template>

<style scoped lang="scss">
.signal-trace-page{padding:12px 16px;display:flex;flex-direction:column;gap:10px;min-height:100%;background:var(--bg-base)}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;.toolbar-left,.toolbar-right{display:flex;align-items:center;gap:8px};.toolbar-hint{font-size:12px;color:var(--text-tertiary)}}
.kpi-row{display:flex;gap:10px;flex-wrap:wrap}
.kpi-card{flex:1;min-width:80px;padding:10px 12px;background:var(--bg-elevated);border-radius:8px;border:1px solid var(--border-default);text-align:center;cursor:default;transition:all .15s;&:hover{border-color:var(--border-hover)};&.bought .kpi-value{color:var(--el-color-success)};&.rejected .kpi-value{color:var(--el-color-danger)};&.active{border-color:var(--el-color-primary-light-5);background:var(--el-color-primary-light-9)};.kpi-value{font-size:22px;font-weight:700;color:var(--text-primary);&.up{color:#f56c6c}&.down{color:#67c23a}&.clickable{cursor:pointer;&:hover{text-decoration:underline}}};.kpi-label{font-size:11px;color:var(--text-tertiary);margin-top:2px}}
.card-header{display:flex;justify-content:space-between;align-items:center;font-size:14px;font-weight:600;.header-right{display:flex;align-items:center;gap:10px};.header-hint{font-size:11px;color:var(--text-tertiary);font-weight:400};.header-legend{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:400;color:var(--text-tertiary)};.legend-item{display:flex;align-items:center;gap:3px};.legend-sep{color:var(--border-default)};.legend-hint{color:var(--text-quaternary)};.lg{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:3px;font-size:10px;font-weight:700;&.pass{background:rgba(103,194,58,.15);color:var(--el-color-success)};&.reject{background:rgba(245,108,108,.18);color:var(--el-color-danger)};&.skip{background:var(--bg-muted);color:var(--text-quaternary)}}}
.main-card{:deep(.el-card__body){padding:0;overflow:auto;max-height:70vh}}
.main-table{width:100%;font-size:12px}
.mt-header{display:flex;align-items:center;padding:8px 12px;background:var(--bg-muted);border-bottom:2px solid var(--border-default);position:sticky;top:0;z-index:2;font-weight:600;color:var(--text-secondary);font-size:11px;.mh-rank{width:28px;flex-shrink:0;text-align:center};.mh-score{width:42px;flex-shrink:0;text-align:center};.mh-stock{width:130px;flex-shrink:0};.mh-strat{width:64px;flex-shrink:0;text-align:center};.mh-pct{width:55px;flex-shrink:0;text-align:right};.mh-vr{width:42px;flex-shrink:0;text-align:right};.mh-tr{width:42px;flex-shrink:0;text-align:right};.mh-mv{width:55px;flex-shrink:0;text-align:right};.mh-pipeline{display:flex;gap:0;flex:1};.mh-cell{flex:1;min-width:48px;text-align:center;padding:4px 2px;border-radius:4px;cursor:pointer;transition:background .15s;&:hover{background:var(--bg-hover)};&.active{background:var(--el-color-primary-light-9);outline:1.5px solid var(--el-color-primary-light-5)};.mh-label{font-weight:600;font-size:10px;color:var(--text-secondary);white-space:nowrap}};.mh-result{width:68px;flex-shrink:0;text-align:center};.mh-reason{width:180px;flex-shrink:0}}
.mt-row{display:flex;align-items:center;padding:5px 12px;border-bottom:1px solid var(--border-lighter);transition:background .12s;cursor:pointer;&:hover{background:var(--bg-hover)};&.row-bought{border-left:3px solid var(--el-color-success);background:rgba(103,194,58,.03)};&.row-passed{border-left:3px solid #e6a23c};&.row-rejected{border-left:3px solid var(--el-color-danger)};&.expanded{background:var(--bg-hover);border-bottom-color:transparent}}
.mr-rank{width:28px;flex-shrink:0;text-align:center;font-size:12px;font-weight:700;color:var(--text-tertiary);&.top3{color:#e6a23c;font-size:14px}}
.mr-score{width:42px;flex-shrink:0;text-align:center}
.score-bar{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:20px;border-radius:10px;font-size:11px;font-weight:700;padding:0 5px;&.high{background:rgba(103,194,58,.18);color:var(--el-color-success)};&.mid{background:rgba(230,162,60,.15);color:#e6a23c};&.low{background:rgba(245,108,108,.12);color:var(--el-color-danger)}}
.mr-stock{width:130px;flex-shrink:0;display:flex;align-items:center;gap:3px;.expand-icon{width:12px;height:12px;color:var(--text-quaternary);flex-shrink:0};.mr-code{font-family:monospace;font-size:11px;color:var(--text-primary);font-weight:600};.mr-name{font-size:11px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.mr-strat{width:64px;flex-shrink:0;text-align:center}
.strat-tag{font-size:10px;padding:1px 4px;border-radius:3px;border:1px solid;font-weight:500}
.mr-pct{width:55px;flex-shrink:0;text-align:right;font-family:monospace;font-size:11px;font-weight:600;&.up{color:#f56c6c}&.down{color:#67c23a}}
.mr-vr,.mr-tr,.mr-mv{font-family:monospace;font-size:11px;text-align:right;color:var(--text-secondary)}
.mr-vr{width:42px;flex-shrink:0}.mr-tr{width:42px;flex-shrink:0}.mr-mv{width:55px;flex-shrink:0}
.mr-pipeline{display:flex;gap:0;flex:1;align-items:center}
.mr-cell{flex:1;min-width:48px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:4px;font-size:14px;font-weight:700;cursor:default;transition:all .12s;&.pass{background:rgba(103,194,58,.15);color:var(--el-color-success);border:1px solid rgba(103,194,58,.25)};&.reject{background:rgba(245,108,108,.18);color:var(--el-color-danger);cursor:pointer;border:1px solid rgba(245,108,108,.35);&:hover{background:rgba(245,108,108,.35);transform:scale(1.1);box-shadow:0 0 8px rgba(245,108,108,.3)}};&.skip{background:var(--bg-muted);color:var(--text-quaternary);border:1px dashed var(--border-lighter)};&.none{background:transparent;color:transparent;border:none}}
.mr-result{width:68px;flex-shrink:0;text-align:center}
.result-badge{font-size:10px;padding:2px 5px;border-radius:4px;font-weight:600;white-space:nowrap;&.bought{background:rgba(103,194,58,.12);color:var(--el-color-success)};&.pending{background:rgba(144,147,153,.12);color:#909399};&.exec-block{background:rgba(230,162,60,.12);color:#e6a23c};&.rejected{background:rgba(245,108,108,.12);color:var(--el-color-danger)}}
.mr-reason{width:180px;flex-shrink:0;padding:0 6px;.reason-bought{font-size:11px;color:var(--el-color-success);font-weight:600};.reason-reject{font-size:11px;color:var(--el-color-danger);overflow:hidden;text-overflow:ellipsis;white-space:nowrap};.reason-exec{font-size:11px;color:#e6a23c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap};.reason-dim{font-size:11px;color:var(--text-quaternary)}}
.row-detail{background:var(--bg-elevated);border-bottom:1px solid var(--border-default);padding:12px 16px;display:flex;flex-direction:column;gap:12px}
.rd-section{.rd-title{font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px}}
.rd-factors{display:flex;flex-wrap:wrap;gap:8px 16px}
.rd-fact{display:flex;align-items:center;gap:4px;font-size:11px;.rd-fact-label{color:var(--text-tertiary);min-width:48px};.rd-fact-value{font-family:monospace;font-weight:600;color:var(--text-primary);&.up{color:#f56c6c}&.down{color:#67c23a}&.warn{color:#e6a23c}};.rd-fact-desc{color:#e6a23c;font-size:10px}}
.rd-pipeline{display:flex;gap:4px}
.rd-pipe-cell{display:flex;flex-direction:column;align-items:center;gap:2px;.rd-pipe-status{width:22px;height:22px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;&.pass{background:rgba(103,194,58,.15);color:var(--el-color-success)};&.reject{background:rgba(245,108,108,.18);color:var(--el-color-danger)};&.skip{background:var(--bg-muted);color:var(--text-quaternary)}};.rd-pipe-label{font-size:10px;color:var(--text-tertiary)};.rd-pipe-reason{font-size:10px;color:var(--text-quaternary);max-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.rd-exec{font-size:12px;color:var(--el-color-success);font-weight:600}
.rd-reject{font-size:12px;color:var(--el-color-danger)}
.rd-signal{font-size:12px;color:var(--text-secondary);line-height:1.5}
.rank-count{font-weight:400;color:var(--text-tertiary);margin-left:2px}
// 评分排行
.rank-card{:deep(.el-card__body){padding:8px 12px;overflow:auto;max-height:35vh}}
.rank-list{display:flex;flex-direction:column;gap:2px}
.rank-item{display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:4px;font-size:11px;transition:background .12s;&:hover{background:var(--bg-hover)};&.ri-bought{border-left:2px solid var(--el-color-success)};&.ri-rejected{border-left:2px solid var(--el-color-danger)};.ri-rank{width:22px;text-align:center;font-weight:700;color:var(--text-tertiary);&.top3{color:#e6a23c;font-size:13px}};.ri-score{width:36px};.ri-stock{width:120px;display:flex;gap:3px;.ri-code{font-family:monospace;font-weight:600;color:var(--text-primary)};.ri-name{color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}};.ri-strat{width:60px;text-align:center};.ri-pct{width:50px;text-align:right;font-family:monospace;font-weight:600;&.up{color:#f56c6c}&.down{color:#67c23a}};.ri-vr,.ri-tr,.ri-mv{font-family:monospace;color:var(--text-secondary);text-align:right};.ri-vr{width:40px};.ri-tr{width:40px};.ri-mv{width:50px};.ri-result{width:60px;text-align:center};.ri-reason{flex:1;color:var(--text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}

.bottom-row{display:flex;gap:10px;align-items:stretch}
.funnel-card{width:300px;min-width:300px;:deep(.el-card__body){padding:8px 12px}}
.funnel-body{display:flex;flex-direction:column;gap:4px}
.funnel-row{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;font-size:12px;background:var(--bg-muted);transition:all .15s;&.clickable{cursor:pointer;&:hover{background:var(--bg-hover);transform:translateX(2px)}};&.clickable.active{background:var(--el-color-primary-light-9);outline:1.5px solid var(--el-color-primary-light-5)};&.total{background:rgba(64,158,255,.06)};&.passed{background:rgba(103,194,58,.05)};&.final{background:rgba(103,194,58,.10)};.fn-left{display:flex;align-items:center;gap:4px;width:80px;flex-shrink:0;.fn-icon{font-size:13px};.fn-label{font-size:11px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}};.fn-right{flex:1;display:flex;align-items:center;gap:6px;.fn-bar-wrap{flex:1;height:6px;border-radius:3px;background:var(--border-lighter);overflow:hidden};.fn-bar{height:100%;border-radius:3px;transition:width .3s ease;&.total{background:linear-gradient(90deg,#409eff,#79bbff)};&.passed,&.final{background:linear-gradient(90deg,#67c23a,#95d475)};background:linear-gradient(90deg,#f56c6c,#fab6b6)};.fn-count{font-weight:700;font-size:12px;color:var(--text-primary);min-width:24px;text-align:right;&.zero{color:var(--text-quaternary);font-weight:400}};.fn-pct{font-size:10px;color:var(--text-tertiary);min-width:28px}}}
.timeline-card{flex:1;min-width:0;:deep(.el-card__body){padding:10px 16px}}
.timeline-body{display:flex;flex-direction:column;gap:12px}
.tl-slot{.tl-slot-header{display:flex;align-items:center;gap:8px;margin-bottom:6px;.tl-slot-tag{font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px;&.premarket{background:rgba(230,162,60,.12);color:#e6a23c};&.early{background:rgba(64,158,255,.12);color:#409eff};&.lunch{background:rgba(144,147,153,.10);color:#909399};&.afternoon{background:rgba(103,194,58,.12);color:#67c23a}};.tl-slot-range{font-size:10px;color:var(--text-quaternary);font-family:monospace};.tl-slot-stats{font-size:11px;margin-left:auto;.tl-ss-cand{color:var(--text-secondary)};.tl-ss-pass{color:var(--el-color-success);font-weight:600};.tl-ss-buy{color:var(--el-color-success);font-weight:700;margin-left:4px}}};.tl-bars{display:flex;gap:3px;align-items:flex-end;padding-left:4px;border-left:2px solid var(--border-lighter);padding-bottom:2px};.tl-bar-group{display:flex;flex-direction:column;align-items:center;gap:2px;min-width:32px};.tl-bar-stack{display:flex;flex-direction:column-reverse;gap:0;cursor:default};.tl-bar-cand{width:20px;border-radius:3px 3px 0 0;background:linear-gradient(180deg,rgba(64,158,255,.25),rgba(64,158,255,.10));border:1px solid rgba(64,158,255,.20);border-bottom:none;min-height:2px;transition:height .2s};.tl-bar-pass{width:20px;border-radius:0 0 3px 3px;background:linear-gradient(180deg,rgba(103,194,58,.35),rgba(103,194,58,.15));border:1px solid rgba(103,194,58,.25);border-top:none;min-height:2px;transition:height .2s};.tl-bar-time{font-size:9px;color:var(--text-quaternary);font-family:monospace};.tl-bar-buy{font-size:8px}}
</style>
