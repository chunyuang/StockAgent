<script setup lang="ts">
/**
 * StrategyConfigPanel - 超短回测策略配置面板
 * 包含数据源、基础配置、交易参数、全局筛选、强制空仓、情绪周期、竞价过滤、5个策略配置
 */
import { computed } from 'vue'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElSwitch,
  ElSelect,
  ElOption,
} from 'element-plus'
import { VideoPlay as Play } from '@element-plus/icons-vue'
import { SWEEP_PARAMS } from '@/config/backtestConstants'

// SWEEP_PARAMS - imported from shared config

const props = defineProps<{
  form: any
  backtestRunning: boolean
  sweepEnabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit'): void
  (e: 'toggle', name: string): void
}>()

// 动态标题计算
const dataSourceTitle = computed(() => `🔌 数据源配置 (${props.form.dataSource.period === 'daily' ? '日线' : '1分钟'}, ${props.form.dataSource.adjust_type === 'qfq' ? '前复权' : '不复权'}, ${props.form.dataSource.start_date || '未设'}~${props.form.dataSource.end_date || '未设'}, 股票池: ${props.form.dataSource.ts_codes || '全市场'})`)
const baseConfigTitle = computed(() => `📅 基础配置 (初始资金¥${(props.form.base.initial_cash / 10000).toFixed(0)}万)`)
const tradeParamsTitle = computed(() => `💹 交易参数 (止损${(props.form.tradeParams.base_stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.tradeParams.base_take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.tradeParams.max_hold_days}天, 单票${(props.form.tradeParams.max_position_per_stock * 100).toFixed(0)}%, 总仓位${(props.form.tradeParams.max_total_position * 100).toFixed(0)}%, 佣金${(props.form.tradeParams.commission_rate * 10000).toFixed(1)}‱, 印花税${(props.form.tradeParams.stamp_duty_rate * 10000).toFixed(1)}‱, 滑点${(props.form.tradeParams.slippage_pct * 1000).toFixed(1)}‰)`)
const globalFilterTitle = computed(() => `🔍 全局筛选 (${props.form.globalFilter.exclude_st ? '剔ST' : '含ST'}, ${props.form.globalFilter.exclude_delisting ? '剔退市' : '含退市'}, 次新<${props.form.globalFilter.exclude_new_stock_days}天, 成交额≥${props.form.globalFilter.min_daily_amount}万, 换手≥${props.form.globalFilter.min_turnover_rate}%)`)
const forceEmptyTitle = computed(() => `⚠️ 强制空仓 ${props.form.forceEmpty.enabled ? '✅' : '❌'} (跌幅≥${(props.form.forceEmpty.index_drop_pct * 100).toFixed(1)}%, 跌停≥${props.form.forceEmpty.limit_down_count}只, 涨停<${props.form.forceEmpty.limit_up_count}只)`)
const sentimentCycleTitle = computed(() => `🧠 情绪周期 ${props.form.sentimentCycle.enabled ? '✅' : '❌'} (涨停${props.form.sentimentCycle.weight_limit_up}, 跌停${props.form.sentimentCycle.weight_limit_down}, 炸板率${props.form.sentimentCycle.weight_blast_rate}, 涨跌差${props.form.sentimentCycle.weight_rise_fall_diff}, 北向${props.form.sentimentCycle.weight_north_inflow})`)
const auctionFilterTitle = computed(() => `⏰ 竞价过滤 ${props.form.auctionFilter.enabled ? '✅' : '❌'} (涨幅${(props.form.auctionFilter.min_auction_pct * 100).toFixed(1)}%~${(props.form.auctionFilter.max_auction_pct * 100).toFixed(1)}%, 成交额≥${props.form.auctionFilter.min_auction_amount}万, 量比≥${props.form.auctionFilter.min_auction_volume_ratio}, 未匹配量正: ${props.form.auctionFilter.min_unmatched_volume_positive ? '✅' : '❌'})`)

