/**
 * 懒加载Tab组件集中定义
 * 从 MarketMonitorView.vue 提取，减少 script 行数
 */
import { defineAsyncComponent } from 'vue'

const asyncOpts = { onError: (err: Error) => console.error('[AsyncComponent] load failed:', err) }

export const ReviewTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./ReviewTab.vue') })
export const OpsTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./OpsTab.vue') })
export const PremarketTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./PremarketTab.vue') })
export const SentimentTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./SentimentTab.vue') })
export const HistoryTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./HistoryTab.vue') })
export const AnalysisTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./AnalysisTab.vue') })
export const AccountTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./AccountTab.vue') })
export const ScanTraceTab = defineAsyncComponent({ ...asyncOpts, loader: () => import('./ScanTraceTab.vue') })
export const PositionRiskMatrix = defineAsyncComponent({ ...asyncOpts, loader: () => import('./PositionRiskMatrix.vue') })
export const MiniKline = defineAsyncComponent({ ...asyncOpts, loader: () => import('./MiniKline.vue') })
export const SignalTracePanel = defineAsyncComponent({ ...asyncOpts, loader: () => import('./SignalTracePanel.vue') })
