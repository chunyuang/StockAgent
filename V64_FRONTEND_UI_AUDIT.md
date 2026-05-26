# V64 前端 UI/UX 审计报告

> 审计时间: 2026-05-27  
> 审计范围: 全部 Vue 组件(21个) + API层(4个) + 配置(2个) + Stores(4个) + 样式系统  
> 版本: V64

---

## 摘要

| 级别 | 数量 | 说明 |
|------|------|------|
| **P0** | 5 | 必须修复：功能Bug或严重UI问题 |
| **P1** | 8 | 应该修复：体验问题、不一致、潜在Bug |
| **P2** | 7 | 建议修复：优化、美化、代码质量 |

**已直接修复**: P0-1, P0-2, P0-3, P0-4, P1-4, P1-6

---

## P0 - 必须修复

### P0-1: StrategyFactorPanel 止损/止盈参数与 strategyDefaults.ts 不一致 ✅已修复
- **文件**: `components/ultrashort/StrategyFactorPanel.vue`
- **问题**: 硬编码的策略参数描述与 `strategyDefaults.ts`（由后端同步生成的单一来源）不一致：
  - 半路追涨: 面板写 `止损5%/止盈10%`，实际 `stop_loss_pct=0.04(4%)/take_profit_pct=0.12(12%)`
  - 首板打板: 面板写 `止损4%/止盈12%`，实际 `stop_loss_pct=0.03(3%)/take_profit_pct=0.08(8%)`
  - 龙头低吸: 面板写 `止损5%/止盈15%/持仓4天`，实际 `SL=3%/TP=30%/hold=7天`
  - 跌停翘板: 面板写 `止损4%`，实际 `stop_loss_pct=0.05(5%)`
- **修复**: 从 `strategyDefaults.ts` 导入 `STRATEGY_CONFIGS`，动态生成 exitSignal/riskFactors/flowSteps，不硬编码

### P0-2: MainLayout 菜单路由映射错误 ✅已修复
- **文件**: `layouts/MainLayout.vue`
- **问题**: `activeMenu` computed 中，`/strategies` 路径映射到 `/monitor`，策略管理页无法正确高亮导航
- **修复**: 改为 `if (path.startsWith('/strategies')) return '/strategies'`，并在 menuItems 中添加策略管理菜单项

### P0-3: StockChart 组件使用 `el-empty` 但未导入 Element Plus 组件 ✅已修复
- **文件**: `components/charts/StockChart.vue`
- **问题**: 模板中使用了 `<el-empty>` 但未在 `<script setup>` 中 import `ElEmpty`，运行时组件未注册
- **修复**: 添加 `import { ElEmpty } from 'element-plus'`，模板改为 `<ElEmpty>`

### P0-4: DataStatusPanel 组件未在 onUnmounted 清除轮询定时器 ✅已修复
- **文件**: `components/ultrashort/DataStatusPanel.vue`
- **问题**: 组件有 `syncPollTimer` 轮询定时器，但没有 `onUnmounted` 钩子清理，切换页面时定时器泄漏
- **修复**: 添加 `onUnmounted(() => { stopPolling() })`

### P0-5: BacktestHistoryPanel 对比面板策略标签暗色模式对比度差
- **文件**: `components/backtest/BacktestHistoryPanel.vue`
- **问题**: 策略标签使用 `var(--warning)`/`var(--stock-up)` 作为背景色，`var(--text-inverse)` 作为文字色。暗色模式下两者都偏暗，对比度极差
- **修复建议**: 使用 `effect="dark"` 让 Element Plus 自动处理文字对比度，或自定义更鲜明的背景色

---

## P1 - 应该修复

### P1-1: SystemStatusView 缺少 CSS 变量适配
- **文件**: `views/system/SystemStatusView.vue`
- **问题**: 使用硬编码的 margin/padding 工具类（`mt-4`, `ml-2`），但组件 scoped 样式中定义的这些类与 Tailwind 命名冲突风险。且 `positive`/`negative` 类名是常见命名，可能被全局样式覆盖
- **修复建议**: 使用 Element Plus 间距组件或内联 style

### P1-2: 策略管理页面无侧边栏入口 ✅已修复(与P0-2一起)
- **文件**: `layouts/MainLayout.vue`
- **问题**: 侧边栏没有"策略管理"菜单项，用户无法通过导航访问策略列表/详情/编辑页面
- **修复**: 在 menuItems 中添加 `{ path: '/strategies', icon: DataLine, title: '策略管理' }`

### P1-3: SettingsView 引用的 PushConfigPanel/LogLevelPanel 未被审计
- **文件**: `views/settings/SettingsView.vue`
- **问题**: 引用了 `PushConfigPanel.vue` 和 `LogLevelPanel.vue` 子组件，不在本次审计范围
- **修复建议**: 后续审计补充

### P1-4: StockChart 成交量颜色判断逻辑不准确 ✅已修复
- **文件**: `components/charts/StockChart.vue`
- **问题**: 成交量颜色用 `d.close >= d.open` 判断涨跌，但 A 股应该用 `d.close >= d.pre_close`（前收盘价）判断
- **修复**: 改为 `d.pre_close != null && d.close >= d.pre_close ? colors.upColor : colors.downColor`

### P1-5: BacktestSummaryTable 年化收益⚠️提示重复
- **文件**: `components/backtest/BacktestSummaryTable.vue`
- **问题**: `nvsLen < 250` 时指标行加 ⚠️ 后缀 + 底部 disclaimer 都显示，提示重复
- **修复建议**: 保留 disclaimer，指标行不加 ⚠️ 后缀

