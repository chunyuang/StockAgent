<script setup lang="ts">
/**
 * UnifiedDateBar — 统一日期选择栏
 * 
 * 所有市场监听Tab共用, 保证日期选择行为一致:
 * 1. 单日选择  2. 默认今天  3. 交易日染色  4. 前后导航
 * 
 * 用法:
 *   const dateBar = useUnifiedDateBar()
 *   watch(() => dateBar.selectedDate.value, () => { fetchMyData() })
 */
import { ElDatePicker } from 'element-plus'
import { onMounted, nextTick } from 'vue'
import { useUnifiedDateBar } from '../composables/useUnifiedDateBar'

const props = defineProps<{
  defaultDate?: string  // 外部初始日期 YYYY-MM-DD, 覆盖默认今天
}>()

const emit = defineEmits<{
  (e: 'change', date: string, dateApi: string): void
}>()

const {
  selectedDate, dateForApi, today, isToday,
  prevDay, nextDay, goToday,
  dateCellClass, disabledDate,
} = useUnifiedDateBar()

// 如果外部传了defaultDate, 设置初始值
if (props.defaultDate) {
  selectedDate.value = props.defaultDate
}

function onDateChange(val: string | null) {
  if (val) {
    selectedDate.value = val
    emit('change', val, val.replace(/-/g, ''))
  }
}

function onNavPrev() {
  prevDay()
  emit('change', selectedDate.value, dateForApi.value)
}

function onNavNext() {
  nextDay()
  emit('change', selectedDate.value, dateForApi.value)
}

function onGoToday() {
  goToday()
  emit('change', selectedDate.value, dateForApi.value)
}

// 不在mounted自动emit, 各Tab自己处理初始数据加载
// (避免tab切换重新挂载时覆盖用户已选的日期)
</script>

<template>
  <div class="unified-date-bar">
    <button class="nav-btn" @click="onNavPrev" title="前一天">◀</button>
    <ElDatePicker
      :modelValue="selectedDate"
      type="date"
      size="small"
      value-format="YYYY-MM-DD"
      :disabled-date="disabledDate"
      :cell-class-name="dateCellClass"
      :clearable="false"
      style="width: 130px"
      @update:modelValue="onDateChange"
    />
    <button class="nav-btn" @click="onNavNext" :disabled="isToday" title="后一天">▶</button>
    <button class="today-btn" :class="{ active: isToday }" @click="onGoToday" :disabled="isToday">今天</button>
  </div>
</template>

<style scoped>
.unified-date-bar {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  flex-shrink: 0;
}
.nav-btn, .today-btn {
  border: 1px solid #dcdfe6;
  background: #fff;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 12px;
  cursor: pointer;
  color: #606266;
  line-height: 22px;
  height: 24px;
  transition: all 0.15s;
}
.nav-btn:hover, .today-btn:hover:not(:disabled) {
  color: #409eff;
  border-color: #c6e2ff;
  background: #ecf5ff;
}
.nav-btn:disabled, .today-btn:disabled {
  color: #c0c4cc;
  cursor: not-allowed;
  background: #f5f7fa;
  border-color: #e4e7ed;
}
.today-btn.active {
  color: #409eff;
  border-color: #409eff;
  font-weight: 600;
}
</style>

<style>
/* 交易日染色 (全局, ElDatePicker内部需要) */
.el-date-table td.date-has-trades .el-date-table-cell {
  background: #e1f3d8 !important;
  color: #67c23a !important;
  font-weight: 600;
}
.el-date-table td.date-no-trades .el-date-table-cell {
  color: #c0c4cc !important;
}
.el-date-table td.date-weekend .el-date-table-cell {
  color: #e6a23c !important;
}
</style>
