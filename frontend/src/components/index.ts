/**
 * 组件统一导出
 */

// Agent 组件
export { default as AgentThinking } from './agent/AgentThinking.vue'
export { default as TaskStatusBadge } from './agent/TaskStatusBadge.vue'

// 图表组件
export { default as StockChart } from './charts/StockChart.vue'

// 通用组件
export { default as SearchBar } from './common/SearchBar.vue'

// 仪表盘组件
export { default as MarketOverviewCard } from './dashboard/MarketOverviewCard.vue'
export { default as WatchlistCard } from './dashboard/WatchlistCard.vue'
export { default as TaskProgressCard } from './dashboard/TaskProgressCard.vue'
export { default as QuickActions } from './dashboard/QuickActions.vue'
export { default as RecentTasks } from './dashboard/RecentTasks.vue'
export { default as HotNewsBoard } from './dashboard/HotNewsBoard.vue'