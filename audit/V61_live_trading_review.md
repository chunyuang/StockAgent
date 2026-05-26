# V61 实盘交易模块审计报告

> 审计日期：2026-05-27
> 审计范围：real_trading/、core/managers/live/、nodes/listener/
> 核心原则：不影响回测模块
> **已应用修复：P0-1, P0-2, P0-4, P0-5, P1-1, P1-4, P2-4**

---

## 审计摘要

| 严重等级 | 数量 | 已修复 | 说明 |
|----------|------|--------|------|
| P0 | 4 | 4 | 运行时崩溃/数据错误，必须立即修复 |
| P1 | 5 | 2 | 逻辑不一致/信号缺失，影响实盘收益 |
| P2 | 4 | 1 | 代码质量/可维护性问题 |
| **总计** | **13** | **7** | |

**最严重发现**：
1. `core/managers/live/nav_tracker.py` 使用未定义变量 `REAL_TRACING_DIR`，运行必崩
2. `core/managers/live/risk_checker.py` 使用未定义变量 `index_code`，市场环境检查必崩
3. `core/managers/live/position_manager.py` 使用自然日计算持仓天数，与回测(交易日)不一致，龙头低吸5天低利润退出可能早触发或晚触发
4. `core/managers/live/position_manager.py` 缺少V60龙头5天低利润退出、缺少策略级参数读取

---

## A. 回测-实盘一致性

### P0-1: live/position_manager.py 持仓天数使用自然日 vs 回测使用交易日

**文件**: `AgentServer/core/managers/live/position_manager.py` L55-68
**影响**: 超时判断错误。周五买入→周一自然日=3天，但回测中是1个交易日。龙头低吸max_hold=7天自然日≈4-5交易日，实际应持有7个交易日(约10自然日)。

**回测行为**: `portfolio_backtest._calc_trade_days_held()` 查MongoDB交易日历，返回交易日数。
**real_trading行为**: 使用交易日近似(`natural_days / 1.5`)。
**live行为**: 直接用自然日`(current_date - buy_date).days`。

**修复**: 将live/position_manager.py的hold_days改为与real_trading/position_manager.py一致的交易日计算。

```python
# === core/managers/live/position_manager.py L55-68 修复 ===
# 替换整个 hold_days 方法

def hold_days(self, current_date: str = None) -> int:
    """计算持仓天数（交易日）
    
    【V61修复:使用交易日而非自然日,与回测引擎_calc_trade_days_held()保持一致】
    自然日计算会导致:周五买入→周一hold_days=3(自然日)→误触发超时(实际仅1个交易日)
    """
    if not current_date:
        current_date = datetime.now().strftime("%Y%m%d")
    try:
        # 优先使用交易日历计算(与回测一致)
        from core.managers import mongo_manager
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在async上下文中,用自然日/1.5近似
                buy_dt = datetime.strptime(self.buy_date, "%Y%m%d")
                current_dt = datetime.strptime(current_date, "%Y%m%d")
                natural_days = (current_dt - buy_dt).days
                return max(0, int(natural_days / 1.5))  # 周末/节假日近似
        except RuntimeError:
            pass
        # 同步上下文:查MongoDB交易日历
        trade_dates = asyncio.get_event_loop().run_until_complete(
            mongo_manager.distinct("stock_daily_ak_full", "trade_date",
                {"trade_date": {"$gte": int(self.buy_date), "$lte": int(current_date)}})
        )
        return max(0, len(trade_dates) - 1)  # 买入日算第0天
    except Exception as e:
        logger.debug(f"交易日计算失败,fallback自然日/1.5: {e}")
        buy_dt = datetime.strptime(self.buy_date, "%Y%m%d")
        current_dt = datetime.strptime(current_date, "%Y%m%d")
        return max(0, int((current_dt - buy_dt).days / 1.5))  # 周末/节假日近似
```

---

### P0-2: live/position_manager.py 缺少V60龙头5天低利润退出检查

**文件**: `AgentServer/core/managers/live/position_manager.py` L385-415 (daily_check方法)
**影响**: 龙头低吸持仓5天利润<3%时不会提前告警退出，占用资金+增加回撤风险。回测中已有此逻辑(V60-优化2)。

