<script setup lang="ts">
/**
 * 策略因子关系 + 整体流程面板
 * 替代原热力图/趋势图(实用性差)
 */

interface StrategyFactor {
  id: string
  name: string
  emoji: string
  color: string
  desc: string
  entrySignal: string        // 入场信号描述
  entryFactors: FactorItem[]  // 入场因子
  exitSignal: string         // 出场信号描述
  exitFactors: string[]       // 出场因子名
  riskFactors: string[]       // 风控因子
  flowSteps: string[]         // 交易流程
}

interface FactorItem {
  name: string
  label: string
  condition: string
  source: string
}

const strategies: StrategyFactor[] = [
  {
    id: 'halfway_chase',
    name: '半路追涨',
    emoji: '🚀',
    color: '#409eff',
    desc: '盘中上涨3%~7%时追入，次日冲高卖出。核心逻辑：强势股盘中启动→趋势延续→短线获利。',
    entrySignal: '盘中涨幅3%~7% + 量能放大 + MA60上方',
    entryFactors: [
      { name: 'intraday_max_rise_pct', label: '盘中最高涨幅', condition: '3% ~ 7%', source: 'OHLCV计算' },
      { name: 'intraday_open_rise_pct', label: '开盘涨幅', condition: '-5% ~ 7% (排除极端)', source: 'OHLCV计算' },
      { name: 'volume_ratio', label: '量比', condition: '≥ 1.5', source: 'factor_auto_compute' },
      { name: 'ma60', label: '60日均线', condition: '收盘>MA60 (趋势过滤)', source: 'factor_auto_compute' },
    ],
    exitSignal: '次日高开≥3%即卖 / 止损5% / 止盈10% / 持仓3天',
    exitFactors: ['open (次日开盘价)', 'close (止损/止盈参考)'],
    riskFactors: ['stop_loss_pct=5%', 'take_profit_pct=10%', 'max_hold_days=3'],
    flowSteps: [
      '9:25 竞价过滤：排除极端高开(>7%)/低开(<-5%)',
      '9:30-14:50 盘中监控：intraday_max_rise_pct达3%~7%',
      '触发买入：按 open×(1+涨幅×0.6) 成交(模拟追高)',
      '次日：高开≥3%→开盘卖出(落袋为安)',
      '次日：未达标→止损5%/止盈10%/3天超时卖出',
    ],
  },
  {
    id: 'first_limit_up',
    name: '首板打板',
    emoji: '🎯',
    color: '#f56c6c',
    desc: '首次涨停封板时买入，赌次日继续涨。核心逻辑：首板封板=最强多头信号→次日溢价。',
    entrySignal: '首次涨停(非连板) + 竞价达标 + 流动性足够',
    entryFactors: [
      { name: 'first_limit_up', label: '首板标记', condition: '=1 (涨停且非连板)', source: 'factor_auto_compute' },
      { name: 'limit_up_yesterday', label: '昨日涨停', condition: '=0 (排除连板)', source: 'factor_auto_compute' },
      { name: 'opening_pct_chg', label: '竞价涨幅', condition: '≥2% (竞价强势)', source: 'OHLCV计算' },
      { name: 'volume_ratio', label: '量比', condition: '≥1.5', source: 'factor_auto_compute' },
      { name: 'circ_mv', label: '流通市值', condition: '5亿~200亿', source: '东方财富' },
    ],
    exitSignal: '次日高开≥3%即卖 / 止损4% / 止盈12% / 持仓3天',
    exitFactors: ['open (次日)', 'close'],
    riskFactors: ['stop_loss_pct=4%', 'take_profit_pct=12%', 'max_hold_days=3', '成交概率(秒板0.3/快板0.5/慢板0.7)'],
    flowSteps: [
      '9:25 竞价检查：opening_pct_chg≥2%',
      '9:30 涨停确认：first_limit_up=1 且 limit_up_yesterday=0',
      '封板买入：根据封板速度计算成交概率(0.3/0.5/0.7)',
      '一字板=0%(买不到) / 秒板30% / 快板50% / 慢板70%',
      '次日：高开≥3%→开盘卖出 / 止损4%/止盈12%/3天超时',
    ],
  },
  {
    id: 'dragon_head',
    name: '龙头低吸',
    emoji: '🐉',
    color: '#e6a23c',
    desc: '前期龙头回调5%~20%后低吸，赌反弹。核心逻辑：龙头回调≠转势→恐慌消化→反弹修复。',
    entrySignal: '5日涨停≥2次 + 回调5%~20% + 回调2~8天 + 量能放大',
    entryFactors: [
      { name: 'limit_up_count', label: '5日涨停次数', condition: '≥2 (确认龙头地位)', source: 'factor_auto_compute' },
      { name: 'pullback_pct', label: '回调幅度', condition: '-20% ~ -5% (负数=回调)', source: 'factor_auto_compute' },
      { name: 'pullback_days', label: '回调天数', condition: '2~8天', source: 'factor_auto_compute' },
      { name: 'volume_ratio', label: '量比', condition: '≥1.0 (有承接)', source: 'factor_auto_compute' },
      { name: 'circ_mv', label: '流通市值', condition: '≥10亿', source: '东方财富' },
    ],
    exitSignal: '止损5% / 止盈6% / 持仓4天',
    exitFactors: ['close'],
    riskFactors: ['stop_loss_pct=5%', 'take_profit_pct=6%', 'max_hold_days=4'],
    flowSteps: [
      '扫描全市场：limit_up_count≥2 (近5日2次涨停=龙头)',
      '回调检测：pullback_pct在-20%~-5%之间 + pullback_days 2~8天',
      '量能确认：volume_ratio≥1.0 (回调有承接)',
      '买入：按 low+(high-low)×0.25 成交(模拟低吸)',
      '卖出：止损5% / 止盈6% / 4天超时',
    ],
  },
  {
    id: 'limit_down_qiao',
    name: '跌停翘板',
    emoji: '🔨',
    color: '#909399',
    desc: '昨日跌停+今日翘板(低开高走)买入，赌超跌反弹。核心逻辑：恐慌过度→翘板资金介入→反弹修复。',
    entrySignal: '昨日跌停 + 今日低开后翻红 + 翘板量能 + 流通市值≥20亿',
    entryFactors: [
      { name: 'limit_down_yesterday', label: '昨日跌停', condition: '=1', source: 'factor_auto_compute' },
      { name: 'open_above_limit_down', label: '开盘高于跌停价', condition: '=1 (翘板信号)', source: 'factor_auto_compute' },
      { name: 'circ_mv', label: '流通市值', condition: '≥20亿 (排除小盘操纵)', source: '东方财富' },
      { name: 'turnover_rate', label: '换手率', condition: '≥3% (流动性)', source: '东方财富' },
      { name: 'sentiment_period_in', label: '情绪周期', condition: 'rising/chaos (非恐慌)', source: '市场级计算' },
    ],
    exitSignal: '次日高开≥3%即卖 / 止损7% / 止盈7% / 持仓3天',
    exitFactors: ['open (次日)', 'close'],
    riskFactors: ['stop_loss_pct=7%', 'take_profit_pct=7%', 'max_hold_days=3', 'min_circ_mv≥20亿'],
    flowSteps: [
      '筛选：limit_down_yesterday=1 (昨日跌停)',
      '翘板确认：open_above_limit_down=1 (今日低开但高于跌停价)',
      '市值过滤：circ_mv≥20亿 (排除微盘操纵股)',
      '买入：按 open×1.005 成交(模拟翘板买入)',
      '次日：高开≥3%→开盘卖出 / 止损7%/止盈7%/3天超时',
    ],
  },
]

