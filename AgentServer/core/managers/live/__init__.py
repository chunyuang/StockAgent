"""
core.managers.live — 实盘交易模块

整合自 real_trading/ 目录，消除 sys.path.insert 反模式，
改用标准 Python import 路径。

⚠️ 模块使用状态 (2026-05-26 审查)
═══════════════════════════════════════

🟢 活跃使用 (有外部引用):
  - risk_checker: DailyScheduler 使用 (1处)
  - signal_pusher: DailyScheduler + Scanner 使用 (2处)

🟡 内部依赖 (仅被同目录其他模块引用):
  - paper_trading_compat: 被 daily_rebalance_report/risk_alert/nav_tracker 引用
  - position_manager: 被 daily_rebalance_report 引用
  - performance_analyzer: 被 performance_calculator/smart_reviewer 引用
  - nav_tracker: 被 performance_calculator 引用

🔴 孤立模块 (无任何外部引用，仅内部互相引用):
  - daily_rebalance_report: 未被调用
  - generate_daily_signals: 未被调用 (已标注弃用提示)
  - performance_calculator: 未被调用
  - realtime_monitor: 未被调用
  - risk_alert: 未被调用
  - smart_reviewer: 未被调用
  - strategy_optimizer: 未被调用
  - trade_gateway: 未被调用 (框架，Phase 3 未实现)

迁移计划:
  - Phase 1 (当前): 标注废弃，确认调用关系
  - Phase 2: 将 risk_checker/signal_pusher 的功能内联到 Scanner
  - Phase 3: 移除所有孤立模块，保留 risk_checker + signal_pusher

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
