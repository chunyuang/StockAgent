# V65 实盘模块审查报告

> 审计日期：2026-05-27
> 审计范围：real_trading/ 8个文件 + nodes/listener/execution/ 2个文件
> 对标基准：AgentServer/nodes/backtest_engine/strategy_defaults.py + sell_signal_checker.py + portfolio_backtest.py
> 核心原则：只审查和输出报告，**不修改任何代码文件**

---

## 审计摘要

| 严重等级 | 数量 | 说明 |
|----------|------|------|
| P0 | 5 | 影响实盘交易正确性，必须修复 |
| P1 | 7 | 影响实盘-回测一致性，建议修复 |
| P2 | 6 | 实盘调优/代码质量建议 |
| **总计** | **18** | |

**最严重发现**：
1. Listener持仓管理器已废弃但仍被DailyScheduler引用，其卖出逻辑与回测严重不一致
2. Listener的next_day_open_sell_pct fallback=0.03，与V53策略级0.02不一致
3. generate_daily_signals.py无法正确分类跌停翘板信号
4. nav_tracker.py CLI入口未await异步方法
5. Listener drawdown_control.py参数来源是settings.py而非strategy_defaults.py

---

## P0 - 必须修复(影响实盘交易正确性)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P0-1 | listener/execution/position_manager.py | 整体 | **已废弃但被DailyScheduler引用**，卖出逻辑与回测严重不一致 | 文件头部标注"废弃时间2026-05-26"，但DailyScheduler仍通过SimulatorExecutor引用。废弃代码不再维护，卖出逻辑缺少：利润锁定、龙头5天低利润、SellSignalChecker统一调用 | 将DailyScheduler迁移到MarketScanner+SimulatedBroker，或确认listener模块不再被实际调用后删除引用 |
| P0-2 | listener/execution/position_manager.py | L227-230 | **next_day_open_sell_pct fallback=0.03，与V53策略级0.02不一致** | 首板打板/龙头低吸/半路追涨的次日高开保护阈值V53已从3%→2%，但listener的`strategy_risk.get("next_day_open_sell_pct", 0.03)` fallback仍为0.03。且GLOBAL_RISK中无next_day_open_sell_pct字段，`GLOBAL_RISK.get("next_day_open_sell_pct", 0.03)`同样返回0.03 | 将fallback从0.03→0.02，与strategy_defaults.py各策略的next_day_open_sell_pct对齐 |
| P0-3 | generate_daily_signals.py | L265-280 | **_get_strategy_for_stock()无法正确分类跌停翘板** | 逻辑：pct_chg≥5%→半路追涨，pct_chg≥-7%→龙头低吸，pct_chg<-7%→跳过。跌停翘板候选(当日从跌停翘起)pct_chg通常在-5%~+5%之间，会被错误归为"龙头低吸"或"半路追涨"，导致交易计划的止损止盈/持仓天数使用错误策略参数 | 增加"跌停翘板"分类：当日曾触及跌停(low≤down_limit)且最终翻红(close>open)→归为跌停翘板，使用其5%/20%/3天的风控参数 |
| P0-4 | nav_tracker.py | L417 | **CLI入口未await异步方法** | `main()`中`tracker.update_daily_nav(args.date)`返回coroutine对象而非执行结果，CLI调用`update`命令静默无效果 | 改为`asyncio.run(tracker.update_daily_nav(args.date))` |
| P0-5 | listener/execution/position_manager.py | L193-260 | **check_daily_stop_loss缺少关键卖出信号，与回测不一致** | 缺少：①利润锁定(盘中冲高≥5%回撤≥2%且收盘≥2%利润) ②龙头5天低利润退出(V63-P0-5) ③SellSignalChecker统一调用。现有冲高回落/利润保护逻辑是内联的，阈值与strategy_defaults不一致(如利润保护≥2%vs策略级pullback_profit_lock_threshold) | 引入SellSignalChecker.check_early_sell()统一检查，补充利润锁定和龙头5天低利润信号，与real_trading/position_manager.py的_check_early_sell_signals()对齐 |

---