**回测行为**: `portfolio_backtest.py` L381-400，龙头低吸持仓5天利润<3%→强制卖出。
**real_trading行为**: 已有此逻辑(L419-425)。
**live行为**: 完全缺失。

**修复**: 在daily_check的超时检查之后添加龙头5天低利润检查：

```python
# === core/managers/live/position_manager.py daily_check方法中 ===
# 在 "检查强制平仓" 代码块之后添加:

            # 【V61:龙头低吸5天低利润提前退出,与回测_check_and_execute_forced_sells对齐】
            if not alert.get('level'):
                _strategy = pos.strategy or '未知'
                _strategy_id = None
                for sid, cfg in STRATEGY_CONFIGS.items():
                    if cfg.get('name') == _strategy:
                        _strategy_id = sid
                        break
                if _strategy_id == 'dragon_head' and alert['hold_days'] >= 5:
                    profit_pct = pos.current_profit_pct(current_price)
                    if profit_pct < 3.0:  # 5天利润<3%
                        alert["alerts"].append(f"⚠️ 龙头5天低利润：持仓{alert['hold_days']}天收益仅{profit_pct:.1f}%，建议提前退出")
                        alert["level"] = "danger"
```

---

### P0-3: live/position_manager.py _check_early_sell_signals 使用策略中文名而非英文ID

**文件**: `AgentServer/core/managers/live/position_manager.py` L426-500
**影响**: `SellSignalChecker` 的 `check_early_sell()` 方法内部使用 `STRATEGY_SELL_SIGNALS` 字典，该字典的key是策略中文名(如"龙头低吸")。但传入的 `strategies` 参数也是中文名，所以这里实际上是**正确**的。然而，策略参数查找是通过 `self._strategy_params[strategy_name]` 传入的，如果 `strategy_name` 与 SellSignalChecker 内部的注册名不一致，会找不到参数。

**分析**: `SellSignalChecker.__init__` 接收 `strategy_params: Dict[str, dict]`，key是策略名。`STRATEGY_SELL_SIGNALS` 的key也是中文名(如"半路追涨"、"龙头低吸")。因此传入中文名是正确的。

**但是**: 利润锁定检查在 `_check_early_sell_signals` 中手写，没有使用 `INTRADAY_PROFIT_LOCK_SIGNALS`，而是直接从 `GLOBAL_RISK` 读取参数，缺少策略级覆盖。这与回测 `check_full_sell` 使用 `INTRADAY_PROFIT_LOCK_SIGNALS` 不一致。

**实际影响**: 目前 `STRATEGY_CONFIGS` 中没有任何策略定义 `intraday_lock_*` 在 riskParams 中(这些参数只存在于 GLOBAL_RISK)，所以策略级覆盖不会生效。但如果未来某个策略需要不同的利润锁定参数，live版不会响应。

**严重等级降为P2-3**，见P2部分。

---

### P1-1: live/position_manager.py 缺少策略级冲高回落/利润保护参数读取

**文件**: `AgentServer/core/managers/live/position_manager.py` L426-500 (`_check_early_sell_signals` 方法)
**影响**: 利润锁定参数只从 `GLOBAL_RISK` 读取，不读策略级参数。

**对比**:
- `real_trading/position_manager.py` L464-471: 读取策略级 `intraday_lock_min_high_rise`/`intraday_lock_pullback_pct`/`intraday_lock_min_profit`
- `core/managers/live/position_manager.py` L485-487: 只读 `GLOBAL_RISK`，没有策略级覆盖

**修复**: 在利润锁定检查中添加策略级参数覆盖：

```python
# === core/managers/live/position_manager.py _check_early_sell_signals ===
# 替换 L485-487:

            # 利润锁定参数: 优先策略级, 回退全局
            lock_min_high = GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.05)
            lock_pullback = GLOBAL_RISK.get('intraday_lock_pullback_pct', 0.02)
            lock_min_profit = GLOBAL_RISK.get('intraday_lock_min_profit', 0.02)
            # 【V61:策略级参数覆盖,与real_trading/position_manager对齐】
            if strategy_risk_params:
                if 'intraday_lock_min_high_rise' in strategy_risk_params:
                    lock_min_high = strategy_risk_params['intraday_lock_min_high_rise']
                if 'intraday_lock_pullback_pct' in strategy_risk_params:
                    lock_pullback = strategy_risk_params['intraday_lock_pullback_pct']
                if 'intraday_lock_min_profit' in strategy_risk_params:
                    lock_min_profit = strategy_risk_params['intraday_lock_min_profit']
```

