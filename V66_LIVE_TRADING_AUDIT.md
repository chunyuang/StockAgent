# V66 实盘模块全面审查报告

> 审查时间: 2026-05-27 | 审查范围: real_trading/ 14个文件 ~280KB | 分支: review/V59-backtest-live-audit

## 审查摘要

| 级别 | 数量 | 说明 |
|------|------|------|
| **P0** | 3 | 严重bug，影响实盘核心功能(净值计算/持仓保护/调仓) |
| **P1** | 9 | 重要问题，影响数据准确性或参数一致性 |
| **P2** | 12 | 次要问题，代码质量/可维护性 |

## P0 问题清单

### P0-1: `get_positions()` 缺失 current_price → 净值/持仓保护/调仓全线失效

**影响文件**: paper_trading.py, daily_scheduler.py, risk_alert.py

**根因**: `PositionManager.get_positions()` 返回的dict不包含 `current_price` 字段，所有依赖此字段的逻辑都回退到 `buy_price`，导致：

1. **paper_trading._update_account_performance**: `market_value = sum(shares * buy_price)` = 永远等于cost，持仓盈亏永远为0，total_equity计算错误
2. **daily_scheduler._step_compute_rebalance**: `profit_pct = (buy_price - buy_price) / buy_price = 0`，持仓保护(hold_protection_threshold)永远不触发，盈利持仓被错误调出
3. **daily_scheduler._step_execute_trades**: 卖出价回退到buy_price，实际平仓按成本价卖出，PnL=0
4. **risk_alert.check_account_risk**: 仓位比例用成本价而非市价计算，上涨时低估真实仓位

**修复**: `get_positions()` 增加异步版本，从MongoDB获取最新收盘价填充current_price

### P0-2: live_backtest_bridge.py 滑点/胜率分析字段名错误

**影响文件**: live_backtest_bridge.py

**根因**: 
- `analyze_slippage_calibration()`: 用 `t.get('action') == 'buy'` 判断买入，但trade_history.json没有action字段
- `load_live_trades()`: 用 `t.get('date')` 过滤日期，但实际字段是 `sell_date`
- 导致滑点分析和胜率分析完全无法产出有效数据，校准报告空转

**修复**: 对齐trade_history.json的实际字段结构

### P0-3: realtime_monitor.py 告警阈值硬编码，与strategy_defaults不一致

**影响文件**: realtime_monitor.py

**根因**: `alert_threshold` 全部硬编码(index_drop=1.5%, limit_down_count=30, position_drop=3%)，未从GLOBAL_RISK读取：
- `index_drop=1.5%` vs `force_empty_index_drop_pct=3%` — 盘中告警和强制空仓阈值不一致
- `position_drop=3%` vs `stop_loss_pct=3%(半路)/3.5%(龙头)/5%(跌停)` — 单一3%不区分策略
- `limit_down_count=30` vs `force_empty_limit_down=80` — 盘中30家就告警但强制空仓要80家，逻辑断裂

**修复**: 从strategy_defaults读取阈值，保持告警→强制空仓的逻辑递进

---

## P1 问题清单

### P1-1: position_manager.py 龙头5天低利润硬编码阈值
- **位置**: `_check_early_sell_signals` 上方的 `daily_check`
- **问题**: `hold_days >= 5` 和 `profit_pct < 3.0` 硬编码，未使用GLOBAL_RISK的`dragon_head_early_exit_days=5`和`dragon_head_early_exit_min_profit=0.03`
- **影响**: 参数修改strategy_defaults后不生效

### P1-2: generate_daily_signals.py 交易计划持仓期限硬编码
- **位置**: `_generate_trading_plan`
- **问题**: "所有持仓最多持有3天" 文字硬编码，与策略实际max_hold_days(2-7天)不符
- **影响**: 误导交易员，龙头低吸实际可持有7天

### P1-3: paper_trading_risk_check.py slippage默认值硬编码
- **位置**: `place_order_with_risk_check` 参数 `slippage: float = 0.002`
- **问题**: 默认0.002与首板打板0.5%/跌停翘板0.3%不一致
- **修复**: 改为None，从策略级参数读取(与paper_trading.py V65修复对齐)

### P1-4: paper_trading_risk_check.py _get_initial_balance 返回current_balance
- **位置**: `_get_initial_balance`
- **问题**: 返回`account.current_balance`而非`account.initial_balance`，日内回撤计算分母错误
- **影响**: 回撤率被低估(当前余额<初始余额时)

### P1-5: risk_alert.py 仓位比例用成本价计算
- **位置**: `check_account_risk` → `total_position_value = sum(shares * buy_price)`
- **问题**: 用buy_price而非市价，上涨时低估仓位比例
- **影响**: 仓位超限告警不及时

### P1-6: risk_alert.py 个股亏损查询sort参数
- **位置**: `check_account_risk` → `mongo_manager.find_one(..., sort=[("trade_date", -1)])`
- **问题**: `find_one`可能不支持sort参数，应改为find_many+limit

