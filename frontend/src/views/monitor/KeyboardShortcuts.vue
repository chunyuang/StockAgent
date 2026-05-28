<script setup lang="ts">
/**
 * 键盘快捷键体系
 * P2-10: F5强扫/F9买入/Ctrl+S卖出/Ctrl+E紧急平仓/1-4策略开关/↑↓切换持仓
 */
import { onMounted, onUnmounted } from 'vue'

const emit = defineEmits<{
  (e: 'force-scan'): void
  (e: 'manual-buy'): void
  (e: 'sell-selected'): void
  (e: 'emergency-liquidate'): void
  (e: 'toggle-strategy', index: number): void
  (e: 'focus-prev'): void
  (e: 'focus-next'): void
  (e: 'show-detail'): void
}>()

function handler(ev: KeyboardEvent) {
  // 不在输入框中时才响应
  const tag = (ev.target as HTMLElement).tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  const key = ev.key.toLowerCase()
  const ctrl = ev.ctrlKey || ev.metaKey

  if (key === 'f5') { ev.preventDefault(); emit('force-scan') }
  else if (key === 'f9') { ev.preventDefault(); emit('manual-buy') }
  else if (ctrl && key === 's') { ev.preventDefault(); emit('sell-selected') }
  else if (ctrl && key === 'e') { ev.preventDefault(); emit('emergency-liquidate') }
  else if (['1', '2', '3', '4'].includes(key)) { emit('toggle-strategy', +key - 1) }
  else if (key === 'arrowup') { ev.preventDefault(); emit('focus-prev') }
  else if (key === 'arrowdown') { ev.preventDefault(); emit('focus-next') }
  else if (key === 'enter') { emit('show-detail') }
}

onMounted(() => window.addEventListener('keydown', handler))
onUnmounted(() => window.removeEventListener('keydown', handler))
</script>

<template>
  <slot />
</template>