---

### P1-2: listener/position_manager.py 缺少利润锁定和龙头5天低利润退出

**文件**: `AgentServer/nodes/listener/execution/position_manager.py` L280-430
**影响**: Listener节点（虽已废弃但仍可启动）缺少：
1. 利润锁定信号(盘中冲高≥5%回撤≥2%收盘≥2%)
2. 龙头5天低利润退出
3. 冲高回落缺少策略级参数(next_day_open_sell_pct从strategy_risk读取正确，但mid_fallback和高阈值硬编码0.01/0.05)

**修复**: 由于Listener已废弃(V54-P0-1已阻止启动)，此处仅标注。如果Listener重新启用，需完整对齐。

---

### P1-3: V59参数(intraday_lock_min_high_rise=0.05, intraday_lock_pullback_pct=0.02, hold_protection_threshold=0.05)同步状态

**检查结果**:

| 参数 | strategy_defaults.py | real_trading/position_manager.py | live/position_manager.py | listener/position_manager.py |
|------|---------------------|--------------------------------|-------------------------|-----------------------------|
| intraday_lock_min_high_rise | 0.05 ✅ | 从GLOBAL_RISK读取 ✅ | 从GLOBAL_RISK读取 ✅ | ❌缺失利润锁定 |
| intraday_lock_pullback_pct | 0.02 ✅ | 从GLOBAL_RISK读取 ✅ | 从GLOBAL_RISK读取 ✅ | ❌缺失利润锁定 |
| hold_protection_threshold | 0.05 ✅ | daily_scheduler读取 ✅ | ❌缺失 | ❌缺失 |
| intraday_lock_min_profit | 0.02 ✅ | 从GLOBAL_RISK读取 ✅ | 从GLOBAL_RISK读取 ✅ | ❌缺失利润锁定 |

**结论**: `hold_protection_threshold` 在 `live/position_manager.py` 中未使用。该参数主要用于调仓时保护盈利持仓不被调出。live/position_manager的daily_check是纯告警模式，不执行调仓，所以缺失影响较小。但如果live版被用于自动交易，此参数必须补上。

---

## B. 实盘优化

### P0-4: live/nav_tracker.py 使用未定义变量 REAL_TRACING_DIR

**文件**: `AgentServer/core/managers/live/nav_tracker.py` L137, L547
**影响**: 运行时 `NameError: name 'REAL_TRACING_DIR' is not defined`，nav_tracker完全无法使用。

**根因**: 从 `real_trading/nav_tracker.py` 迁移时遗漏了 `REAL_TRACING_DIR` 和 `PROJECT_ROOT` 的定义。

**修复**:

```python
# === core/managers/live/nav_tracker.py ===
# 在文件顶部(imports之后)添加:

import os
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
REAL_TRACING_DIR = os.path.join(_PROJECT_ROOT, 'real_trading')

# 然后替换 L137:
#   self.data_dir = os.path.join(REAL_TRACING_DIR, "nav_history")
# 改为:
#   self.data_dir = data_dir or os.path.join(REAL_TRACING_DIR, "nav_history")

# 替换 L547:
#   trade_history_file = os.path.join(REAL_TRACING_DIR, "trade_history.json")
# (同上，已定义REAL_TRACING_DIR后无需修改)
```

---

### P0-5: live/risk_checker.py 使用未定义变量 index_code

**文件**: `AgentServer/core/managers/live/risk_checker.py` L252
**影响**: `_check_market_environment()` 调用时 `NameError: name 'index_code' is not defined`，市场环境检查完全失效。

**根因**: 应该使用 `self.config["reference_index"]`（值为"sh000001"），但代码中写成了未定义的 `index_code`。

**修复**:

