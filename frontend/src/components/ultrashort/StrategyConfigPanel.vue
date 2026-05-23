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
const dataSourceTitle = computed(() => `🔌 数据源配置 (${props.form.dataSource.period === 'daily' ? '日线' : '1分钟'}, ${props.form.dataSource.adjust_type === 'qfq' ? '前复权' : '不复权'}, 股票池: ${props.form.dataSource.ts_codes || '全市场'})`)
const baseConfigTitle = computed(() => `📅 基础配置 (${props.form.dataSource.start_date}~${props.form.dataSource.end_date}, 初始资金¥${(props.form.base.initial_cash / 10000).toFixed(0)}万)`)
const tradeParamsTitle = computed(() => `💹 交易参数 (止损${(props.form.tradeParams.base_stop_loss_pct * 100).toFixed(1)}%, 止盈${(props.form.tradeParams.base_take_profit_pct * 100).toFixed(1)}%, 持仓${props.form.tradeParams.max_hold_days}天, 总仓${(props.form.tradeParams.max_total_position * 100).toFixed(0)}%, 单票${(props.form.tradeParams.max_position_per_stock * 100).toFixed(0)}%, 佣金${(props.form.tradeParams.commission_rate * 1000).toFixed(1)}‰, 印花税${(props.form.tradeParams.stamp_duty_rate * 1000).toFixed(0)}‰, 滑点${(props.form.tradeParams.slippage_pct * 1000).toFixed(1)}‰)`)
const globalFilterTitle = computed(() => `🔍 全局筛选 (剔除ST: ${props.form.globalFilter.exclude_st ? '✅' : '❌'}, 剔除退市: ${props.form.globalFilter.exclude_delisting ? '✅' : '❌'}, 次新股≥${props.form.globalFilter.exclude_new_stock_days}天, 成交额≥${props.form.globalFilter.min_daily_amount}万, 换手率≥${props.form.globalFilter.min_turnover_rate}%)`)
const forceEmptyTitle = computed(() => `⚠️ 强制空仓 ${props.form.forceEmpty.enabled ? '✅' : '❌'} (跌幅≥${(props.form.forceEmpty.index_drop_pct * 100).toFixed(1)}%, 跌停≥${props.form.forceEmpty.limit_down_count}只, 涨停<${props.form.forceEmpty.limit_up_count}只)`)
const sentimentCycleTitle = computed(() => `🧠 情绪周期 ${props.form.sentimentCycle.enabled ? '✅' : '❌'} (涨停${props.form.sentimentCycle.weight_limit_up}, 跌停${props.form.sentimentCycle.weight_limit_down}, 炸板率${props.form.sentimentCycle.weight_blast_rate}, 涨跌差${props.form.sentimentCycle.weight_rise_fall_diff}, 北向${props.form.sentimentCycle.weight_north_inflow})`)
const auctionFilterTitle = computed(() => `⏰ 竞价过滤 ${props.form.auctionFilter.enabled ? '✅' : '❌'} (涨幅${(props.form.auctionFilter.min_auction_pct * 100).toFixed(1)}%~${(props.form.auctionFilter.max_auction_pct * 100).toFixed(1)}%, 成交额≥${props.form.auctionFilter.min_auction_amount}万, 量比≥${props.form.auctionFilter.min_auction_volume_ratio}, 未匹配量正: ${props.form.auctionFilter.min_unmatched_volume_positive ? '✅' : '❌'})`)

const halfwayChaseTitle = computed(() => {
  const p = props.form.strategyConfigs.halfway_chase.params, r = props.form.strategyConfigs.halfway_chase.riskParams
  return `🏃‍♂️ 半路追涨策略 ${props.form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌'} (涨幅${(p.min_rise_pct * 100).toFixed(1)}%~${(p.max_rise_pct * 100).toFixed(1)}%, 量比${p.min_volume_ratio}~${p.max_volume_ratio}, 收盘≥${(p.min_close_rise_pct * 100).toFixed(1)}%, 开盘≤${(p.max_open_rise_pct * 100).toFixed(1)}%, ${p.allow_after_10am ? '10点后可买' : '10点前'}, 次日高开≥${(p.next_day_open_sell_pct * 100).toFixed(0)}%卖, 止损${(r.stop_loss_pct * 100).toFixed(0)}%/止盈${(r.take_profit_pct * 100).toFixed(0)}%, 持仓${r.max_hold_days}天, 滑点${(r.slippage_pct * 1000).toFixed(1)}‰)`
})
const firstLimitUpTitle = computed(() => {
  const p = props.form.strategyConfigs.first_limit_up.params, r = props.form.strategyConfigs.first_limit_up.riskParams
  return `🥇 首板打板策略 ${props.form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌'} (开盘${p.opening_pct_min}%~${p.opening_pct_max}%, 量比≥${p.min_volume_ratio}, 换手${p.min_turnover_rate}%~${p.max_turnover_rate}%, 流通市值${p.min_circulation_market_cap}~${p.max_circulation_market_cap}亿, 成交:一字${(p.hit_probability_yizi * 100).toFixed(0)}%/秒${(p.hit_probability_fast * 100).toFixed(0)}%/快${(p.hit_probability_normal * 100).toFixed(0)}%/慢${(p.hit_probability_slow * 100).toFixed(0)}%, 次日高开≥${(p.next_day_open_sell_pct * 100).toFixed(0)}%卖, 止损${(r.stop_loss_pct * 100).toFixed(0)}%/止盈${(r.take_profit_pct * 100).toFixed(0)}%, 持仓${r.max_hold_days}天, 滑点${(r.slippage_pct * 1000).toFixed(1)}‰)`
})
const limitUpOpenTitle = computed(() => {
  const p = props.form.strategyConfigs.limit_up_open.params, r = props.form.strategyConfigs.limit_up_open.riskParams
  return `📈 涨停开板策略 ${props.form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌'} (连板≥${p.min_consecutive_limit}板, 开板≤${p.max_open_duration}分钟, 封单≥${p.min_seal_after_open}万, 换手≥${p.min_turnover_rate}%, 开盘${p.opening_pct_min}%~${p.opening_pct_max}%, 量比≥${p.min_volume_ratio}, 止损${(r.stop_loss_pct * 100).toFixed(0)}%/止盈${(r.take_profit_pct * 100).toFixed(0)}%, 持仓${r.max_hold_days}天, 滑点${(r.slippage_pct * 1000).toFixed(1)}‰)`
})
const dragonHeadTitle = computed(() => {
  const p = props.form.strategyConfigs.dragon_head.params, r = props.form.strategyConfigs.dragon_head.riskParams
  return `🐲 龙头低吸策略 ${props.form.strategyConfigs.dragon_head.enabled ? '✅' : '❌'} (连板≥${p.min_consecutive_limit}板, 回调${(p.min_correction_pct * 100).toFixed(0)}%~${(p.max_correction_pct * 100).toFixed(0)}%, 量比${p.min_volume_ratio}~${p.max_volume_ratio}, 回调${p.correction_days_min}~${p.correction_days_max}天, 次日高开≥${(p.next_day_open_sell_pct * 100).toFixed(0)}%卖, 止损${(r.stop_loss_pct * 100).toFixed(0)}%/止盈${(r.take_profit_pct * 100).toFixed(0)}%, 持仓${r.max_hold_days}天, 滑点${(r.slippage_pct * 1000).toFixed(1)}‰)`
})
const limitDownQiaoTitle = computed(() => {
  const p = props.form.strategyConfigs.limit_down_qiao.params, r = props.form.strategyConfigs.limit_down_qiao.riskParams
  return `💥 跌停翘板策略 ${props.form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌'} (连跌≥${p.min_consecutive_limit}天, 换手≥${p.min_turnover_rate}%, 翘板≥${p.min_qiao_amount}万, 翘板后涨幅≥${(p.min_rise_after_qiao * 100).toFixed(0)}%, 流通市值≥${p.min_circulation_market_cap}亿, ${p.require_high_sentiment ? '要求高情绪' : '不限情绪'}, 次日高开≥${(p.next_day_open_sell_pct * 100).toFixed(0)}%卖, 回落≥${(p.pullback_mid_fallback_pct * 100).toFixed(1)}%保护, 止损${(r.stop_loss_pct * 100).toFixed(0)}%/止盈${(r.take_profit_pct * 100).toFixed(0)}%, 持仓${r.max_hold_days}天, 滑点${(r.slippage_pct * 1000).toFixed(1)}‰)`
})

