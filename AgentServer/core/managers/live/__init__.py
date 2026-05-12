"""
core.managers.live — 实盘交易模块

整合自 real_trading/ 目录，消除 sys.path.insert 反模式，
改用标准 Python import 路径。

模块说明:
- paper_trading_compat: 模拟盘兼容层(桥接SimTradingEngine)
- position_manager: 持仓管理(MongoDB存储)
- risk_checker: 买入前风控检查
- signal_pusher: 飞书/企业微信/钉钉推送
- performance_analyzer: 绩效分析
- performance_calculator: 绩效指标计算
- nav_tracker: 净值跟踪
- risk_alert: 风险告警引擎
- realtime_monitor: 盘中实时监控(AKShare轮询, Phase 2 将改WebSocket)
- trade_gateway: 交易网关(框架, Phase 3 实现券商API)
- generate_daily_signals: 日信号生成
- daily_rebalance_report: 调仓报告
- smart_reviewer: 智能复盘
- strategy_optimizer: 策略优化
"""