```python
# === core/managers/live/risk_checker.py L252 ===
# 替换:
#   {'ts_code': index_code, 'trade_date': {'$gte': int(datetime.now().strftime('%Y%m%d')) - 100}},
# 为:
#   {'ts_code': self.config["reference_index"], 'trade_date': {'$gte': int(datetime.now().strftime('%Y%m%d')) - 100}},

# 同时 L254:
#   today_drop = abs(index_doc.get('pct_chg', 0) / 100) if index_doc and index_doc.get('pct_chg') else self.market_data.get(f"{index_code}_today_drop", 0.01)
# 替换 index_code 为 self.config["reference_index"]

# L258, L260 同样替换:
#   details = {"index_code": self.config["reference_index"], ...}
#   return False, f"市场环境恶劣，{self.config['reference_index']}今日跌幅..."
```

---

### P1-4: signal_pusher.py 推送止损止盈信息硬编码5%/10%/20%

**文件**: `AgentServer/core/managers/live/signal_pusher.py` L212-213, L227
**影响**: 推送消息中的止损止盈价和仓位限制与实际策略参数不一致，误导用户。

**具体问题**:
1. L212: `stock['close'] * 0.95` → 止损价按5%算，实际策略止损3%
2. L213: `stock['close'] * 1.1` → 止盈价按10%算，实际策略止盈7%-30%
3. L227: "单票仓位不超过20%" → 实际max_position_per_stock=35%

**修复**:

```python
# === core/managers/live/signal_pusher.py _generate_markdown_content ===
# 替换 L209-215 附近:

                for idx, stock in enumerate(signals, 1):
                    lhb_tag = " 🎉龙虎榜" if stock.get("has_lhb") else ""
                    content.append(f"#### {idx}. {stock['name']}({stock['ts_code']}){lhb_tag}")
                    content.append(f"- 策略：**{stock['strategy']}** | 行业：{stock.get('industry', '未知')}")
                    content.append(f"- 信号类型：**{stock.get('signal_type', '买入')}**")
                    confidence = stock.get('confidence')
                    if confidence is not None:
                        content.append(f"- 置信度：**{confidence:.0%}**")
                    content.append(f"- 收盘价：**{stock['close']:.2f}** | 涨跌幅：**{stock['pct_chg']:.2f}%**")
                    
                    # 【V61:从strategy_defaults读取策略级止损止盈,不再硬编码5%/10%】
                    from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK, STRATEGY_NAME_TO_ID
                    _strategy_id = STRATEGY_NAME_TO_ID.get(stock.get('strategy', ''), '')
                    _risk_params = STRATEGY_CONFIGS.get(_strategy_id, {}).get('riskParams', {})
                    _sl_pct = _risk_params.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])
                    _tp_pct = _risk_params.get('take_profit_pct', GLOBAL_RISK['take_profit_pct'])
                    _slippage = _risk_params.get('slippage_pct', GLOBAL_RISK['slippage_pct'])
                    
                    buy_price = stock['close'] * (1 + _slippage)  # 含滑点的买入价
                    content.append(f"- 建议买入价：≤**{buy_price:.2f}**")
                    content.append(f"- 止损价：**{buy_price * (1 - _sl_pct):.2f}**(-{_sl_pct*100:.0f}%) | 止盈价：**{buy_price * (1 + _tp_pct):.2f}**(+{_tp_pct*100:.0f}%)")
                    
                    reason = stock.get('reason') or stock.get('recommend_reason')
                    if reason:
                        content.append(f"- 推荐理由：{reason}")
                    if stock.get("has_lhb"):
                        content.append(f"- 龙虎榜净买入：**{stock['lhb_net_buy']/10000:.1f}万** | 原因：{stock.get('lhb_reason', '')}")
                    content.append("")

# L227 替换:
#   content.append("2. 单票仓位不超过20%，总仓位不超过上限")
# 为:
                    content.append(f"2. 单票仓位不超过{GLOBAL_RISK['max_position_per_stock']*100:.0f}%，总仓位不超过{GLOBAL_RISK['max_total_position']*100:.0f}%")
```

**注意**: `real_trading/signal_pusher.py` 有完全相同的问题，同样需要修复。

---