// ============ 右侧描述 ============
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
    tips: ['大盘跌≥3%+跌停≥80只 → 极端恐慌信号', '触发后次日不会再买入，直到情绪恢复', '建议保持开启，避免系统性暴跌风险']
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
    title: '🏃‍♂️ 半路追涨策略',
    desc: '在盘中股票已经上涨但尚未涨停时追入，博弈后续继续冲高甚至封板。适合强势市场的顺势交易。',
    tips: ['核心参数：涨幅3%~7%的强势股', '量比2.0~3.0确认放量而非缩量上涨', '收盘涨幅≥5%确认非冲高回落(关键过滤)', '开盘涨幅≤3%排除竞价已过热的票', '平均收益偏弱(+1.97%)，注意风控']
  },
  first_limit_up: {
    title: '🥇 首板打板策略',
    desc: '在股票首次涨停时排队买入，博弈次日高开溢价。回测中模拟了不同涨停速度的实际成交概率。',
    tips: ['成交概率是核心：一字板0%、秒板30%、快板50%、慢板70%', '流通市值50~500亿为最佳区间', '换手率3%~15%量价配合最佳', '次日高开≥3%自动止盈（高开即卖）', '止损4%为打板策略的底线']
  },
  limit_up_open: {
    title: '📈 涨停开板策略',
    desc: '连板股盘中开板后回封时买入，博弈回封后次日继续高开。需要连板基础确保龙头地位。',
    tips: ['最少2连板以上，确保不是杂毛股', '开板≤10分钟即回封，说明主力坚决', '回封后封单≥1万手确认抛压已消化', '止损4%严格控制开板后继续下跌风险']
  },
  dragon_head: {
    title: '🐲 龙头低吸策略',
    desc: '在龙头股回调到支撑位时低吸买入，博弈龙头二波启动。适合市场分歧后的再次一致。',
    tips: ['核心：连板龙头+缩量回调到5/10日均线', '回调5%~35%为健康调整区间', '量比0.5~2.0确认缩量而非放量下跌', '支撑位选5日均线适合强势回调', '止损5%/止盈15%给龙头更大的波动空间']
  },
  limit_down_qiao: {
    title: '💥 跌停翘板策略',
    desc: '在跌停板被大资金撬开时追入，博弈翘板后的大幅反弹。高风险高回报，需配合情绪周期。',
    tips: ['连跌1天以上才有足够恐慌释放', '翘板金额≥1000万确认大资金介入', '翘板后涨幅≥3%确认反转力度', '市场强势时翘板成功率高', '止损4%+止盈20%：高赔率策略']
  }
}

const activeDescription = computed(() => {
  if (!activeCollapse.value.length) return null
  const last = activeCollapse.value[activeCollapse.value.length - 1]
  return sectionDescriptions[last] || null
})

// 折叠面板
const activeCollapse = defineModel<string[]>('activeCollapse', { default: [] })

// 模式切换
const configMode = ref<'edit' | 'flow'>('edit')

// Toggle 辅助
function toggleStrategy(strategyId: string) {
  const cfg = props.form.strategyConfigs[strategyId]
  // v-model already toggled enabled, just sync strategies array
  if (cfg.enabled) {
    if (!props.form.strategies.includes(strategyId)) props.form.strategies.push(strategyId)
  } else {
    props.form.strategies = props.form.strategies.filter((k: string) => k !== strategyId)
  }
}