// 回测9层筛选流程
const filterLayers = [
  { layer: 1, name: '强制空仓', emoji: '🛑', desc: '涨停/跌停极端数→清仓', factors: ['limit_up_count', 'limit_down_count'], when: '大盘跌停≥50只或涨停≤10且指数跌≥3%' },
  { layer: 2, name: '特殊时期', emoji: '📅', desc: '月末/周五降仓', factors: ['日期判断'], when: '月末最后3天/周五(降低仓位)' },
  { layer: 3, name: '情绪周期', emoji: '😊', desc: '市场情绪→仓位系数', factors: ['sentiment_score', 'limit_up_count', 'limit_down_count'], when: '情绪=涨停-跌停+大盘*10+50, rising=70+, chaos=40-70, panic=<40' },
  { layer: 4, name: '盘前预选', emoji: '🔍', desc: '排除ST/退市/低流动性', factors: ['circ_mv', 'turnover_rate'], when: '排除ST/退市/流通市值<5亿/换手率<3%' },
  { layer: 5, name: '竞价过滤', emoji: '⏰', desc: '竞价涨幅筛选', factors: ['opening_pct_chg'], when: '首板≥2%, 半路排除极端(>7%/<-5%)' },
  { layer: 6, name: '策略量能', emoji: '📊', desc: '各策略核心因子筛选', factors: ['见各策略'], when: '执行各策略的因子条件(上表)' },
  { layer: 7, name: '综合排序', emoji: '🏆', desc: '策略优先级+去重+上限', factors: ['策略优先级'], when: '龙头>跌停>首板>半路, 同股去重(保留优先级高的), 最多10只' },
  { layer: 8, name: '仓位控制', emoji: '⚖️', desc: '情绪×特殊×单票上限', factors: ['仓位系数'], when: '单票20%, 总仓位=情绪系数×特殊系数×70%' },
  { layer: 9, name: '成交模拟', emoji: '💰', desc: '滑点/成交概率/买入价', factors: ['slippage_pct', 'hit_probability'], when: '涨停0.5%/跌停0.5%/其他0.1%滑点' },
]