## P1 - 建议修复(影响实盘-回测一致性)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P1-1 | listener/execution/drawdown_control.py | 整体 | **参数来源是settings.py而非strategy_defaults.py** | 回撤控制参数(max_daily_drawdown=5%, max_total_drawdown=20%, max_consecutive_losses=3, cooling_days=3)来自settings.trading，与GLOBAL_RISK无关。如果GLOBAL_RISK调整回撤参数，此处不会跟随变化 | 将关键参数改为从GLOBAL_RISK读取，如GLOBAL_RISK.get("max_daily_drawdown_pct", 5.0) |
| P1-2 | real_trading/position_manager.py | L247-298 | **_check_early_sell_signals未传high/low给SellSignalChecker** | check_early_sell(pos.ts_code, [strategy_name], pos.buy_price, open_price, close_price)只传open/close。虽然position_manager有独立的利润锁定检查(使用high/low)，但SellSignalChecker内部如果有依赖high/low的信号判断，将缺失数据 | 确认SellSignalChecker.check_early_sell是否需要high/low参数，如果需要则传入。当前利润锁定是独立实现的，但未来SellSignalChecker新增信号可能遗漏 |
| P1-3 | listener/execution/position_manager.py | L240 | **hold_days使用自然日/1.5近似** | 检查超时卖出时用`int(hold_days / 1.5)`近似交易日，但回测用MongoDB交易日历精确计算。real_trading/position_manager.py已有V63-P1-6交易日历缓存修复，但listener版本未同步 | 迁移到MarketScanner或同步V63-P1-6的交易日历缓存实现 |
| P1-4 | real_trading/paper_trading.py | L170-178 | **close_position的slippage默认参数0.002可能被非策略调用覆盖** | 函数签名`slippage: float = 0.002`，但内部会从strategy_defaults读取策略级滑点(首板0.5%/跌停翘板0.3%)。问题：外部调用如果显式传了slippage=0.002，会覆盖策略级读取，导致打板卖出滑点错误 | 将默认参数改为slippage: float = None，内部判断None时才从策略级读取 |
| P1-5 | real_trading/daily_scheduler.py | L40-42 | **引用已废弃的core/managers/live/模块** | PerformanceCalculator、DailyRebalanceReportGenerator、DataMaintainer来自core/managers/live/，V54重构后这些模块移入_deprecated/。如果_deprecated/下的代码被清理，DailyScheduler将无法启动 | 确认这些模块是否还在_deprecated/下，如果是则将其迁移到real_trading/或替换为等效实现 |
| P1-6 | generate_daily_signals.py | L155-170 | **竞价过滤范围-5%~7%与回测可能不完全对齐** | 代码注释说"与回测对齐"，但回测的竞价过滤在ultra_short.py中的实现可能使用不同阈值。需要确认回测引擎的实际竞价过滤逻辑是否确实是-5%~7% | 对比ultra_short.py中竞价过滤的实际阈值，确认一致性 |
| P1-7 | listener/execution/position_manager.py | L185-195 | **profit_pct单位不一致** | 代码中`position.profit_pct / 100 >= 0.02`暗示profit_pct存储为百分比(如5.0表示5%)，但strategy_defaults使用小数(0.05表示5%)。如果profit_pct实际返回小数(0.05)，则`0.05/100=0.0005 < 0.02`永远不会触发利润保护 | 确认profit_pct的存储单位，统一为小数或百分比 |

---

## P2 - 实盘调优建议

### P2-1: sys.path.insert反模式
**文件**: 所有10个文件  
**问题**: 全部使用`sys.path.insert(0, ...)`做模块查找，每次import都可能修改全局路径，不同模块的路径插入顺序可能冲突  
**建议**: 使用pyproject.toml将项目安装到venv中，消除运行时路径操作

### P2-2: PerformanceAnalyzer不读取strategy_defaults
**文件**: real_trading/performance_analyzer.py  
**问题**: 绩效分析器的优化建议基于硬编码阈值(胜率40%/盈亏比1.2/回撤20%)，不读取strategy_defaults中的实际参数  
**建议**: 从GLOBAL_RISK读取max_total_position等参数，使建议更贴合实际配置

### P2-3: SmartReviewer不读取strategy_defaults
**文件**: real_trading/smart_reviewer.py  
**问题**: 复盘建议基于硬编码阈值(交易50次/胜率40%/盈亏比1.2等)，与实际策略参数脱节  
**建议**: 从strategy_defaults读取当前策略的风控参数，使建议更有针对性

### P2-4: live_backtest_bridge滑点分析依赖action字段
**文件**: real_trading/live_backtest_bridge.py  
**问题**: `analyze_slippage_calibration()`按`action=='buy'`过滤交易记录，但real_trading的trade_history.json格式没有action字段，只有buy_date/sell_date/profit等。会导致滑点分析永远返回空结果  
**建议**: 修改为从buy_price与actual_buy_price的差值计算滑点，或在place_order时记录slippage_pct到交易历史

### P2-5: T+1阻塞集是扁平字符串集
**文件**: real_trading/paper_trading.py  
**问题**: `_t1_blocked`使用`"account_id:ts_code"`格式的扁平字符串，JSON序列化/反序列化效率低且不易扩展  
**建议**: 改为嵌套结构`{account_id: [ts_code1, ts_code2]}`，提高可读性和查询效率

### P2-6: nav_tracker.py持仓市值依赖MongoDB可用性
**文件**: real_trading/nav_tracker.py  
**问题**: `update_daily_nav()`从MongoDB获取收盘价计算市值，如果MongoDB不可用则fallback到buy_price(成本价)，导致净值计算失真  
**建议**: fallback时尝试从本地缓存/东方财富API获取价格，或标记当日净值为"估算值"

---

## 回测-实盘互惠优化建议

### 1. 实盘滑点实测反馈到回测
**现状**: live_backtest_bridge.py有滑点对比框架，但trade_history.json缺少slippage_pct字段，分析永远为空  
**建议**: 在paper_trading.py的place_order/close_position中将实际滑点(slippage_pct, actual_vs_declared_price)写入交易记录。具体：trade_record增加`slippage_actual_pct`字段，live_backtest_bridge可直接分析