// 扫描参数辅助
const currentSweepParam = computed(() => SWEEP_PARAMS.find(p => p.value === props.form.sweep.param))
const currentSweepUnit = computed(() => currentSweepParam.value?.unit || '')

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
    <!-- 模式切换 -->
    <div class="mode-switcher">
      <button :class="['mode-btn', configMode === 'edit' ? 'active' : '']" @click="configMode = 'edit'">🎯 参数配置</button>
      <button :class="['mode-btn', configMode === 'flow' ? 'active' : '']" @click="configMode = 'flow'">🔄 执行流程</button>
    </div>

    <!-- 编辑模式 -->
    <template v-if="configMode === 'edit'">
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
        <div class="collapse-content">
        <div class="collapse-content-left">
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🔌 数据源配置</div>
            <div class="desc-panel-text">定义回测的数据来源。日线适合隔日交易策略，1分钟K线适合盘中策略。前复权可消除分红除权影响，回测更准确。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">日线回测最常用，1分钟数据量大计算慢</div>
              <div class="desc-panel-tip">前复权可消除除权缺口，避免假信号</div>
              <div class="desc-panel-tip">股票池留空=全市场A股(剔除筛选后)</div>
              <div class="desc-panel-tip">建议区间≥3个月，样本量足够统计显著</div>
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 基础配置 -->
      <ElCollapseItem name="baseConfig">
        <template #title><span>{{ baseConfigTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
        <ElForm label-width="120px">
          <ElFormItem label="初始资金">
            <ElInputNumber v-model="form.base.initial_cash" :min="100000" :max="1000000000" style="width: 200px" prefix="¥" />
          </ElFormItem>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">📅 基础配置</div>
            <div class="desc-panel-text">回测的时间范围和初始资金。时间范围决定样本量，初始资金影响仓位管理。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">建议区间≥3个月确保统计显著性</div>
              <div class="desc-panel-tip">初始资金≥100万，太低影响单票仓位分配</div>
              <div class="desc-panel-tip">避免牛市区间回测（幸存者偏差）</div>
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>

      <!-- 交易参数 -->
      <ElCollapseItem name="tradeParams">
        <template #title><span>{{ tradeParamsTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
        <ElForm label-width="120px">
          <ElFormItem label="基础止损">
            <ElInputNumber v-model="form.tradeParams.base_stop_loss_pct" :min="0" :max="1" :step="0.001" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="基础止盈">
            <ElInputNumber v-model="form.tradeParams.base_take_profit_pct" :min="0" :max="1" :step="0.001" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="最大持仓天数">
            <ElInputNumber v-model="form.tradeParams.max_hold_days" :min="1" :max="10" style="width: 150px" />
            <span class="unit">天</span>
          </ElFormItem>
          <ElFormItem label="单票最大仓位">
            <ElInputNumber v-model="form.tradeParams.max_position_per_stock" :min="0" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">%</span>
          </ElFormItem>
          <ElFormItem label="总仓位上限">
            <ElInputNumber v-model="form.tradeParams.max_total_position" :min="0" :max="1" :step="0.05" style="width: 150px" />
            <span class="unit">%</span>
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">💹 交易参数</div>
            <div class="desc-panel-text">全局交易规则，策略级风控参数可覆盖默认值。止损止盈决定盈亏比，仓位管理控制风险敞口。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">止损3%~5%为超短常见范围，太小容易被震出</div>
              <div class="desc-panel-tip">总仓位70%留30%现金应对加仓机会</div>
              <div class="desc-panel-tip">滑点2‰模拟涨停排队的真实成交偏差</div>
              <div class="desc-panel-tip">佣金万3+印花税千1为典型交易成本</div>
              <div class="desc-panel-tip">单票仓位25%可持仓4只，分散风险</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 全局筛选 -->
      <ElCollapseItem name="globalFilter">
        <template #title><span>{{ globalFilterTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🔍 全局筛选</div>
            <div class="desc-panel-text">全策略共用的股票过滤规则，不满足条件的股票不会进入任何策略的候选池。是第一道质量关卡。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">剔除ST避免退市风险股，建议开启</div>
              <div class="desc-panel-tip">次新股≥60天排除上市初期不稳定波动</div>
              <div class="desc-panel-tip">成交额≥5000万确保流动性，避免卖出困难</div>
              <div class="desc-panel-tip">换手率≥3%排除无人关注的僵尸股</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 强制空仓 -->
      <ElCollapseItem name="forceEmpty">
        <template #title><span>{{ forceEmptyTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">⚠️ 强制空仓</div>
            <div class="desc-panel-text">市场极端情况下的保护机制。当大盘大跌+跌停家数激增时，强制卖出所有持仓，避免系统性暴跌。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">大盘跌≥3%+跌停≥80只→极端恐慌信号</div>
              <div class="desc-panel-tip">触发后次日不会再买入，直到情绪恢复</div>
              <div class="desc-panel-tip">建议保持开启，避免系统性暴跌风险</div>
              <div class="desc-panel-tip">涨停家数阈值<30只，多方力量枯竭</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 情绪周期 -->
      <ElCollapseItem name="sentimentCycle">
        <template #title><span>{{ sentimentCycleTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🧠 情绪周期</div>
            <div class="desc-panel-text">通过多维度指标量化市场情绪，影响各策略的信号强度和仓位分配。情绪得分0~1，高分=强势市场。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">涨停/跌停家数反映多空力量对比</div>
              <div class="desc-panel-tip">炸板率反映打板封板质量，高炸板=弱市</div>
              <div class="desc-panel-tip">北向资金反映外资流向偏好</div>
              <div class="desc-panel-tip">权重之和无需为1，各自独立缩放</div>
              <div class="desc-panel-tip">跌停翘板策略建议要求高情绪周期</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 竞价过滤 -->
      <ElCollapseItem name="auctionFilter">
        <template #title><span>{{ auctionFilterTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">⏰ 竞价过滤</div>
            <div class="desc-panel-text">在集合竞价阶段对候选股进行预筛选，过滤竞价表现不佳的标的。是盘中策略的第一道关卡。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">竞价涨幅2%~8%为宜，过高可能开盘即巅峰</div>
              <div class="desc-panel-tip">未匹配量为正说明买盘强于卖盘</div>
              <div class="desc-panel-tip">竞价量比≥2说明市场关注度高</div>
              <div class="desc-panel-tip">竞价成交额≥1000万排除冷门股</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 半路追涨 -->
      <ElCollapseItem name="halfway_chase">
        <template #title><span>{{ halfwayChaseTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.halfway_chase.enabled" @change="() => toggleStrategy('halfway_chase')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.params.min_rise_pct  * 100).toFixed(1) }}%)</span>
            </ElFormItem>
            <ElFormItem label="最高实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_rise_pct" :min="0" :max="0.3" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.params.max_rise_pct  * 100).toFixed(1) }}%)</span>
            </ElFormItem>
            <ElFormItem label="最低量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_volume_ratio" :min="0.5" :max="10" :step="0.1" :precision="1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最高量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_volume_ratio" :min="1" :max="20" :step="0.1" :precision="1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="最低收盘涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_close_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.params.min_close_rise_pct  * 100).toFixed(1) }}%)</span>
            </ElFormItem>
            <ElFormItem label="最高开盘涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_open_rise_pct" :min="0" :max="0.2" :step="0.005" :precision="3" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.params.max_open_rise_pct  * 100).toFixed(1) }}%)</span>
            </ElFormItem>
            <ElFormItem label="允许10点后买入" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElSwitch v-model="form.strategyConfigs.halfway_chase.params.allow_after_10am" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
            </ElFormItem>
            <ElFormItem label="次日高开即卖≥" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.next_day_open_sell_pct" :min="0" :max="0.1" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.params.next_day_open_sell_pct * 100).toFixed(0) }}%)</span>
            </ElFormItem>
          </div>
                  <!-- 策略风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（可覆盖全局默认值）</div>
            <div class="risk-params-desc">本策略专属的风控参数，优先级高于全局交易参数。半路追涨冲高回落概率大，止损宜严格；止盈12%锁定日内强势收益。</div>
            <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.riskParams.stop_loss_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.riskParams.take_profit_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.max_hold_days" :min="1" :max="10" style="width: 130px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">({{ (form.strategyConfigs.halfway_chase.riskParams.slippage_pct  * 1000).toFixed(1) }}‰)</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🏃‍♂️ 半路追涨策略</div>
            <div class="desc-panel-text">在盘中股票已经上涨但尚未涨停时追入，博弈后续继续冲高甚至封板。核心逻辑：放量上攻的强势股在盘中确认后跟进，适合强势市场的顺势交易。关键过滤：收盘涨幅≥5%确认非冲高回落，开盘涨幅≤3%排除竞价已过热，量比2.0~3.0确认放量而非缩量上涨。⚠️平均收益偏弱(+1.97%)，注意风控。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">核心参数：涨幅3%~7%的强势股，过高风险大</div>
              <div class="desc-panel-tip">量比1.5~3.0确认放量而非缩量上涨</div>
              <div class="desc-panel-tip">收盘涨幅≥5%确认非冲高回落(关键过滤)</div>
              <div class="desc-panel-tip">开盘涨幅≤3%排除竞价已过热的票</div>
              <div class="desc-panel-tip">允许10点后买入可捕捉午盘强势股</div>
              <div class="desc-panel-tip">⚠️ 平均收益偏弱(+1.97%)，注意风控</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 首板打板 -->
      <ElCollapseItem name="first_limit_up">
        <template #title><span>{{ firstLimitUpTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.next_day_open_sell_pct" :min="0" :max="0.1" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">%</span>
            </ElFormItem>
          </div>
          <!-- 成交概率配置 -->
          <div class="risk-params-section">
            <div class="risk-params-title">🎲 成交概率模拟（涨停买入概率）</div>
            <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="一字板" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_yizi" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.params.hit_probability_yizi  * 100).toFixed(0) }}%)</span>
              </ElFormItem>
              <ElFormItem label="秒板(开≥8%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_fast" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.params.hit_probability_fast  * 100).toFixed(0) }}%)</span>
              </ElFormItem>
              <ElFormItem label="快板(开2~8%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_normal" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.params.hit_probability_normal  * 100).toFixed(0) }}%)</span>
              </ElFormItem>
              <ElFormItem label="慢板(开<2%)" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.hit_probability_slow" :min="0" :max="1" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.params.hit_probability_slow  * 100).toFixed(0) }}%)</span>
              </ElFormItem>
            </div>
          </div>
                  <!-- 策略风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（可覆盖全局默认值）</div>
            <div class="risk-params-desc">打板失败后下跌速度快，止损4%为底线。次日高开即卖机制优于固定止盈，滑点5‰模拟涨停排队成交偏差。</div>
            <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.riskParams.stop_loss_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.riskParams.take_profit_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.max_hold_days" :min="1" :max="10" style="width: 130px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">({{ (form.strategyConfigs.first_limit_up.riskParams.slippage_pct  * 1000).toFixed(1) }}‰)</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🥇 首板打板策略</div>
            <div class="desc-panel-text">在股票首次涨停时排队买入，博弈次日高开溢价。成交概率是核心差异：回测模拟了一字板5%/秒板30%/快板60%/慢板80%的实际成交概率。次日高开≥3%自动止盈（高开即卖机制），流通市值20~100亿为最佳区间，换手率5%~15%量价配合最佳。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">成交概率是核心：一字板5%/秒板30%/快板60%/慢板80%</div>
              <div class="desc-panel-tip">流通市值20~100亿为最佳区间</div>
              <div class="desc-panel-tip">换手率5%~15%量价配合最佳</div>
              <div class="desc-panel-tip">次日高开≥3%自动止盈（高开即卖）</div>
              <div class="desc-panel-tip">止损4%为打板策略的底线</div>
              <div class="desc-panel-tip">竞价涨幅-2%~5%排除一字板和低开股</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 涨停开板 -->
      <ElCollapseItem name="limit_up_open">
        <template #title><span>{{ limitUpOpenTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
              <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_turnover_rate" :min="1" :max="50" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">%</span>
            </ElFormItem>
          </div>
                  <!-- 策略风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（可覆盖全局默认值）</div>
            <div class="risk-params-desc">开板回封失败则次日大概率低开，止损4%严格控制风险。回封成功后次日溢价较高，止盈15%锁定利润。</div>
            <div :disabled="!form.strategyConfigs.limit_up_open.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_up_open.riskParams.stop_loss_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_up_open.riskParams.take_profit_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.max_hold_days" :min="1" :max="10" style="width: 130px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_up_open.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_up_open.riskParams.slippage_pct  * 1000).toFixed(1) }}‰)</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">📈 涨停开板策略</div>
            <div class="desc-panel-text">连板股盘中开板后回封时买入，博弈回封后次日继续高开。最少2连板以上确保龙头地位，开板≤10分钟即回封说明主力坚决。回封后封单≥1万手确认抛压已消化。此策略对连板数和回封速度要求严格，是高确定性策略。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">最少2连板以上，确保不是杂毛股</div>
              <div class="desc-panel-tip">开板≤10分钟即回封，说明主力坚决</div>
              <div class="desc-panel-tip">回封后封单≥1万手确认抛压已消化</div>
              <div class="desc-panel-tip">止损4%严格控制开板后继续下跌风险</div>
              <div class="desc-panel-tip">开板时间>10分钟的股回封概率低</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 龙头低吸 -->
      <ElCollapseItem name="dragon_head">
        <template #title><span>{{ dragonHeadTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.min_correction_pct" :min="0" :max="0.5" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.params.min_correction_pct  * 100).toFixed(0) }}%)</span>
            </ElFormItem>
            <ElFormItem label="最高回调幅度" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.max_correction_pct" :min="0.05" :max="0.6" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.params.max_correction_pct  * 100).toFixed(0) }}%)</span>
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
            <ElFormItem label="次日高开即卖≥" :disabled="!form.strategyConfigs.dragon_head.enabled">
              <ElInputNumber v-model="form.strategyConfigs.dragon_head.params.next_day_open_sell_pct" :min="0" :max="0.1" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.params.next_day_open_sell_pct * 100).toFixed(0) }}%)</span>
            </ElFormItem>
          </div>
                  <!-- 策略风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（可覆盖全局默认值）</div>
            <div class="risk-params-desc">龙头股波动较大，止损5%给予更宽的调整空间。低吸后若启动二波涨幅可观，止盈15%平衡收益与回撤风险。</div>
            <div :disabled="!form.strategyConfigs.dragon_head.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.riskParams.stop_loss_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.riskParams.take_profit_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.max_hold_days" :min="1" :max="10" style="width: 130px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.dragon_head.enabled">
                <ElInputNumber v-model="form.strategyConfigs.dragon_head.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.dragon_head.enabled" /><span class="unit">({{ (form.strategyConfigs.dragon_head.riskParams.slippage_pct  * 1000).toFixed(1) }}‰)</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">🐲 龙头低吸策略</div>
            <div class="desc-panel-text">在龙头股回调到支撑位时低吸买入，博弈龙头二波启动。核心：连板龙头+缩量回调到5/10日均线。回调5%~35%为健康调整区间，量比0.5~2.0确认缩量而非放量下跌。适合市场分歧后的再次一致，是低吸高赔率策略。止损5%给予龙头更大的波动空间。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">核心：连板龙头+缩量回调到5/10日均线</div>
              <div class="desc-panel-tip">回调5%~35%为健康调整区间</div>
              <div class="desc-panel-tip">量比0.5~2.0确认缩量而非放量下跌</div>
              <div class="desc-panel-tip">支撑位选5日均线适合强势回调</div>
              <div class="desc-panel-tip">止损5%给龙头更大的波动空间</div>
              <div class="desc-panel-tip">回调天数1~7天，太久趋势已走坏</div>
            </div>
          </div>
        </div>
        </div>
            </ElCollapseItem>

      <!-- 跌停翘板 -->
      <ElCollapseItem name="limit_down_qiao">
        <template #title><span>{{ limitDownQiaoTitle }}</span></template>
        <div class="collapse-content">
        <div class="collapse-content-left">
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
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao" :min="0" :max="0.2" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao  * 100).toFixed(0) }}%)</span>
            </ElFormItem>
            <ElFormItem label="最小流通市值" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_circulation_market_cap" :min="5" :max="500" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="要求高情绪周期" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElSwitch v-model="form.strategyConfigs.limit_down_qiao.params.require_high_sentiment" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
            </ElFormItem>
            <ElFormItem label="最低换手率" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_turnover_rate" :min="1" :max="50" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="次日高开即卖≥" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.next_day_open_sell_pct" :min="0" :max="0.1" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.params.next_day_open_sell_pct * 100).toFixed(0) }}%)</span>
            </ElFormItem>
            <ElFormItem label="冲高回落阈值" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.pullback_mid_fallback_pct" :min="0" :max="0.05" :step="0.005" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.params.pullback_mid_fallback_pct * 100).toFixed(1) }}%)</span>
            </ElFormItem>
          </div>
                  <!-- 策略风控参数 -->
          <div class="risk-params-section">
            <div class="risk-params-title">💹 策略风控（可覆盖全局默认值）</div>
            <div class="risk-params-desc">跌停翘板是高风险高回报策略，翘板失败继续跌停概率大，止损4%严格控损。翘板成功后反弹空间大，止盈20%平衡赔率与利润兑现。</div>
            <div :disabled="!form.strategyConfigs.limit_down_qiao.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="止损比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.stop_loss_pct" :min="0.005" :max="0.15" :step="0.005" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.riskParams.stop_loss_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="止盈比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.take_profit_pct" :min="0.01" :max="0.5" :step="0.01" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.riskParams.take_profit_pct  * 100).toFixed(1) }}%)</span>
              </ElFormItem>
              <ElFormItem label="最大持仓天数" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.max_hold_days" :min="1" :max="10" style="width: 130px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="滑点比例" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.riskParams.slippage_pct" :min="0" :max="0.01" :step="0.001" :precision="3" style="width: 130px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">({{ (form.strategyConfigs.limit_down_qiao.riskParams.slippage_pct  * 1000).toFixed(1) }}‰)</span>
              </ElFormItem>
            </div>
          </div>
        </ElForm>
        </div>
        <div class="collapse-content-right">
          <div class="desc-panel">
            <div class="desc-panel-title">💥 跌停翘板策略</div>
            <div class="desc-panel-text">在跌停板被大资金撬开时追入，博弈翘板后的大幅反弹。高风险高回报：翘板失败可能继续跌停，翘板成功反弹空间可观。连跌2天以上才有足够恐慌释放，翘板金额≥1000万确认大资金介入，翘板后涨幅≥3%确认反转力度。建议配合情绪周期，市场强势时翘板成功率高。</div>
            <div class="desc-panel-tips">
              <div class="desc-panel-tips-title">💡 调优建议</div>
              <div class="desc-panel-tip">连跌1天以上才有足够恐慌释放</div>
              <div class="desc-panel-tip">翘板金额≥1000万确认大资金介入</div>
              <div class="desc-panel-tip">翘板后涨幅≥3%确认反转力度</div>
              <div class="desc-panel-tip">建议开启高情绪周期要求（市场强势时翘板成功率高）</div>
              <div class="desc-panel-tip">止损4%+止盈20%：高赔率策略</div>
            </div>
          </div>
        </div>
        </div>
      </ElCollapseItem>
    </ElCollapse>
  </ElCard>
    </template>

    <!-- 执行流程模式 -->
    <template v-if="configMode === 'flow'">
      <ElCard class="config-card">
        <template #header>
          <div class="card-header">
            <span>🔄 策略执行流程（详细决策树）</span>
            <div class="header-actions">
              <ElButton @click="emit('submit')" :icon="Play" type="success" :loading="backtestRunning" size="default">
                {{ backtestRunning ? '回测中...' : '开始回测' }}
              </ElButton>
            </div>
          </div>
        </template>
        <div class="flow-container">

          <!-- ═══ 1. 数据源 ═══ -->
          <div class="flow-step">
            <div class="flow-step-header">
              <div class="flow-step-num">1</div>
              <div class="flow-step-title">🔌 数据源加载</div>
              <div class="flow-step-badge">{{ form.dataSource.period === 'daily' ? '日线' : '1分钟' }} · {{ form.dataSource.adjust_type === 'qfq' ? '前复权' : '不复权' }}</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-desc">从MongoDB加载K线数据，日期范围 {{ form.dataSource.start_date }} ~ {{ form.dataSource.end_date }}，初始资金 ¥{{ (form.base.initial_cash / 10000).toFixed(0) }}万</div>
              <div class="flow-logic">
                <div class="flow-cond">IF 股票代码在 ts_codes 白名单 → 加载</div>
                <div class="flow-cond">ELSE IF ts_codes 为空 → 加载全市场</div>
                <div class="flow-cond">数据字段: OHLCV + 涨停价/跌停价 + 换手率 + 流通市值</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 2. 全局筛选 ═══ -->
          <div class="flow-step">
            <div class="flow-step-header">
              <div class="flow-step-num">2</div>
              <div class="flow-step-title">🔍 全局筛选（逐条过滤）</div>
              <div class="flow-step-badge">输出: 候选股票池</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond flow-cond-reject">❌ ST股 → 剔除{{ form.globalFilter.exclude_st ? '✓' : '✗' }}</div>
                <div class="flow-cond flow-cond-reject">❌ 退市股 → 剔除{{ form.globalFilter.exclude_delisting ? '✓' : '✗' }}</div>
                <div class="flow-cond flow-cond-reject">❌ 次新股(上市 < {{ form.globalFilter.exclude_new_stock_days }}天) → 剔除</div>
                <div class="flow-cond flow-cond-reject">❌ 日成交额 < {{ form.globalFilter.min_daily_amount }}万 → 剔除</div>
                <div class="flow-cond flow-cond-reject">❌ 换手率 < {{ form.globalFilter.min_turnover_rate }}% → 剔除</div>
                <div class="flow-cond flow-cond-accept">✅ 通过全部筛选 → 进入候选池</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 3. 情绪周期 ═══ -->
          <div class="flow-step" :class="{ 'flow-disabled': !form.sentimentCycle.enabled }">
            <div class="flow-step-header">
              <div class="flow-step-num">3</div>
              <div class="flow-step-title">🧠 情绪周期判断 {{ form.sentimentCycle.enabled ? '' : '(未启用→跳过)' }}</div>
              <div class="flow-step-badge">得分0~100</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond">计算: 涨停数×{{ form.sentimentCycle.weight_limit_up }} + 跌停数×{{ form.sentimentCycle.weight_limit_down }} + ... → 情绪得分</div>
                <div class="flow-cond flow-cond-branch">IF 得分 ≥ 70 → 🟢 强势(激进策略信号加强，仓位上限放宽)</div>
                <div class="flow-cond flow-cond-branch">IF 30 ≤ 得分 < 70 → 🟡 震荡(正常信号强度，标准仓位)</div>
                <div class="flow-cond flow-cond-branch">IF 得分 < 30 → 🔴 弱势(保守策略信号减弱，仓位收紧)</div>
                <div class="flow-cond">影响: 各策略的信号权重 × 情绪系数，仓位上限 × 情绪系数</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 4. 竞价过滤 ═══ -->
          <div class="flow-step" :class="{ 'flow-disabled': !form.auctionFilter.enabled }">
            <div class="flow-step-header">
              <div class="flow-step-num">4</div>
              <div class="flow-step-title">⏰ 集合竞价预筛 {{ form.auctionFilter.enabled ? '' : '(未启用→跳过)' }}</div>
              <div class="flow-step-badge">9:15~9:25</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond">竞价涨幅范围: {{ (form.auctionFilter.min_auction_pct * 100).toFixed(1) }}% ~ {{ (form.auctionFilter.max_auction_pct * 100).toFixed(1) }}%</div>
                <div class="flow-cond flow-cond-branch">IF 竞价涨幅在范围内 → 进入盘中监控</div>
                <div class="flow-cond flow-cond-reject">ELSE → 剔除(竞价过高/过低都不参与)</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 5. 策略信号生成(核心) ═══ -->
          <div class="flow-step flow-step-group">
            <div class="flow-step-header">
              <div class="flow-step-num">5</div>
              <div class="flow-step-title">📊 策略信号生成（逐股遍历候选池）</div>
              <div class="flow-step-badge">{{ form.strategies.length }}个策略并行</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-desc">对候选池中每只股票，依次用已启用的策略判断是否产生买入信号</div>
              <div class="flow-strategies">

                <!-- 半路追涨 -->
                <div v-if="form.strategyConfigs.halfway_chase.enabled" class="flow-strategy-card">
                  <div class="flow-strategy-header">🏃‍♂️ 半路追涨</div>
                  <div class="flow-logic">
                    <div class="flow-cond">① 实时涨幅 {{ (form.strategyConfigs.halfway_chase.params.min_rise_pct * 100).toFixed(1) }}% ~ {{ (form.strategyConfigs.halfway_chase.params.max_rise_pct * 100).toFixed(1) }}%?</div>
                    <div class="flow-cond">② 量比 {{ form.strategyConfigs.halfway_chase.params.min_volume_ratio }} ~ {{ form.strategyConfigs.halfway_chase.params.max_volume_ratio }}?</div>
                    <div class="flow-cond">③ 收盘涨幅 ≥ {{ (form.strategyConfigs.halfway_chase.params.min_close_rise_pct * 100).toFixed(1) }}%?</div>
                    <div class="flow-cond">④ 开盘涨幅 ≤ {{ (form.strategyConfigs.halfway_chase.params.max_open_rise_pct * 100).toFixed(1) }}%?</div>
                    <div class="flow-cond">⑤ {{ form.strategyConfigs.halfway_chase.params.allow_after_10am ? '允许' : '不允许' }}10点后买入</div>
                    <div class="flow-cond flow-cond-branch">→ 次日高开 ≥ {{ (form.strategyConfigs.halfway_chase.params.next_day_open_sell_pct * 100).toFixed(0) }}% → 冲高回落保护</div>
                    <div class="flow-cond flow-cond-accept">✅ 全部满足 → 产生买入信号</div>
                    <div class="flow-cond flow-cond-reject">❌ 任一不满足 → 跳过</div>
                  </div>
                </div>

                <!-- 首板打板 -->
                <div v-if="form.strategyConfigs.first_limit_up.enabled" class="flow-strategy-card">
                  <div class="flow-strategy-header">🥇 首板打板</div>
                  <div class="flow-logic">
                    <div class="flow-cond">① 首次涨停(非连板)?</div>
                    <div class="flow-cond">② 开盘涨幅 {{ form.strategyConfigs.first_limit_up.params.opening_pct_min }}% ~ {{ form.strategyConfigs.first_limit_up.params.opening_pct_max }}%?</div>
                    <div class="flow-cond">③ 量比 ≥ {{ form.strategyConfigs.first_limit_up.params.min_volume_ratio }}?</div>
                    <div class="flow-cond">④ 换手率 {{ form.strategyConfigs.first_limit_up.params.min_turnover_rate }}% ~ {{ form.strategyConfigs.first_limit_up.params.max_turnover_rate }}%?</div>
                    <div class="flow-cond">⑤ 流通市值 {{ form.strategyConfigs.first_limit_up.params.min_circulation_market_cap }} ~ {{ form.strategyConfigs.first_limit_up.params.max_circulation_market_cap }}亿?</div>
                    <div class="flow-cond flow-cond-branch">→ 成交概率模拟: 一字板{{ (form.strategyConfigs.first_limit_up.params.hit_probability_yizi * 100).toFixed(0) }}% / 秒板{{ (form.strategyConfigs.first_limit_up.params.hit_probability_fast * 100).toFixed(0) }}% / 快板{{ (form.strategyConfigs.first_limit_up.params.hit_probability_normal * 100).toFixed(0) }}% / 慢板{{ (form.strategyConfigs.first_limit_up.params.hit_probability_slow * 100).toFixed(0) }}%</div>
                    <div class="flow-cond flow-cond-branch">→ 次日高开 ≥ {{ (form.strategyConfigs.first_limit_up.params.next_day_open_sell_pct * 100).toFixed(0) }}% → 自动卖出</div>
                    <div class="flow-cond flow-cond-accept">✅ 全部满足 → 按概率决定是否成交</div>
                  </div>
                </div>

                <!-- 涨停开板 -->
                <div v-if="form.strategyConfigs.limit_up_open.enabled" class="flow-strategy-card">
                  <div class="flow-strategy-header">📈 涨停开板回封</div>
                  <div class="flow-logic">
                    <div class="flow-cond">① 连板数 ≥ {{ form.strategyConfigs.limit_up_open.params.min_consecutive_limit }}板?</div>
                    <div class="flow-cond">② 盘中开板时长 ≤ {{ form.strategyConfigs.limit_up_open.params.max_open_duration }}分钟?</div>
                    <div class="flow-cond">③ 回封后封单 ≥ {{ form.strategyConfigs.limit_up_open.params.min_seal_after_open }}万?</div>
                    <div class="flow-cond">④ 换手率 ≥ {{ form.strategyConfigs.limit_up_open.params.min_turnover_rate }}%?</div>
                    <div class="flow-cond">⑤ 开盘涨幅 {{ form.strategyConfigs.limit_up_open.params.opening_pct_min }}% ~ {{ form.strategyConfigs.limit_up_open.params.opening_pct_max }}%?</div>
                    <div class="flow-cond">⑥ 量比 ≥ {{ form.strategyConfigs.limit_up_open.params.min_volume_ratio }}?</div>
                    <div class="flow-cond flow-cond-accept">✅ 全部满足 → 开板时买入，等回封确认</div>
                    <div class="flow-cond flow-cond-reject">❌ 超时未回封 → 放弃/次日止损</div>
                  </div>
                </div>

                <!-- 龙头低吸 -->
                <div v-if="form.strategyConfigs.dragon_head.enabled" class="flow-strategy-card">
                  <div class="flow-strategy-header">🐲 龙头低吸</div>
                  <div class="flow-logic">
                    <div class="flow-cond">① 连板数 ≥ {{ form.strategyConfigs.dragon_head.params.min_consecutive_limit }}板(确认龙头)?</div>
                    <div class="flow-cond">② 回调幅度 {{ (form.strategyConfigs.dragon_head.params.min_correction_pct * 100).toFixed(0) }}% ~ {{ (form.strategyConfigs.dragon_head.params.max_correction_pct * 100).toFixed(0) }}%?</div>
                    <div class="flow-cond">③ 量比 {{ form.strategyConfigs.dragon_head.params.min_volume_ratio }} ~ {{ form.strategyConfigs.dragon_head.params.max_volume_ratio }}(缩量回调)?</div>
                    <div class="flow-cond">④ 回调天数 {{ form.strategyConfigs.dragon_head.params.correction_days_min }} ~ {{ form.strategyConfigs.dragon_head.params.correction_days_max }}天?</div>
                    <div class="flow-cond flow-cond-branch">→ 触发均线支撑: 5日/10日均线附近</div>
                    <div class="flow-cond flow-cond-branch">→ 次日高开 ≥ {{ (form.strategyConfigs.dragon_head.params.next_day_open_sell_pct * 100).toFixed(0) }}% → 冲高回落保护</div>
                    <div class="flow-cond flow-cond-accept">✅ 全部满足 → 低吸买入</div>
                  </div>
                </div>

                <!-- 跌停翘板 -->
                <div v-if="form.strategyConfigs.limit_down_qiao.enabled" class="flow-strategy-card">
                  <div class="flow-strategy-header">💥 跌停翘板</div>
                  <div class="flow-logic">
                    <div class="flow-cond">① 连续跌停 ≥ {{ form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit }}天?</div>
                    <div class="flow-cond">② 翘板金额 ≥ {{ form.strategyConfigs.limit_down_qiao.params.min_qiao_amount }}万(大资金介入)?</div>
                    <div class="flow-cond">③ 翘板后涨幅 ≥ {{ (form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao * 100).toFixed(0) }}%(确认反转)?</div>
                    <div class="flow-cond">④ 流通市值 ≥ {{ form.strategyConfigs.limit_down_qiao.params.min_circulation_market_cap }}亿?</div>
                    <div class="flow-cond">⑤ {{ form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '要求高情绪周期(得分≥60)' : '不限情绪周期' }}</div>
                    <div class="flow-cond flow-cond-branch">→ 次日高开 ≥ {{ (form.strategyConfigs.limit_down_qiao.params.next_day_open_sell_pct * 100).toFixed(0) }}% → 冲高回落保护</div>
                    <div class="flow-cond flow-cond-branch">→ 盘中回落 ≥ {{ (form.strategyConfigs.limit_down_qiao.params.pullback_mid_fallback_pct * 100).toFixed(1) }}% → 利润保护触发</div>
                    <div class="flow-cond flow-cond-accept">✅ 全部满足 → 翘板时追入</div>
                    <div class="flow-cond flow-cond-reject">❌ 翘板失败继续跌停 → 次日止损</div>
                  </div>
                </div>

              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 6. 风控与仓位 ═══ -->
          <div class="flow-step">
            <div class="flow-step-header">
              <div class="flow-step-num">6</div>
              <div class="flow-step-title">🛡️ 风控与仓位管理</div>
              <div class="flow-step-badge">逐信号判断</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond flow-cond-branch">① 当前总仓位 + 本次仓位 ≤ {{ (form.tradeParams.max_total_position * 100).toFixed(0) }}%?</div>
                <div class="flow-cond flow-cond-branch">② 单票仓位 ≤ {{ (form.tradeParams.max_position_per_stock * 100).toFixed(0) }}%?</div>
                <div class="flow-cond flow-cond-branch">③ 同一股票不同策略信号 → 取信号最强的策略</div>
                <div class="flow-cond flow-cond-accept">✅ 通过 → 执行买入</div>
                <div class="flow-cond flow-cond-reject">❌ 超限 → 缩减仓位或放弃</div>
                <div class="flow-cond">交易成本: 佣金{{ (form.tradeParams.commission_rate * 1000).toFixed(1) }}‰ + 印花税{{ (form.tradeParams.stamp_duty_rate * 1000).toFixed(0) }}‰ + 滑点{{ (form.tradeParams.slippage_pct * 1000).toFixed(1) }}‰</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 7. 强制空仓 ═══ -->
          <div class="flow-step" :class="{ 'flow-disabled': !form.forceEmpty.enabled }">
            <div class="flow-step-header">
              <div class="flow-step-num">7</div>
              <div class="flow-step-title">⚠️ 强制空仓 {{ form.forceEmpty.enabled ? '' : '(未启用→跳过)' }}</div>
              <div class="flow-step-badge">极端行情</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond flow-cond-branch">IF 指数跌幅 ≥ {{ (form.forceEmpty.index_drop_pct * 100).toFixed(1) }}% → 触发</div>
                <div class="flow-cond flow-cond-branch">IF 跌停数 ≥ {{ form.forceEmpty.limit_down_count }}只 → 触发</div>
                <div class="flow-cond flow-cond-accept">→ 清仓所有持仓，次日不买入，等待情绪恢复</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 8. 卖出决策(核心) ═══ -->
          <div class="flow-step flow-step-group">
            <div class="flow-step-header">
              <div class="flow-step-num">8</div>
              <div class="flow-step-title">📤 卖出决策（按优先级逐条判断）</div>
              <div class="flow-step-badge">每日盘后/盘中</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-desc">对每笔持仓，按以下优先级依次判断，触发任一即卖出：</div>
              <div class="flow-logic">
                <div class="flow-cond flow-cond-priority">🔴 P1 强制空仓 — 极端行情触发，无条件清仓</div>
                <div class="flow-cond flow-cond-priority">🟠 P2 止损 — 跌幅 ≥ 策略止损%(策略级覆盖 > 全局默认)</div>
                <div class="flow-cond flow-cond-priority">🟡 P3 最大持仓天数 — 持仓 > 策略max_hold_days天 → 卖出</div>
                <div class="flow-cond flow-cond-priority">🟢 P4 高开即卖 — 次日高开 ≥ 阈值(3%+) → 开盘卖出(半路/首板/龙头/跌停翘板通用)</div>
                <div class="flow-cond flow-cond-priority">🔵 P5 利润保护 — 盈利后冲高回落超阈值(pullback_mid_fallback_pct) → 锁定部分利润</div>
                <div class="flow-cond flow-cond-priority">🟣 P6 止盈 — 涨幅 ≥ 策略止盈% → 卖出</div>
                <div class="flow-cond flow-cond-priority">⚪ P7 利润锁定(V42新增) — 盘中大幅冲高后回撤 → 保护性卖出(不扣滑点)</div>
                <div class="flow-cond">未触发任何条件 → 继续持有</div>
              </div>
              <div class="flow-detail" style="margin-top:8px">
                <span>策略级风控优先于全局默认值</span>
                <span>卖出后资金回到可用余额，次日可重新分配</span>
              </div>
            </div>
          </div>
          <div class="flow-arrow">▼</div>

          <!-- ═══ 9. 结算 ═══ -->
          <div class="flow-step">
            <div class="flow-step-header">
              <div class="flow-step-num">9</div>
              <div class="flow-step-title">💰 日终结算</div>
              <div class="flow-step-badge">记录交易日志</div>
            </div>
            <div class="flow-step-body">
              <div class="flow-logic">
                <div class="flow-cond">① 更新持仓成本/浮盈/浮亏</div>
                <div class="flow-cond">② 记录当日买卖交易到日志</div>
                <div class="flow-cond">③ 计算当日净值/累计收益/回撤</div>
                <div class="flow-cond">④ 进入下一交易日，回到步骤2</div>
              </div>
            </div>
          </div>

        </div>
      </ElCard>
    </template>
  </div>
