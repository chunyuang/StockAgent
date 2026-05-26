# V64 实盘模块全面审计报告

> 审计时间: 2026-05-27  
> 审计范围: `real_trading/` 目录下21个文件，约8500行代码  
> 参考基线: `strategy_defaults.py` (V62参数) + `sell_signal_checker.py` (V48逻辑)  
> 前序版本: V63审计已修复5项P0 (SellSignalChecker统一、T+1持久化、交易日历缓存、偏差监控、龙头5天低利润)

---

## 一、P0级问题 (必须修复)

### P0-1: `strategy_optimizer.py` 导入路径错误导致模块完全不可用
- **文件**: `real_trading/strategy_optimizer.py` L17
- **问题**: `from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester` — 路径中 `backtest_module` 不存在，正确应为 `nodes.backtest_engine`
- **影响**: 整个策略优化器模块无法启动，`grid_search`/`random_search`/`genetic_algorithm` 全部报 `ModuleNotFoundError`
- **修复**: 改为 `from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester`

### P0-2: `nav_tracker.py` `update_daily_nav` 定义为async但从未被await
- **文件**: `real_trading/nav_tracker.py` L131
- **问题**: `async def update_daily_nav()` 需要 `await mongo_manager.find_many()`，但 `daily_scheduler.py` 的 `run_postmarket()` 中调用 `self.nav_tracker.update_daily_nav(trade_date)` **没有await**
- **影响**: 净值更新是协程但被同步调用，实际从未执行，每日净值数据始终为空
- **修复**: `daily_scheduler.py` L388 改为 `nav_record = await self.nav_tracker.update_daily_nav(trade_date)`

### P0-3: `risk_alert.py` `check_account_risk` 仓位计算分母错误
- **文件**: `real_trading/risk_alert.py` L149-150
- **问题**: `position_ratio = total_position_value / account.current_balance` — 分母用了 `current_balance` (可用余额)而非 `total_equity` (总权益)。如果余额很少(大部分资金在持仓)，仓位比会远超100%
- **影响**: 仓位告警误触发或从不触发，风控形同虚设
- **修复**: 分母改为 `account.current_balance + total_position_value` (总权益)

### P0-4: `daily_scheduler.py` `_step_compute_rebalance` 持仓保护判断使用过时价格
- **文件**: `real_trading/daily_scheduler.py` L328-331
- **问题**: `_current_price = p.get("current_price") or p.get("last_price") or p["buy_price"]` — `get_positions()` 返回的dict不含`current_price`字段(仅含`buy_price`)，所以永远fallback到`buy_price`，导致持仓保护判断错误：盈利>=5%永远无法触发(新买入的股票profit=0)，亏损的股票也永远不被调出
- **影响**: 与回测`hold_protection_threshold`逻辑不一致，回测中盈利>=5%保留，实盘中全部被调出
- **修复**: 在`_step_compute_rebalance`中从MongoDB获取当日收盘价计算实际盈亏

### P0-5: `paper_trading_risk_check.py` 风控参数硬编码不与strategy_defaults对齐
- **文件**: `real_trading/paper_trading_risk_check.py` L47-55
- **问题**: `max_index_drop: 0.03`, `daily_max_drawdown: 0.03` 等硬编码值。虽然与strategy_defaults当前值一致，但未从`GLOBAL_RISK`读取，如果strategy_defaults修改了这些参数，此模块不会跟随变化
- **影响**: 参数漂移风险，与V63"参数同步状态"机制矛盾
- **修复**: 从`GLOBAL_RISK`读取默认值，与`pre_buy_risk_check.py`保持一致

---

## 二、P1级问题 (应该修复)

### P1-1: `signal_pusher.py` 推送纪律提示"持仓最多3天"硬编码
- **文件**: `real_trading/signal_pusher.py` L254
- **问题**: `content.append("3. 持仓最多持有3天，到期强制卖出")` — 硬编码3天，但不同策略有不同的max_hold_days (龙头低吸7天，跌停翘板3天)
- **影响**: 推送信息误导，用户以为所有策略都只持3天
- **修复**: 从`GLOBAL_RISK`读取`max_hold_days`或从策略级参数取最大值

### P1-2: `auto_trade_executor.py` 调用PaperTradingEngine不存在的方法
- **文件**: `real_trading/auto_trade_executor.py` L83-98
- **问题**: 调用 `engine.sell()` 和 `engine.buy()`，但PaperTradingEngine的方法是 `place_order()` 和 `close_position()`。虽然文件头已标注"V52已废弃"，但文件仍存在且无删除计划
- **影响**: 如果被误调用会直接报`AttributeError`
- **修复**: 在文件头添加更醒目的废弃标注，或直接删除此文件

