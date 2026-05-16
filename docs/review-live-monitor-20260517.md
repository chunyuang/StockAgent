# 实时监控全面审查报告

**审查日期**: 2026-05-17
**分支**: feature/live-trading
**审查范围**: scanner.py (1980行) + live_filter_pipeline.py (502行) + broker.py (719行) + api/scanner.py (1112行) + MarketMonitorView.vue (534行)

---

## 一、架构总览

```
前端 (MarketMonitorView.vue)
  ↕ REST API + WebSocket
后端 API (nodes/web/api/scanner.py)
  ↕
MarketScanner (nodes/market_monitor/scanner.py)
  ├── LiveFilterPipeline (9层筛选)
  ├── SimulatedBroker (仿真撮合)
  ├── DataSourceRouter (数据源路由)
  │   ├── EastmoneyAdapter (全市场快照, 免费)
  │   └── BiyingAdapter (涨停池/五档, 200次/天)
  └── CircuitBreaker (风控熔断)
```

## 二、P0 严重问题 (影响正确性/资金安全)

### P0-1: `_save_timeline_to_mongo` 引用 `self._account_id` 不存在
- **位置**: scanner.py `_save_timeline_to_mongo()`
- **问题**: 使用 `self._account_id`，但类中只有 `self.account_id`
- **影响**: 收盘后timeline保存到MongoDB会抛AttributeError
- **修复**: `self._account_id` → `self.account_id`

### P0-2: `_check_positions` 止损价计算与 `_check_positions_quick` 不一致
- **位置**: scanner.py 两处止损逻辑
- **问题**: 
  - `_check_positions`: `stop_loss_price = pos.avg_cost * (1 + stop_loss_pct / 100)` (stop_loss_pct=-3, 结果=0.97✅)
  - `_check_positions_quick`: `stop_loss_price = pos.avg_cost * (1 - risk.get("stop_loss_pct", 0.03))` (0.03, 结果=0.97✅)
  - 但跳空止损判断: `_check_positions` 用 `today_open < stop_loss_price` ✅
  - `_check_positions_quick` 也用 `open_price < stop_loss_price` ✅
  - **但** `_check_positions` 中 `stop_loss_pct` 是百分比形式(-3.0)，计算 `(1 + stop_loss_pct / 100)` = 0.97 ✅
  - `_check_positions_quick` 中 `stop_loss_price = pos.avg_cost * (1 - risk.get("stop_loss_pct", 0.03))` = 0.97 ✅
  - **实际上两者结果一致，但代码表达方式不同，容易混淆**
- **修复**: 统一止损价计算方式，提取为公共方法

### P0-3: `reset_account` 中 `scanner.config` 应为 `scanner._config` 或 `scanner.config`
- **位置**: api/scanner.py `reset_account()`
- **问题**: `scanner.config.get("initial_cash", 1_000_000)` 但 MarketScanner 的 config 存在 `self.config`
- **验证**: `self.config = config or {}` ✅ 正确
- **但**: 重置时 `scanner._broker.account.available_cash = initial_cash` 直接修改Account属性，SimulatedBroker可能有更好的reset方法
- **影响**: 低，但不够优雅

### P0-4: WebSocket推送数据格式与前端不匹配
- **位置**: scanner.py `_publish_scanner_event` + redis_ws_bridge.py
- **问题**: scanner推送 `scanner:signals` 频道，但前端WebSocket监听的是 `scanner_signal` / `scanner_position` / `scanner_timeline` 类型
- **影响**: 实时推送可能不工作，前端只能靠轮询
- **修复**: 确保Redis PubSub → WebSocket桥的格式转换正确

### P0-5: `_detect_anomalies` 急速拉升检测逻辑有误
- **位置**: scanner.py `_detect_anomalies()`
- **问题**: 对比 `self._realtime_cache` 中的价格变化，但 `_realtime_cache` 在 `scan_once` 的 `_fetch_realtime_batch` 中被整体替换，所以 `cached["price"]` 永远等于当前 `price`，5分钟涨幅检测永远为0
- **影响**: 急速拉升信号永远不触发
- **修复**: 需要保存上一轮扫描的价格快照，与当前价格对比

## 三、P1 重要问题 (影响功能完整性)

### P1-1: 前端无实时K线/分时图
- **问题**: 信号和持仓只显示数字，没有价格走势可视化
- **影响**: 用户无法直观判断买入时机
- **建议**: 增加迷你分时图(sparkline)或K线图

