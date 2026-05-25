"""
Listener 节点 — ⚠️ 已废弃，请使用 MarketScanner

此模块已被 nodes/market_monitor/scanner.py (MarketScanner) 取代。

废弃原因:
1. Listener 的4个策略(涨停开板/半路追涨/龙头战法/首板打板)与回测V45的3个策略(半路追涨/龙头低吸/跌停翘板)不一致
2. MarketScanner 直接复用回测 _build_strategy_filter_conditions，确保实盘与回测逻辑对齐
3. MarketScanner 支持9层筛选管道(LiveFilterPipeline)，覆盖了Listener的全部功能并更完善
4. MarketScanner 使用东方财富(免费无限)+必盈，而Listener用Tushare(有限流)

迁移指引:
- 实盘扫描: MarketScanner (nodes/market_monitor/scanner.py)
- 9层筛选: LiveFilterPipeline (nodes/market_monitor/live_filter_pipeline.py)
- 撮合引擎: SimulatedBroker (nodes/market_monitor/broker.py)
- 情绪周期: EmotionCycleManager (nodes/listener/strategies/emotion_cycle.py) ← 仍在用，保留
- 信号推送: SignalPusher (core/managers/live/signal_pusher.py) ← 仍在用，保留
- 每日调度: DailyScheduler (nodes/scheduler/daily_scheduler.py) ← 引用SimulatorExecutor，待迁移

保留的子模块(其他模块仍在引用):
- strategies/emotion_cycle.py → EmotionCycleManager (全局单例，Scanner的L3层使用)
- execution/simulator_executor.py → DailyScheduler引用(待迁移到broker后可移除)

不再维护的子模块:
- strategies/limit_open.py → 功能已由Scanner的anomaly检测覆盖
- strategies/price_change.py → 功能已由Scanner复用回测策略覆盖
- strategies/leading_dragon.py → 功能已由Scanner的dragon_head策略覆盖
- strategies/first_board.py → 功能已由Scanner的first_limit_up策略覆盖
- strategies/ma5_buy.py → 已在V50前移除
- execution/position_manager.py → 功能已由SimulatedBroker+Scanner覆盖
- execution/drawdown_control.py → 功能已由Scanner的circuit_breaker覆盖
- execution/daily_reporter.py → 功能已由core/managers/live/daily_rebalance_report覆盖
- evolution/strategy_evolution.py → 实验性模块，未集成

废弃时间: 2026-05-26
预计完全移除: 待DailyScheduler迁移完成后
"""

from .node import ListenerNode

__all__ = ["ListenerNode"]
