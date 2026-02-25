/**
 * Pinia Store 统一导出
 */

import { createPinia } from 'pinia'

export const pinia = createPinia()

export { useUserStore } from './user'
export { useTaskStore } from './task'
export { useMarketStore } from './market'
export { useThemeStore } from './theme'