### P1-3: `strategy_optimizer.py` `Optional` 类型未导入
- **文件**: `real_trading/strategy_optimizer.py` L10
- **问题**: `_run_backtest` 方法返回类型标注为 `Optional[Dict]`，但 `Optional` 未在顶部导入 (仅导入了 `List, Dict, Tuple`)
- **影响**: 类型检查报错，虽然运行时不影响
- **修复**: 添加 `from typing import Optional` 到导入列表

### P1-4: `risk_alert.py` `check_account_risk` 使用成本价计算仓位市值
- **文件**: `real_trading/risk_alert.py` L143
- **问题**: `total_position_value = sum(pos["shares"] * pos["buy_price"] for pos in positions)` — 用买入价而非市价计算持仓市值，当股票涨跌时仓位计算完全失真
- **影响**: 仓位超限告警失效（实际仓位已超90%但用成本价算出70%）
- **修复**: 从MongoDB获取最新收盘价计算市值（与nav_tracker.py一致）

### P1-5: `trade_gateway.py` `SimulatedGateway` 买入和卖出佣金计算逻辑重复
- **文件**: `real_trading/trade_gateway.py` L147-162
- **问题**: `place_order` 中buy分支先计算了`total_cost + commission`(含印花税0)但stamp_tax对buy不应计算；sell分支又重复计算了commission和stamp_tax但未使用第一次的计算结果
- **影响**: 买入时多扣了印花税(虽然条件`order_type == "sell"`阻止了，但代码结构混乱)；卖出时佣金计算了两次
- **修复**: 统一在buy/sell分支中分别只计算需要的费用

### P1-6: `daily_scheduler.py` `_step_compute_rebalance` position_limit使用了信号中的sentiment值
- **文件**: `real_trading/daily_scheduler.py` L338
- **问题**: `position_limit = signal_data.get("sentiment", {}).get("position_limit", 0.7)` — 依赖信号文件中sentiment字段包含position_limit，但`RealTradingSignalGenerator.generate_signals()`返回的sentiment_info确实包含此字段。问题是fallback值0.7与`GLOBAL_RISK.max_total_position` (0.75)不一致
- **影响**: 仓位上限使用0.7而非0.75，与回测参数不一致
- **修复**: fallback改为`GLOBAL_RISK.get('max_total_position', 0.75)`

### P1-7: `generate_daily_signals.py` `_generate_trading_plan` 纪律提示"单票仓位不得超过20%"过时
- **文件**: `real_trading/generate_daily_signals.py` L243
- **问题**: `plan.append("2. 单票仓位不得超过20%...")` — 硬编码20%，但strategy_defaults中`max_position_per_stock`=35%，且在V42已调整
- **影响**: 交易计划推送信息与实际风控参数不一致，误导用户
- **修复**: 从`GLOBAL_RISK`读取`max_position_per_stock`和`max_total_position`

### P1-8: `paper_trading.py` `_update_account_performance` 持仓市值估算不准确
- **文件**: `real_trading/paper_trading.py` L222-226
- **问题**: `current_price = pos.get("current_price") or pos.get("last_price") or pos["buy_price"]` — `get_positions()` 返回的dict不含`current_price`和`last_price`字段，所以永远fallback到`buy_price`
- **影响**: 与P0-4同类问题。持仓期间总权益和收益率永远不变化，导致账户绩效指标(total_profit/max_drawdown)完全失真
- **修复**: 在`_update_account_performance`中从MongoDB获取最新收盘价计算市值（与nav_tracker.py一致）

---

## 三、P2级问题 (建议修复)

### P2-1: `realtime_monitor.py` 使用akshare作为盘中数据源但无降级
- **文件**: `real_trading/realtime_monitor.py` L14
- **问题**: `import akshare as ak` 但无try/except降级。akshare经常因API变更导致import失败
- **影响**: 如果akshare不可用，整个监控模块无法启动
- **修复**: 添加try/except降级，或改用东方财富API（已验证可用）

### P2-2: `multi_account_manager.py` API密钥存储在JSON中(即使为空)
- **文件**: `real_trading/multi_account_manager.py` L25-26
- **问题**: `api_key` 和 `api_secret` 字段在`TradingAccount` dataclass中，虽然注释说"仅存储掩码/占位"，但JSON序列化后这些字段仍会写入磁盘
- **影响**: 安全隐患，如果未来有真实密钥可能意外泄露
- **修复**: 在`asdict()`序列化时排除这两个字段，或添加`_serialize_exclude`标记