const halfwayChaseTitle = computed(() => `🏃‍♂️ 半路追涨策略 ${props.form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌'} (涨幅${(props.form.strategyConfigs.halfway_chase.params.min_rise_pct * 100).toFixed(1)}%~${(props.form.strategyConfigs.halfway_chase.params.max_rise_pct * 100).toFixed(1)}%, 量比${props.form.strategyConfigs.halfway_chase.params.min_volume_ratio}~${props.form.strategyConfigs.halfway_chase.params.max_volume_ratio}, 收盘≥${(props.form.strategyConfigs.halfway_chase.params.min_close_rise_pct * 100).toFixed(1)}%, 开盘≤${(props.form.strategyConfigs.halfway_chase.params.max_open_rise_pct * 100).toFixed(1)}%, ${props.form.strategyConfigs.halfway_chase.params.allow_after_10am ? '可10点后' : '仅10点前'}, 追踪止损${(props.form.strategyConfigs.halfway_chase.riskParams.trailing_stop_pct * 100).toFixed(1)}%, 止损${(props.form.strategyConfigs.halfway_chase.riskParams.stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.strategyConfigs.halfway_chase.riskParams.take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.strategyConfigs.halfway_chase.riskParams.max_hold_days}天, 滑点${(props.form.strategyConfigs.halfway_chase.riskParams.slippage_pct * 1000).toFixed(1)}‰)`)
const firstLimitUpTitle = computed(() => `🥇 首板打板策略 ${props.form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌'} (竞价${(props.form.strategyConfigs.first_limit_up.params.opening_pct_min * 100).toFixed(0)}%~${(props.form.strategyConfigs.first_limit_up.params.opening_pct_max * 100).toFixed(0)}%, 量比≥${props.form.strategyConfigs.first_limit_up.params.min_volume_ratio}, 换手${props.form.strategyConfigs.first_limit_up.params.min_turnover_rate}%~${props.form.strategyConfigs.first_limit_up.params.max_turnover_rate}%, 流通市值${props.form.strategyConfigs.first_limit_up.params.min_circulation_market_cap}~${props.form.strategyConfigs.first_limit_up.params.max_circulation_market_cap}亿, 成交概率: 一字${(props.form.strategyConfigs.first_limit_up.params.hit_probability_yizi * 100).toFixed(0)}%/秒板${(props.form.strategyConfigs.first_limit_up.params.hit_probability_fast * 100).toFixed(0)}%/快板${(props.form.strategyConfigs.first_limit_up.params.hit_probability_normal * 100).toFixed(0)}%/慢板${(props.form.strategyConfigs.first_limit_up.params.hit_probability_slow * 100).toFixed(0)}%, 次日高开≥${(props.form.strategyConfigs.first_limit_up.params.next_day_open_sell_pct * 100).toFixed(0)}%卖, 止损${(props.form.strategyConfigs.first_limit_up.riskParams.stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.strategyConfigs.first_limit_up.riskParams.take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.strategyConfigs.first_limit_up.riskParams.max_hold_days}天, 滑点${(props.form.strategyConfigs.first_limit_up.riskParams.slippage_pct * 1000).toFixed(1)}‰)`)
const limitUpOpenTitle = computed(() => `📈 涨停开板策略 ${props.form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌'} (连板≥${props.form.strategyConfigs.limit_up_open.params.min_consecutive_limit}板, 开板≤${props.form.strategyConfigs.limit_up_open.params.max_open_duration}分钟, 回封封单≥${props.form.strategyConfigs.limit_up_open.params.min_seal_orders}万手, 换手≥${props.form.strategyConfigs.limit_up_open.params.min_turnover_rate}%, 止损${(props.form.strategyConfigs.limit_up_open.riskParams.stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.strategyConfigs.limit_up_open.riskParams.take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.strategyConfigs.limit_up_open.riskParams.max_hold_days}天, 滑点${(props.form.strategyConfigs.limit_up_open.riskParams.slippage_pct * 1000).toFixed(1)}‰)`)
const dragonHeadTitle = computed(() => `🐲 龙头低吸策略 ${props.form.strategyConfigs.dragon_head.enabled ? '✅' : '❌'} (连板≥${props.form.strategyConfigs.dragon_head.params.min_consecutive_limit}板, 流通市值≥${props.form.strategyConfigs.dragon_head.params.min_circulation_market_cap}亿, 回调${(props.form.strategyConfigs.dragon_head.params.min_correction_pct * 100).toFixed(0)}%~${(props.form.strategyConfigs.dragon_head.params.max_correction_pct * 100).toFixed(0)}%共${props.form.strategyConfigs.dragon_head.params.correction_days_min}~${props.form.strategyConfigs.dragon_head.params.correction_days_max}天, 量比${props.form.strategyConfigs.dragon_head.params.min_volume_ratio}~${props.form.strategyConfigs.dragon_head.params.max_volume_ratio}, 支撑${props.form.strategyConfigs.dragon_head.params.support_level === 'ma5' ? 'MA5' : props.form.strategyConfigs.dragon_head.params.support_level === 'ma10' ? 'MA10' : '平台'}, 止损${(props.form.strategyConfigs.dragon_head.riskParams.stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.strategyConfigs.dragon_head.riskParams.take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.strategyConfigs.dragon_head.riskParams.max_hold_days}天, 滑点${(props.form.strategyConfigs.dragon_head.riskParams.slippage_pct * 1000).toFixed(1)}‰)`)
const limitDownQiaoTitle = computed(() => `💥 跌停翘板策略 ${props.form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌'} (连跌≥${props.form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit}天, 翘板≥${props.form.strategyConfigs.limit_down_qiao.params.min_qiao_amount}万, 翘板后涨≥${(props.form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao * 100).toFixed(0)}%, 流通市值≥${props.form.strategyConfigs.limit_down_qiao.params.min_circulation_market_cap}亿, ${props.form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '需高情绪' : '不限情绪'}, 止损${(props.form.strategyConfigs.limit_down_qiao.riskParams.stop_loss_pct * 100).toFixed(1)}%/止盈${(props.form.strategyConfigs.limit_down_qiao.riskParams.take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.strategyConfigs.limit_down_qiao.riskParams.max_hold_days}天, 滑点${(props.form.strategyConfigs.limit_down_qiao.riskParams.slippage_pct * 1000).toFixed(1)}‰)`)