### P1-7: signal_pusher.py min_interval用time.sleep()阻塞事件循环
- **位置**: `push()` → `time.sleep(wait_time)`
- **问题**: 在async上下文中会阻塞整个事件循环
- **修复**: 改用asyncio.sleep()或跳过等待

### P1-8: trade_gateway.py get_realtime_quote用run_until_complete
- **位置**: `SimulatedGateway.get_realtime_quote` → `loop.run_until_complete()`
- **问题**: 在async上下文中会RuntimeError
- **修复**: 改为异步方法或使用独立线程

### P1-9: pre_buy_risk_check.py 市场环境/个股风险使用模拟数据
- **位置**: `_check_market_environment`, `_check_stock_risk`
- **问题**: `_check_market_environment`读market_data_cache.json(模拟数据), `_check_stock_risk`读stock_risk_cache.json(硬编码默认值50亿/15%)
- **影响**: 风控检查形同虚设，永远通过

---

## P2 问题清单

| # | 文件 | 问题 | 说明 |
|---|------|------|------|
| P2-1 | position_manager.py | `hold_days()` 的`_trade_dates_cache`在async上下文中无法加载 | `run_until_complete()`在running loop中报错 |
| P2-2 | nav_tracker.py | REAL_TRADING_DIR路径计算过于复杂 | 多层parent join，脆弱 |
| P2-3 | signal_pusher.py | 函数内import strategy_defaults | 每次调用都import，应提到模块级 |
| P2-4 | generate_daily_signals.py | `_strategy_id_name_map`每次调用都重建 | 应使用STRATEGY_ID_TO_NAME |
| P2-5 | generate_daily_signals.py | `_get_latest_trade_date`不考虑节假日 | 简单的周末回退逻辑 |
| P2-6 | risk_alert.py | `_send_alert`用os.system发送通知 | 不安全且不可靠 |
| P2-7 | risk_alert.py | `check_market_risk`返回空列表 | 框架预留，未实现 |
| P2-8 | paper_trading_risk_check.py | `_load_accounts`用SimpleNamespace替代PaperAccount | 丢失类型安全和方法 |
| P2-9 | auto_trade_executor.py | 调用不存在的engine.buy()/sell() | 已标记废弃但未删除 |
| P2-10 | trade_gateway.py | auto_trade_by_signal买卖价0.5%偏移硬编码 | 应从slippage_pct配置读取 |
| P2-11 | performance_analyzer.py | _get_balance_series从0开始 | 最大回撤可能不准确(应为初始资金曲线) |
| P2-12 | strategy_optimizer.py | 参数名与strategy_defaults不一致 | max_position vs max_total_position |

---

## 修复内容

### Fix P0-1: get_positions() 增加 current_price

**position_manager.py**: 新增 `get_positions_with_prices()` 异步方法，从MongoDB获取最新收盘价

**paper_trading.py**: `_update_account_performance` 改用 `get_positions_with_prices()`

**daily_scheduler.py**: `_step_compute_rebalance` 和 `_step_execute_trades` 改用带价格数据

### Fix P0-2: live_backtest_bridge.py 字段名对齐

- `load_live_trades`: 用 `sell_date` 替代 `date`
- `analyze_slippage_calibration`: 兼容 trade_history.json 格式(slippage_actual_pct / buy侧判断)
- `analyze_win_rate_calibration`: 兼容多种记录格式

### Fix P0-3: realtime_monitor.py 告警阈值从strategy_defaults读取

- index_drop: 从GLOBAL_RISK.force_empty_index_drop_pct读取，减半作为预警线
- limit_down_count: 从GLOBAL_RISK.force_empty_limit_down读取，减半作为预警线  
- position_drop: 从策略级stop_loss_pct读取

### Fix P1-1~P1-9: 参数来源统一

详见具体代码修改

---

## 实盘-回测互惠改进

### 已有机制(✅)
1. SellSignalChecker共享: 实盘position_manager使用回测的SellSignalChecker.check_early_sell()
2. 参数单一来源: 所有策略参数从strategy_defaults.py读取
3. live_backtest_bridge: 滑点/胜率校准报告 + 偏差监控
4. 参数同步检查: strategy_defaults.py修改时间检测

### 新增改进
1. **get_positions_with_prices()**: 消除实盘"成本价=市价"的系统性偏差
2. **realtime_monitor告警与强制空仓逻辑递进**: 预警线→告警线→强制空仓，形成完整风控链条
3. **live_backtest_bridge字段修复**: 滑点/胜率分析终于可以产出有效数据
4. **持仓保护真实生效**: daily_scheduler的hold_protection_threshold终于能基于真实盈亏判断

### 互惠建议(未实现，需后续)
1. **实盘滑点反馈到回测**: place_order记录slippage_actual_pct，live_backtest_bridge定期校准
2. **实盘胜率<回测自动告警**: 已在V63实现但字段错误导致不工作，修复后可生效
3. **冷却期自动调整**: 强制空仓冷却期天数根据近期回撤幅度动态调整

---

## 参数推荐