### P1-5: risk_checker.py _check_market_environment 使用同步方式调用async MongoDB

**文件**: `AgentServer/core/managers/live/risk_checker.py` L250-253
**影响**: `asyncio.get_event_loop().run_until_complete()` 在已有event loop的async上下文中会报错 `This event loop is already running`。

**修复**: 将 `_check_market_environment` 改为async方法，或使用 `nest_asyncio`：

```python
# === core/managers/live/risk_checker.py ===
# 方案1: 将_check_market_environment改为async (推荐)

    async def _check_market_environment(self) -> Tuple[bool, str, Dict]:
        """检查市场环境(异步版本)"""
        if not self.config["market_filter_enabled"]:
            return True, "市场环境过滤已禁用", {"enabled": False}
        
        index_code = self.config["reference_index"]
        try:
            from core.managers.mongo_manager import mongo_manager
            if not mongo_manager.client:
                await mongo_manager.initialize()
            index_doc = await mongo_manager.find_one(
                "stock_daily_ak_full",
                {'ts_code': index_code, 'trade_date': {'$gte': int(datetime.now().strftime('%Y%m%d')) - 100}},
                sort=[('trade_date', -1)],
                projection={'pct_chg': 1}
            )
            today_drop = abs(index_doc.get('pct_chg', 0) / 100) if index_doc and index_doc.get('pct_chg') else self.market_data.get(f"{index_code}_today_drop", 0.01)
            
            # ... 后续逻辑不变
        
        except Exception as e:
            logger.error(f"⚠️  市场环境检查异常: {e}")
            return True, "市场环境检查异常，默认允许交易", {"error": str(e)}

# 同时 check_before_buy 中的调用也要 await
```

---

### P2-1: risk_checker.py 缺少force_empty(强制空仓)检查

**文件**: `AgentServer/core/managers/live/risk_checker.py`
**影响**: 买入前风控不检查大盘是否触发强制空仓条件(跌停≥80只/涨停≤10只/大盘跌≥3%)。回测中这些条件通过 `_print_market_environment` 和 `force_empty` 逻辑实现。

**当前检查**: 只检查指数跌幅(`max_index_drop=0.03`)，但不检查涨跌停数量。

**建议修复**:

```python
# 在 _check_market_environment 中增加涨跌停检查:
    async def _check_limit_board_environment(self) -> Tuple[bool, str, Dict]:
        """检查涨跌停环境"""
        from core.managers.mongo_manager import mongo_manager
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        
        today = int(datetime.now().strftime('%Y%m%d'))
        try:
            # 统计涨停/跌停数量
            limit_up_count = await mongo_manager.count_documents(
                "stock_daily_ak_full",
                {"trade_date": today, "pct_chg": {"$gte": 9.8}}
            )
            limit_down_count = await mongo_manager.count_documents(
                "stock_daily_ak_full",
                {"trade_date": today, "pct_chg": {"$lte": -9.8}}
            )
            
            force_empty_limit_down = GLOBAL_RISK.get('force_empty_limit_down', 80)
            force_empty_limit_up = GLOBAL_RISK.get('force_empty_limit_up', 10)
            
            if limit_down_count >= force_empty_limit_down:
                return False, f"跌停{limit_down_count}只≥{force_empty_limit_down}只，强制空仓", {"limit_down": limit_down_count}
            if limit_up_count <= force_empty_limit_up:
                return False, f"涨停{limit_up_count}只≤{force_empty_limit_up}只，强制空仓", {"limit_up": limit_up_count}
            
            return True, f"涨停{limit_up_count}只/跌停{limit_down_count}只，正常", {"limit_up": limit_up_count, "limit_down": limit_down_count}
        except Exception as e:
            logger.warning(f"涨跌停检查失败: {e}")
            return True, "涨跌停检查异常，默认允许", {"error": str(e)}
```

---

## C. 实盘-回测相互助力

### C1. 回测卖出信号反哺实盘

回测的卖出信号优先级体系(冲高回落 > 利润保护 > 高开即卖 > 利润锁定 > 止损 > 跳空止损 > 止盈 > 超时 > 龙头5天低利润)已在 `SellSignalChecker` 中完整实现。

