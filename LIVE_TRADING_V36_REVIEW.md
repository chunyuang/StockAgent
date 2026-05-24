# 实盘模块深度审查报告 (V36)

**审查日期**: 2026-05-24  
**审查范围**: 9个实盘核心文件, ~4900行代码  
**对比基准**: strategy_defaults.py / sell_signal_checker.py / portfolio_backtest.py  
**审查人**: AI Code Reviewer (subagent)

---

## 📊 问题统计

| 级别 | 数量 | 说明 |
|------|------|------|
| **P0** | 4 | 逻辑错误/回测-实盘不一致，必须修复 |
| **P1** | 8 | 功能缺陷/数据不一致，建议修复 |
| **P2** | 10 | 优化建议/代码质量，可择机修复 |

---

## 🔴 P0级问题（必须修复）

### P0-1: 实盘缺少冲高回落/利润保护/利润锁定/高开即卖卖出信号
**文件**: `position_manager.py` (daily_check), `paper_trading.py` (daily_settlement)  
**行号**: position_manager.py L362-450, paper_trading.py L332-395  
**标签**: `回测-实盘不一致`

**问题描述**:  
回测引擎在每日开盘时通过 `SellSignalChecker.check_early_sell()` 执行4类保护性卖出信号：
1. 冲高回落 (高开≥3%且高开低收)
2. 利润保护 (高开低收但收盘仍有≥2%利润)
3. 利润锁定 (盘中冲高≥6%但从高点回撤≥2.5%)
4. 高开即卖 (首板打板专用)

实盘的 `position_manager.daily_check()` **只检查止损/止盈/超期**，完全没有上述4类保护性信号。这意味着：
- 持仓高开低收（冲高回落）时，回测会以open价卖出保护利润，实盘不会
- 盘中冲高8%但回落到5%时，回测有利润锁定，实盘没有
- 首板打板次日高开3%+时，回测高开即卖，实盘不会

**影响**: 实盘利润回吐远大于回测，这是回测-实盘差异的最大来源。  
**修复方案**: 在 `position_manager.daily_check()` 和 `paper_trading.daily_settlement()` 中引入 `SellSignalChecker`，实现与回测一致的卖出信号检查：

```python
from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker

# daily_check中新增:
checker = SellSignalChecker(strategy_params, strategy_risk_params, risk_config)
for ts_code, pos in self.positions.items():
    early_sell_price, early_sell_reason = checker.check_early_sell(
        ts_code, [pos.strategy], pos.buy_price, open_price, close_price)
    if early_sell_price > 0:
        # 触发保护性卖出
```

---

### P0-2: 实盘止损止盈只检查固定价格，不检查盘中高低价
**文件**: `position_manager.py` L419-427  
**行号**: L419 `if low <= pos.stop_loss_price:`, L427 `if high >= pos.take_profit_price:`  
**标签**: `回测-实盘不一致`

**问题描述**:  
回测引擎用 `low <= stop_price` 判断止损（盘中最低价触及止损价）和 `high >= tp_price` 判断止盈（盘中最高价触及止盈价），还区分跳空止损（open直接跳空低开低于止损价）。

实盘 `position_manager.daily_check()` **代码确实使用了low/high**，这一点是对的。但问题是：
- 实盘在 `paper_trading.daily_settlement()` 中执行卖出时，用的是 `alert.get("current_price", 0)` 即收盘价，而非止损价/跳空开盘价
- 回测止损卖出价= `cost * (1 - sl_pct)`，跳空止损= `open`，实盘全用收盘价

**影响**: 止损/跳空止损的卖出价不一致，实盘亏损可能更大（收盘价可能低于止损价）  
**修复方案**: 
```python
# daily_settlement中:
if "止损" in a:
    # 使用止损价而非收盘价
    sell_price = pos.stop_loss_price  # 止损价
    # 检查是否跳空止损(open < stop_loss_price)
    if daily.get("open", 0) <= pos.stop_loss_price:
        sell_price = daily["open"]  # 跳空止损以open卖出
    reason = "跳空止损" if sell_price == daily.get("open", 0) else "止损平仓"
```

---

### P0-3: 实盘止损止盈按固定价格(建仓时设定)，不随策略变更更新
**文件**: `position_manager.py` Position dataclass, `paper_trading.py` L224-233  
**标签**: `回测-实盘不一致`