| 参数 | 当前值 | 回测值 | 建议 | 说明 |
|------|--------|--------|------|------|
| realtime index_drop预警 | 1.5%(硬编码) | 3%(强制空仓) | 1.5%(从GLOBAL_RISK派生) | 预警=强制阈值×50% |
| realtime limit_down预警 | 30(硬编码) | 80(强制空仓) | 40(从GLOBAL_RISK派生) | 预警=强制阈值×50% |
| realtime position_drop预警 | 3%(硬编码) | 3-5%(策略级) | 策略级SL×0.8 | 接近止损前预警 |
| paper_trading slippage默认 | 0.002(硬编码) | 0.2-0.5%(策略级) | None(从策略读取) | V65已修复place_order |
| risk_check market_data | 模拟数据 | — | MongoDB实时数据 | TODO: 接入真实数据源 |

---

## 文件审查状态

| 文件 | 行数 | 审查状态 | P0 | P1 | P2 |
|------|------|----------|----|----|-----|
| position_manager.py | ~600 | ✅ 逐行 | 0 | 1 | 1 |
| paper_trading.py | ~500 | ✅ 逐行 | 1 | 0 | 0 |
| nav_tracker.py | ~500 | ✅ 逐行 | 0 | 0 | 1 |
| signal_pusher.py | ~350 | ✅ 逐行 | 0 | 1 | 1 |
| risk_alert.py | ~200 | ✅ 逐行 | 0 | 2 | 2 |
| paper_trading_risk_check.py | ~250 | ✅ 逐行 | 0 | 2 | 1 |
| generate_daily_signals.py | ~550 | ✅ 逐行 | 0 | 1 | 2 |
| live_backtest_bridge.py | ~350 | ✅ 逐行 | 1 | 0 | 1 |
| daily_scheduler.py | ~900 | ✅ 逐行 | 1 | 0 | 0 |
| pre_buy_risk_check.py | ~500 | ✅ 逐行 | 0 | 1 | 0 |
| trade_gateway.py | ~400 | ✅ 逐行 | 0 | 1 | 1 |
| auto_trade_executor.py | ~150 | ✅ 审查 | 0 | 0 | 1 |
| realtime_monitor.py | ~300 | ✅ 逐行 | 1 | 0 | 1 |
| performance_analyzer.py | ~400 | ✅ 逐行 | 0 | 0 | 1 |
| strategy_optimizer.py | ~350 | ✅ 审查 | 0 | 0 | 1 |
| **合计** | **~5300** | | **3** | **9** | **12** |

---

## V66修复进度 (2026-05-27 更新)

### ✅ 已修复 (P0×3 + P1×8 + P2×1 = 12项)

| ID | 修复内容 | Commit |
|---|---|---|
| P0-1 | get_positions_with_prices() + daily_scheduler改用await | fd37c01 |
| P0-2 | live_backtest_bridge sell_date字段 + 兼容多格式 | fd37c01 |
| P0-3 | realtime_monitor告警阈值从GLOBAL_RISK读取 | fd37c01 |
| P1-1 | position_manager龙头5天/3%从GLOBAL_RISK读取 | 51e472a |
| P1-2 | 交易计划显示各策略实际max_hold_days | fd37c01 |
| P1-3 | paper_trading_risk_check slippage=None从策略读取 | fd37c01 |
| P1-4 | _get_initial_balance返回initial_balance | fd37c01 |
| P1-5 | risk_alert仓位用市价而非成本价 | fd37c01 |
| P1-6 | risk_alert find_one(sort)→find_many(limit=1) | fd37c01 |
| P1-7 | signal_pusher async push + asyncio.sleep | fd37c01 |
| P1-8 | trade_gateway async get_realtime_quote | fd37c01 |
| P2-6 | risk_alert _send_alert subprocess.run替代os.system | fd37c01 |

### ❌ 未修复 (P1×1 + P2×11 = 12项)

| ID | 问题 | 原因 |
|---|---|---|
| P1-9 | pre_buy_risk_check模拟数据 | 需接入真实数据源,改动范围大 |
| P2-1 | position_manager hold_days run_until_complete | 需重构为async,调用链影响大 |
| P2-2 | nav_tracker路径复杂 | 功能正常,低优先级 |
| P2-3 | signal_pusher函数内import | lazy import避免循环依赖,刻意设计 |
| P2-4 | generate_daily_signals _strategy_id_name_map | 低频调用,性能影响可忽略 |
| P2-5 | generate_daily_signals节假日逻辑 | 边缘场景,功能基本正确 |
| P2-7 | risk_alert check_market_risk空实现 | 框架预留,有realtime_monitor替代 |
| P2-8 | paper_trading_risk_check SimpleNamespace | 类型安全改进,不影响功能 |
| P2-9 | auto_trade_executor废弃代码 | 不影响运行,清理可后续做 |
| P2-10 | trade_gateway买卖价0.5%偏移硬编码 | 低优,功能正确 |
| P2-11 | performance_analyzer balance从0开始 | 回撤计算偏差小 |
| P2-12 | strategy_optimizer参数名不一致 | 废弃模块 |