// ============ 策略/配置描述 ============
const sectionDescriptions: Record<string, { title: string; desc: string; tips?: string[] }> = {
  dataSource: {
    title: '🔌 数据源配置',
    desc: '定义回测的数据来源，包括K线周期、复权方式和股票池范围。',
    tips: ['日线适合隔日交易策略，1分钟适合盘中策略', '前复权可消除分红除权影响，回测更准确', '股票池留空则覆盖全市场A股']
  },
  baseConfig: {
    title: '📅 基础配置',
    desc: '回测的时间范围和初始资金设置。',
    tips: ['建议选择3个月以上区间，样本量足够', '初始资金影响仓位管理，建议≥100万']
  },
  tradeParams: {
    title: '💹 交易参数',
    desc: '全局交易规则，包括止损止盈、仓位管理和交易成本。策略级风控参数可覆盖这些默认值。',
    tips: ['止损3%~5%为超短常见范围', '总仓位70%留30%现金应对加仓', '滑点2‰模拟涨停排队的真实成交偏差', '佣金万3+印花税千1为典型交易成本']
  },
  globalFilter: {
    title: '🔍 全局筛选',
    desc: '全策略共用的股票过滤规则，不满足条件的股票不会进入任何策略的候选池。',
    tips: ['剔除ST避免退市风险股', '次新股≥60天排除上市初期不稳定波动', '成交额≥5000万确保流动性', '换手率≥3%排除无人关注的僵尸股']
  },
  forceEmpty: {
    title: '⚠️ 强制空仓',
    desc: '市场极端情况下的保护机制。当大盘大跌、跌停家数激增时，强制卖出所有持仓。',
    tips: ['大盘跌≥2%+跌停≥50只 → 极端恐慌信号', '触发后次日不会再买入，直到情绪恢复', '建议保持开启，避免系统性暴跌风险']
  },
  sentimentCycle: {
    title: '🧠 情绪周期',
    desc: '通过多维度指标量化市场情绪，影响各策略的信号强度和仓位分配。',
    tips: ['涨停/跌停家数反映多空力量对比', '炸板率反映打板封板质量', '北向资金反映外资流向偏好', '权重之和无需为1，各自独立缩放']
  },
  auctionFilter: {
    title: '⏰ 竞价过滤',
    desc: '在集合竞价阶段对候选股进行预筛选，过滤竞价表现不佳的标的。',
    tips: ['竞价涨幅2%~8%为宜，过高可能开盘即巅峰', '未匹配量为正说明买盘强于卖盘', '竞价量比≥2说明市场关注度高']
  },
  halfway_chase: {
    title: '🏃♂️ 半路追涨策略',
    desc: '在盘中股票已经上涨但尚未涨停时追入，博弈后续继续冲高甚至封板。适合强势市场的顺势交易。',
    tips: ['核心参数：涨幅3%~7%的强势股', '量比1.5~3.0确认放量而非缩量上涨', '收盘涨幅≥2%确认非冲高回落', '开盘涨幅≤5%排除竞价已过热的票', '平均收益偏弱(+1.97%)，注意风控']
  },
  first_limit_up: {
    title: '🥇 首板打板策略',
    desc: '在股票首次涨停时排队买入，博弈次日高开溢价。回测中模拟了不同涨停速度的实际成交概率。',
    tips: ['成交概率是核心：一字板5%、秒板30%、快板60%、慢板80%', '流通市值20~100亿为最佳区间', '换手率5%~15%量价配合最佳', '次日高开≥3%自动止盈（高开即卖）', '止损4%为打板策略的底线']
  },
  limit_up_open: {
    title: '📈 涨停开板策略',
    desc: '连板股盘中开板后回封时买入，博弈回封后次日继续高开。需要连板基础确保龙头地位。',
    tips: ['最少2连板以上，确保不是杂毛股', '开板≤10分钟即回封，说明主力坚决', '回封后封单≥1万手确认抛压已消化', '止损4%严格控制开板后继续下跌风险']
  },
  dragon_head: {
    title: '🐲 龙头低吸策略',
    desc: '在龙头股回调到支撑位时低吸买入，博弈龙头二波启动。适合市场分歧后的再次一致。',
    tips: ['核心：连板龙头+缩量回调到5/10日均线', '回调5%~35%为健康调整区间', '量比0.5~2.0确认缩量而非放量下跌', '支撑位选5日均线适合强势回调', '止损5%给龙头更大的波动空间']
  },
  limit_down_qiao: {
    title: '💥 跌停翘板策略',
    desc: '在跌停板被大资金撬开时追入，博弈翘板后的大幅反弹。高风险高回报，需配合情绪周期。',
    tips: ['连跌1天以上才有足够恐慌释放', '翘板金额≥5000万确认大资金介入', '翘板后涨幅≥3%确认反转力度', '建议开启高情绪周期要求（市场强势时翘板成功率高）', '止损4%+止盈25%：高赔率策略']
  }
}

const activeDescription = computed(() => {
  if (!activeCollapse.value.length) return null
  const last = activeCollapse.value[activeCollapse.value.length - 1]
  return sectionDescriptions[last] || null
})

// 折叠面板
const activeCollapse = defineModel<string[]>('activeCollapse', { default: [] })

// Toggle 辅助
function toggleStrategy(strategyId: string) {
  const cfg = props.form.strategyConfigs[strategyId]
  cfg.enabled = !cfg.enabled
  if (cfg.enabled) {
    if (!props.form.strategies.includes(strategyId)) props.form.strategies.push(strategyId)
  } else {
    props.form.strategies = props.form.strategies.filter((k: string) => k !== strategyId)
  }
}

// 扫描参数辅助
const currentSweepParam = computed(() => SWEEP_PARAMS.find(p => p.value === props.form.sweep.param))
const _currentSweepUnit = computed(() => currentSweepParam.value?.unit || '') // 备用

function onSweepParamChange() {
  const p = currentSweepParam.value
  if (p) {
    props.form.sweep.start = p.min / p.factor
    props.form.sweep.end = p.max / p.factor
    props.form.sweep.step = p.step / p.factor
  }
}
</script>

