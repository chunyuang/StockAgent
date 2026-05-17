# 实时监控全面审查报告 V2

**审查日期**: 2026-05-18
**分支**: feature/live-trading
**审查范围**: scanner.py (2093行) + live_filter_pipeline.py (502行) + broker.py (717行) + api/scanner.py (1526行) + MarketMonitorView.vue (615行)

---

## 一、架构总览

```
前端 (MarketMonitorView.vue) — 3列布局+顶部状态栏+底部时间线
  ↕ REST API + WebSocket (Redis PubSub桥接)
后端 API (nodes/web/api/scanner.py) — 1526行, 30+端点
  ↕
MarketScanner (nodes/market_monitor/scanner.py) — 2093行
  ├── LiveFilterPipeline (9层筛选)
  ├── SimulatedBroker (仿真撮合, T+1/涨跌停/滑点)
  ├── DataSourceRouter (数据源路由)
  │   ├── EastmoneyAdapter (全市场快照, 免费, 3秒)
  │   └── BiyingAdapter (涨停池/五档, 200次/天)
  └── CircuitBreaker (风控熔断: 单日5%/连续3亏)
```

## 二、P0 严重问题 (影响正确性/资金安全)

### P0-1: 止损价计算不一致 — 两处不同公式
- **位置**: scanner.py `_check_positions()` vs `_check_positions_quick()`
- **问题**: 
  - `_check_positions`: `stop_loss_price = pos.avg_cost * (1 + stop_loss_pct / 100)` (stop_loss_pct=-3.0, →0.97✅)
  - `_check_positions_quick`: `stop_loss_price = pos.avg_cost * (1 - risk.get("stop_loss_pct", 0.03))` (→0.97✅)
  - **数值一致但表达混乱**: 一个用百分比形式(-3.0)×100, 一个用小数形式(0.03)
- **修复**: 提取 `_calc_stop_loss_price(pos, risk)` 公共方法, 统一用小数形式

### P0-2: `_check_positions` 中 `risk` 变量在循环外定义但循环内使用
- **位置**: scanner.py `_check_positions()` 卖出决策详情
- **问题**: `decision_detail` 中引用 `risk` 变量, 但 `risk` 是在 for 循环内为每个 pos 计算的, 最后一个 pos 的 risk 可能被错误引用
- **影响**: 卖出决策详情中的止损/止盈参数可能显示错误策略的值
- **修复**: 在卖出循环内重新获取对应 pos 的 risk

### P0-3: WebSocket推送格式不匹配 — 前端无法实时更新
- **位置**: scanner.py `_publish_scanner_event` → Redis → ws_bridge → 前端
- **问题**: scanner推送 `scanner:signals` 频道, 但前端监听的是 `scanner_signal` / `scanner_position` / `scanner_timeline` 类型
- **影响**: 实时推送可能不工作, 前端只能靠5秒轮询
- **修复**: 检查ws_bridge的格式转换, 或统一scanner推送格式

### P0-4: `_detect_anomalies` 急速拉升检测 — prev_cache保存时机
- **位置**: scanner.py `_fetch_realtime_batch()` + `_detect_anomalies()`
- **问题**: `_prev_realtime_cache` 在 `_fetch_realtime_batch` 中保存, 但 `_detect_anomalies` 在 `scan_once` 的 Step 3.6 调用, 此时 `_realtime_cache` 已被更新
- **验证**: `_prev_realtime_cache = dict(self._realtime_cache)` 在更新前保存 ✅ (已在5/17修复)
- **但**: `_check_positions_quick` 不更新 `_prev_realtime_cache`, 所以持仓检查轮不触发急速拉升(合理, 因为持仓检查不拉全量行情)

### P0-5: `reset_account` 重置为initial_cash但未考虑已有亏损
- **位置**: api/scanner.py `reset_account()`
- **问题**: `scanner._broker.account.available_cash = initial_cash` 重置为100万, 但如果之前亏损了, total_assets也应重置
- **验证**: 代码已重置 `total_assets = initial_cash` ✅ (5/17已修)
- **但**: MongoDB中的 `broker_accounts` 记录可能残留旧数据

## 三、P1 重要问题 (影响功能完整性/可操作性)

### P1-1: 前端信号卡片信息密度不足 — 缺少关键决策信息
- **问题**: 信号卡片只显示代码/名称/策略/涨跌幅/量比/换手, 缺少:
  - 流通市值(是否小盘股)
  - PE/PB(估值是否合理)
  - 连板数(首板还是多连板)
  - 封单资金(涨停强度)
- **影响**: 用户无法快速判断信号质量, 需要逐个点"决策"弹窗
- **修复**: 在信号卡片增加关键因子摘要行

### P1-2: 持仓卡片缺少市值和盈亏金额
- **问题**: 持仓只显示盈亏百分比, 不显示盈亏金额(¥)和持仓市值
- **影响**: 用户不知道每只股票亏了多少钱, 无法快速判断是否需要止损
- **修复**: 增加 `market_value` 和 `profit_amount` 字段