### 2. 实盘胜率偏差自动告警
**现状**: live_backtest_bridge.py有check_live_backtest_deviation()，阈值15%胜率偏差/3%收益偏差/0.2%滑点偏差  
**建议**: 将此检查集成到daily_scheduler的盘后流程中，偏差超阈值时推送飞书告警，而非仅生成报告需人工查看

### 3. 参数同步自动化
**现状**: 实盘模块通过`from strategy_defaults import`读取参数，服务重启后才生效  
**建议**: 增加参数热更新机制——daily_scheduler启动时记录strategy_defaults.py的mtime，每次盘前检查mtime是否变化，变化则reload模块并打印diff

### 4. 实盘交易记录反哺回测验证
**现状**: live_backtest_bridge只做对比，不验证  
**建议**: 增加回测验证步骤：取实盘同一时间段的真实信号和成交价，用回测引擎重放，对比收益差异。如果差异>10%，说明回测假设(滑点/成交率)需要校准

### 5. 废弃模块清理路线图
**现状**: listener/execution/下的position_manager.py和drawdown_control.py已标注废弃，但DailyScheduler仍引用  
**建议**: 
- Phase 1: 确认MarketScanner的check_daily_stop_loss已覆盖listener版本的所有信号类型
- Phase 2: 将DailyScheduler的SimulatorExecutor引用改为MarketScanner
- Phase 3: 删除listener/execution/下的废弃模块

---

## 参数一致性校验表

| 参数 | strategy_defaults.py | real_trading/ | listener/ | 一致? |
|------|---------------------|---------------|-----------|-------|
| 全局止损 | 0.03 | 从defaults读取✅ | settings.trading.default_stop_loss_pct⚠️ | ⚠️ |
| 全局止盈 | 0.07 | 从defaults读取✅ | 未使用(策略级) | ✅ |
| 全局max_hold | 3 | 从defaults读取✅ | 自然日/1.5⚠️ | ❌ |
| 半路追涨SL/TP | 0.03/0.12 | 从defaults读取✅ | 从defaults读取✅ | ✅ |
| 首板打板SL/TP | 0.03/0.10 | 从defaults读取✅ | 从defaults读取✅ | ✅ |
| 龙头低吸SL/TP | 0.03/0.30 | 从defaults读取✅ | 从defaults读取✅ | ✅ |
| 跌停翘板SL/TP | 0.05/0.20 | 从defaults读取✅ | 从defaults读取✅ | ✅ |
| 首板滑点 | 0.005 | 从defaults读取✅ | 未设置⚠️ | ⚠️ |
| 跌停翘板滑点 | 0.003 | 从defaults读取✅ | 未设置⚠️ | ⚠️ |
| next_day_open_sell_pct | 各策略0.02 | 从defaults读取✅ | fallback 0.03❌ | ❌ |
| max_total_position | 0.75 | 从defaults读取✅ | settings.trading⚠️ | ⚠️ |
| max_position_per_stock | 0.35 | 从defaults读取✅ | settings.trading⚠️ | ⚠️ |
| intraday_lock | 5%/2%/2% | 从defaults读取✅ | 无此信号❌ | ❌ |
| hold_protection | 0.05 | 从defaults读取✅ | 无此逻辑❌ | ❌ |
| 龙头5天低利润 | 5天/3% | V63已实现✅ | 无此信号❌ | ❌ |
| 强制空仓冷却 | 2天/0.6上限 | GLOBAL_RISK定义✅ | drawdown_control冷却3天⚠️ | ⚠️ |

**图例**: ✅完全一致 ⚠️来源不同但值可能相同 ❌不一致

---

## 各文件审查结论

| 文件 | 行数 | P0 | P1 | P2 | 主要风险 |
|------|------|----|----|-----|----------|
| real_trading/paper_trading.py | ~320 | 0 | 1 | 1 | slippage默认参数覆盖策略级 |
| real_trading/position_manager.py | ~430 | 0 | 1 | 0 | SellSignalChecker未传high/low |
| real_trading/generate_daily_signals.py | ~310 | 1 | 1 | 0 | 跌停翘板分类缺失 |
| real_trading/daily_scheduler.py | ~470 | 0 | 1 | 0 | 引用已废弃模块 |
| real_trading/live_backtest_bridge.py | ~280 | 0 | 0 | 1 | 滑点分析依赖不存在的字段 |
| real_trading/smart_reviewer.py | ~300 | 0 | 0 | 1 | 硬编码阈值 |
| real_trading/nav_tracker.py | ~430 | 1 | 0 | 1 | CLI未await异步方法 |
| real_trading/performance_analyzer.py | ~340 | 0 | 0 | 1 | 硬编码阈值 |
| listener/execution/position_manager.py | ~310 | 2 | 3 | 0 | 已废弃+卖出信号缺失+参数fallback错误 |
| listener/execution/drawdown_control.py | ~220 | 0 | 1 | 0 | 参数来源非strategy_defaults |

---

*此报告由V65实盘模块审查自动生成，不自动修改任何代码*
*审查基准commit: main分支最新*
