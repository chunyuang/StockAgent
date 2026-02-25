# Stock Agent Frontend

AI 驱动的智能股票分析系统 - 前端

## 技术栈

- **框架**: Vue 3.4 + TypeScript
- **UI 组件**: Element Plus 2.6
- **状态管理**: Pinia 2.1
- **路由**: Vue Router 4
- **HTTP 客户端**: Axios
- **图表**: ECharts 5 + vue-echarts
- **样式**: SCSS + Tailwind CSS
- **构建工具**: Vite 5

## 项目结构

```
frontend/
├── src/
│   ├── api/                    # API 接口封装
│   │   ├── http.ts             # Axios 封装 + JWT
│   │   ├── websocket.ts        # WebSocket 客户端
│   │   ├── modules/            # 各模块 API
│   │   │   ├── auth.ts         # 认证
│   │   │   ├── user.ts         # 用户
│   │   │   ├── strategy.ts     # 策略
│   │   │   └── stock.ts        # 股票数据
│   │   └── index.ts            # 统一导出
│   │
│   ├── stores/                 # Pinia 状态管理
│   │   ├── user.ts             # 用户状态
│   │   ├── task.ts             # 任务状态
│   │   └── market.ts           # 市场数据
│   │
│   ├── router/                 # 路由配置
│   │   └── index.ts
│   │
│   ├── layouts/                # 布局组件
│   │   ├── MainLayout.vue      # 主布局
│   │   └── AuthLayout.vue      # 认证页布局
│   │
│   ├── views/                  # 页面组件
│   │   ├── auth/               # 登录/注册
│   │   ├── dashboard/          # 仪表盘
│   │   ├── analysis/           # 分析任务
│   │   ├── stock/              # 个股详情
│   │   ├── strategy/           # 策略管理
│   │   ├── watchlist/          # 自选股
│   │   ├── settings/           # 设置
│   │   └── error/              # 错误页
│   │
│   ├── components/             # 通用组件
│   │   ├── common/             # 基础组件
│   │   ├── charts/             # 图表组件
│   │   └── dashboard/          # 仪表盘组件
│   │
│   ├── composables/            # 组合式函数
│   │   └── useWebSocket.ts
│   │
│   ├── styles/                 # 全局样式
│   │   └── main.scss
│   │
│   ├── App.vue                 # 根组件
│   └── main.ts                 # 入口文件
│
├── public/                     # 静态资源
├── index.html                  # HTML 模板
├── package.json                # 依赖配置
├── vite.config.ts              # Vite 配置
├── tsconfig.json               # TypeScript 配置
└── tailwind.config.js          # Tailwind 配置
```

## 快速开始

### 安装依赖

```bash
cd frontend
npm install
```

### 开发模式

```bash
npm run dev
```

访问 http://localhost:5173

### 生产构建

```bash
npm run build
```

### 预览构建

```bash
npm run preview
```

## 环境变量

创建 `.env.local` 文件配置环境变量：

```env
# API 地址
VITE_API_BASE_URL=/api/v1

# WebSocket 地址
VITE_WS_URL=ws://localhost:8000/ws/connect
```

## 功能特性

### 🏠 仪表盘
- 大盘概览（上证、深证、创业板）
- 自选股实时行情
- 任务进度实时更新
- 快捷操作入口

### 📊 分析功能
- 个股多维度分析
- 大盘趋势分析
- 自然语言查询
- 分析结果可视化

### 📈 K线图表
- 日K线展示
- MA5/MA10/MA20 均线
- 成交量柱状图
- 数据缩放功能

### 🎯 策略管理
- 创建自定义策略
- 股票池配置
- 分析权重设置
- 策略执行与追踪

### ⭐ 自选股
- 添加/移除自选股
- 实时行情展示
- 快速分析入口

### 🔔 实时推送
- WebSocket 实时连接
- 任务进度推送
- 行情数据推送
- 自动重连机制

## 与后端集成

前端通过以下方式与后端通信：

1. **HTTP API**: 通过 Axios 调用 REST API
2. **WebSocket**: 实时接收任务进度和行情更新
3. **JWT 认证**: 自动处理 Token 刷新

### API 代理配置

开发环境下，Vite 会自动代理 API 请求：

```typescript
// vite.config.ts
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
  '/ws': {
    target: 'ws://localhost:8000',
    ws: true,
  },
}
```

## 开发规范

### 组件命名
- 页面组件: `XxxView.vue`
- 布局组件: `XxxLayout.vue`
- 通用组件: `PascalCase.vue`

### 状态管理
- 使用 Composition API 风格的 Pinia Store
- Store 文件命名: `useXxxStore`

### 样式规范
- 使用 SCSS 编写样式
- 全局变量定义在 `main.scss`
- 组件样式使用 `scoped`

## License

MIT