</template>

<script lang="ts">
export default { name: 'StrategyConfigPanel' }
</script>

<style scoped lang="scss">
.config-layout-v2 {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* 模式切换 */
.mode-switcher {
  display: flex;
  gap: 0;
  margin-bottom: 12px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  overflow: hidden;
  width: fit-content;
}
.mode-btn {
  padding: 7px 20px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  &:hover { background: var(--bg-hover); }
  &.active {
    background: var(--primary-500);
    color: #fff;
  }
}

/* 展开区域左右布局 */
.collapse-content {
  display: flex;
  gap: 0;
  align-items: stretch;
  position: relative;
}
.collapse-content-left {
  flex: 1;
  min-width: 0;
  padding-right: 16px;
  max-width: 50%;
}
.collapse-content-right {
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  align-items: center;
  padding-left: 24px;
  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 10%;
    bottom: 10%;
    width: 1px;
    background: var(--border-default);
  }
  &::after {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    width: 12px;
    height: 1px;
    background: var(--primary-300);
  }
}
.desc-panel {
  background: var(--bg-muted);
  border: 1px solid var(--border-default);
  border-left: 3px solid var(--primary-400);
  border-radius: 6px;
  padding: 14px 16px;
}
.desc-panel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 10px;
}
.desc-panel-text {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.8;
  margin-bottom: 12px;
}
.desc-panel-tips {
  border-top: 1px solid var(--border-default);
  padding-top: 8px;
  margin-top: 2px;
}
.desc-panel-tips-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary-500);
  margin-bottom: 8px;
}
.desc-panel-tip {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
  padding-left: 10px;
  position: relative;
  &::before {
    content: '•';
    position: absolute;
    left: 0;
    color: var(--primary-400);
  }
}

