<script setup lang="ts">
/**
 * FactorStatusTag — 因子数据状态标签
 * 状态: ✅绿(fresh) ⬜灰(stale) 🟠橙(error) ❌红(missing)
 */
import { computed } from 'vue'
import type { FactorDataStatus } from '@/api/modules/factor'

const props = defineProps<{
  status: FactorDataStatus
  /** 是否显示文字，默认false只显示圆点 */
  showText?: boolean
  /** 尺寸: small / default */
  size?: 'small' | 'default'
}>()

const statusMap: Record<FactorDataStatus, { color: string; bg: string; text: string; emoji: string }> = {
  fresh:  { color: '#10b981', bg: 'rgba(16,185,129,0.12)', text: '正常', emoji: '✅' },
  stale:  { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', text: '沿用', emoji: '⬜' },
  error:  { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', text: '异常', emoji: '🟠' },
  missing:{ color: '#ef4444', bg: 'rgba(239,68,68,0.12)', text: '缺失', emoji: '❌' },
}

const info = computed(() => statusMap[props.status] || statusMap.missing)
</script>

<template>
  <span
    class="fv-status-tag"
    :class="[size || 'default', status]"
    :title="info.text"
  >
    <span class="fv-status-dot" :style="{ background: info.color }" />
    <span v-if="showText" class="fv-status-label">{{ info.text }}</span>
  </span>
</template>

<style scoped lang="scss">
.fv-status-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 4px;
  border-radius: 3px;
  line-height: 1;
  white-space: nowrap;

  &.small {
    .fv-status-dot { width: 5px; height: 5px; }
    .fv-status-label { font-size: 9px; }
  }

  &.default {
    .fv-status-dot { width: 6px; height: 6px; }
    .fv-status-label { font-size: 10px; }
  }
}

.fv-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.fv-status-label {
  color: var(--text-tertiary);
  font-size: 10px;
}
</style>
