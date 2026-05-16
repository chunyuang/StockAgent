# real_trading/ — ⚠️ DEPRECATED

**此目录已废弃，保留仅供参考。**

所有功能已整合到 `AgentServer/` 中：

| 旧文件 | 新位置 |
|--------|--------|
| daily_scheduler.py | AgentServer/nodes/scheduler/daily_scheduler.py |
| generate_daily_signals.py | AgentServer/nodes/market_monitor/scanner.py (scan_once) |
| auto_trade_executor.py | AgentServer/nodes/market_monitor/broker.py (SimulatedBroker) |
| daily_rebalance_report.py | AgentServer/nodes/web/api/scanner.py (daily-report) |
| data_maintainer.py | AgentServer/scripts/ |
| mobile_api.py | AgentServer/nodes/web/api/ |
| multi_account_manager.py | AgentServer/nodes/market_monitor/scanner.py (多账户) |
| nav_tracker.py | AgentServer/nodes/web/api/scanner.py (account) |
| paper_accounts.json | MongoDB: scanner_accounts |
| paper_positions_*.json | MongoDB: scanner_positions |

**不要修改此目录下的文件。** 如需修改，请修改 AgentServer/ 中对应文件。

整合日期: 2026-05-17
