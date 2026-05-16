# 实时监控功能全面审查报告

## 审查时间: 2026-05-17 03:00

## 一、当前架构概览

### 核心模块
| 模块 | 文件 | 行数 | 状态 |
|------|------|------|------|
| MarketScanner | nodes/market_monitor/scanner.py | 1779 | ✅可用 |
| LiveFilterPipeline | nodes/market_monitor/live_filter_pipeline.py | 502 | ✅可用 |
| SimulatedBroker | nodes/market_monitor/broker.py | ~500 | ✅可用 |
| Scanner API | nodes/web/api/scanner.py | 881 | ✅可用 |
| EastmoneyAdapter | src/data_sources/eastmoney_adapter.py | 502 | ✅可用 |
| BiyingAdapter | src/data_sources/biying_adapter.py | 417 | ✅可用 |
| DataSourceRouter | nodes/market_monitor/data_source_router.py | 303 | ✅可用 |
| MarketMonitorView | frontend/src/views/monitor/MarketMonitorView.vue | 423 | ✅可用 |
| LiveTradingView | frontend/src/views/trading/LiveTradingView.vue | 481 | ⚠️独立 |
| DailyScheduler | nodes/scheduler/daily_scheduler.py | 832 | ⚠️与scanner重叠 |

### 数据流
```
东方财富(全市场5400只) + 必盈(涨停池/跌停池/炸板池)
  → MarketScanner._fetch_realtime_batch()
  → _merge_factors() (日级因子+实时)
  → _apply_strategies() (4策略筛选)
  → _apply_filter_pipeline() (9层筛选)
  → _detect_anomalies() (异动检测)
  → _execute_signals() (SimulatedBroker撮合)
  → _check_positions() (止损止盈)
  → API + WebSocket → 前端
```

## 二、发现的问题 (按严重程度排序)

### P0 — 致命/数据丢失

1. **_publish_scanner_event 静态方法bug**: scanner.py L865 定义为 `@staticmethod` 但第一个参数是 `self`，调用时也传了 `self`。这导致所有Redis推送静默失败，前端无实时更新。
   - 影响: WebSocket推送完全失效，前端只能靠5秒轮询
   - 修复: 去掉 `@staticmethod` 或改为正确的静态方法

2. **_signal_to_dict 缺少 @staticmethod**: L871 定义为普通方法但无 self 参数，作为实例方法调用时会报 TypeError
   - 影响: get_signals() 可能失败
   - 修复: 加 @staticmethod 或改为实例方法

3. **PositionStatus 数据类未使用**: 定义了 PositionStatus 但从未实例化，_position_to_dict 有两个版本(实例方法+静态方法)冲突

### P1 — 功能缺陷

4. **LiveTradingView 与 MarketMonitorView 功能重叠**: 两个Vue页面做类似的事，LiveTradingView引用的是旧的trading API(/trading/*)，MarketMonitorView引用scanner API。用户困惑该用哪个。

5. **DailyScheduler 与 Scanner 职责重叠**: 两者都有选股+执行+止损逻辑，容易冲突。Scanner已整合9层筛选，但DailyScheduler仍有独立实现。

6. **无调试模式**: 当前无法在不执行交易的情况下测试扫描流程。scan_once会自动买入，无法"干跑"看信号。
   - 需要: dry_run模式(只扫描+筛选，不执行交易)

7. **无逐层调试**: 9层筛选管道无法逐层查看中间结果。前端只看到最终信号，不知道哪一层过滤了什么。
   - 需要: 每层的输入/输出/过滤原因可查

8. **实时行情缓存刷新策略不智能**: 东方财富5秒TTL，非交易时间也在刷新(浪费)。盘中全量扫描5分钟间隔，但持仓检查30秒间隔，两者价格可能不一致。

9. **止损止盈检查不完整**: 
   - _check_positions_quick 只检查止损止盈，不检查跳空止损(需要open价格)
   - 跌停不可卖出的规则在broker中，但scanner的_check_positions没检查

10. **信号过期机制缺失**: _update_signals注释了"简化: 每次扫描重建"，但实际是增量追加。信号只增不减，_active_signals会无限增长。

### P2 — 体验/效率

11. **前端无实时K线/分时图**: 只有数字，没有价格走势图，无法直观判断买卖点

12. **无回放/模拟功能**: 无法用历史数据回放某天的扫描过程来调试策略

13. **策略参数修改需重启**: update_strategy_config只更新内存，不影响已运行的扫描循环

14. **涨跌停池非交易时间返回空**: 前端显示"暂无数据"，应提示"非交易时间"

15. **MongoDB查询效率**: _load_stock_list 和 _load_daily_factors 每次启动都全量查询，无缓存

16. **real_trading/ 目录冗余**: 20+独立脚本与AgentServer功能重叠，应清理或标记deprecated

## 三、开发计划

### Phase 1: 修复P0+P1核心bug (立即)
- 修复_publish_scanner_event和_signal_to_dict
- 统一LiveTradingView → MarketMonitorView
- 添加dry_run调试模式
- 添加9层筛选逐层调试API
- 信号过期清理机制

### Phase 2: 调试工具 (核心需求)
- 逐层筛选可视化(前端展示每层过滤结果)
- dry_run模式(只扫描不交易)
- 单只股票调试(指定ts_code走完整流程)
- 历史回放(用历史数据模拟扫描)

### Phase 3: 实盘增强
- 实时K线/分时图集成
- 智能刷新(交易时间才拉数据)
- 策略参数热更新
- DailyScheduler整合到Scanner
- real_trading/清理

### Phase 4: 高级功能
- 多账户管理
- 风控规则可视化配置
- 自动复盘报告
- 信号评分系统
