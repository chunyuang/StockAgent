<!--
  UnifiedDateBar - 统一日期选择器
  v2.9.97

  所有市场监听 Tab 共用此组件:
  - v-model: 当前日期 (YYYYMMDD 字符串)
  - 自动从 /unified/date-availability 拉取染色数据
  - 有交易日: 绿色 ●
  - 无交易日: 灰色 ○
  - 周末: 不可选
  - 默认今天

  用法:
    <UnifiedDateBar v-model="currentDate" :days="60" @change="onDateChange" />
-->
<template>
  <div class="unified-date-bar">
    <el-button-group>
      <el-button size="small" @click="goPrev" :disabled="!prevDate">
        <el-icon><ArrowLeft /></el-icon>
      </el-button>
      <el-button size="small" @click="goToday" :type="isToday ? 'primary' : 'default'">
        今日
      </el-button>
      <el-button size="small" @click="goNext" :disabled="!nextDate">
        <el-icon><ArrowRight /></el-icon>
      </el-button>
    </el-button-group>

    <el-date-picker
      v-model="pickerDate"
      type="date"
      size="small"
      placeholder="选择日期"
      format="YYYY-MM-DD"
      value-format="YYYY-MM-DD"
      :disabled-date="isDisabledDate"
      :cell-class-name="getCellClass"
      style="width: 150px; margin-left: 8px"
      @change="onPickerChange"
    />

    <div class="date-status" :class="`status-${currentStatus}`">
      <span class="status-dot"></span>
      <span>{{ statusLabel }}</span>
      <span v-if="currentInfo.buys || currentInfo.sells" class="counts">
        买{{ currentInfo.buys }} / 卖{{ currentInfo.sells }}
      </span>
    </div>

    <div v-if="loading" class="loading-hint">加载中...</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import { getChinaDateInt } from '@/utils/chinaDate'

interface DateInfo {
  status: 'trades' | 'no-trades' | 'weekend'
  weekday: number
  is_today: boolean
  count: number
  buys: number
  sells: number
}

const props = defineProps<{
  modelValue?: string  // YYYYMMDD
  days?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: string): void
  (e: 'change', val: string): void
}>()

const days = computed(() => props.days || 60)
const availability = ref<Record<string, DateInfo>>({})
const loading = ref(false)

// 内部 picker 用 'YYYY-MM-DD' 格式 (Element Plus)
const pickerDate = ref('')

const currentDate = computed(() => {
  // 输出统一为 'YYYYMMDD'
  return props.modelValue || todayStr()
})

function todayStr(): string {
  return getChinaDateInt()
}

function ymdToDash(s: string): string {
  if (!s || s.length !== 8) return ''
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
}

function dashToYmd(s: string): string {
  if (!s) return ''
  return s.replace(/-/g, '')
}

const currentInfo = computed<DateInfo>(() => {
  return availability.value[currentDate.value] || {
    status: 'no-trades',
    weekday: 0,
    is_today: false,
    count: 0,
    buys: 0,
    sells: 0,
  }
})

const currentStatus = computed(() => currentInfo.value.status)

const statusLabel = computed(() => {
  const s = currentStatus.value
  if (s === 'trades') return '有交易'
  if (s === 'weekend') return '周末'
  return '无交易'
})

const isToday = computed(() => currentDate.value === todayStr())

// 排序后的可选日期列表
const sortedDates = computed(() => {
  return Object.keys(availability.value).sort()
})

const prevDate = computed(() => {
  const i = sortedDates.value.indexOf(currentDate.value)
  if (i <= 0) return ''
  // 找上一个非周末日期
  for (let j = i - 1; j >= 0; j--) {
    const d = sortedDates.value[j]
    if (availability.value[d]?.status !== 'weekend') return d
  }
  return ''
})

const nextDate = computed(() => {
  const i = sortedDates.value.indexOf(currentDate.value)
  if (i < 0 || i >= sortedDates.value.length - 1) return ''
  for (let j = i + 1; j < sortedDates.value.length; j++) {
    const d = sortedDates.value[j]
    if (availability.value[d]?.status !== 'weekend') return d
  }
  return ''
})

function setDate(v: string) {
  if (!v) return
  emit('update:modelValue', v)
  emit('change', v)
}

function goPrev() {
  if (prevDate.value) setDate(prevDate.value)
}

function goNext() {
  if (nextDate.value) setDate(nextDate.value)
}

function goToday() {
  setDate(todayStr())
}

function onPickerChange(val: string | null) {
  if (val) setDate(dashToYmd(val))
}

// 禁用周末和超出范围 (d 是 ElDatePicker 本地 Date) // 时区安全
function isDisabledDate(d: Date): boolean {
  if (d.getDay() === 0 || d.getDay() === 6) return true // 时区安全
  // 超出可用范围(60天前/明天后)禁用
  const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}` // 时区安全
  if (!availability.value[ymd] && ymd !== todayStr()) {
    // 不在可用列表中, 但允许选今天
    return true
  }
  return false
}

// 日历单元格染色
function getCellClass(data: { dayjs: any }): string {
  const d = data.dayjs
  const ymd = `${d.year()}${String(d.month() + 1).padStart(2, '0')}${String(d.date()).padStart(2, '0')}`
  const info = availability.value[ymd]
  if (!info) return ''
  if (info.status === 'trades') return 'cell-has-trades'
  if (info.status === 'weekend') return 'cell-weekend'
  return 'cell-no-trades'
}

async function loadAvailability() {
  loading.value = true
  try {
    const r: any = await api.get(`/unified/date-availability?days=${days.value}`)
    const p = r.data || r
    if (p.success) {
      availability.value = p.data || {}
    }
  } catch (e) {
    console.warn('[UnifiedDateBar] load availability failed', e)
  } finally {
    loading.value = false
  }
}

// 同步 picker
watch(currentDate, (v) => {
  pickerDate.value = ymdToDash(v)
}, { immediate: true })

onMounted(() => {
  loadAvailability()
  if (!props.modelValue) {
    setDate(todayStr())
  }
})

defineExpose({ refresh: loadAvailability })
</script>

<style scoped>
.unified-date-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-bg-color-page);
  border-radius: 6px;
  flex-wrap: wrap;
}

.date-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  margin-left: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-trades {
  background: rgba(103, 194, 58, 0.15);
  color: #67c23a;
}

.status-trades .status-dot {
  background: #67c23a;
}

.status-no-trades {
  background: rgba(144, 147, 153, 0.15);
  color: #909399;
}

.status-no-trades .status-dot {
  background: #909399;
}

.status-weekend {
  background: rgba(245, 108, 108, 0.1);
  color: #f56c6c;
}

.status-weekend .status-dot {
  background: #f56c6c;
}

.counts {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-left: 4px;
}

.loading-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-left: 4px;
}
</style>

<style>
/* 日历单元格染色 (全局, 因为 Element Plus popover 渲染到 body) */
.el-date-picker .cell-has-trades {
  position: relative;
}
.el-date-picker .cell-has-trades::after {
  content: '';
  position: absolute;
  bottom: 4px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  background: #67c23a;
  border-radius: 50%;
}

.el-date-picker .cell-weekend {
  color: #c0c4cc !important;
  background: var(--el-fill-color-light);
}

.el-date-picker .cell-no-trades {
  color: var(--el-text-color-secondary);
}
</style>