**实盘现状**:
- `real_trading/position_manager.py`: 手写逻辑实现，与回测基本对齐但有细节差异
- `core/managers/live/position_manager.py`: 使用 `SellSignalChecker.check_early_sell()` + 手写利润锁定，V60龙头5天低利润缺失
- `listener/position_manager.py`: 手写逻辑，缺少利润锁定和龙头5天低利润

**建议**: 统一使用 `SellSignalChecker` 作为唯一卖出信号来源，避免三套代码维护三套逻辑。

### C2. 实盘滑点/成交概率校准回测

**当前状态**:
- 回测中首板打板使用成交概率模拟(一字0%/秒板20%/快速40%/盘中50%)
- 实盘的成交概率尚未统计(无数据反馈机制)

**建议**: 在 `paper_trading_compat.py` 中记录每笔申报→成交的实际概率，定期统计并与回测参数对比。

### C3. 龙头低吸5天低利润退出(V60)实盘对应

**回测**: `portfolio_backtest.py` L381-400，龙头低吸持仓5天利润<3%→`龙头5天低利润`退出
**实盘(real_trading)**: `position_manager.py` L419-425，danger级别告警
**实盘(live)**: ❌ 缺失(P0-2已列出修复)
**实盘(listener)**: ❌ 缺失(Listener已废弃)

---

## D. 代码质量

### P2-2: live/position_manager.py 与 real_trading/position_manager.py 大量重复代码

**问题**: 两个文件共1300+行，约60%代码重复。`real_trading/` 版本更新(V49-V60)，`live/` 版本停留在V47。维护两套代码是严重的技术债。

**建议**: `real_trading/position_manager.py` 是权威版本。`core/managers/live/position_manager.py` 应该直接import real_trading版本，或提取公共基类。

### P2-3: live/position_manager.py _check_early_sell_signals 利润锁定未使用INTRADAY_PROFIT_LOCK_SIGNALS

**文件**: `core/managers/live/position_manager.py` L472-497
**问题**: 利润锁定是手写逻辑，而回测使用 `INTRADAY_PROFIT_LOCK_SIGNALS` 注册表。如果新增策略有不同利润锁定参数，live版需要手动添加if/else。

**影响**: 当前所有策略使用GLOBAL_RISK的统一参数，暂无影响。但扩展性差。

### P2-4: live/paper_trading_compat.py PaperAccount 缺少必要属性

**文件**: `core/managers/live/paper_trading_compat.py` L69-76
**问题**: `PaperAccount` 缺少 `current_balance`、`initial_balance`、`status` 属性，但 `nav_tracker.py` 引用了这些属性(如 `self.account.current_balance` L163, `self.account.initial_balance` L165)。

**影响**: `nav_tracker.py` 运行时会抛 `AttributeError`。

**修复**:

```python
# === core/managers/live/paper_trading_compat.py PaperAccount ===
# 替换为:

class PaperAccount:
    """模拟账户 — 兼容旧接口"""
    
    def __init__(self, account_id: str, name: str = "", initial_cash: float = 1_000_000):
        self.account_id = account_id
        self.name = name or account_id
        self.initial_balance = initial_cash
        self.current_balance = initial_cash
        self.status = "active"
        self.engine = PaperTradingEngine(account_id, initial_cash)
```

---

## 修复优先级和影响评估

| # | 严重等级 | 问题 | 影响范围 | 修复难度 |
|---|---------|------|---------|---------|
| P0-1 | P0 | live/position_manager.py 自然日vs交易日 | 龙头低吸超时判断错误 | 低 |
| P0-2 | P0 | live/position_manager.py 缺V60龙头5天低利润 | 龙头低吸利润回吐 | 低 |
| P0-4 | P0 | live/nav_tracker.py REAL_TRACING_DIR未定义 | nav_tracker完全不可用 | 低 |
| P0-5 | P0 | live/risk_checker.py index_code未定义 | 市场环境检查崩溃 | 低 |
| P1-1 | P1 | live/position_manager.py 缺策略级利润锁定参数 | 未来策略参数覆盖失效 | 低 |
| P1-4 | P1 | signal_pusher.py 硬编码5%/10%/20% | 推送信息误导 | 低 |
| P1-5 | P1 | risk_checker.py 同步调用async MongoDB | async上下文中报错 | 中 |
| P2-1 | P2 | risk_checker.py 缺强制空仓涨跌停检查 | 极端行情下可能继续开仓 | 中 |
| P2-2 | P2 | 两套position_manager.py代码重复 | 维护成本高 | 高 |
| P2-3 | P2 | 利润锁定手写vs注册表 | 扩展性差 | 中 |
| P2-4 | P2 | PaperAccount缺属性 | nav_tracker报错 | 低 |