### P1-2: 策略参数热更新不持久化
- **问题**: `update_strategy_config` 只修改内存配置，重启后丢失
- **影响**: 用户调参后重启丢失
- **建议**: 保存到MongoDB或JSON文件

### P1-3: 9层筛选管道缺少L9(买入执行层)
- **问题**: LiveFilterPipeline只实现了L1-L8，L9(买入执行/T+1/跳空止损)在scanner中
- **影响**: 不影响功能，但9层管道不完整
- **建议**: 文档说明L9在scanner中实现

### P1-4: 前端信号过期无倒计时
- **问题**: 信号有5分钟过期机制，但前端不显示剩余时间
- **影响**: 用户不知道信号何时过期
- **建议**: 显示信号剩余有效时间

### P1-5: 持仓卡片止损止盈价格计算在前端重复
- **问题**: 前端自行计算止损价/止盈价 `pos.cost_price * (1 - pos.stop_loss_pct / 100)`
- **影响**: 与后端计算可能不一致(百分比vs小数)
- **建议**: 后端直接返回止损价/止盈价

### P1-6: 无盘后复盘自动生成
- **问题**: daily-report API存在但前端无入口
- **影响**: 盘后无法快速回顾
- **建议**: 增加复盘Tab

### P1-7: 手动下单无确认弹窗
- **问题**: quickBuy/quickSell 直接下单，无二次确认
- **影响**: 误操作风险
- **建议**: 增加确认弹窗(可配置跳过)

### P1-8: 数据源状态不可操作
- **问题**: 前端显示数据源状态但无法切换/重连
- **影响**: 数据源故障时需重启
- **建议**: 增加数据源重连按钮

## 四、P2 改进建议 (影响用户体验)

### P2-1: 前端3列布局在窄屏下体验差
- **问题**: 240px + auto + 280px 在<1024px时变为单列但内容过多
- **建议**: 增加Tab切换模式

### P2-2: 信号列表无排序选项
- **问题**: 信号按添加顺序显示
- **建议**: 支持按涨幅/量比/策略排序

### P2-3: 时间线无筛选
- **问题**: 所有买卖记录混在一起
- **建议**: 增加按策略/买卖方向筛选

### P2-4: 持仓盈亏无颜色渐变
- **问题**: 只有红绿文字
- **建议**: 持仓卡片背景色随盈亏渐变

### P2-5: 无声音提醒
- **问题**: 新信号/止损/熔断无声音提醒
- **建议**: 增加可选声音提醒

### P2-6: 涨停池数据无刷新按钮
- **问题**: 涨停池数据只在scan_once时更新
- **建议**: 增加独立刷新按钮

### P2-7: 无持仓成本分布图
- **问题**: 只显示总成本
- **建议**: 增加成本分布可视化

### P2-8: 策略开关修改后无即时反馈
- **问题**: 切换策略enabled后需等下次扫描才生效
- **建议**: 显示"下次扫描生效"提示

## 五、代码质量问题

### Q1: scanner.py 1980行过大
- **建议**: 拆分为 scanner_core.py + scanner_strategies.py + scanner_risk.py

### Q2: `_signal_to_dict` 和 `_position_to_dict` 重复
- **问题**: `get_positions()` 和 `_position_to_dict()` 逻辑重复
- **建议**: 统一使用 `_position_to_dict`

### Q3: API中 `__import__("datetime")` 不规范
- **位置**: api/scanner.py manual_trade
- **建议**: 使用顶部import

### Q4: 前端Vue组件534行过大
- **建议**: 拆分为子组件(SignalList/PositionCard/TimelineBar/StrategyPanel)

### Q5: 硬编码的必盈licence
- **位置**: scanner.py `_fetch_realtime_batch`
- **建议**: 从配置文件读取

## 六、开发优先级

| 优先级 | 编号 | 工作量 | 描述 |
|--------|------|--------|------|
| P0 | P0-1 | 5min | 修复_account_id引用 |
| P0 | P0-5 | 30min | 修复急速拉升检测 |
| P0 | P0-4 | 1h | 修复WebSocket推送格式 |
| P1 | P1-7 | 1h | 手动下单确认弹窗 |
| P1 | P1-4 | 30min | 信号过期倒计时 |
| P1 | P1-5 | 30min | 后端返回止损止盈价 |
| P1 | P1-6 | 2h | 盘后复盘Tab |
| P1 | P1-1 | 4h | 迷你分时图 |
| P2 | P2-1 | 2h | 响应式Tab布局 |
| P2 | P2-5 | 1h | 声音提醒 |