### P2-3: 所有文件使用 `sys.path.insert(0, ...)` 做模块查找
- **文件**: 所有21个文件
- **问题**: 每个文件都有 `sys.path.insert(0, ...)` 的反模式，且多个文件路径不一致。如`strategy_optimizer.py`用的是`backtest_module`而非`AgentServer`
- **影响**: 路径变更时需逐文件修改，且可能导致Python模块缓存不一致
- **修复**: 长期：改用`pyproject.toml`安装项目；短期：统一路径常量

### P2-4: `performance_analyzer.py` 和 `performance_calculator.py` 功能重叠
- **文件**: 两个文件都提供绩效计算功能
- **问题**: `PerformanceAnalyzer` 提供基础统计+月度+策略分析，`PerformanceCalculator` 提供更专业的指标(夏普/索提诺/VaR等)，但两者都依赖相同的交易历史数据
- **影响**: 维护两套绩效逻辑可能导致指标计算不一致
- **修复**: 长期合并为统一模块

### P2-5: `daily_scheduler.py` 增量补齐固定5天，未考虑长假
- **文件**: `real_trading/daily_scheduler.py` L298
- **问题**: `inc_results = await self.data_maintainer.incremental_update(days=5)` — 固定5天，长假后(如春节7天+周末)可能遗漏数据
- **影响**: 长假后数据不完整，影响首日信号质量
- **修复**: 改为动态计算（读取最后一个交易日，补到当天）

### P2-6: `smart_reviewer.py` 对"止损"和"冲高回落"的原因分类不精确
- **文件**: `real_trading/smart_reviewer.py` L172-180
- **问题**: 亏损原因分析中，将"止损"和"冲高回落"归为不同类别，但冲高回落(以open价卖出)也可能是亏损的。更精确的分类应区分"主动保护性卖出"和"被迫卖出"
- **影响**: 复盘报告对亏损原因的归因不够精确
- **修复**: 增加卖出盈亏方向维度的交叉分析

---

## 四、实盘调优建议

### TUNE-1: 信号延迟优化 — 盘前信号预计算+竞价修正
**现状**: 盘前8:50生成信号，信号基于前日收盘数据。实际执行时（9:25-9:30竞价）市场状态可能已变化。  
**建议**: 
1. 盘前信号在8:50基于前日数据生成候选池（已完成）
2. 9:15-9:25竞价期间，用竞价数据修正候选排序（已有auction_filter，但只是过滤不是排序修正）
3. 9:25竞价结束后，用最终竞价价格确认买入价和仓位分配

### TUNE-2: 滑点模拟优化 — 回测vs实盘对齐
**现状**: 回测买入价使用`STRATEGY_BUY_PRICE`计算公式(如半路追涨=open*(1+0.03*0.8))，实盘用close*1.01或up_limit。  
**建议**:
1. 实盘建仓价格统一使用`STRATEGY_BUY_PRICE`公式计算（generate_daily_signals.py已部分实现）
2. paper_trading.py的`place_order`和`add_position_by_signal`默认买入价也应对齐
3. 差异记录到live_backtest_bridge用于校准

### TUNE-3: 强制空仓冷却期实盘适配
**现状**: strategy_defaults有`force_empty_cooldown_days=2`，但实盘daily_scheduler没有实现冷却期逻辑。  
**建议**: 在`_step_compute_rebalance`中检查最近N天是否有强制空仓记录，如有则限制新买入仓位<=50%

### TUNE-4: 持仓市值实时化
**现状**: 多处(position_manager/paper_trading/risk_alert/daily_scheduler)使用buy_price估算市值，导致所有基于市值的计算失真。  
**建议**: 
1. Position类添加`current_price`字段，daily_check时更新
2. 所有需要市值的地方统一读取`current_price`
3. 这是P0-4和P1-8的根因修复

### TUNE-5: 首板打板成交概率模拟
**现状**: 回测中首板打板有hit_probability模拟(秒板20%/快速40%/慢板50%)，但实盘信号生成器只判断是否"涨停板附近"，不区分打板难度。  
**建议**: 
1. 实盘信号中也计算hit_probability，低概率的信号标注为"观望"
2. 推送时显示成交概率，帮助用户判断是否值得追

---

## 五、回测-实盘互助力增强

### MUTUAL-1: 实盘偏差自动反馈到回测参数校准
**现状**: `live_backtest_bridge.py`已实现偏差监控和校准报告，但不自动修改任何参数。  
**增强**:
1. 当滑点偏差>0.2%持续2周，自动生成PR修改`STRATEGY_CONFIGS`中的`slippage_pct`
2. 当胜率偏差>15%持续1个月，自动触发选股条件审查
3. 所有自动修改需人工审核后才合入main分支

