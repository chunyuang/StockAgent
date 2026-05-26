# _deprecated/ — 已废弃的live模块

这些模块已不再被任何外部代码引用，移入此处归档。
如需恢复，请先确认引用关系，再移回上级目录。

| 模块 | 原用途 | 废弃原因 | 替代方案 |
|------|--------|----------|----------|
| daily_rebalance_report | 每日调仓报告 | 0外部引用 | Scanner._save_timeline |
| generate_daily_signals | 信号生成(旧版) | 0外部引用 | MarketScanner.scan_once |
| performance_calculator | 绩效计算 | 0外部引用 | performance_analyzer |
| realtime_monitor | 实时监控 | 0外部引用 | RiskWatchdog |
| risk_alert | 风控警报 | 0外部引用 | RiskWatchdog |
| smart_reviewer | 智能复核 | 0外部引用 | PreTradeChecker |
| strategy_optimizer | 策略优化 | 0外部引用 | StrategyParamCenter |
| trade_gateway | 交易网关 | 0外部引用 | SimulatedBroker |