**问题描述**:  
回测引擎在每一天重新计算 `code_sl, code_tp = self._get_sl_tp_for_code(code)`，这意味着：
- 如果策略参数更新，次日止损止盈线自动跟随
- 多策略同股时，止损取min(所有策略)，止盈取min(所有策略)（V34修复）

实盘在建仓时固定计算 `stop_loss_price = actual_buy_price * (1 - sl_pct)` 和 `take_profit_price = actual_buy_price * (1 + tp_pct)`，之后永不更新。如果：
1. 用户修改了策略参数，已有持仓不会自动更新止损止盈线
2. 持仓策略标签只有一个（如"龙头低吸"），但如果按回测逻辑应该同时属于多策略，止损止盈取最严格值

**影响**: 策略参数变更后，旧持仓无法自动跟随  
**修复方案**: 
1. 每日结算时重新计算止损止盈线：`pos.stop_loss_price = pos.buy_price * (1 - current_sl_pct)`
2. 或者增加"更新止损止盈"方法，在策略参数变更时批量更新

---

### P0-4: 交易计划止损止盈显示与实际计算不一致
**文件**: `generate_daily_signals.py` L491-500  
**行号**: L491-500  
**标签**: `回测-实盘不一致`

**问题描述**:  
在 `_generate_trading_plan()` 中：
```python
# L491: 止损止盈计算使用了策略级参数 + 情绪调整系数
stop_loss_pct = _srisk.get("stop_loss_pct", self.config["stop_loss_pct"]) * sentiment_info.get("stop_loss_adjust", 1.0)
take_profit_pct = _srisk.get("take_profit_pct", self.config["take_profit_pct"]) * sentiment_info.get("take_loss_adjust", 1.0)
stop_loss_price = buy_price * (1 - stop_loss_pct)
take_profit_price = buy_price * (1 + take_profit_pct)

# L499-500: 但显示的是全局参数 * 情绪调整，不是策略级参数
plan.append(f"   止损价：{stop_loss_price:.2f}（跌幅{self.config['stop_loss_pct'] * sentiment_info['stop_loss_adjust'] * 100:.1f}%）")
plan.append(f"   止盈价：{take_profit_price:.2f}（涨幅{self.config['take_profit_pct'] * sentiment_info['take_profit_adjust'] * 100:.1f}%）")
```

**问题1**: 实际计算用的是策略级参数（如龙头低吸SL=3%），但显示用的是全局参数（SL=3%）。数值巧合一致，但逻辑不一致。
**问题2**: `sentiment_info.get("stop_loss_adjust", 1.0)` 和 `sentiment_info.get("take_profit_adjust", 1.0)` 在回测中不存在。回测引擎的止损止盈没有情绪调整系数，这是实盘独有的参数，会导致止损止盈线与回测不同。
**问题3**: 即使显示逻辑修正，止损止盈价格的计算基于预估买入价（非实际成交价），与paper_trading.py建仓时基于实际成交价（含滑点）计算的止损止盈价格不同。

**影响**: 用户看到的止损止盈百分比与实际建仓后的止损止盈不一致  
**修复方案**: 
1. 显示文本改为 `stop_loss_pct * 100` 而非 `self.config['stop_loss_pct'] * sentiment_info['stop_loss_adjust'] * 100`
2. 移除 `stop_loss_adjust` / `take_profit_adjust` 情绪调整，与回测保持一致
3. 或者在交易计划中明确标注"止损止盈为预估值，实际以建仓后为准"

---

## 🟡 P1级问题（建议修复）

### P1-1: 实盘缺少持仓保护(hold_protection)逻辑
**文件**: `position_manager.py`, `paper_trading.py`  
**标签**: `回测-实盘不一致`

回测引擎在调仓卖出时有持仓保护机制（V34/V35）：盈利≥5%的股票不允许被调仓卖出，只能由保护性信号（冲高回落/止损/止盈等）自然退出。实盘的 `daily_scheduler._step_compute_rebalance()` 没有此保护，任何不在信号列表中的持仓都会被调仓卖出，即使盈利5%+。

