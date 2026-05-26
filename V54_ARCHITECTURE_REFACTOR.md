# V54 架构统一重构方案

> 时间：2026-05-26
> 目标：解决双系统并行、模块割裂、风控独立性问题

## 一、当前架构问题诊断

### 1.1 双系统并行现状
| 模块 | 行数 | 状态 | 外部引用 |
|------|------|------|----------|
| nodes/listener/ | 3912 | ⚠️ 已标注废弃但仍在main.py启动 | ListenerNode被main.py引用 |
| nodes/market_monitor/ | 7957 | ✅ 生产主力 | scanner.py是核心 |
| core/managers/live/ | 6650 | ⚠️ 大量死代码 | 仅signal_pusher/risk_checker被引用 |

### 1.2 live/模块使用分析
- **活跃(被外部引用)**: signal_pusher(3refs), risk_checker(1ref)
- **仅内部引用**: paper_trading_compat(3), performance_analyzer(3), position_manager(2), nav_tracker(1)
- **完全死代码(0外部)**: daily_rebalance_report, generate_daily_signals, performance_calculator, realtime_monitor, risk_alert, smart_reviewer, strategy_optimizer, trade_gateway

### 1.3 V51已实现但需加强的模块
- ✅ SignalDispatcher: 已集成Scanner，但飞书通道未完全启用
- ✅ RiskWatchdog: 已集成，但仅做监控，未实现独立紧急平仓
- ✅ StrategyParamCenter: 已集成，但Scanner尚未完全从其读取参数
- ✅ PreTradeChecker/SlippageModel: 已集成

## 二、重构计划

### P0-1: 废弃Listener，统一信号出口
1. main.py移除ListenerNode启动
2. Listener策略文件标记为deprecated(已完成)，添加import guard
3. emotion_cycle.py迁移到market_monitor/（唯一保留的模块）
4. signal_pusher.py迁移到market_monitor/，作为SignalDispatcher的飞书通道

### P0-2: 整合live/死代码
1. 将活跃模块(risk_checker, signal_pusher)迁移到market_monitor/
2. 死代码移入live/_deprecated/子目录
3. 更新daily_scheduler.py的import路径

### P0-3: 独立紧急平仓通道
1. RiskWatchdog增加emergency_liquidate()方法
2. 直接调用Broker.sell_all()，不经过Scanner主循环
3. Web API增加/ scanner/emergency-liquidate端点
4. GUI增加红色紧急按钮

### P1-1: 参数中心完全激活
1. Scanner启动时从ParamCenter加载参数替代直接import strategy_defaults
2. update_strategy_config()通过ParamCenter持久化到MongoDB
3. API端点暴露参数修改能力

### P1-2: GUI重构 — 驾驶舱视图
1. 顶部全局状态栏(运行模式/风控状态/可用资金)
2. 左侧策略控制面板(可折叠)
3. 中间实时信号+持仓盈亏
4. 右侧风控仪表盘(回撤进度条/熔断状态/健康检查)

### P2-1: 分级行情
1. tiered_scanner.py已存在，需激活
2. L1: 东财全市场5分钟
3. L2: 必盈自选池30秒
4. L3: 持仓股实时检查

## 三、执行顺序

1. ✅ 诊断完成
2. 🔜 P0-1: 废弃Listener
3. 🔜 P0-2: 整合live/
4. 🔜 P0-3: 紧急平仓
5. 🔜 P1-1: 参数中心
6. 🔜 P1-2: GUI重构