---

## 两套Position Manager差异对比表

| 特性 | real_trading/ | core/managers/live/ | 回测 |
|------|--------------|---------------------|------|
| hold_days计算 | 交易日(MongoDB/1.5近似) | 自然日 ❌ | 交易日 |
| 止损止盈来源 | strategy_defaults ✅ | strategy_defaults ✅ | strategy_defaults |
| 跳空止损 | 区分open/止损价 ✅ | 区分open/止损价 ✅ | SellSignalChecker |
| 冲高回落 | 手写+策略级参数 ✅ | SellSignalChecker ✅ | SellSignalChecker |
| 利润保护 | 手写 ✅ | SellSignalChecker ✅ | SellSignalChecker |
| 高开即卖 | 首板打板专用 ✅ | SellSignalChecker ✅ | SellSignalChecker |
| 利润锁定 | 手写+策略级参数 ✅ | 手写(缺策略级) | INTRADAY_PROFIT_LOCK |
| V60龙头5天低利润 | ✅ | ❌ | ✅ |
| hold_protection_threshold | daily_scheduler ✅ | ❌ | ✅ |
| _save_positions | _save_positions() | save_to_mongodb() | N/A |

---

## 附录：实盘活跃模块清单(V54重构后)

| 模块 | 路径 | 行数 | 外部引用 | 状态 |
|------|------|------|---------|------|
| signal_pusher | core/managers/live/ | 380 | 3 | ✅活跃 |
| risk_checker | core/managers/live/ | 667 | 1 | ⚠️有P0 bug |
| paper_trading_compat | core/managers/live/ | 78 | 3 | ⚠️PaperAccount缺属性 |
| performance_analyzer | core/managers/live/ | 494 | 3 | ✅活跃 |
| position_manager | core/managers/live/ | 671 | 2 | ⚠️多个P0/P1 |
| nav_tracker | core/managers/live/ | 614 | 1 | ❌不可用(未定义变量) |

> 已废弃模块(在_deprecated/目录): trade_gateway, smart_reviewer, generate_daily_signals, risk_alert, daily_rebalance_report, realtime_monitor, strategy_optimizer, performance_calculator

---

*报告由审计Agent自动生成 | 2026-05-27*

---

## 已应用修复清单

以下修复已直接应用到代码文件中：

| # | 问题 | 修复文件 | 状态 |
|---|------|---------|------|
| P0-1 | hold_days自然日→交易日 | core/managers/live/position_manager.py | ✅已修复 |
| P0-2 | 缺V60龙头5天低利润 | core/managers/live/position_manager.py | ✅已修复 |
| P0-4 | REAL_TRACING_DIR未定义 | core/managers/live/nav_tracker.py | ✅已修复 |
| P0-5 | index_code未定义 | core/managers/live/risk_checker.py | ✅已修复 |
| P1-1 | 缺策略级利润锁定参数 | core/managers/live/position_manager.py | ✅已修复 |
| P1-4 | signal_pusher硬编码SL/TP | live/signal_pusher.py + real_trading/signal_pusher.py | ✅已修复 |
| P2-4 | PaperAccount缺属性 | core/managers/live/paper_trading_compat.py | ✅已修复 |
| P1-5 | risk_checker sync→async | (未修复,需更大范围改动) | ⏳待修复 |
| P2-1 | risk_checker缺涨跌停检查 | (未修复,需新增方法) | ⏳待修复 |
| P2-2 | 两套position_manager重复 | (未修复,架构重构) | ⏳待修复 |
| P2-3 | 利润锁定手写vs注册表 | (未修复,扩展性问题) | ⏳待修复 |