**修复方案**: 在 `_step_compute_rebalance()` 中增加持仓保护判断：
```python
for pos in current_positions:
    if pos["ts_code"] not in signal_codes:
        profit_pct = (current_price - pos["buy_price"]) / pos["buy_price"]
        if profit_pct >= hold_protection_threshold:
            to_hold.append(pos)  # 盈利保护，不调出
        else:
            to_sell.append(pos)
```

---

### P1-2: 实盘PreBuyRiskChecker市场环境检查使用模拟数据
**文件**: `pre_buy_risk_check.py` L247-264  
**行号**: L256 `today_drop = self.market_data.get(f"{index_code}_today_drop", 0.01)`

市场环境检查的核心数据（上证指数跌幅）使用硬编码的模拟数据（默认1%），而非从MongoDB/东方财富获取实际数据。这意味着：
- 指数跌幅3%时应该拒绝开仓，但实盘永远读到1%的模拟值，风控形同虚设
- `market_data_cache.json` 从未被真实数据填充

**修复方案**: 从MongoDB读取上证指数当日pct_chg：
```python
doc = await mongo_manager.find_one("stock_daily_ak_full", 
    {"ts_code": "000001.SH", "trade_date": int(current_date)})
today_drop = abs(doc["pct_chg"] / 100) if doc else 0
```

---

### P1-3: 实盘PreBuyRiskChecker个股风险检查使用模拟数据
**文件**: `pre_buy_risk_check.py` L307-322  
**行号**: L310-315

个股风险检查（市值/波动率/涨跌停天数）全部使用硬编码模拟数据：
```python
stock_info = self.stock_risk_cache.get(ts_code, {
    "market_cap": 50,  # 模拟50亿市值
    "volatility_20d": 0.15,  # 模拟20日波动率15%
})
```
默认值全在安全范围内，个股风控形同虚设。

**修复方案**: 从MongoDB读取daily_basic获取流通市值，计算20日波动率。

---

### P1-4: 实盘佣金计算与回测不一致
**文件**: `paper_trading.py` L215, `trade_gateway.py` L93-94  
**标签**: `回测-实盘不一致`

回测引擎买入时只扣佣金，不扣印花税（A股规则：买入无印花税）。但 `trade_gateway.py` 的 SimulatedGateway 在买入时同时扣佣金和印花税：
```python
# L161-163: 买入时
commission = max(total_cost * 0.0003, 5)
stamp_tax = total_cost * 0.001 if order_type == "sell" else 0  # 正确：买入不扣
total_payment = total_cost + commission + stamp_tax  # 买入时stamp_tax=0

# L93 注释: "买入：扣除资金+佣金（万2，最低5元）" ← 注释错误，实际代码是万3
```

但 `paper_trading.py` L215 买入只扣佣金，不扣印花税（正确）。所以 `paper_trading.py` 与回测一致，但 `trade_gateway.py` 的注释"万2"与代码"万3"不一致。

**修复方案**: 修正 trade_gateway.py 注释"万2"→"万3"

---

### P1-5: 实盘缺少T+1约束
**文件**: `paper_trading.py`, `position_manager.py`, `daily_scheduler.py`  
**标签**: `回测-实盘不一致`

回测引擎有6处T+1约束（当日买入不可当日卖出），实盘完全没有实现：
- `paper_trading.py` 的 `close_position()` 不检查是否当日建仓
- `position_manager.py` 的 `daily_check()` 不检查是否当日建仓
- `daily_scheduler.py` 的盘中调度可能在同一天先买后卖

虽然实际运行中可能不太会触发（盘前建仓、盘后结算的时间差），但在以下场景会出问题：
- 手动CLI操作：先buy再sell同一天同一股票
- 盘中调度自动止损：当日建仓后盘中触发止损，实盘会执行但A股规则不允许

**修复方案**: Position增加buy_date字段（已有），close_position检查buy_date是否为今天。

---

### P1-6: paper_trading_risk_check.py 是半成品，未集成到主流程
**文件**: `paper_trading_risk_check.py` (全文301行)  
**标签**: `代码质量`

`PaperTradingEngineWithRisk` 类的 `place_order_with_risk_check()` 方法中有 TODO 注释：
```python
# TODO: 这里应该调用原有的buy_stock逻辑
# 模拟返回成功（仅用于演示）
return {"success": True, "msg": "下单成功(风控检查已通过)"}
```