const expandedStrategy = defineModel<string>('expanded', { default: '' })

function toggleStrategy(id: string) {
  expandedStrategy.value = expandedStrategy.value === id ? '' : id
}
</script>

<template>
  <div class="strategy-factor-panel">
    <!-- 整体流程 -->
    <div class="section-title">🔄 回测9层筛选流程</div>
    <div class="flow-pipeline">
      <div v-for="l in filterLayers" :key="l.layer" class="flow-step">
        <div class="flow-num">{{ l.layer }}</div>
        <div class="flow-content">
          <div class="flow-name">{{ l.emoji }} {{ l.name }}</div>
          <div class="flow-desc">{{ l.desc }}</div>
          <div class="flow-factors">
            <code v-for="f in l.factors" :key="f" class="factor-tag">{{ f }}</code>
          </div>
          <div class="flow-when">{{ l.when }}</div>
        </div>
        <div v-if="l.layer < 9" class="flow-arrow">→</div>
      </div>
    </div>

    <!-- 各策略详情 -->
    <div class="section-title" style="margin-top: 24px">📋 各策略因子关系</div>
    <div class="strategy-cards">
      <div v-for="s in strategies" :key="s.id" class="s-card" :class="{ expanded: expandedStrategy === s.id }">
        <div class="s-header" @click="toggleStrategy(s.id)" :style="{ borderLeftColor: s.color }">
          <span class="s-emoji">{{ s.emoji }}</span>
          <span class="s-name" :style="{ color: s.color }">{{ s.name }}</span>
          <span class="s-desc-inline">{{ s.desc.slice(0, 30) }}...</span>
          <span class="s-expand">{{ expandedStrategy === s.id ? '收起 ▲' : '展开 ▼' }}</span>
        </div>
        
        <div v-if="expandedStrategy === s.id" class="s-body">
          <div class="s-desc-full">{{ s.desc }}</div>
          
          <!-- 入场 -->
          <div class="s-section">
            <div class="s-section-title">📥 入场信号：{{ s.entrySignal }}</div>
            <div class="factor-table">
              <div class="ft-header">
                <span class="ft-col ft-name-col">因子字段</span>
                <span class="ft-col ft-label-col">含义</span>
                <span class="ft-col ft-cond-col">条件</span>
                <span class="ft-col ft-src-col">来源</span>
              </div>
              <div v-for="f in s.entryFactors" :key="f.name" class="ft-row">
                <code class="ft-col ft-name-col">{{ f.name }}</code>
                <span class="ft-col ft-label-col">{{ f.label }}</span>
                <span class="ft-col ft-cond-col">{{ f.condition }}</span>
                <span class="ft-col ft-src-col">{{ f.source }}</span>
              </div>
            </div>
          </div>
          
          <!-- 出场 -->
          <div class="s-section">
            <div class="s-section-title">📤 出场信号：{{ s.exitSignal }}</div>
            <div class="s-sub">出场因子：{{ s.exitFactors.join(', ') }}</div>
          </div>
          
          <!-- 风控 -->
          <div class="s-section">
            <div class="s-section-title">🛡️ 风控参数</div>
            <div class="risk-tags">
              <span v-for="r in s.riskFactors" :key="r" class="risk-tag">{{ r }}</span>
            </div>
          </div>
          
          <!-- 交易流程 -->
          <div class="s-section">
            <div class="s-section-title">🔢 交易流程</div>
            <div class="flow-steps">
              <div v-for="(step, i) in s.flowSteps" :key="i" class="flow-step-item">
                <span class="step-num">{{ i + 1 }}</span>
                <span class="step-text">{{ step }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.strategy-factor-panel { padding: 0; }

.section-title {
  font-size: 16px; font-weight: 700; color: #303133; margin-bottom: 12px;
  padding-bottom: 8px; border-bottom: 2px solid #409eff;
}

// 9层筛选流程
.flow-pipeline {
  display: flex; flex-direction: column; gap: 8px;
}
.flow-step {
  display: flex; align-items: flex-start; gap: 10px;
}
.flow-num {
  width: 28px; height: 28px; border-radius: 50%; background: #409eff; color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700;
  flex-shrink: 0; margin-top: 2px;
}
.flow-content { flex: 1; }
.flow-name { font-weight: 600; font-size: 14px; }
.flow-desc { font-size: 12px; color: #909399; margin-top: 1px; }
.flow-factors { margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap; }
.factor-tag {
  font-size: 11px; background: #ecf5ff; color: #409eff; padding: 1px 6px;
  border-radius: 3px; font-family: 'SF Mono', monospace;
}
.flow-when { font-size: 11px; color: #606266; margin-top: 3px; line-height: 1.5; background: #fafafa; padding: 3px 8px; border-radius: 4px; }
.flow-arrow { color: #c0c4cc; font-size: 18px; align-self: center; }

// 策略卡片
.strategy-cards { display: flex; flex-direction: column; gap: 8px; }
.s-card {
  border: 1px solid #ebeef5; border-radius: 8px; overflow: hidden; transition: all 0.2s;
  &.expanded { border-color: #409eff; box-shadow: 0 2px 12px rgba(64,158,255,0.1); }
}
.s-header {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  cursor: pointer; border-left: 4px solid; background: #fafafa;
  &:hover { background: #f0f2f5; }
}
.s-emoji { font-size: 20px; }
.s-name { font-weight: 700; font-size: 16px; }
.s-desc-inline { font-size: 12px; color: #909399; flex: 1; }
.s-expand { font-size: 12px; color: #909399; }

.s-body { padding: 16px; border-top: 1px solid #ebeef5; }
.s-desc-full { font-size: 13px; color: #606266; line-height: 1.6; margin-bottom: 16px; padding: 8px 12px; background: #f5f7fa; border-radius: 6px; }

.s-section { margin-bottom: 14px; }
.s-section-title { font-weight: 600; font-size: 13px; color: #303133; margin-bottom: 8px; }
.s-sub { font-size: 12px; color: #606266; }

.factor-table {
  width: 100%; border: 1px solid #ebeef5; border-radius: 6px; overflow: hidden;
}
.ft-header { display: flex; background: #f5f7fa; font-size: 12px; font-weight: 600; color: #909399; }
.ft-row { display: flex; border-top: 1px solid #ebeef5; &:hover { background: #fafcff; } }
.ft-col { padding: 6px 10px; font-size: 12px; }
.ft-name-col { width: 170px; font-family: 'SF Mono', monospace; color: #409eff; }
.ft-label-col { width: 110px; color: #303133; }
.ft-cond-col { flex: 1; color: #e6a23c; font-weight: 500; }
.ft-src-col { width: 120px; color: #909399; font-size: 11px; }

.risk-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.risk-tag {
  font-size: 11px; background: #fef0f0; color: #f56c6c; padding: 2px 8px;
  border-radius: 4px; border: 1px solid #fde2e2;
}

.flow-steps { display: flex; flex-direction: column; gap: 6px; }
.flow-step-item { display: flex; align-items: flex-start; gap: 8px; }
.step-num {
  width: 20px; height: 20px; border-radius: 50%; background: #ecf5ff; color: #409eff;
  display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600;
  flex-shrink: 0;
}
.step-text { font-size: 12px; color: #606266; line-height: 1.5; }
</style>
