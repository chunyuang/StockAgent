# UI优化记录 - feature/ui-responsive-v2

## 分支: feature/ui-responsive-v2 (基于 fix/v34-audit)

## 已完成 ✅
1. MarketMonitorView: 3列网格弹性化 + flex-wrap + min-width:0
2. UltraShortBacktestViewV2: 配置面板clamp(340px,35vw,520px) + Tab栏白色背景
3. StrategyConfigPanel: Collapse标题背景色+圆角+展开高亮
4. BacktestHistoryPanel: 卡片/列表双模式重构
5. 所有子组件: grid列minmax弹性化 + flex-wrap + overflow

## 待优化 📋

### 全局 - MainLayout
- [ ] 侧边栏在窄屏时自动收起为64px
- [ ] 页面标题区域与内容区有空白间隙

### 1. 超短策略回测 (UltraShortBacktestViewV2)
- [ ] Tab栏右侧操作按钮(服务检查)样式不够突出
- [ ] 配置面板折叠项标题太长，横向滚动体验差
- [ ] 数据状态Tab里的统计卡片用了硬编码颜色，暗色主题不兼容
- [ ] 日志面板终端字体过小(12.5px)，高分屏难读

### 2. 市场监听 (MarketMonitorView)
- [ ] 涨停池标签页缺少视觉层次
- [ ] 持仓卡片止损距离显示方式可以更好
- [ ] 手动下单区域布局过密

### 3. 系统管理 (SystemStatusView)  
- [ ] 页面标题font-size 26px过大
- [ ] 统计网格 grid-template-columns: repeat(4,1fr) 不弹性

### 4. 数据库管理 (DbAdminView)
- [ ] actions-grid固定2列，窄屏溢出
- [ ] stats-grid固定4列，窄屏溢出
- [ ] 结果JSON区域缺少代码高亮

### 5. 设置 (SettingsView)
- [ ] max-width 800px 在宽屏浪费空间
- [ ] 无暗色主题适配

### 6. 个股详情 (StockDetailView)
- [ ] 已有良好响应式(900px/640px断点)
- [ ] 底部导航3列grid在小屏应堆叠(已有@media处理)