实际交易逻辑未实现，该文件从未被daily_scheduler或其他模块调用。且风控参数硬编码，不从strategy_defaults读取。

**修复方案**: 
1. 将风控检查集成到 `PaperTradingEngine.place_order()` 中（而非创建新类）
2. 风控参数从strategy_defaults读取
3. 删除或标注该文件为废弃

---

### P1-7: daily_scheduler._step_compute_rebalance 卖出逻辑不完整
**文件**: `daily_scheduler.py` L782-812  
**标签**: `逻辑缺陷`

调仓计算中 `to_sell` 只包含"不在信号列表中的持仓"，但缺少：
1. 持仓保护（P1-1）
2. 超期强卖（max_hold_days）— 依赖后续daily_settlement检查
3. 止损/止盈检查 — 依赖后续daily_settlement检查
4. 冲高回落/利润保护 — 完全缺失（P0-1）

**修复方案**: 调仓卖出应综合考虑信号列表+止损止盈+保护性信号+持仓保护

---

### P1-8: generate_daily_signals 止损止盈显示百分比错误
**文件**: `generate_daily_signals.py` L499-500

止损止盈价格使用策略级参数计算（正确），但显示文本使用全局参数：
```python
# 计算用策略级参数
stop_loss_pct = _srisk.get("stop_loss_pct", ...) * sentiment_info.get("stop_loss_adjust", 1.0)
# 显示用全局参数 ← 不一致
f"跌幅{self.config['stop_loss_pct'] * sentiment_info['stop_loss_adjust'] * 100:.1f}%"
```

例如龙头低吸策略SL=3%，全局SL=3%时数值巧合一致，但半路追涨SL=4%时，显示的4%会与全局3%不一致。实际测试：如果策略SL=4%，止损价按4%算，但文字显示3%，用户会困惑。

**修复方案**: 改为 `f"跌幅{stop_loss_pct * 100:.1f}%"` 使用实际计算值

---

## 🔵 P2级问题（可择机修复）

### P2-1: sys.path.insert 反模式
**文件**: 所有实盘文件  
**行号**: L7-8 (每个文件都有)

所有文件开头都有：
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
sys.path.insert(0, os.path.dirname(__file__))
```
代码中已标注FIXME。应改用 pyproject.toml + pip install -e . 方式。

---

### P2-2: position_manager 持仓天数计算使用自然日/1.5近似
**文件**: `position_manager.py` L91-110  
**标签**: `回测-实盘不一致`

回测引擎使用交易日历精确计算 `_calc_trade_days_held()`，实盘在异步上下文中无法使用交易日历，fallback为 `natural_days / 1.5` 近似。周五买入→周一应为1个交易日，近似值为 `2/1.5 ≈ 1.3`，接近但不够精确。

**修复方案**: 预加载交易日历到内存，避免每次查MongoDB。

---

### P2-3: risk_alert.py 仓位计算使用成本价而非市价
**文件**: `risk_alert.py` L179  
**行号**: `total_position_value = sum(pos["shares"] * pos["buy_price"] for pos in positions)`  
**注释已标注**: `# TODO: 用当前市价替代成本价`

代码已自认知问题，但未修复。使用成本价会导致：
- 盈利股的仓位被低估
- 亏损股的仓位被高估
- 仓位超限告警不准确

---

### P2-4: risk_alert.py check_account_risk 是同步方法但调用了await
**文件**: `risk_alert.py` L162  
**行号**: `async def check_account_risk` 中调用 `await mongo_manager.find_one`

`check_account_risk` 是 `async def`，但 `run_daily_check` 是同步方法调用它时不await。这会导致协程未执行，个股亏损检查数据永远是fallback值。

**修复方案**: `run_daily_check` 改为async，或单独处理个股亏损检查。

---

### P2-5: pre_buy_risk_check 连续亏损统计基于独立trade_history.json
**文件**: `pre_buy_risk_check.py` L22-23

PreBuyRiskChecker维护自己的 `trade_history.json`，与position_manager的 `trade_history.json` 是不同文件。两个文件可能不同步，导致连续亏损计数不准确。

**修复方案**: 统一使用position_manager的交易历史，或共享同一个数据源。

---

### P2-6: generate_daily_signals 策略匹配逻辑过于简化
**文件**: `generate_daily_signals.py` L358-373

