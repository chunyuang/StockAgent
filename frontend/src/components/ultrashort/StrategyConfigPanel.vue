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

const props = defineProps<{
  form: any
  backtestRunning: boolean
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

const halfwayChaseTitle = computed(() => `🏃‍♂️ 半路追涨策略 ${props.form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌'} (涨幅${(props.form.strategyConfigs.halfway_chase.params.min_rise_pct * 100).toFixed(1)}%~${(props.form.strategyConfigs.halfway_chase.params.max_rise_pct * 100).toFixed(1)}%, 量比≥${props.form.strategyConfigs.halfway_chase.params.min_volume_ratio}倍, 10点后买入: ${props.form.strategyConfigs.halfway_chase.params.allow_after_10am ? '✅' : '❌'})`)
const firstLimitUpTitle = computed(() => `🥇 首板打板策略 ${props.form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌'} (封单≥${props.form.strategyConfigs.first_limit_up.params.min_seal_amount}万, ≤${props.form.strategyConfigs.first_limit_up.params.max_limit_up_time}涨停, 热点板块: ${props.form.strategyConfigs.first_limit_up.params.require_hot_sector ? '✅' : '❌'})`)
const limitUpOpenTitle = computed(() => `📈 涨停开板策略 ${props.form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌'} (连板≥${props.form.strategyConfigs.limit_up_open.params.min_consecutive_limit}板, 开板≤${props.form.strategyConfigs.limit_up_open.params.max_open_duration}分钟)`)
const leaderBuyDipTitle = computed(() => `🐲 龙头低吸策略 ${props.form.strategyConfigs.leader_buy_dip.enabled ? '✅' : '❌'} (连板≥${props.form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit}板, 回调${(props.form.strategyConfigs.leader_buy_dip.params.min_correction_pct * 100).toFixed(0)}%~${(props.form.strategyConfigs.leader_buy_dip.params.max_correction_pct * 100).toFixed(0)}%)`)
const limitDownQiaoTitle = computed(() => `💥 跌停翘板策略 ${props.form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌'} (连板≥${props.form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit}板, 翘板金额≥${props.form.strategyConfigs.limit_down_qiao.params.min_qiao_amount}万, 仅高潮期: ${props.form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '✅' : '❌'})`)

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
</script>

<template>
  <ElCard class="config-card">
    <template #header>
      <div class="card-header">
        <span>⚙️ 回测配置</span>
        <ElButton @click="emit('submit')" :icon="Play" type="success" :loading="backtestRunning" size="large">
          {{ backtestRunning ? '回测中...' : '开始回测' }}
        </ElButton>
      </div>
    </template>

    <ElCollapse v-model="activeCollapse">
      <!-- 数据源配置 -->
      <ElCollapseItem name="dataSource">
        <template #title><span>{{ dataSourceTitle }}</span></template>
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
            <ElInput v-model="form.dataSource.start_date" placeholder="YYYYMMDD" />
          </ElFormItem>
          <ElFormItem label="结束日期">
            <ElInput v-model="form.dataSource.end_date" placeholder="YYYYMMDD" />
          </ElFormItem>
        </ElForm>
      </ElCollapseItem>

      <!-- 基础配置 -->
      <ElCollapseItem name="baseConfig">
        <template #title><span>{{ baseConfigTitle }}</span></template>
        <ElForm label-width="120px">
          <ElFormItem label="初始资金">
            <ElInputNumber v-model="form.base.initial_cash" :min="100000" :max="1000000000" style="width: 200px" prefix="¥" />
          </ElFormItem>
        </ElForm>
      </ElCollapseItem>

      <!-- 交易参数 -->
      <ElCollapseItem name="tradeParams">
        <template #title><span>{{ tradeParamsTitle }}</span></template>
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
      </ElCollapseItem>

      <!-- 全局筛选 -->
      <ElCollapseItem name="globalFilter">
        <template #title><span>{{ globalFilterTitle }}</span></template>
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
      </ElCollapseItem>

      <!-- 强制空仓 -->
      <ElCollapseItem name="forceEmpty">
        <template #title><span>{{ forceEmptyTitle }}</span></template>
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
      </ElCollapseItem>

      <!-- 情绪周期 -->
      <ElCollapseItem name="sentimentCycle">
        <template #title><span>{{ sentimentCycleTitle }}</span></template>
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
      </ElCollapseItem>

      <!-- 竞价过滤 -->
      <ElCollapseItem name="auctionFilter">
        <template #title><span>{{ auctionFilterTitle }}</span></template>
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
      </ElCollapseItem>

      <!-- 半路追涨 -->
      <ElCollapseItem name="halfway_chase">
        <template #title><span>{{ halfwayChaseTitle }}</span></template>
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.halfway_chase.enabled" @change="() => toggleStrategy('halfway_chase')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_rise_pct" :min="0" :max="0.2" :step="0.001" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最高实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_rise_pct" :min="0" :max="0.3" :step="0.001" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最低量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_volume_ratio" :min="1" :max="10" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" /><span class="unit">倍</span>
            </ElFormItem>
            <ElFormItem label="允许10点后买入" :disabled="!form.strategyConfigs.halfway_chase.enabled">
              <ElSwitch v-model="form.strategyConfigs.halfway_chase.params.allow_after_10am" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
            </ElFormItem>
          </div>
        </ElForm>
      </ElCollapseItem>

      <!-- 首板打板 -->
      <ElCollapseItem name="first_limit_up">
        <template #title><span>{{ firstLimitUpTitle }}</span></template>
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.first_limit_up.enabled" @change="() => toggleStrategy('first_limit_up')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低封单金额" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.min_seal_amount" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="最晚涨停时间" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInput v-model="form.strategyConfigs.first_limit_up.params.max_limit_up_time" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
            </ElFormItem>
            <ElFormItem label="最大流通市值" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_circulation_market_cap" :min="10" :max="1000" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">亿</span>
            </ElFormItem>
            <ElFormItem label="最大炸板次数" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_blast_count" :min="0" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" /><span class="unit">次</span>
            </ElFormItem>
            <ElFormItem label="要求是热点板块" :disabled="!form.strategyConfigs.first_limit_up.enabled">
              <ElSwitch v-model="form.strategyConfigs.first_limit_up.params.require_hot_sector" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
            </ElFormItem>
          </div>
        </ElForm>
      </ElCollapseItem>

      <!-- 涨停开板 -->
      <ElCollapseItem name="limit_up_open">
        <template #title><span>{{ limitUpOpenTitle }}</span></template>
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
        </ElForm>
      </ElCollapseItem>

      <!-- 龙头低吸 -->
      <ElCollapseItem name="leader_buy_dip">
        <template #title><span>{{ leaderBuyDipTitle }}</span></template>
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.leader_buy_dip.enabled" @change="() => toggleStrategy('leader_buy_dip')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.leader_buy_dip.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低连板高度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit" :min="3" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" /><span class="unit">板</span>
            </ElFormItem>
            <ElFormItem label="最低回调幅度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.min_correction_pct" :min="0" :max="0.5" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最高回调幅度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.max_correction_pct" :min="0" :max="1" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最少回调天数" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.correction_days_min" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" /><span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="最多回调天数" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.correction_days_max" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" /><span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="支撑位" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
              <ElSelect v-model="form.strategyConfigs.leader_buy_dip.params.support_level" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElOption label="MA5" value="ma5" />
                <ElOption label="MA10" value="ma10" />
                <ElOption label="平台" value="platform" />
              </ElSelect>
            </ElFormItem>
          </div>
        </ElForm>
      </ElCollapseItem>

      <!-- 跌停翘板 -->
      <ElCollapseItem name="limit_down_qiao">
        <template #title><span>{{ limitDownQiaoTitle }}</span></template>
        <ElForm label-width="160px">
          <ElFormItem label="启用策略"><ElSwitch v-model="form.strategyConfigs.limit_down_qiao.enabled" @change="() => toggleStrategy('limit_down_qiao')" /></ElFormItem>
          <div :disabled="!form.strategyConfigs.limit_down_qiao.enabled" class="grid grid-cols-2 gap-4">
            <ElFormItem label="最低连板高度" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit" :min="3" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">板</span>
            </ElFormItem>
            <ElFormItem label="翘板最低成交额" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_qiao_amount" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="翘板后最低涨幅" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao" :min="0" :max="0.2" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" /><span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="仅情绪高潮期允许" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
              <ElSwitch v-model="form.strategyConfigs.limit_down_qiao.params.require_high_sentiment" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
            </ElFormItem>
          </div>
        </ElForm>
      </ElCollapseItem>
    </ElCollapse>
  </ElCard>
</template>

<script lang="ts">
export default { name: 'StrategyConfigPanel' }
</script>

<style scoped lang="scss">
.config-card {
  margin-bottom: 20px;
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 16px;
  }
}
.unit {
  margin-left: 8px;
  color: #909399;
}
:deep(.el-collapse-item__header) {
  white-space: nowrap !important;
  overflow-x: auto !important;
  padding-right: 40px !important;
}
:deep(.el-collapse-item__header::-webkit-scrollbar) { height: 4px; }
:deep(.el-collapse-item__header::-webkit-scrollbar-thumb) { background-color: #dcdfe6; border-radius: 2px; }
:deep(.el-collapse-item__arrow) {
  position: absolute;
  right: 15px;
  background: #fff;
  padding-left: 10px;
}
</style>