.section-desc {
  display: none;
}

/* 执行流程 */
.flow-container {
  padding: 8px 0;
}
.flow-step {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 14px 18px;
  transition: all 0.2s;
  &.flow-disabled {
    opacity: 0.45;
    border-style: dashed;
  }
  &:hover { border-color: var(--primary-300); }
  &.flow-step-group {
    border-color: var(--primary-200);
    border-width: 2px;
    background: linear-gradient(135deg, var(--bg-elevated) 0%, rgba(var(--primary-100), 0.05) 100%);
  }
}
.flow-step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.flow-step-num {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--primary-500);
  color: #fff;
  border-radius: 50%;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}
.flow-step-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.flow-step-badge {
  font-size: 12px;
  color: var(--text-tertiary);
  background: var(--bg-muted);
  padding: 2px 10px;
  border-radius: 10px;
  margin-left: auto;
  white-space: nowrap;
}
.flow-step-body {
  padding-left: 38px;
}
.flow-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 6px;
}
.flow-logic {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.flow-cond {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--bg-muted);
  &.flow-cond-reject {
    border-left: 3px solid #f56c6c;
    color: #f56c6c;
    background: rgba(245, 108, 108, 0.06);
  }
  &.flow-cond-accept {
    border-left: 3px solid #67c23a;
    color: #67c23a;
    background: rgba(103, 194, 58, 0.06);
  }
  &.flow-cond-branch {
    border-left: 3px solid #409eff;
    color: #409eff;
    background: rgba(64, 158, 255, 0.06);
  }
  &.flow-cond-priority {
    font-weight: 500;
    padding: 4px 10px;
  }
}
.flow-detail {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
}
.flow-arrow {
  text-align: center;
  color: var(--primary-300);
  font-size: 16px;
  font-weight: 700;
  padding: 3px 0;
  line-height: 1;
}
.flow-strategies {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.flow-strategy-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  padding: 10px 14px;
}
.flow-strategy-header {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-default);
}