`_get_strategy_for_stock()` 使用简单规则判断策略：
- 涨停→首板打板
- 涨幅≥5%→半路追涨
- 其他→龙头低吸

这个简化规则与回测的多因子筛选逻辑完全不同，可能导致：
1. 跌停翘板候选被归类为"龙头低吸"
2. 策略标签错误导致止损止盈参数错误

**修复方案**: 使用策略筛选的原始结果（`stock_strategy_map`），不要二次推断。

---

### P2-7: trade_gateway.py SimulatedGateway佣金与paper_trading.py重复实现
**文件**: `trade_gateway.py` L93, `paper_trading.py` L215

两个模块独立实现佣金计算逻辑，注释不一致（trade_gateway注释"万2"但代码"万3"）。如果佣金规则变更需要改两处。

**修复方案**: 提取公共的佣金计算函数。

---

### P2-8: paper_trading.py daily_settlement 卖出滑点未根据策略调整
**文件**: `paper_trading.py` L345-381

daily_settlement中自动平仓时调用 `close_position()` 未传入策略级滑点参数。止损/超期强卖不应扣滑点（与回测SLIPPAGE_RULES一致），但当前代码默认扣0.2%滑点。

**修复方案**: 止损/超期/强制空仓不扣滑点，止盈/冲高回落扣滑点。

---

### P2-9: 信号推送confidence字段未在信号生成中设置
**文件**: `signal_pusher.py` L95-102

SignalPusher支持min_confidence过滤，但 `generate_daily_signals.py` 生成的信号没有confidence字段，导致过滤永远不生效。

**修复方案**: 在信号生成时计算confidence分数。

---

### P2-10: risk_alert.py 使用os.system发送飞书消息
**文件**: `risk_alert.py` L126  
**行号**: `os.system(f'/root/.openclaw/bin/openclaw message send --message "{alert_message}" --channel feishu')`

1. 使用os.system有命令注入风险（alert_message可能含特殊字符）
2. 同步调用会阻塞
3. 依赖openclaw CLI在PATH中

**修复方案**: 使用Python SDK或HTTP API替代。

---

## 📊 回测-实盘参数对齐检查

| 参数 | 回测(strategy_defaults) | 实盘 | 对齐状态 |
|------|------------------------|------|----------|
| 全局止损 | 3% | 3% (从GLOBAL_RISK读取) | ✅ |
| 全局止盈 | 7% | 7% (从GLOBAL_RISK读取) | ✅ |
| 半路追涨SL | 4% | 4% (从STRATEGY_CONFIGS读取) | ✅ |
| 半路追涨TP | 12% | 12% (从STRATEGY_CONFIGS读取) | ✅ |
| 半路追涨hold | 3天 | 3天 (从STRATEGY_CONFIGS读取) | ✅ |
| 龙头低吸SL | 3% | 3% (从STRATEGY_CONFIGS读取) | ✅ |
| 龙头低吸TP | 30% | 30% (从STRATEGY_CONFIGS读取) | ✅ |
| 龙头低吸hold | 5天 | 5天 (从STRATEGY_CONFIGS读取) | ✅ |
| 跌停翘板SL | 5% | 5% (从STRATEGY_CONFIGS读取) | ✅ |
| 跌停翘板TP | 20% | 20% (从STRATEGY_CONFIGS读取) | ✅ |
| 跌停翘板hold | 3天 | 3天 (从STRATEGY_CONFIGS读取) | ✅ |
| 滑点(半路/龙头) | 0.2% | 0.2% (从STRATEGY_CONFIGS读取) | ✅ |
| 滑点(跌停翘板) | 0.3% | 0.3% (从STRATEGY_CONFIGS读取) | ✅ |
| 佣金 | 万3 | 万3 | ✅ |
| 印花税 | 千1 | 千1 | ✅ |
| 强制空仓跌停 | ≥80只 | (委托回测引擎_check_force_empty) | ✅ |
| 强制空仓涨幅 | ≤10只 | (委托回测引擎_check_force_empty) | ✅ |
| 大盘跌幅触发 | ≥3% | (委托回测引擎_check_force_empty) | ✅ |
| 冲高回落 | ✅(check_pullback) | ❌缺失 | **🔴P0-1** |
| 利润保护 | ✅(check_profit_protect) | ❌缺失 | **🔴P0-1** |
| 利润锁定 | ✅(check_intraday_profit_lock) | ❌缺失 | **🔴P0-1** |
| 高开即卖 | ✅(check_high_open_sell) | ❌缺失 | **🔴P0-1** |
| 持仓保护 | ✅(hold_protection) | ❌缺失 | **🟡P1-1** |
| T+1约束 | ✅(6处检查) | ❌缺失 | **🟡P1-5** |
| 跳空止损 | ✅(open≤stop_price) | ❌用收盘价 | **🔴P0-2** |
| 止损不扣滑点 | ✅(SLIPPAGE_RULES) | ❌默认扣 | **🟡P2-8** |
| 市场环境风控 | ✅(实际数据) | ❌模拟数据 | **🟡P1-2** |
| 个股风控 | ✅(实际数据) | ❌模拟数据 | **🟡P1-3** |