### P1-6: theme.scss 暗色模式 `--info-bg` 重复定义 ✅已修复
- **文件**: `styles/theme.scss`
- **问题**: 暗色模式中 `--info-bg` 被定义两次，第二次覆盖第一次
- **修复**: 删除第一个重复定义

### P1-7: BacktestHistoryPanel 无分页支持
- **文件**: `components/backtest/BacktestHistoryPanel.vue`
- **问题**: 只取 limit=100 无 offset 分页，数据量大时无法翻页查看更多历史
- **修复建议**: 添加分页支持（offset + loadMore / 虚拟滚动）

### P1-8: StrategyFactorPanel 首板打板成交概率描述与 strategyDefaults 不一致 ✅已修复
- **文件**: `components/ultrashort/StrategyFactorPanel.vue`
- **问题**: flowSteps 写"秒板30%/快板50%/慢板70%"，实际值为一字板0%/快板20%/正常45%/慢板60%
- **修复**: 从 `strategyDefaults.ts` 动态读取成交概率值

---

## P2 - 建议修复

### P2-1: BacktestResultPanel 大量硬编码样式值
- **文件**: `components/ultrashort/BacktestResultPanel.vue`
- **问题**: 大量内联 style 如 `font-size: 12px`、`color: #xxx`，不使用 CSS 变量，暗色模式下可能异常
- **建议**: 用 CSS 变量替换硬编码颜色值

### P2-2: DataStatusPanel 未使用 v-if 延迟渲染
- **文件**: `components/ultrashort/DataStatusPanel.vue`
- **问题**: 无论 visible 为何值都渲染完整 DOM（含 echarts 图表），面板默认隐藏时造成不必要初始化开销
- **建议**: 用 `v-if="visible"` 替代 `v-show`

### P2-3: MarketMonitorView 引用的 scanner 工具函数未审计
- **文件**: `views/monitor/MarketMonitorView.vue`
- **问题**: `import { ... } from '@/utils/scanner'` 未在审计范围
- **建议**: 后续审计 `utils/scanner.ts`

### P2-4: stockApi 功能不完整
- **文件**: `api/modules/stock.ts`
- **问题**: 只有 `getStockInfo` 和 `searchStocks` 两个方法，StockDetailView 需要的 `getStockDaily`/`getRealtimeQuotes` 等未定义
- **建议**: 扩展 stockApi 模块，添加完整的类型化 API 方法

### P2-5: CockpitView 实盘模式切换确认弹窗文案优化
- **文件**: `views/monitor/CockpitView.vue`
- **问题**: 确认弹窗文案过于技术化，普通用户可能不理解
- **建议**: 加入具体风险说明和操作不可逆提示

### P2-6: 全局字体设置缺少 Linux 中文字体
- **文件**: `styles/theme.scss`
- **问题**: `--font-sans` 在 Linux 上无 PingFang SC 和微软雅黑，回退到 sans-serif 可能不美观
- **建议**: 添加 `'Noto Sans SC'` 作为 Linux 回退中文字体

### P2-7: FactorReferencePanel allFactors 数组硬编码在组件中
- **文件**: `components/ultrashort/FactorReferencePanel.vue`
- **问题**: 70+ 个因子定义硬编码在 Vue 组件中，后端新增因子需手动同步
- **建议**: 提取到 `config/factorDefinitions.ts` 配置文件，或从后端 API 动态获取

---

## UI 改进建议

### 1. 回测结果可视化增强
- 添加**净值曲线图**（ECharts 折线图），回测结果已有 `net_value_series` 数据
- 添加**月度收益热力图**，按月/策略维度展示收益分布
- 添加**回撤曲线图**，与净值曲线叠加大幅提升风险感知
- 回测历史对比面板的柱状图（V63已加）可扩展为雷达图，多维度对比

### 2. 驾驶舱实时数据展示
- 添加**大盘指数实时走势微图**（sparkline），嵌入卡片中
- 持仓列表增加**盈亏进度条**（类似 mini bar），直观显示个股盈亏
- 信号管道9层流程图（DataStatusPanel 已有类似实现），可复用到驾驶舱
- 添加**刷新倒计时指示器**（30s 自动刷新时显示环形进度）

### 3. 策略因子面板交互优化
- 因子参考面板添加**因子关系图**（DAG 有向图），展示因子依赖关系
- 策略配置面板参数滑块增加**预设模板**（保守/均衡/激进），一键切换
- 参数变更时实时显示**影响预览**（如修改止损，显示历史交易中会被触发的止损笔数变化）

### 4. 交易记录展示优化
- 添加**交易时间轴**视图，按日期展示买卖时点
- 每笔交易添加**盈亏瀑布图**，直观展示累计盈亏
- 交易记录导出 Excel/CSV 功能

### 5. 色彩和视觉一致性
- 所有组件统一使用 CSS 变量，禁止硬编码颜色
- 暗色模式图表统一使用 `--chart-*` 变量
- 侧边栏菜单项风格统一：`🚀 驾驶舱` emoji 与其他项不统一，建议全部去掉或全部加上

---

## 已修复清单

| 编号 | 修复内容 | 文件 |
|------|---------|------|
| P0-1 | StrategyFactorPanel 参数动态化(从strategyDefaults导入) | StrategyFactorPanel.vue |
| P0-2 | MainLayout 路由映射修正 + 添加策略管理菜单 | MainLayout.vue |
| P0-3 | StockChart 导入 ElEmpty 组件 | StockChart.vue |
| P0-4 | DataStatusPanel 添加 onUnmounted 清理定时器 | DataStatusPanel.vue |
| P1-4 | StockChart 成交量颜色改用 pre_close 判断 | StockChart.vue |
| P1-6 | theme.scss 删除重复 --info-bg 定义 | theme.scss |