.config-card {
  margin-bottom: 12px;
  :deep(.el-card__header) { padding: 8px 16px; }
  :deep(.el-card__body) { padding: 12px 16px; }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 14px;
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .sweep-toggle {
      display: flex;
      align-items: center;
      gap: 4px;
      .sweep-label {
        font-size: 12px;
        color: #606266;
      }
    }
  }
}
.sweep-config {
  padding: 12px 16px;
  background: var(--info-bg);
  border-radius: 6px;
  margin-bottom: 12px;
  border: 1px dashed var(--primary-400);
  .sweep-config-layout {
    display: flex;
    gap: 24px;
    align-items: flex-start;
  }
  .sweep-config-left {
    flex: 0 0 380px;
  }
  .sweep-config-right {
    flex: 1;
    min-width: 0;
  }
  .sweep-config-title {
    font-weight: 600;
    font-size: 14px;
    color: var(--primary-500);
    margin-bottom: 8px;
  }
}
.unit {
  margin-left: 8px;
  color: var(--text-tertiary);
}
.risk-params-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 2px solid var(--border-default);
  .risk-params-title {
    font-weight: 600;
    font-size: 13px;
    color: var(--primary-500);
    margin-bottom: 4px;
    padding-left: 6px;
    border-left: 3px solid var(--warning);
    line-height: 1;
  }
  .risk-params-desc {
    font-size: 12px;
    color: var(--text-tertiary);
    line-height: 1.6;
    margin-bottom: 10px;
    padding-left: 9px;
  }
}
.risk-override-group {
  padding: 10px 0;
  border-bottom: 1px dashed var(--border-default);
  &:last-child { border-bottom: none; }
}
.risk-override-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
:deep(.el-collapse) {
  border-top: 2px solid var(--border-default) !important;
}
:deep(.el-collapse-item__header) {
  white-space: normal !important;
  overflow: visible !important;
  padding-right: 40px !important;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-default) !important;
  font-size: 14px;
  line-height: 1.5;
  min-height: 44px;
  height: auto !important;
}
:deep(.el-collapse-item__header::-webkit-scrollbar) { height: 4px; }
:deep(.el-collapse-item__header::-webkit-scrollbar-thumb) { background-color: var(--border-muted); border-radius: 2px; }
:deep(.el-collapse-item__arrow) {
  position: absolute;
  right: 15px;
  background: var(--bg-elevated);
  padding-left: 10px;
}
</style>
