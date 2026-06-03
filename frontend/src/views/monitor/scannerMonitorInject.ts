/**
 * ScannerMonitor provide/inject key
 * 用于MarketMonitorView子组件间共享composable数据
 * 【v2.9.74: 新增provide/inject模式, 替代大量props传递】
 */
import { inject, type InjectionKey } from 'vue'

export interface ScannerMonitorData {
  // 让子组件按需访问composable数据
  [key: string]: any
}

export const SCANNER_MONITOR_KEY: InjectionKey<ScannerMonitorData> = Symbol('scannerMonitor')

/** 子组件中使用: const m = useScannerMonitorInject() */
export function useScannerMonitorInject() {
  const data = inject(SCANNER_MONITOR_KEY)
  if (!data) throw new Error('useScannerMonitorInject must be used inside MarketMonitorView')
  return data
}