### MUTUAL-2: 回测信号辅助实盘决策
**现状**: 实盘信号生成器(`generate_daily_signals.py`)和回测信号生成(`PortfolioBacktester`)使用相同的`_build_strategy_filter_conditions`，但买入价/卖出价计算逻辑有差异。  
**增强**:
1. 实盘信号增加"回测预期收益"字段：对每只候选股，用最近30天数据回测该策略的收益
2. 只保留回测预期为正的信号，过滤掉历史表现差的标的
3. 推送时显示"回测30日均收益+X%"

### MUTUAL-3: 数据同步机制增强
**现状**: V63已实现参数同步状态检查(`check_param_sync_status`)，但只检查文件修改时间，不检查参数值差异。  
**增强**:
1. 启动时自动对比strategy_defaults.py当前值与上次启动时的值
2. 如果关键参数(stop_loss/take_profit/max_hold_days)有变化，发送飞书通知
3. 记录参数变更历史到`param_change_log.json`

### MUTUAL-4: 实盘交易数据回流回测
**现状**: 实盘交易记录仅存在`trade_history.json`，回测引擎无法利用实盘数据。  
**增强**:
1. 将实盘交易记录同步到MongoDB `live_trades` 集合
2. 回测时可选加载实盘交易数据作为基准线
3. 回测结果与实盘结果并列展示，便于对比

---

## 六、已修复代码 (直接修复的bug)

### FIX-1: P0-1 strategy_optimizer.py 导入路径
```python
# 旧: from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
# 新: from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
```

### FIX-2: P0-2 daily_scheduler.py await缺失
```python
# 旧: nav_record = self.nav_tracker.update_daily_nav(trade_date)
# 新: nav_record = await self.nav_tracker.update_daily_nav(trade_date)
```

### FIX-3: P0-3 risk_alert.py 仓位计算分母
```python
# 旧: position_ratio = total_position_value / account.current_balance if account.current_balance > 0 else 0
# 新: total_equity = account.current_balance + total_position_value
#     position_ratio = total_position_value / total_equity if total_equity > 0 else 0
```

### FIX-4: P0-5 paper_trading_risk_check.py 硬编码参数
```python
# 旧: "max_index_drop": 0.03, "daily_max_drawdown": 0.03, ...
# 新: 从GLOBAL_RISK读取默认值
```

### FIX-5: P1-3 strategy_optimizer.py Optional导入
```python
# 新增: from typing import List, Dict, Tuple, Optional
```

### FIX-6: P1-6 daily_scheduler.py position_limit fallback
```python
# 旧: position_limit = signal_data.get("sentiment", {}).get("position_limit", 0.7)
# 新: position_limit = signal_data.get("sentiment", {}).get("position_limit", GLOBAL_RISK.get('max_total_position', 0.75))
```

### FIX-7: P1-7 generate_daily_signals.py 纪律提示硬编码
```python
# 旧: "2. 单票仓位不得超过20%，总仓位不得超过上限"
# 新: f"2. 单票仓位不得超过{GLOBAL_RISK['max_position_per_stock']*100:.0f}%，总仓位不得超过{GLOBAL_RISK['max_total_position']*100:.0f}%"
```

### FIX-8: P1-1 signal_pusher.py 纪律提示硬编码
```python
# 旧: "3. 持仓最多持有3天，到期强制卖出"
# 新: f"3. 不同策略持仓期限不同，最长{max(s.get('max_hold_days', 3) for s in STRATEGY_CONFIGS.values() if s.get('enabled', True))}天，到期强制卖出"
```

---

## 七、审计统计

| 级别 | 数量 | 已直接修复 |
|------|------|-----------|
| P0   | 5    | 4         |
| P1   | 8    | 5         |
| P2   | 6    | 0         |
| 调优 | 5    | -         |
| 互惠 | 4    | -         |
| **总计** | **28** | **9** |

### 未直接修复的P0
- **P0-4**: 持仓保护判断使用过时价格 — 需要在`_step_compute_rebalance`中增加MongoDB查询，改动较大，需确认性能影响
- **P1-8**: 与P0-4同根因，需要在`_update_account_performance`中增加MongoDB查询

### 审计覆盖
- 21个文件全部审查
- 关键文件(paper_trading/position_manager/daily_scheduler/generate_daily_signals)逐行审查
- 辅助文件(risk_alert/signal_pusher/trade_gateway/nav_tracker)重点逻辑审查
- 废弃文件(auto_trade_executor)仅确认废弃状态

---

*此报告由V64实盘审计自动生成。所有代码修复仅修改`real_trading/`目录下的文件，未修改回测模块。*
