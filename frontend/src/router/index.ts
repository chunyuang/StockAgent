/**
 * Vue Router - 超短策略量化交易系统(精简版)
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/ultra-short', redirect: '/' },
  { path: '/ultra-short-new', redirect: '/' },
  { path: '/ultra-short-v2', redirect: '/' },
  { path: '/backtest/ultra-short', redirect: '/' },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'UltraShortBacktestV2',
        component: () => import('@/views/backtest/UltraShortBacktestViewV2.vue'),
        meta: { title: '超短策略回测', hideTitle: true },
      },
      {
        path: 'stock/:code',
        name: 'StockDetail',
        component: () => import('@/views/stock/StockDetailView.vue'),
        meta: { title: '个股详情' },
      },
      {
        path: 'monitor',
        name: 'MarketMonitor',
        component: () => import('@/views/monitor/MarketMonitorView.vue'),
        meta: { title: '市场监听' },
      },
      {
        path: 'cockpit',
        name: 'Cockpit',
        component: () => import('@/views/monitor/CockpitView.vue'),
        meta: { title: '驾驶舱' },
      },

      {
        path: 'strategies',
        redirect: '/monitor',
      },
      {
        path: 'strategies/new',
        redirect: '/monitor',
      },
      {
        path: 'strategies/:id',
        redirect: '/monitor',
      },
      {
        path: 'strategies/:id/edit',
        redirect: '/monitor',
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