### P1-3: 时间线缺少盈亏金额和累计盈亏
- **问题**: 时间线只显示盈亏百分比, 不显示金额; 无累计盈亏趋势
- **影响**: 用户无法快速知道今天总共赚/亏了多少
- **修复**: 增加 `profit_amount` 和累计统计

### P1-4: 策略参数热更新不持久化
- **问题**: `update_strategy_config` 只修改内存, 重启丢失
- **修复**: 保存到MongoDB `scanner_config` 集合

### P1-5: 前端缺少数据源状态可视化
- **问题**: 数据源状态只在API返回, 前端没有直观展示东方财富/必盈的可用性
- **修复**: 在顶部状态栏增加数据源健康指示器

### P1-6: 持仓排序默认应按盈亏排序(最亏的在最前)
- **问题**: 当前按 `profit_pct` 升序(最亏在前) ✅ 已实现
- **但**: 应增加排序切换(按盈亏/按市值/按策略)

### P1-7: 手动下单缺少价格自动填充和验证
- **问题**: 手动下单需要用户自己输入价格, 但用户可能不知道当前价
- **修复**: 自动从行情填充价格, 并显示买卖五档

## 四、P2 优化建议 (提升体验/可维护性)

### P2-1: scanner.py 代码过长(2093行) — 需拆分
- **建议**: 拆分为 scanner_core.py + scanner_positions.py + scanner_signals.py

### P2-2: API端点过多(30+) — 需归类整理
- **建议**: 按功能分组: /status, /control, /data, /trade, /debug, /report

### P2-3: 前端CSS过于冗长 — 需提取公共样式
- **建议**: 提取 .code/.name/.up/.down/.empty 等公共类到全局CSS

### P2-4: 缺少迷你分时图(sparkline)
- **建议**: 用Canvas/SVG绘制5分钟价格走势迷你图

### P2-5: 信号过期倒计时只在前端计算 — 后端也应返回
- **验证**: `_signal_to_dict` 已返回 `expire_remaining` ✅

### P2-6: 缺少持仓盈亏颜色渐变条
- **验证**: 已有 `.pos-bar` ✅, 但应增加渐变效果

### P2-7: 前端缺少键盘快捷键
- **建议**: Ctrl+S保存快照, Ctrl+R刷新, Ctrl+F强制扫描

### P2-8: 缺少信号去重逻辑可视化
- **问题**: 信号按 ts_code+strategy 去重, 但前端看不到去重过程
- **建议**: 显示"已有3个半路追涨信号, 新增1个"

### P2-9: broker.py 持仓用dict而非有序结构
- **问题**: `self.positions = {}` 无序, 导致前端持仓顺序不稳定
- **建议**: 改为 OrderedDict 或排序后返回

### P2-10: 缺少账户历史资产曲线
- **建议**: 用 performance_snapshots 绘制资产曲线图

## 五、代码质量问题

### CQ-1: scanner.py `_check_positions` 和 `_check_positions_quick` 逻辑重复
- **问题**: 两处止损止盈逻辑几乎相同, 只是数据源不同(全量行情 vs 东方财富缓存)
- **修复**: 提取 `_check_stop_loss_take_profit(positions, realtime_data)` 公共方法

### CQ-2: API中 `_sanitize` 只处理float NaN, 不处理dict中的None值
- **问题**: MongoDB查询可能返回None, 前端JSON序列化没问题但不优雅
- **修复**: `_sanitize` 也处理None→null

### CQ-3: 前端 `fetchAll` 每次都请求5个API — 可合并
- **问题**: status+signals+positions+timeline+orders 分5次请求
- **建议**: 增加 `/scanner/all` 合并端点, 减少HTTP开销

### CQ-4: broker.py `_recalc_account` 每次调用都重新计算
- **问题**: get_account()每次都_recalc, 但持仓价格可能没变
- **建议**: 增加脏标记, 只在持仓价格变化时重算

### CQ-5: scanner.py 多处 `try: await ... except: pass` 静默吞异常
- **问题**: save_state/timeline/push 等非关键操作失败被静默吞掉
- **建议**: 至少 logger.warning 记录

## 六、本次修复计划

### Phase 1: P0修复 (正确性)
1. P0-1: 提取 `_calc_stop_loss_price()` 公共方法, 统一止损价计算
2. P0-2: 修复 `_check_positions` 中 risk 变量引用错误
3. P0-3: 检查并修复WebSocket推送格式
4. P0-5: 清理reset_account中MongoDB残留数据

### Phase 2: P1增强 (可操作性)
1. P1-1: 信号卡片增加关键因子摘要(市值/PE/连板/封单)
2. P1-2: 持仓卡片增加市值和盈亏金额
3. P1-3: 时间线增加盈亏金额和累计统计
4. P1-5: 顶部状态栏增加数据源健康指示器
5. P1-7: 手动下单自动填充价格

### Phase 3: 代码质量
1. CQ-1: 提取公共止损止盈检查方法
2. CQ-3: 增加 `/scanner/all` 合并端点
3. CQ-5: 非关键异常改为 logger.warning