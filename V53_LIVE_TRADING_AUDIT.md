# V53 实盘交易模块审查报告

> 审查时间：2026-05-26  
> 审查范围：real_trading/ 全部13个模块  
> 回测参数来源：AgentServer/nodes/backtest_engine/strategy_defaults.py  
> 审查人：实盘交易模块审查专家

---

## 目录

1. [问题汇总](#1-问题汇总)
2. [逐文件审查](#2-逐文件审查)
3. [回测↔实盘双向助力建议](#3-回测实盘双向助力建议)
4. [已验证和未验证的问题](#4-已验证和未验证的问题)
5. [修复代码](#5-修复代码)

---

## 1. 问题汇总

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 | 3 | 直接影响交易结果或资金安全的严重问题 |
| P1 | 8 | 参数不一致、逻辑偏差、风控漏洞 |
| P2 | 7 | 代码质量、可维护性、性能问题 |
| P3 | 4 | 注释、命名、风格等小问题 |

### P0 问题清单

| # | 文件 | 问题 |
|---|------|------|
| P0-1 | daily_scheduler.py | max_position_per_stock fallback 0.2 与 strategy_defaults 0.35 不一致 |
| P0-2 | generate_daily_signals.py | 信号生成使用 pct_chg(T日因子)，存在未来函数风险 |
| P0-3 | trade_gateway.py | auto_trade_by_signal 硬编码 max_single_position=0.2，与 strategy_defaults 0.35 不一致 |

### P1 问题清单

| # | 文件 | 问题 |
|---|------|------|
| P1-1 | daily_scheduler.py | _step_compute_rebalance 盈利计算公式符号错误 |
| P1-2 | daily_scheduler.py | 持仓保护盈利计算未扣滑点成本 |
| P1-3 | paper_trading.py | _t1_blocked 集合只添加不清除(跨session失效) |
| P1-4 | paper_trading.py | daily_settlement T+1清除逻辑错误 |
| P1-5 | pre_buy_risk_check.py | 市场环境检查使用模拟数据，非实际行情 |
| P1-6 | pre_buy_risk_check.py | 个股风险检查使用缓存模拟数据 |
| P1-7 | risk_alert.py | run_daily_check 错误日志("✅"用logger.error) |
| P1-8 | position_manager.py | hold_days 异步上下文中自然日/1.5近似精度不足 |

### P2 问题清单

| # | 文件 | 问题 |
|---|------|------|
| P2-1 | auto_trade_executor.py | 模块已废弃但仍存在，调用不存在的API |
| P2-2 | all files | sys.path.insert 反模式 |
| P2-3 | mobile_api.py | API_KEY为空时仅warning不阻止启动 |
| P2-4 | performance_report.py | 每次调用新建MongoDB连接不关闭 |
| P2-5 | nav_tracker.py | 持仓市值用 buy_price 而非 current_price |
| P2-6 | risk_alert.py | check_account_risk 是 async 但 run_daily_check 非async |
| P2-7 | trade_gateway.py | SimulatedGateway.get_realtime_quote 使用 run_until_complete 可能冲突 |

### P3 问题清单

| # | 文件 | 问题 |
|---|------|------|
| P3-1 | smart_reviewer.py | 无策略参数来源引用 |
| P3-2 | position_manager.py | add_position_by_signal 默认买入价 close*1.01 未对齐回测 |
| P3-3 | generate_daily_signals.py | _get_strategy_for_stock 策略判断逻辑过于简化 |
| P3-4 | daily_scheduler.py | PROJECT_ROOT 路径硬编码6层上级目录 |

---

## 2. 逐文件审查

### 2.1 paper_trading.py — 模拟交易核心

**已验证的V52遗留修复：**
- ✅ 止损止盈已从 strategy_defaults 动态读取（V40修复）
- ✅ 滑点已从策略级参数读取（V38修复）
- ✅ 卖出滑点规则已调用 should_apply_slippage（V52修复）
- ✅ 跳空止损/冲高回落卖出价格已对齐回测（V47/V48修复）
- ✅ T+1约束已实现（V50修复）

**发现的问题：**

#### P1-3: _t1_blocked 集合只添加不清除(跨session失效)

```python
# 第161-163行
if not hasattr(self, '_t1_blocked'):
    self._t1_blocked = set()
self._t1_blocked.add(f"{account_id}:{ts_code}")
```

问题：`_t1_blocked` 是实例属性，PaperTradingEngine 每次 `_load_accounts` 都会重新创建。如果进程重启，T+1锁定信息丢失。更重要的是，`daily_settlement` 中的清除逻辑有bug。

#### P1-4: daily_settlement T+1清除逻辑错误

```python
# 第193-198行
self._t1_blocked = {
    k for k in self._t1_blocked 
    if k.split(':')[0] in accounts  # 只清相关账户
}
```

问题：这个清除逻辑保留了"账户ID在accounts列表中"的记录，但注释说"只保留当日买入的,清除过期的"。实际上它没有清除任何过期记录——它保留的是属于当前账户的记录，而不是当日的。正确逻辑应该是：次日运行时，清除所有T+1锁定（因为次日可以卖出昨日买入的），只保留当日新买入的。

**修复方案：** daily_settlement 中清除T+1锁定应在结算完成后统一清除，而不是在开始时条件性保留。具体修复见第5节。

#### 其他观察：
- 佣金万3与 strategy_defaults.commission_rate=0.0003 对齐 ✅
- 印花税千1与 strategy_defaults.stamp_duty_rate=0.001 对齐 ✅
- 卖出时滑点扣减逻辑与回测 SLIPPAGE_RULES 对齐 ✅

---

### 2.2 daily_scheduler.py — 每日调度

#### P0-1: max_position_per_stock fallback 0.2 与 strategy_defaults 0.35 不一致

```python
# 第151行
"max_position_per_stock": global_risk["max_position_per_stock"],  # 0.2
```

注释写0.2但 strategy_defaults 中 `max_position_per_stock=0.35`。实际值取决于运行时 global_risk 的值，注释误导。如果 global_risk 正确读取，值为0.35，注释应更新。

**严重性：** 注释误导，实际值应正确（因为从GLOBAL_RISK读取），但需验证运行时是否正确加载。

#### P1-1: _step_compute_rebalance 盈利计算公式符号错误

```python
# 第296行
profit_pct = (p.get("current_price", 0) or p.get("buy_price", 0) - p["buy_price"]) / p["buy_price"]
```

Python运算符优先级：`0 or p.get("buy_price", 0) - p["buy_price"]` 会先计算 `p.get("buy_price", 0) - p["buy_price"]`（=0），然后 `0 or 0` = `0`。当 `current_price` 为0或不存在时，profit_pct 永远为0。

正确逻辑应该是：
```python
_current = p.get("current_price") or p.get("last_price") or p["buy_price"]
profit_pct = (_current - p["buy_price"]) / p["buy_price"] if p["buy_price"] > 0 else 0
```

#### P1-2: 持仓保护盈利计算未扣滑点成本

`_step_compute_rebalance` 中的持仓保护判断 `profit_pct >= hold_protection_threshold` 使用的是简单价差收益率。但回测中，持仓保护是在考虑了买入滑点后的实际成本基础上计算的。实盘应保持一致，使用包含滑点的买入价（即 `actual_buy_price`）。

影响：轻微。如果滑点0.2%，偏差约0.2%，对5%阈值影响不大，但逻辑应一致。

---

### 2.3 generate_daily_signals.py — 信号生成

#### P0-2: 信号生成使用 pct_chg(T日因子)，存在未来函数风险

这是最关键的问题。信号生成流程中：

1. **`_get_stock_details`** 读取了 `pct_chg`（T日收盘才确定）
2. **`_get_strategy_for_stock`** 使用 `pct_chg >= 5` 判断策略
3. **`backtester._build_strategy_filter_conditions`** 的筛选条件中包含 `pct_chg` 相关条件

根据V25未来函数分析（memory记录）：
- 半路追涨 `pct_chg≥5%` 贡献48.4%总收益，去掉后胜率从69.8%→45.2%
- `pct_chg` 本质是过滤"冲高回落"假信号
- **实盘建议：半路追涨需改收盘价买入**

strategy_defaults 中有 `live_trading_mode: False` 开关，但信号生成器未使用此开关。

**修复方案：** 
1. 信号生成器应检查 `GLOBAL_RISK["live_trading_mode"]`
2. 当 `live_trading_mode=True` 时，将 pct_chg 条件降级为使用前一日数据
3. 半路追涨的信号应在收盘确认后生成（盘后生成，次日执行）

---

### 2.4 pre_buy_risk_check.py — 买入前风控

**V52遗留验证：**
- ✅ 止损阈值已从 strategy_defaults 读取，不再硬编码5%

#### P1-5: 市场环境检查使用模拟数据

```python
# 第178行
today_drop = self.market_data.get(f"{index_code}_today_drop", 0.01)  # 模拟1%跌幅
```

`_check_market_environment` 使用硬编码模拟数据而非实际行情。这意味着市场环境过滤形同虚设——默认总是1%跌幅（低于3%阈值），永远通过。

**修复方案：** 从MongoDB获取上证指数当日数据，计算实际跌幅。

#### P1-6: 个股风险检查使用缓存模拟数据

```python
# 第222行
stock_info = self.stock_risk_cache.get(ts_code, {
    "market_cap": 50,  # 模拟50亿市值
    "volatility_20d": 0.15,  # 模拟20日波动率15%
})
```

`_check_stock_risk` 使用模拟默认数据。当股票不在缓存中时，默认50亿市值/15%波动率总是通过检查，风控形同虚设。

**修复方案：** 从MongoDB的 `stock_daily_ak_full` / `daily_basic` 获取实际市值和波动率数据。

---

### 2.5 smart_reviewer.py — 智能复盘

无P0/P1问题。模块功能完整，复盘逻辑合理。

**P3-1: 无策略参数来源引用**

复盘建议中提到"收紧止损幅度"等，但未引用 strategy_defaults 中的实际参数值，无法量化建议。

---

### 2.6 trade_gateway.py — 交易网关

#### P0-3: auto_trade_by_signal 硬编码 max_single_position=0.2

```python
# 第373行
def auto_trade_by_signal(self, signals, max_position=0.7, max_single_position=0.2):
```

strategy_defaults 中 `max_position_per_stock=0.35`（3只均分=33%，留2%buffer）。此默认值0.2=20%过于保守，会导致：
- 最多买3只（0.7/0.2=3.5），每只20%仓位
- 资金利用率不足（3只×20%=60%，剩余40%闲置）

**修复方案：** 默认值应从 strategy_defaults 读取。

#### P2-7: SimulatedGateway.get_realtime_quote 使用 run_until_complete

```python
# 第219行
loop = asyncio.get_event_loop()
doc = loop.run_until_complete(mongo_manager.find_one(...))
```

在已有事件循环（如FastAPI/uvicorn）中调用 `run_until_complete` 会抛出 RuntimeError。仅在CLI直接运行时安全。

---

### 2.7 performance_calculator.py — 绩效计算

无P0/P1问题。计算逻辑完整，与回测指标体系对齐。

Sortino比率计算使用 `sum(r^2)/N`（仅下行），与V30回测修复后的方式一致。✅

---

### 2.8 performance_report.py — 绩效报告

#### P2-4: 每次调用新建MongoDB连接不关闭

```python
# 第71-75行
import pymongo
from core.settings import settings as _s
_client = pymongo.MongoClient(_s.mongo.url)
_db = _client[_s.mongo.database]
doc = _db.stock_daily_ak_full.find_one(...)
_client.close()
```

每次获取当前价格都新建连接，性能差且可能耗尽连接池。应使用 mongo_manager。

---

### 2.9 mobile_api.py — 移动端API

#### P2-3: API_KEY为空时仅warning不阻止启动

```python
# 第22-24行
API_KEY = os.getenv("MOBILE_API_KEY", "")
if not API_KEY:
    import warnings
    warnings.warn("MOBILE_API_KEY 未设置...")
```

API_KEY为空时仍可启动服务，虽然每个请求都会401，但更好的做法是启动时即报错退出。

---

### 2.10 auto_trade_executor.py — 自动执行器

#### P2-1: 模块已废弃，调用不存在的API

文件头已标注 `V52已废弃`，但代码仍调用 `engine.sell()` 和 `engine.buy()` 方法（PaperTradingEngine 只有 `close_position` 和 `place_order`）。如有人误用会直接报错。

**建议：** 删除此文件或在 `__init__.py` 中移除导出，避免误用。

---

### 2.11 position_manager.py — 仓位管理

**已验证的修复：**
- ✅ 止损止盈已从 strategy_defaults 动态读取（V40修复）
- ✅ 中文名→英文ID反向映射（V35修复）
- ✅ 跳空止损与回测对齐（V50修复）
- ✅ 冲高回落/利润保护/利润锁定与回测对齐（V49/V50修复）
- ✅ 高开即卖(首板打板)已实现（V50修复）

#### P1-8: hold_days 异步上下文中自然日/1.5近似精度不足

```python
# 第70行
return max(0, int(natural_days / 1.5))  # 周末/节假日近似
```

回测引擎使用精确的交易日历（`_calc_trade_days_held` O(1)索引映射），而实盘在async上下文中只能用自然日/1.5近似。周五买入→周一 = 3天/1.5 = 2天（实际1个交易日），偏差1天。

**影响：** 可能导致持仓超期判断提前1天触发，提前卖出。对max_hold_days=3的策略影响较大。

**修复方案：** 预加载交易日历到内存，避免async查询。

#### P3-2: add_position_by_signal 默认买入价 close*1.01 未对齐回测

```python
# 第140行
buy_price = signal["close"] * 1.01
```

回测中买入价由 `STRATEGY_BUY_PRICE` 函数计算（如半路追涨用open+涨幅加权），而非统一close*1.01。此方法在 paper_trading.py.place_order 中已不使用（place_order 直接接受买入价），但 add_position_by_signal 的便捷入口仍用旧逻辑。

---

### 2.12 risk_alert.py — 风控警报

#### P1-7: run_daily_check 错误日志级别

```python
# 第167行
if not alerts:
    logger.error("✅ 今日风控检查通过，无异常")
```

"无异常"是正常状态，不应使用 `logger.error`。应为 `logger.info`。

#### P2-6: check_account_risk 是 async 但 run_daily_check 非async

```python
# 第99行
async def check_account_risk(self, account_id: str) -> List[Dict]:

# 第155行
def run_daily_check(self, account_id: str = None):
    ...
    alerts.extend(self.check_account_risk(acc_id))  # ❌ 调用async函数未await
```

`run_daily_check` 是同步函数但调用了 `async check_account_risk`，返回的是coroutine对象而非实际结果。告警不会实际执行。

---

### 2.13 nav_tracker.py — 净值追踪

#### P2-5: 持仓市值用 buy_price 而非 current_price

```python
# 第143行
market_value = sum(p["shares"] * p.get("current_price", p["buy_price"]) for p in positions)
```

`get_positions()` 返回的字典中没有 `current_price` 字段（PositionManager.get_positions 只返回 buy_price/shares/total_cost 等），所以 `p.get("current_price", p["buy_price"])` 永远 fallback 到 buy_price。

**影响：** 净值计算中持仓市值始终等于成本，PnL永远为0，净值曲线无法反映真实收益。

**修复方案：** 在 update_daily_nav 中从MongoDB获取当日收盘价计算市值。

---

## 3. 回测↔实盘双向助力建议

### 3.1 回测→实盘反馈（回测结果指导实盘参数调整）

| 建议编号 | 内容 | 优先级 |
|----------|------|--------|
| RTF-1 | 回测的胜率/盈亏比/最大回撤应作为实盘参数调整的基准线。当实盘胜率显著低于回测时（如>10%偏差），自动触发策略参数重新校准 | 高 |
| RTF-2 | 回测的卖出原因分布（止损/止盈/冲高回落/超时占比）应指导实盘风控参数调整。如止损占比>30%，应检查买入筛选标准 | 高 |
| RTF-3 | 回测中V47的龙头低吸max_hold_days=7已在strategy_defaults更新，实盘应自动跟随（已通过PositionManager从strategy_defaults读取实现）✅ | — |
| RTF-4 | 回测的STRATEGY_PULLBACK_PARAMS（如龙头低吸profit_lock_threshold=0.08）应同步到实盘position_manager的daily_check | 中 |

### 3.2 实盘→回测反馈（实盘交易结果反馈到回测参数调优）

| 建议编号 | 内容 | 优先级 |
|----------|------|--------|
| FTR-1 | 实盘滑点/成交率数据应反馈到回测。如某策略实际滑点>回测假设，应调整回测的slippage_pct | 高 |
| FTR-2 | 实盘的pct_chg未来函数影响应量化。实盘使用_prev替代pct_chg后的胜率对比回测胜率，差值即为未来函数溢价 | 高 |
| FTR-3 | 实盘交易记录应可导入回测引擎重新回测，验证"如果用相同标的和时机，回测结果是否一致" | 中 |
| FTR-4 | 实盘的持仓天数分布应与回测对比。如实盘平均持仓>回测（因为盘中无法及时卖出），需在回测中增加卖出延迟 | 中 |
| FTR-5 | 实盘成交率（特别是首板打板）应反馈到回测的hit_probability参数 | 中 |

---

## 4. 已验证和未验证的问题

### 4.1 已验证的V52遗留问题

| 遗留问题 | 状态 | 验证结果 |
|----------|------|----------|
| pre_buy_risk_check.py 硬编码5%止损 | ✅ 已修复 | check_before_sell 从 strategy_defaults 动态读取止损阈值 |
| auto_trade_executor.py 使用旧API | ⚠️ 已标注废弃 | 文件头已标注V52废弃，但代码仍存在且调用不存在的buy()/sell()方法 |

### 4.2 已验证的修复（V35-V52在各模块中的体现）

| 修复 | 验证状态 | 文件 |
|------|----------|------|
| V40: 止损止盈从strategy_defaults读取 | ✅ | paper_trading.py, position_manager.py |
| V38: 滑点从策略级参数读取 | ✅ | paper_trading.py |
| V35: 中文名→英文ID映射 | ✅ | paper_trading.py, position_manager.py |
| V50: T+1约束 | ✅ | paper_trading.py |
| V47: 止损价/跳空止损卖出价格对齐 | ✅ | paper_trading.py |
| V48: 冲高回落/利润保护卖出价对齐 | ✅ | paper_trading.py |
| V49: 冲高回落等阈值从strategy_defaults读取 | ✅ | position_manager.py |
| V52: should_apply_slippage调用 | ✅ | paper_trading.py |

### 4.3 未验证的潜在问题

| 问题 | 风险 | 需验证方式 |
|------|------|------------|
| 实盘信号生成是否在盘后运行（避免pct_chg未来函数） | 高 | 检查cron调度时间 |
| PositionManager.hold_days 在async环境中的精度 | 中 | 端到端测试 |
| nav_tracker净值计算中current_price缺失 | 高 | 检查实际净值记录 |
| pre_buy_risk_check的风控是否被绕过 | 高 | 模拟触发场景 |

---

## 5. 修复代码

### Fix P0-1: daily_scheduler.py max_position_per_stock 注释修正<tool_call>edit<arg_key>path</arg_key><arg_value>/root/.openclaw/workspace/StockAgent/real_trading/daily_scheduler.py