/**
 * Vue Router 配置 - 超短策略量化交易系统
 * 精简版: 只保留回测/监听/交易/管理功能
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  // 超短策略回测页面，免登录访问
  {
    path: '/ultra-short-v2',
    name: 'UltraShortBacktestV2',
    component: () => import('@/views/backtest/UltraShortBacktestViewV2.vue'),
    meta: { title: '超短策略回测', requiresAuth: false },
  },
  // 兼容旧路径
  { path: '/ultra-short', redirect: '/ultra-short-v2', meta: { requiresAuth: false } },
  { path: '/ultra-short-new', redirect: '/ultra-short-v2', meta: { requiresAuth: false } },
  { path: '/backtest/ultra-short', redirect: '/ultra-short-v2', meta: { requiresAuth: false } },
  // 根路径重定向到回测
  { path: '/', redirect: '/ultra-short-v2', meta: { requiresAuth: false } },

  // 主布局
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/ultra-short-v2' },
      // 个股详情(交易信号等跳转)
      {
        path: 'stock/:code',
        name: 'StockDetail',
        component: () => import('@/views/stock/StockDetailView.vue'),
        meta: { title: '个股详情' },
      },
      // 交易信号
      {
        path: 'trading-signals',
        name: 'TradingSignals',
        component: () => import('@/views/trading/TradingSignalsView.vue'),
        meta: { title: '交易信号' },
      },
      // 今日预选池
      {
        path: 'stock-pool',
        name: 'StockPool',
        component: () => import('@/views/pool/StockPoolView.vue'),
        meta: { title: '今日预选池' },
      },
      // 今日持仓
      {
        path: 'position',
        name: 'Position',
        component: () => import('@/views/position/PositionView.vue'),
        meta: { title: '今日持仓' },
      },
      // 风控中心
      {
        path: 'risk-control',
        name: 'RiskControl',
        component: () => import('@/views/risk/RiskControlView.vue'),
        meta: { title: '风控中心' },
      },
      // 实时监控大屏
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/monitor/MonitorView.vue'),
        meta: { title: '实时监控' },
      },
      // 绩效报告
      {
        path: 'performance',
        name: 'PerformanceReport',
        component: () => import('@/views/trading/PerformanceReportView.vue'),
        meta: { title: '绩效报告' },
      },
      // 市场监听/策略
      {
        path: 'strategies',
        name: 'StrategyList',
        component: () => import('@/views/strategy/StrategyListView.vue'),
        meta: { title: '市场监听' },
      },
      {
        path: 'strategies/new',
        name: 'StrategyCreate',
        component: () => import('@/views/strategy/StrategyEditView.vue'),
        meta: { title: '创建策略' },
      },
      {
        path: 'strategies/:id',
        name: 'StrategyDetail',
        component: () => import('@/views/strategy/StrategyDetailView.vue'),
        meta: { title: '策略详情' },
      },
      {
        path: 'strategies/:id/edit',
        name: 'StrategyEdit',
        component: () => import('@/views/strategy/StrategyEditView.vue'),
        meta: { title: '编辑策略' },
      },
      // 设置
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: { title: '设置' },
      },
      // 数据库管理
      {
        path: 'admin/db',
        name: 'DbAdmin',
        component: () => import('@/views/admin/DbAdminView.vue'),
        meta: { title: '数据库管理' },
      },
      // 系统状态
      {
        path: 'system/status',
        name: 'SystemStatus',
        component: () => import('@/views/system/SystemStatusView.vue'),
        meta: { title: '系统状态' },
      },
    ],
  },
  // 404
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// 路由守卫: 跳过登录验证
router.beforeEach((to, _from, next) => {
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - StockAgent`
  }
  const mockToken = 'mock-token-123456'
  if (!localStorage.getItem('access_token')) {
    localStorage.setItem('access_token', mockToken)
    localStorage.setItem('refresh_token', 'mock-refresh-token-123456')
  }
  next()
})

export default router
