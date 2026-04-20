/**
 * Vue Router 配置
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// ==================== 路由定义 ====================

const routes: RouteRecordRaw[] = [
  // 认证相关
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { title: '登录', guest: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/RegisterView.vue'),
    meta: { title: '注册', guest: true },
  },
  // 唯一超短策略回测页面，免登录访问
  {
    path: '/ultra-short-v2',
    name: 'UltraShortBacktestV2',
    component: () => import('@/views/backtest/UltraShortBacktestViewV2.vue'),
    meta: { title: '超短策略回测系统 V2.0 私募级实盘版', requiresAuth: false },
  },
  // 兼容所有旧路径，全部重定向到新页面
  {
    path: '/ultra-short',
    redirect: '/ultra-short-v2',
    meta: { requiresAuth: false },
  },
  {
    path: '/ultra-short-new',
    redirect: '/ultra-short-v2',
    meta: { requiresAuth: false },
  },
  {
    path: '/backtest/ultra-short',
    redirect: '/ultra-short-v2',
    meta: { requiresAuth: false },
  },
  // 根路径重定向到仪表盘主页
  {
    path: '/',
    redirect: '/dashboard',
    meta: { requiresAuth: false },
  },
  
  // 主布局
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '仪表盘' },
      },
      
      // 分析
      {
        path: 'analysis',
        name: 'AnalysisList',
        component: () => import('@/views/analysis/AnalysisListView.vue'),
        meta: { title: '分析任务' },
      },
      {
        path: 'analysis/:id',
        name: 'AnalysisDetail',
        component: () => import('@/views/analysis/AnalysisDetailView.vue'),
        meta: { title: '分析详情' },
      },
      
      // 股票
      {
        path: 'stock/:code',
        name: 'StockDetail',
        component: () => import('@/views/stock/StockDetailView.vue'),
        meta: { title: '个股详情' },
      },
      
      // 行情分析
      {
        path: 'market',
        name: 'MarketAnalysis',
        component: () => import('@/views/market/MarketAnalysisView.vue'),
        meta: { title: '行情分析' },
      },
      
      // 板块策略
      {
        path: 'sector-strategy',
        name: 'SectorStrategy',
        component: () => import('@/views/market/SectorStrategyView.vue'),
        meta: { title: '板块分析' },
      },
      
      // 热点追踪
      {
        path: 'hot-news',
        name: 'HotNews',
        component: () => import('@/views/market/HotNewsView.vue'),
        meta: { title: '热点追踪' },
      },
      

      
      // 实盘交易 - 模拟盘
      {
        path: 'sim-account',
        name: 'SimAccount',
        component: () => import('@/views/trading/SimAccountView.vue'),
        meta: { title: '模拟交易' },
      },
      
      // 实盘交易 - 交易信号
      {
        path: 'trading-signals',
        name: 'TradingSignals',
        component: () => import('@/views/trading/TradingSignalsView.vue'),
        meta: { title: '交易信号' },
      },
      
      // 实盘交易 - 绩效报告
      {
        path: 'performance',
        name: 'PerformanceReport',
        component: () => import('@/views/trading/PerformanceReportView.vue'),
        meta: { title: '绩效报告' },
      },
      
      // 自选股
      {
        path: 'watchlist',
        name: 'Watchlist',
        component: () => import('@/views/watchlist/WatchlistView.vue'),
        meta: { title: '自选股' },
      },
      
      // 策略
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

// ==================== 创建 Router ====================

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// ==================== 路由守卫 ====================
// 临时跳过所有登录验证，方便调试
router.beforeEach((to, _from, next) => {
  // 设置页面标题
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - StockAgent`
  }
  
  // 模拟登录状态，直接放行
  const mockToken = 'mock-token-123456'
  if (!localStorage.getItem('access_token')) {
    localStorage.setItem('access_token', mockToken)
    localStorage.setItem('refresh_token', 'mock-refresh-token-123456')
  }
  
  next()
})

export default router