---

## 🔄 回测-实盘协同建议

### 1. 卖出信号代码共享

回测的 `SellSignalChecker` 已经是纯函数设计，可以直接在实盘中使用。建议：

```python
# position_manager.py daily_check 中:
from nodes.backtest_engine.factor_selection.sell_signal_checker import (
    SellSignalChecker, should_apply_slippage
)

checker = SellSignalChecker(strategy_params, strategy_risk_params, risk_config)
result = checker.check_early_sell(code, strategies, cost, open_price, close_price)
```

这是最高优先级的对齐工作（P0-1），能让实盘卖出行为与回测完全一致。

### 2. 因子计算代码共享

`generate_daily_signals.py` 已调用回测引擎的 `factor_engine.compute_factors()` 和 `_build_strategy_filter_conditions()`，这是正确的。建议进一步共享：
- 选股结果直接使用策略筛选的 `stock_strategy_map`，不要二次推断（P2-6）
- 买入价计算直接使用 `STRATEGY_BUY_PRICE` 映射（已部分实现，L474）

### 3. 回测结果指导实盘

当前回测参数（STRATEGY_CONFIGS）已经是实盘的单一来源，这很好。可以进一步：
- 回测运行后自动输出当前参数摘要到实盘可读的JSON
- 实盘启动时校验参数版本号，确保与最新回测一致

### 4. 实盘数据反馈回测

建议增加：
- 实盘每日PnL写入MongoDB，回测可以对比同日模拟PnL
- 实盘滑点实际值（成交价vs预期价）统计，反馈到回测滑点模型
- 实盘信号命中率统计（产生信号→实际建仓→最终盈亏），优化信号质量

### 5. 实盘特有优化

| 项目 | 当前状态 | 建议 |
|------|---------|------|
| 异常恢复 | 无 | daily_scheduler增加断点续跑，记录每个step的完成状态 |
| 盘中决策 | 仅检查止损/止盈 | 增加冲高回落实时监控（需要盘中行情） |
| 日志完整性 | logging.info为主 | 增加结构化日志（JSON格式），便于后续分析 |
| 数据校验 | DataMaintainer已实现 | ✅ |
| 仓位管理 | 固定top_n=5 | 根据情绪周期动态调整（冰点期0只，高潮期5只） |

---

## 📋 修复优先级建议

| 优先级 | 问题ID | 修复工作量 | 影响 |
|--------|--------|-----------|------|
| 🔴立即 | P0-1 | 中(2-3天) | 卖出信号对齐，消除最大回测-实盘差异源 |
| 🔴立即 | P0-2 | 小(0.5天) | 止损卖出价修正 |
| 🔴立即 | P0-4 | 小(0.5天) | 交易计划显示修正 |
| 🟡尽快 | P0-3 | 小(0.5天) | 止损止盈动态更新 |
| 🟡尽快 | P1-1 | 小(0.5天) | 持仓保护 |
| 🟡尽快 | P1-2 | 中(1天) | 市场环境风控数据源 |
| 🟡尽快 | P1-3 | 中(1天) | 个股风控数据源 |
| 🟡尽快 | P1-5 | 小(0.5天) | T+1约束 |
| 🟡择机 | P1-4/P1-6/P1-7/P1-8 | 小 | 代码质量 |
| 🔵低优 | P2-x | 各小 | 优化建议 |

---

*报告结束。代码未做任何修改，仅做审查和报告。*
