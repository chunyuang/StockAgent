# ⚠️ DEPRECATED — 此目录已迁移

所有模块已整合到 `AgentServer/core/managers/live/` 和 `AgentServer/nodes/scheduler/`。

## 迁移映射

| 原文件 | 新位置 |
|--------|--------|
| `daily_scheduler.py` | `nodes/scheduler/daily_scheduler.py` (合并版) |
| `paper_trading.py` | `core/managers/live/paper_trading_compat.py` (桥接SimTradingEngine) |
| `position_manager.py` | `core/managers/live/position_manager.py` |
| `pre_buy_risk_check.py` | `core/managers/live/risk_checker.py` |
| `signal_pusher.py` | `core/managers/live/signal_pusher.py` |
| `performance_analyzer.py` | `core/managers/live/performance_analyzer.py` |
| `performance_calculator.py` | `core/managers/live/performance_calculator.py` |
| `performance_report.py` | `core/managers/live/performance_report.py` |
| `nav_tracker.py` | `core/managers/live/nav_tracker.py` |
| `risk_alert.py` | `core/managers/live/risk_alert.py` |
| `realtime_monitor.py` | `core/managers/live/realtime_monitor.py` |
| `trade_gateway.py` | `core/managers/live/trade_gateway.py` |
| `data_maintainer.py` | `nodes/scheduler/data_maintainer.py` |
| `generate_daily_signals.py` | `core/managers/live/generate_daily_signals.py` |
| `daily_rebalance_report.py` | `core/managers/live/daily_rebalance_report.py` |
| `smart_reviewer.py` | `core/managers/live/smart_reviewer.py` |
| `strategy_optimizer.py` | `core/managers/live/strategy_optimizer.py` |
| `multi_account_manager.py` | 待整合(Phase 2) |
| `mobile_api.py` | 待整合(Phase 2) |
| `auto_trade_executor.py` | 待整合(Phase 3) |

## 变更说明

1. **删除 sys.path.insert**: 全部改用标准 import 路径
2. **JSON→MongoDB**: 持仓/交易记录从文件改为MongoDB存储
3. **PaperTradingEngine→SimTradingEngine**: 合并为一个引擎，兼容层保留旧接口
4. **DailyScheduler 整合**: 合并 real_trading/ 和 nodes/scheduler/ 两个版本，增加风控检查+信号推送+结算

此目录将在 Phase 1 完成后删除。