<template>
  <div class="config-layout-v2">
  <ElCard class="config-card">
    <template #header>
      <div class="card-header">
        <span>⚙️ 回测配置</span>
        <div class="header-actions">
          <div class="sweep-toggle">
            <span class="sweep-label">参数扫描</span>
            <ElSwitch v-model="form.sweep.enabled" size="small" />
          </div>
          <ElButton @click="emit('submit')" :icon="Play" type="success" :loading="backtestRunning" size="default">
            {{ backtestRunning ? (form.sweep.enabled ? '扫描中...' : '回测中...') : (form.sweep.enabled ? '开始扫描' : '开始回测') }}
          </ElButton>
        </div>
      </div>
    </template>

    <!-- 参数扫描配置 -->
    <div v-if="form.sweep.enabled" class="sweep-config">
      <div class="sweep-config-layout">
        <div class="sweep-config-left">
          <div class="sweep-config-title">🔬 参数扫描配置</div>
          <ElForm label-width="120px" size="small">
            <ElFormItem label="扫描参数">
              <ElSelect v-model="form.sweep.param" @change="onSweepParamChange" style="width: 200px">
                <ElOption v-for="p in SWEEP_PARAMS" :key="p.value" :label="p.label" :value="p.value" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="起始值">
              <ElInputNumber v-model="form.sweep.start" :min="0" :step="0.01" :precision="3" style="width: 150px" />
              <span class="unit">{{ currentSweepParam ? (form.sweep.start * currentSweepParam.factor).toFixed(currentSweepParam.factor > 1 ? 0 : 1) + currentSweepParam.unit : '' }}</span>
            </ElFormItem>
            <ElFormItem label="结束值">
              <ElInputNumber v-model="form.sweep.end" :min="0" :step="0.01" :precision="3" style="width: 150px" />
              <span class="unit">{{ currentSweepParam ? (form.sweep.end * currentSweepParam.factor).toFixed(currentSweepParam.factor > 1 ? 0 : 1) + currentSweepParam.unit : '' }}</span>
            </ElFormItem>
            <ElFormItem label="步长">
              <ElInputNumber v-model="form.sweep.step" :min="0.001" :step="0.01" :precision="3" style="width: 150px" />
              <span class="unit">{{ currentSweepParam ? (form.sweep.step * currentSweepParam.factor).toFixed(currentSweepParam.factor > 1 ? 0 : 1) + currentSweepParam.unit : '' }}</span>
            </ElFormItem>
          </ElForm>
        </div>
        <div class="sweep-config-right">
          <div class="desc-panel-title">🔬 参数扫描说明</div>
          <div class="desc-panel-text">对选定参数在指定范围内按步长遍历，每个值独立跑一次完整回测，最终对比不同参数值下的收益/胜率/回撤，找到最优参数组合。</div>
          <div class="desc-panel-tips-title">📊 可扫描参数</div>
          <div class="desc-panel-tip">止损比例 — 测试不同止损宽度对收益和胜率的影响，范围1%~20%</div>
          <div class="desc-panel-tip">止盈比例 — 测试不同止盈目标对最终收益的影响，范围1%~50%</div>
          <div class="desc-panel-tip">最大持仓天数 — 测试持股时长与收益的关系，范围1~10天</div>
          <div class="desc-panel-tip">单票最大仓位 — 测试集中度对风险收益的影响，范围5%~50%</div>
          <div class="desc-panel-tip">总仓位上限 — 测试仓位管理对整体表现的影响，范围10%~100%</div>
          <div class="desc-panel-tip">半路追涨最小涨幅 — 优化追涨入场的最佳涨幅阈值</div>
          <div class="desc-panel-tip">最小量比 — 优化放量确认的最佳量比阈值</div>
          <div class="desc-panel-tips-title">💡 使用建议</div>
          <div class="desc-panel-tip">步长不宜过小，否则扫描次数过多耗时很长</div>
          <div class="desc-panel-tip">止损扫描步长建议1%，止盈步长建议5%</div>
          <div class="desc-panel-tip">先粗扫确定大致范围，再细扫精确定位最优值</div>
          <div class="desc-panel-tip">扫描结果会生成参数-收益对比图表，直观展示最优区间</div>
        </div>
      </div>
    </div>

    <ElCollapse v-model="activeCollapse">
      <!-- 数据源配置 -->
      <ElCollapseItem name="dataSource">
        <template #title><span>{{ dataSourceTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="120px">
          <ElFormItem label="周期">
            <ElSelect v-model="form.dataSource.period" style="width: 150px">
              <ElOption label="日线" value="daily" />
              <ElOption label="1分钟" value="1min" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="复权方式">
            <ElSelect v-model="form.dataSource.adjust_type" style="width: 150px">
              <ElOption label="前复权" value="qfq" />
              <ElOption label="不复权" value="none" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="股票代码">
            <ElInput v-model="form.dataSource.ts_codes" placeholder="空为全市场，多只逗号分隔" style="width: 300px" />
          </ElFormItem>
          <ElFormItem label="开始日期">
            <ElInput v-model="form.dataSource.start_date" placeholder="如20260105" />
          </ElFormItem>
          <ElFormItem label="结束日期">
            <ElInput v-model="form.dataSource.end_date" placeholder="如20260320" />
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.dataSource">
          <div class="desc-title">{{ sectionDescriptions.dataSource.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.dataSource.desc }}</div>
          <div v-if="sectionDescriptions.dataSource.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.dataSource.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 基础配置 -->
      <ElCollapseItem name="baseConfig">
        <template #title><span>{{ baseConfigTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="120px">
          <ElFormItem label="初始资金">
            <ElInputNumber v-model="form.base.initial_cash" :min="100000" :max="1000000000" style="width: 200px" prefix="¥" />
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.baseConfig">
          <div class="desc-title">{{ sectionDescriptions.baseConfig.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.baseConfig.desc }}</div>
          <div v-if="sectionDescriptions.baseConfig.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.baseConfig.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 交易参数 -->
      <ElCollapseItem name="tradeParams">
        <template #title><span>{{ tradeParamsTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="120px">
          <ElFormItem label="基础止损">
            <ElInputNumber v-model="form.tradeParams.base_stop_loss_pct" :min="0" :max="1" :step="0.005" :precision="3" style="width: 150px" />
            <span class="unit">= {{ (form.tradeParams.base_stop_loss_pct * 100).toFixed(1) }}%</span>
          </ElFormItem>
          <ElFormItem label="基础止盈">
            <ElInputNumber v-model="form.tradeParams.base_take_profit_pct" :min="0" :max="1" :step="0.01" :precision="2" style="width: 150px" />
            <span class="unit">= {{ (form.tradeParams.base_take_profit_pct * 100).toFixed(1) }}%</span>
          </ElFormItem>
          <ElFormItem label="最大持仓天数">
            <ElInputNumber v-model="form.tradeParams.max_hold_days" :min="1" :max="10" style="width: 150px" />
            <span class="unit">天</span>
          </ElFormItem>
          <ElFormItem label="单票最大仓位">
            <ElInputNumber v-model="form.tradeParams.max_position_per_stock" :min="0" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">= {{ (form.tradeParams.max_position_per_stock * 100).toFixed(0) }}%</span>
          </ElFormItem>
          <ElFormItem label="总仓位上限">
            <ElInputNumber v-model="form.tradeParams.max_total_position" :min="0" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">= {{ (form.tradeParams.max_total_position * 100).toFixed(0) }}%</span>
          </ElFormItem>
          <ElFormItem label="佣金费率">
            <ElInputNumber v-model="form.tradeParams.commission_rate" :min="0" :max="0.01" :step="0.00001" style="width: 150px" />
            <span class="unit">‰</span>
          </ElFormItem>
          <ElFormItem label="印花税税率">
            <ElInputNumber v-model="form.tradeParams.stamp_duty_rate" :min="0" :max="0.01" :step="0.0001" disabled style="width: 150px" />
            <span class="unit">‰</span>
          </ElFormItem>
          <ElFormItem label="滑点比例">
            <ElInputNumber v-model="form.tradeParams.slippage_pct" :min="0" :max="0.01" :step="0.0001" style="width: 150px" />
            <span class="unit">‰</span>
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.tradeParams">
          <div class="desc-title">{{ sectionDescriptions.tradeParams.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.tradeParams.desc }}</div>
          <div v-if="sectionDescriptions.tradeParams.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.tradeParams.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 全局筛选 -->
      <ElCollapseItem name="globalFilter">
        <template #title><span>{{ globalFilterTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="剔除ST/*ST"><ElSwitch v-model="form.globalFilter.exclude_st" /></ElFormItem>
          <ElFormItem label="剔除退市股"><ElSwitch v-model="form.globalFilter.exclude_delisting" /></ElFormItem>
          <ElFormItem label="剔除上市未满N天次新股">
            <ElInputNumber v-model="form.globalFilter.exclude_new_stock_days" :min="30" :max="365" style="width: 150px" />
            <span class="unit">天</span>
          </ElFormItem>
          <ElFormItem label="最低日成交额">
            <ElInputNumber v-model="form.globalFilter.min_daily_amount" :min="100" :max="10000" style="width: 150px" />
            <span class="unit">万元</span>
          </ElFormItem>
          <ElFormItem label="最低换手率">
            <ElInputNumber v-model="form.globalFilter.min_turnover_rate" :min="1" :max="20" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.globalFilter">
          <div class="desc-title">{{ sectionDescriptions.globalFilter.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.globalFilter.desc }}</div>
          <div v-if="sectionDescriptions.globalFilter.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.globalFilter.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 强制空仓 -->
      <ElCollapseItem name="forceEmpty">
        <template #title><span>{{ forceEmptyTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用强制空仓"><ElSwitch v-model="form.forceEmpty.enabled" /></ElFormItem>
          <ElFormItem label="大盘跌幅≥" :disabled="!form.forceEmpty.enabled">
            <ElInputNumber v-model="form.forceEmpty.index_drop_pct" :min="0" :max="0.2" :step="0.001" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="跌停家数≥" :disabled="!form.forceEmpty.enabled">
            <ElInputNumber v-model="form.forceEmpty.limit_down_count" :min="0" :max="500" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
            <span class="unit">只</span>
          </ElFormItem>
          <ElFormItem label="涨停家数<" :disabled="!form.forceEmpty.enabled">
            <ElInputNumber v-model="form.forceEmpty.limit_up_count" :min="0" :max="500" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
            <span class="unit">只</span>
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.forceEmpty">
          <div class="desc-title">{{ sectionDescriptions.forceEmpty.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.forceEmpty.desc }}</div>
          <div v-if="sectionDescriptions.forceEmpty.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.forceEmpty.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 情绪周期 -->
      <ElCollapseItem name="sentimentCycle">
        <template #title><span>{{ sentimentCycleTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用情绪周期"><ElSwitch v-model="form.sentimentCycle.enabled" /></ElFormItem>
          <ElFormItem label="涨停家数权重" :disabled="!form.sentimentCycle.enabled">
            <ElInputNumber v-model="form.sentimentCycle.weight_limit_up" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
          </ElFormItem>
          <ElFormItem label="跌停家数权重" :disabled="!form.sentimentCycle.enabled">
            <ElInputNumber v-model="form.sentimentCycle.weight_limit_down" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
          </ElFormItem>
          <ElFormItem label="炸板率权重" :disabled="!form.sentimentCycle.enabled">
            <ElInputNumber v-model="form.sentimentCycle.weight_blast_rate" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
          </ElFormItem>
          <ElFormItem label="涨跌家数差权重" :disabled="!form.sentimentCycle.enabled">
            <ElInputNumber v-model="form.sentimentCycle.weight_rise_fall_diff" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
          </ElFormItem>
          <ElFormItem label="北向资金权重" :disabled="!form.sentimentCycle.enabled">
            <ElInputNumber v-model="form.sentimentCycle.weight_north_inflow" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.sentimentCycle">
          <div class="desc-title">{{ sectionDescriptions.sentimentCycle.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.sentimentCycle.desc }}</div>
          <div v-if="sectionDescriptions.sentimentCycle.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.sentimentCycle.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 竞价过滤 -->
      <ElCollapseItem name="auctionFilter">
        <template #title><span>{{ auctionFilterTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用竞价过滤"><ElSwitch v-model="form.auctionFilter.enabled" /></ElFormItem>
          <ElFormItem label="最低竞价涨幅" :disabled="!form.auctionFilter.enabled">
            <ElInputNumber v-model="form.auctionFilter.min_auction_pct" :min="0" :max="0.1" :step="0.001" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="最高竞价涨幅" :disabled="!form.auctionFilter.enabled">
            <ElInputNumber v-model="form.auctionFilter.max_auction_pct" :min="0" :max="0.2" :step="0.001" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="未匹配量必须为正" :disabled="!form.auctionFilter.enabled">
            <ElSwitch v-model="form.auctionFilter.min_unmatched_volume_positive" :disabled="!form.auctionFilter.enabled" />
          </ElFormItem>
          <ElFormItem label="最低竞价成交额" :disabled="!form.auctionFilter.enabled">
            <ElInputNumber v-model="form.auctionFilter.min_auction_amount" :min="100" :max="10000" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
            <span class="unit">万元</span>
          </ElFormItem>
          <ElFormItem label="最低竞价量比" :disabled="!form.auctionFilter.enabled">
            <ElInputNumber v-model="form.auctionFilter.min_auction_volume_ratio" :min="1" :max="10" :step="0.1" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
            <span class="unit">倍</span>
          </ElFormItem>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.auctionFilter">
          <div class="desc-title">{{ sectionDescriptions.auctionFilter.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.auctionFilter.desc }}</div>
          <div v-if="sectionDescriptions.auctionFilter.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.auctionFilter.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 半路追涨 -->
      <ElCollapseItem name="halfway_chase">
        <template #title><span>{{ halfwayChaseTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.halfway_chase.enabled" @change="() => toggleStrategy('halfway_chase')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.params.min_rise_pct * 100).toFixed(1) }}%</span>
            </ElFormItem>
            <ElFormItem label="最高实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_rise_pct" :min="0" :max="0.3" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.params.max_rise_pct * 100).toFixed(1) }}%</span>
            </ElFormItem>
            <ElFormItem label="最低量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_volume_ratio" :min="0.5" :max="10" :step="0.1" :precision="1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最高量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_volume_ratio" :min="1" :max="20" :step="0.1" :precision="1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最低收盘涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_close_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.params.min_close_rise_pct * 100).toFixed(1) }}%</span>
            </ElFormItem>
            <ElFormItem label="最高开盘涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_open_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.params.max_open_rise_pct * 100).toFixed(1) }}%</span>
            </ElFormItem>
            <ElFormItem label="允许10点后买入" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElSwitch v-model="form.strategyConfigs.halfway_chase.params.allow_after_10am" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
            </ElFormItem>
          </div>
          <!-- 策略级风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（覆盖全局参数）</div>
            <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.riskParams.stop_loss_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.riskParams.take_profit_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.max_hold_days" :min="1" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.riskParams.slippage_pct * 1000).toFixed(1) }}‰</span>
              </ElFormItem>
              <ElFormItem v-if="form.strategyConfigs.halfway_chase.riskParams.trailing_stop_pct != null" label="追踪止损" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.trailing_stop_pct" :min="0" :max="0.05" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">{{ (form.strategyConfigs.halfway_chase.riskParams.trailing_stop_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.halfway_chase">
          <div class="desc-title">{{ sectionDescriptions.halfway_chase.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.halfway_chase.desc }}</div>
          <div v-if="sectionDescriptions.halfway_chase.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.halfway_chase.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 首板打板 -->
      <ElCollapseItem name="first_limit_up">
        <template #title><span>{{ firstLimitUpTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.first_limit_up.enabled" @change="() => toggleStrategy('first_limit_up')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="竞价涨幅下限" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.opening_pct_min" :min="-10" :max="10" :step="0.5" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="竞价涨幅上限" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.opening_pct_max" :min="0" :max="15" :step="0.5" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最低量比" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.min_volume_ratio" :min="0.5" :max="10" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最低换手率" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.min_turnover_rate" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最高换手率" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_turnover_rate" :min="5" :max="50" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最小流通市值" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.min_circulation_market_cap" :min="5" :max="1000" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="最高流通市值" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_circulation_market_cap" :min="50" :max="2000" :step="10" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="次日高开即卖≥" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.next_day_open_sell_pct" :min="0" :max="0.1" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.params.next_day_open_sell_pct * 100).toFixed(1) }}%</span>
            </ElFormItem>
          </div>
          <!-- 成交概率配置 -->
          <div class="risk-params-section">
            <div class="risk-params-title">🎲 成交概率模拟（涨停买入概率）</div>
            <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="一字板" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_yizi" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.params.hit_probability_yizi * 100).toFixed(0) }}%</span>
              </ElFormItem>
              <ElFormItem label="秒板(开≥8%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_fast" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.params.hit_probability_fast * 100).toFixed(0) }}%</span>
              </ElFormItem>
              <ElFormItem label="快板(开2~8%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_normal" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.params.hit_probability_normal * 100).toFixed(0) }}%</span>
              </ElFormItem>
              <ElFormItem label="慢板(开<2%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_slow" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.params.hit_probability_slow * 100).toFixed(0) }}%</span>
              </ElFormItem>
            </div>
          </div>
          <!-- 策略级风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（覆盖全局参数）</div>
            <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.riskParams.stop_loss_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.riskParams.take_profit_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.max_hold_days" :min="1" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">{{ (form.strategyConfigs.first_limit_up.riskParams.slippage_pct * 1000).toFixed(1) }}‰</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.first_limit_up">
          <div class="desc-title">{{ sectionDescriptions.first_limit_up.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.first_limit_up.desc }}</div>
          <div v-if="sectionDescriptions.first_limit_up.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.first_limit_up.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 涨停开板 -->
      <ElCollapseItem name="limit_up_open">
        <template #title><span>{{ limitUpOpenTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.limit_up_open.enabled" @change="() => toggleStrategy('limit_up_open')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.limit_up_open.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最少连板数" :disabled="!form.strategyConfigs.limit_up_open.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_consecutive_limit" :min="2" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">板</span>
            </ElFormItem>
            <ElFormItem label="最大开板时长" :disabled="!form.strategyConfigs.limit_up_open.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.max_open_duration" :min="1" :max="60" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">分钟</span>
            </ElFormItem>
            <ElFormItem label="回封后最低封单" :disabled="!form.strategyConfigs.limit_up_open.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_seal_after_open" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="最低换手率" :disabled="!form.strategyConfigs.limit_up_open.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_turnover_rate" :min="0" :max="1" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">%</span>
            </ElFormItem>
          </div>
          <!-- 策略级风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（覆盖全局参数）</div>
            <div :disabled="!form.strategyConfigs.limit_up_open.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_up_open.riskParams.stop_loss_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_up_open.riskParams.take_profit_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.max_hold_days" :min="1" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_up_open.riskParams.slippage_pct * 1000).toFixed(1) }}‰</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.limit_up_open">
          <div class="desc-title">{{ sectionDescriptions.limit_up_open.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.limit_up_open.desc }}</div>
          <div v-if="sectionDescriptions.limit_up_open.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.limit_up_open.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 龙头低吸 -->
      <ElCollapseItem name="dragon_head">
        <template #title><span>{{ dragonHeadTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.dragon_head.enabled" @change="() => toggleStrategy('dragon_head')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.dragon_head.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最小连板数" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.min_consecutive_limit" :min="1" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">板</span>
            </ElFormItem>
            <ElFormItem label="最小流通市值" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.min_circulation_market_cap" :min="5" :max="500" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="最低回调幅度" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.min_correction_pct" :min="0" :max="0.5" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">{{ (form.strategyConfigs.dragon_head.params.min_correction_pct * 100).toFixed(0) }}%</span>
            </ElFormItem>
            <ElFormItem label="最高回调幅度" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.max_correction_pct" :min="0.05" :max="0.6" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">{{ (form.strategyConfigs.dragon_head.params.max_correction_pct * 100).toFixed(0) }}%</span>
            </ElFormItem>
            <ElFormItem label="最少回调天数" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.correction_days_min" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="最多回调天数" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.correction_days_max" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="最低量比" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.min_volume_ratio" :min="0" :max="5" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最高量比" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.max_volume_ratio" :min="1" :max="10" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="支撑位" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElSelect v-model="form.strategyConfigs.dragon_head.params.support_level" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElOption label="5日均线" value="ma5" />
                <ElOption label="10日均线" value="ma10" />
                <ElOption label="平台支撑" value="platform" />
              </ElSelect>
            </ElFormItem>
          </div>
          <!-- 策略级风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（覆盖全局参数）</div>
            <div :disabled="!form.strategyConfigs.dragon_head.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">{{ (form.strategyConfigs.dragon_head.riskParams.stop_loss_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">{{ (form.strategyConfigs.dragon_head.riskParams.take_profit_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.max_hold_days" :min="1" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">{{ (form.strategyConfigs.dragon_head.riskParams.slippage_pct * 1000).toFixed(1) }}‰</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.dragon_head">
          <div class="desc-title">{{ sectionDescriptions.dragon_head.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.dragon_head.desc }}</div>
          <div v-if="sectionDescriptions.dragon_head.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.dragon_head.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 跌停翘板 -->
      <ElCollapseItem name="limit_down_qiao">
        <template #title><span>{{ limitDownQiaoTitle }}</span></template>
        <div class="item-layout"><div class="item-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.limit_down_qiao.enabled" @change="() => toggleStrategy('limit_down_qiao')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.limit_down_qiao.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最小连跌数" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit" :min="1" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="翘板最低成交额" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_qiao_amount" :min="100" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="翘板后最低涨幅" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao" :min="0" :max="0.2" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao * 100).toFixed(0) }}%</span>
            </ElFormItem>
            <ElFormItem label="最小流通市值" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_circulation_market_cap" :min="5" :max="500" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="要求高情绪周期" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElSwitch v-model="form.strategyConfigs.limit_down_qiao.params.require_high_sentiment" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
            </ElFormItem>
          </div>
          <!-- 策略级风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（覆盖全局参数）</div>
            <div :disabled="!form.strategyConfigs.limit_down_qiao.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_down_qiao.riskParams.stop_loss_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_down_qiao.riskParams.take_profit_pct * 100).toFixed(1) }}%</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.max_hold_days" :min="1" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">{{ (form.strategyConfigs.limit_down_qiao.riskParams.slippage_pct * 1000).toFixed(1) }}‰</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
              </div><div class="item-right" v-if="sectionDescriptions.limit_down_qiao">
          <div class="desc-title">{{ sectionDescriptions.limit_down_qiao.title }}</div>
          <div class="desc-text">{{ sectionDescriptions.limit_down_qiao.desc }}</div>
          <div v-if="sectionDescriptions.limit_down_qiao.tips?.length" class="desc-tips">
            <div class="desc-tips-title">💡 参数建议</div>
            <div v-for="(tip, i) in sectionDescriptions.limit_down_qiao.tips" :key="i" class="desc-tip-item">
              <span class="desc-tip-dot">•</span> {{ tip }}
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>
    </ElCollapse>
  </ElCard>
</div>
</template>

<script lang="ts">
export default { name: 'StrategyConfigPanel' }
</script>

<style scoped lang="scss">
.config-card {
  margin-bottom: 12px;
  border: none;
  box-shadow: none;
  background: transparent;
  :deep(.el-card__header) { padding: 10px 16px; background: transparent; border-bottom: 1px solid var(--border-default); }
  :deep(.el-card__body) { padding: 12px 16px; }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 700;
    font-size: 15px;
    flex-wrap: wrap;
    gap: 10px;
    min-width: 0;
    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .sweep-toggle {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      .sweep-label {
        font-size: 12px;
        color: var(--text-secondary);
        white-space: nowrap;
      }
    }
  }
}
.sweep-config {
  padding: 14px 18px;
  background: linear-gradient(135deg, var(--primary-50) 0%, var(--primary-100) 100%);
  border-radius: 8px;
  margin-bottom: 14px;
  border: 1px dashed var(--primary-300);
  .sweep-config-title {
    font-weight: 700;
    font-size: 13px;
    color: var(--primary-500);
    margin-bottom: 10px;
  }
}

/* 左右两栏布局 */
.config-layout-v2 {
  min-height: calc(100vh - 180px);
}

/* 折叠项内部左右布局 */
.item-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.item-left {
  flex: 1;
  min-width: 0;
  max-width: 55%;
}
.item-right {
  flex: 1;
  flex-shrink: 0;
  position: sticky;
  top: 60px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  background: var(--bg-elevated, #fff);
  border: 1px solid var(--border-default, #e4e7ed);
  border-radius: 8px;
  padding: 16px;
}

/* 右侧描述面板 */
.desc-panel {
  background: var(--bg-elevated, #fff);
  border: 1px solid var(--border-default, #e4e7ed);
  border-radius: 8px;
  padding: 20px;
  transition: all 0.3s;
}
.desc-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary, #303133);
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--el-color-primary-light-3, #79bbff);
}
.desc-text {
  font-size: 13px;
  color: var(--text-secondary, #606266);
  line-height: 1.6;
  margin-bottom: 14px;
}
.desc-tips {
  background: var(--el-color-primary-light-9, #ecf5ff);
  border: 1px solid var(--el-color-primary-light-7, #c6e2ff);
  border-radius: 6px;
  padding: 12px;
}
.desc-tips-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-color-primary, #409eff);
  margin-bottom: 8px;
}
.desc-tip-item {
  font-size: 12px;
  color: var(--text-secondary, #606266);
  line-height: 1.6;
  margin-bottom: 4px;
}
.desc-tip-dot {
  color: var(--el-color-primary, #409eff);
  margin-right: 4px;
}
.desc-empty {
  text-align: center;
  padding: 40px 20px;
}
.desc-empty-icon {
  font-size: 36px;
  margin-bottom: 12px;
}
.desc-empty-text {
  font-size: 14px;
  color: var(--text-secondary, #606266);
  margin-bottom: 6px;
}
.desc-empty-sub {
  font-size: 12px;
  color: var(--text-tertiary, #909399);
}

/* 参数扫描左右布局 */
.sweep-config-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.sweep-config-left {
  flex: 1;
  min-width: 0;
}
.sweep-config-right {
  width: 260px;
  flex-shrink: 0;
  background: var(--bg-elevated, #fff);
  border: 1px solid var(--border-default, #e4e7ed);
  border-radius: 8px;
  padding: 16px;
}
.desc-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #303133);
  margin-bottom: 10px;
}
.desc-panel-text {
  font-size: 13px;
  color: var(--text-secondary, #606266);
  line-height: 1.6;
  margin-bottom: 12px;
}
.desc-panel-tips-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-color-primary, #409eff);
  margin-bottom: 8px;
  margin-top: 10px;
}
.desc-panel-tip {
  font-size: 12px;
  color: var(--text-secondary, #606266);
  line-height: 1.6;
  margin-bottom: 4px;
  padding-left: 8px;
  border-left: 2px solid var(--el-color-primary-light-7, #c6e2ff);
}
.unit {
  margin-left: 8px;
  color: var(--text-tertiary);
  font-size: 12px;
}
.risk-params-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border-default);
  .risk-params-title {
    font-weight: 700;
    font-size: 13px;
    color: var(--el-color-primary);
    margin-bottom: 10px;
    padding-left: 6px;
    border-left: 3px solid var(--el-color-warning);
    line-height: 1;
  }
}
:deep(.el-collapse) {
  border: none;
}
:deep(.el-collapse-item__header) {
  white-space: normal !important;
  overflow: visible !important;
  padding-right: 40px !important;
  font-weight: 600;
  font-size: 13px;
  background: var(--bg-elevated);
  border-radius: 6px;
  margin-bottom: 4px;
  border: 1px solid var(--border-default);
  min-height: 40px;
  line-height: 1.5;
  padding-top: 8px;
  padding-bottom: 8px;
}
:deep(.el-collapse-item__header.is-active) {
  background: var(--bg-active);
  border-color: var(--primary-200);
  color: var(--primary-500);
}
:deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}
:deep(.el-collapse-item__content) {
  padding: 12px 8px 16px;
}
:deep(.el-collapse-item__header::-webkit-scrollbar) { height: 4px; }
:deep(.el-collapse-item__header::-webkit-scrollbar-thumb) { background-color: var(--border-muted); border-radius: 2px; }
:deep(.el-collapse-item__arrow) {
  position: absolute;
  right: 15px;
  background: var(--bg-elevated);
  padding-left: 10px;
}
:deep(.el-form-item) {
  margin-bottom: 14px;
}
:deep(.el-form-item__label) {
  font-size: 13px;
  color: var(--text-secondary);
}
:deep(.el-input-number) {
  width: 160px;
}
:deep(.el-select) {
  width: 180px;
}
:deep(.el-switch) {
  margin-right: 4px;
}
/* 【V63修复:P1-10】移动端适配 */
@media (max-width: 768px) {
  .config-layout-v2 {
  min-height: calc(100vh - 180px);
    flex-direction: column;
  }
  .item-layout {
    flex-direction: column;
  }
  .item-right {
    width: 100%;
    position: static;
    margin-top: 12px;
  }
  .sweep-config-layout {
    flex-direction: column;
  }
  .sweep-config-right {
    width: 100%;
    margin-top: 12px;
  }
  .config-panel :deep(.el-form-item__label) {
    width: 100px !important;
    font-size: 12px;
  }
  .config-panel :deep(.el-input-number) {
    width: 120px;
  }
  .config-panel :deep(.el-select) {
    width: 140px;
  }
  .config-panel :deep(.el-collapse-item__header) {
    font-size: 13px;
  }
}
</style>
