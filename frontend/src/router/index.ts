/**
 * Vue Router - 超短策略量化交易系统(精简版)
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/ultra-short-v2',
    name: 'UltraShortBacktestV2',
    component: () => import('@/views/backtest/UltraShortBacktestViewV2.vue'),
    meta: { title: '超短策略回测', requiresAuth: false },
  },
  { path: '/ultra-short', redirect: '/ultra-short-v2' },
  { path: '/ultra-short-new', redirect: '/ultra-short-v2' },
  { path: '/backtest/ultra-short', redirect: '/ultra-short-v2' },
  { path: '/', redirect: '/ultra-short-v2' },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/ultra-short-v2' },
      {
        path: 'stock/:code',
        name: 'StockDetail',
        component: () => import('@/views/stock/StockDetailView.vue'),
        meta: { title: '个股详情' },
      },
      {
        path: 'live-trading',
        name: 'LiveTrading',
        component: () => import('@/views/trading/LiveTradingView.vue'),
        meta: { title: '实盘交易' },
      },

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
      {
        path: 'system/status',
        name: 'SystemStatus',
        component: () => import('@/views/system/SystemStatusView.vue'),
        meta: { title: '系统状态' },
      },
      {
        path: 'admin/db',
        name: 'DbAdmin',
        component: () => import('@/views/admin/DbAdminView.vue'),
        meta: { title: '数据库管理' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: { title: '设置' },
      },
    ],
  },
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
  scrollBehavior() { return { top: 0 } },
})

router.beforeEach((to, _from, next) => {
  const title = to.meta.title as string
  if (title) document.title = `${title} - StockAgent`
  if (!localStorage.getItem('access_token')) {
    localStorage.setItem('access_token', 'mock-token-123456')
    localStorage.setItem('refresh_token', 'mock-refresh-token-123456')
  }
  next()
})

export default router
