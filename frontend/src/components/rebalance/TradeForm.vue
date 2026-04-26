<script setup lang="ts">
/**
 * TradeForm - 买入/卖出交易表单组件
 * 支持股票代码选择、数量输入、价格输入、策略标注
 */
import { reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { SimAccount, Position } from '@/api'
import {
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElSelect,
  ElOption,
  ElRadioGroup,
  ElRadioButton,
  ElButton,
} from 'element-plus'

const props = defineProps<{
  accounts: SimAccount[]
  positions: Position[]
}>()

const emit = defineEmits<{
  (e: 'trade', payload: { account_id: string; ts_code: string; stock_name: string; direction: 'buy' | 'sell'; quantity: number; price: number; strategy: string; reason: string }): void
}>()

const form = reactive({
  account_id: '',
  direction: 'buy' as 'buy' | 'sell',
  ts_code: '',
  stock_name: '',
  quantity: 100,
  price: 0,
  strategy: '',
  reason: '',
})

// 初始化默认账户
watch(() => props.accounts, (val) => {
  if (val.length > 0 && !form.account_id) {
    form.account_id = val[0].account_id
  }
}, { immediate: true })

// 卖出时，只能从持仓中选择
const sellOptions = computed(() => {
  return props.positions.filter(p => p.quantity > 0)
})

// 估算金额
const estimatedAmount = computed(() => {
  return form.quantity * form.price
})

// 佣金
const commission = computed(() => {
  const c = estimatedAmount.value * 0.0002
  return Math.max(c, 5)
})

// 印花税（卖出时）
const stampDuty = computed(() => {
  if (form.direction === 'sell') {
    return estimatedAmount.value * 0.001
  }
  return 0
})

// 总费用
const totalCost = computed(() => {
  if (form.direction === 'buy') {
    return estimatedAmount.value + commission.value
  }
  return estimatedAmount.value - commission.value - stampDuty.value
})

/** 选择卖出股票 */
function onSellStockSelect(ts_code: string) {
  const pos = props.positions.find(p => p.ts_code === ts_code)
  if (pos) {
    form.stock_name = pos.stock_name
    form.quantity = Math.min(pos.available_quantity, 100)
    form.price = pos.current_price || pos.avg_cost
  }
}

/** 股票代码变化时自动填充名称 */
function onTsCodeChange(code: string) {
  const pos = props.positions.find(p => p.ts_code === code)
  if (pos) {
    form.stock_name = pos.stock_name
    form.price = pos.current_price || pos.avg_cost
  }
}

/** 提交交易 */
function handleSubmit() {
  if (!form.account_id) { ElMessage.warning('请选择账户'); return }
  if (!form.ts_code) { ElMessage.warning('请输入股票代码'); return }
  if (!form.stock_name) { ElMessage.warning('请输入股票名称'); return }
  if (form.quantity <= 0 || form.quantity % 100 !== 0) { ElMessage.warning('数量必须为100的整数倍'); return }
  if (form.price <= 0) { ElMessage.warning('请输入有效价格'); return }

  emit('trade', { ...form })
}
</script>

<template>
  <div class="trade-form">
    <ElForm label-width="90px" size="small">
      <!-- 交易方向 -->
      <ElFormItem label="交易方向">
        <ElRadioGroup v-model="form.direction">
          <ElRadioButton value="buy">🟢 买入</ElRadioButton>
          <ElRadioButton value="sell">🔴 卖出</ElRadioButton>
        </ElRadioGroup>
      </ElFormItem>

      <!-- 账户选择 -->
      <ElFormItem label="交易账户">
        <ElSelect v-model="form.account_id" placeholder="选择账户" style="width: 100%">
          <ElOption
            v-for="acc in accounts"
            :key="acc.account_id"
            :label="`${acc.name} (可用: ¥${(acc.available_cash || 0).toLocaleString()})`"
            :value="acc.account_id"
          />
        </ElSelect>
      </ElFormItem>

      <!-- 股票 - 卖出模式使用下拉选择 -->
      <template v-if="form.direction === 'sell'">
        <ElFormItem label="卖出股票">
          <ElSelect
            v-model="form.ts_code"
            placeholder="从持仓中选择"
            style="width: 100%"
            @change="onSellStockSelect"
          >
            <ElOption
              v-for="pos in sellOptions"
              :key="pos.position_id"
              :label="`${pos.stock_name}(${pos.ts_code}) 可卖:${pos.available_quantity}股`"
              :value="pos.ts_code"
            />
          </ElSelect>
        </ElFormItem>
      </template>

      <!-- 股票 - 买入模式手动输入 -->
      <template v-else>
        <ElFormItem label="股票代码">
          <ElInput
            v-model="form.ts_code"
            placeholder="如 000001.SZ"
            @change="onTsCodeChange(form.ts_code)"
          />
        </ElFormItem>
        <ElFormItem label="股票名称">
          <ElInput v-model="form.stock_name" placeholder="输入股票名称" />
        </ElFormItem>
      </template>

      <!-- 价格和数量 -->
      <ElFormItem label="委托价格">
        <ElInputNumber
          v-model="form.price"
          :min="0.01"
          :precision="2"
          :step="0.01"
          style="width: 100%"
        />
      </ElFormItem>
      <ElFormItem label="委托数量">
        <ElInputNumber
          v-model="form.quantity"
          :min="100"
          :step="100"
          style="width: 100%"
        />
        <div class="quantity-hint">必须为100的整数倍（1手=100股）</div>
      </ElFormItem>

      <!-- 策略和原因 -->
      <ElFormItem label="策略来源">
        <ElSelect v-model="form.strategy" placeholder="可选" clearable style="width: 100%">
          <ElOption label="半路追涨" value="halfway_chase" />
          <ElOption label="首板打板" value="first_limit_up" />
          <ElOption label="涨停开板" value="limit_up_open" />
          <ElOption label="龙头低吸" value="leader_buy_dip" />
          <ElOption label="跌停翘板" value="limit_down_qiao" />
          <ElOption label="手动交易" value="manual" />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="交易原因">
        <ElInput v-model="form.reason" type="textarea" :rows="2" placeholder="记录交易原因" />
      </ElFormItem>

      <!-- 费用预估 -->
      <ElFormItem label="费用预估">
        <div class="cost-summary">
          <div>委托金额: ¥{{ estimatedAmount.toLocaleString() }}</div>
          <div>佣金: ¥{{ commission.toFixed(2) }}</div>
          <div v-if="form.direction === 'sell'">印花税: ¥{{ stampDuty.toFixed(2) }}</div>
          <div class="total" :class="form.direction">
            {{ form.direction === 'buy' ? '需支付' : '预计到账' }}: ¥{{ totalCost.toLocaleString() }}
          </div>
        </div>
      </ElFormItem>

      <!-- 提交 -->
      <ElFormItem>
        <ElButton
          :type="form.direction === 'buy' ? 'success' : 'danger'"
          @click="handleSubmit"
          style="width: 100%"
        >
          {{ form.direction === 'buy' ? '确认买入' : '确认卖出' }}
        </ElButton>
      </ElFormItem>
    </ElForm>
  </div>
</template>

<script lang="ts">
export default { name: 'TradeForm' }
</script>

<style scoped>
.trade-form { padding: 12px 0; }
.quantity-hint {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin-top: 2px;
}
.cost-summary {
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}
.cost-summary .total {
  font-weight: 600;
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed var(--el-border-color);
}
.cost-summary .total.buy { color: #67c23a; }
.cost-summary .total.sell { color: #f56c6c; }
</style>
