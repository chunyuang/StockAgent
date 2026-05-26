# V62 实盘交易系统深度审计报告

> **审计时间**: 2026-05-27 04:30~05:00  
> **审计范围**: `real_trading/` 16个文件 + `core/managers/live/` 4个文件  
> **审计基线**: 回测引擎 `sell_signal_checker.py` + `strategy_defaults.py` + `portfolio_backtest.py`  
> **不可修改**: 回测模块代码  

---

## P0: 资金安全或风控漏洞

### P0-1: 两个 PositionManager 实现不一致——卖出信号逻辑完全不同

| 属性 | 值 |
|------|------|
| **文件1** | `real_trading/position_manager.py` (693行) |
| **文件2** | `AgentServer/core/managers/live/position_manager.py` (723行) |
| **行号** | real_trading L458-508 vs live L467-543 |
| **影响** | 🔴 **严重** — 两套代码可能产生不同的风控决策 |

**问题描述**:  
项目存在两份独立的 `PositionManager`，实现逻辑完全不同：

1. **`real_trading/position_manager.py`**: 在 `daily_check()` 中内联实现了所有卖出信号检查（冲高回落/利润保护/高开即卖/利润锁定），用 if-elif 链手动匹配策略名（`_strategy == '首板打板'`）
2. **`core/managers/live/position_manager.py`**: 在 `_check_early_sell_signals()` 中调用回测的 `SellSignalChecker.check_early_sell()`，直接复用回测逻辑

**风险**:
- `paper_trading.py` 引用的是 `real_trading/position_manager.py`（同目录），用内联逻辑
- `nav_tracker.py` 引用的是 `core/managers/live/position_manager.py`（同目录），用 SellSignalChecker
- 两套代码参数读取路径不同、信号优先级不同、边界条件不同
- 修改一处容易遗漏另一处，导致实盘与回测长期不一致

**建议修复**:  
统一为一套实现。推荐方案：`real_trading/position_manager.py` 也采用 `SellSignalChecker`（与 live/ 版本一致），删除内联的 if-elif 卖出逻辑。如果两个模块必须共存，应抽取为共享库。

---

### P0-2: real_trading/position_manager.py 利润保护阈值硬编码 0.02

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L500 |
| **影响** | 🔴 **高** — 利润保护参数无法按策略调整 |

**问题描述**:  
```python
elif close_rise >= 0.02 and open_rise >= 0.02 and current_price < open_p:
```
利润保护的 `min_close_rise` 和 `min_open_rise` 硬编码为 0.02，而回测 `check_profit_protect()` 从 `params` 读取 `profit_protect_min_close_rise` 和 `profit_protect_min_open_rise`（默认也是 0.02，但支持策略级覆盖）。

**风险**:  
未来如果某策略需要调整利润保护阈值（如跌停翘板 min_close_rise=0.03），实盘不会生效，因为硬编码无法被策略参数覆盖。

**建议修复**:  
```python
_pp_min_close = _strategy_params.get('profit_protect_min_close_rise', 0.02)
_pp_min_open = _strategy_params.get('profit_protect_min_open_rise', 0.02)
elif close_rise >= _pp_min_close and open_rise >= _pp_min_open and current_price < open_p:
```

---

### P0-3: real_trading/position_manager.py next_day_open_sell_pct fallback 值与回测不一致

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L458 |
| **影响** | 🔴 **高** — 高开保护阈值不一致 |

**问题描述**:  
```python
_pullback_threshold = _strategy_params.get('next_day_open_sell_pct', GLOBAL_RISK.get('next_day_open_sell_pct', 0.03))
```
fallback 值为 0.03（3%），但 `strategy_defaults.py` 中 `GLOBAL_RISK` 已在 V53 从 3% → 2%。这意味着如果 `strategy_defaults` 导入失败或 `_strategy_params` 为空，fallback 到 0.03 而非正确的 0.02。

对比回测 `check_pullback()`:  
```python
threshold = params.get('next_day_open_sell_pct', GLOBAL_RISK.get('next_day_open_sell_pct', 0.02))
```

**风险**:  
fallback 0.03 意味着高开 2%-3% 的股票不会被冲高回落保护，与回测不一致。

**建议修复**:  
```python
_pullback_threshold = _strategy_params.get('next_day_open_sell_pct', GLOBAL_RISK.get('next_day_open_sell_pct', 0.02))
```

---

### P0-4: paper_trading.py 卖出信号触发级别逻辑不完整——利润保护/利润锁定告警级别不一致

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/paper_trading.py` |
| **行号** | L392-425 |
| **影响** | 🔴 **高** — 利润保护/利润锁定信号可能不被执行 |

**问题描述**:  
`paper_trading.py` 的 `daily_settlement()` 根据告警级别决定是否卖出：
- `danger` 级别 → 止损/超期/冲高回落 → 触发卖出 ✅
- `success` 级别 → 止盈/利润保护/利润锁定 → 触发卖出 ✅

但 `real_trading/position_manager.py` 中：
- 利润保护: `alert["level"] = "success"` ✅
- 利润锁定: `alert["level"] = "success"` ✅

而 `core/managers/live/position_manager.py` 中：
- 利润保护/冲高回落: `alert["level"] = "warning"` ❌
- 利润锁定: `alert["level"] = "warning"` ❌

**风险**:  
如果实际运行的是 live/ 版本的 PositionManager，利润保护和利润锁定信号被标记为 `warning` 级别，而 `paper_trading.py` 只在 `success` 级别处理这些信号，**导致利润保护/利润锁定永远不会触发自动卖出**。

**建议修复**:  
统一告警级别。利润保护/利润锁定应为 `success`（因为建议卖出盈利）或 `warning`（需要在 paper_trading.py 中也处理 `warning` 级别的利润保护/利润锁定）。

---

### P0-5: 龙头5天低利润检查仅在部分文件中实现

| 属性 | 值 |
|------|------|
| **文件1** | `real_trading/position_manager.py` L419 |
| **文件2** | `core/managers/live/position_manager.py` L397 |
| **影响** | 🟡 **中** — 两处实现逻辑和位置不同 |

**问题描述**:  
- `real_trading/position_manager.py` L419: 在止损检查之前，检查 `_strategy == '龙头低吸' and hold_days >= 5 and profit < 3%`
- `core/managers/live/position_manager.py` L397: 在止损检查之后，检查 `_strategy_id == 'dragon_head' and hold_days >= 5 and profit < 3%`

两处实现：
1. 策略名匹配方式不同（中文名 vs 英文ID）
2. 检查顺序不同（止损前 vs 止损后）
3. live/ 版本只在 `not alert.get('level')` 时才触发（已有danger级别告警时被跳过）

**建议修复**:  
统一为一处实现。推荐放在止损检查之前，且两种策略名匹配都应支持。

---

## P1: 实盘-回测不一致

### P1-1: real_trading/position_manager.py 利润锁定缺少策略级 pullback_profit_lock_threshold

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L484-489 |
| **影响** | 🟡 **中** — 龙头低吸冲高回落利润保护阈值可能不一致 |

**问题描述**:  
冲高回落检查中：
```python
_pullback_profit_lock = _strategy_params.get('pullback_profit_lock_threshold', None)
```
回测中 `STRATEGY_PULLBACK_PARAMS['龙头低吸']['pullback_profit_lock_threshold'] = 0.06`，但 `_strategy_params` 来自 `STRATEGY_CONFIGS[strategy_id]['params']`，不包含 `STRATEGY_PULLBACK_PARAMS` 中的值。

回测的 `SellSignalChecker._get_sell_params()` 正确合并了 `pullback_params` + `base_params` + `risk_params`，但实盘的内联逻辑只读了 `params`（不含 pullback_params），导致 `pullback_profit_lock_threshold` 永远为 `None`（除非在 STRATEGY_CONFIGS.params 中也定义了）。

**影响**:  
龙头低吸利润≥6%时冲高回落不会跳过（因为 `_pullback_profit_lock` 始终为 None），与回测行为不一致。

**建议修复**:  
方案A: 改用 `SellSignalChecker`（与 live/ 版本一致）  
方案B: 合并 `STRATEGY_PULLBACK_PARAMS` 到参数读取中：
```python
from nodes.backtest_engine.factor_selection.sell_signal_checker import STRATEGY_PULLBACK_PARAMS
_pullback_params = STRATEGY_PULLBACK_PARAMS.get(_strategy, {})
_pullback_profit_lock = _pullback_params.get('pullback_profit_lock_threshold', _strategy_params.get('pullback_profit_lock_threshold', None))
```

---

### P1-2: real_trading/position_manager.py 冲高回落检查信号优先级与回测不同

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L477-497 |
| **影响** | 🟡 **中** — 高开即卖/冲高回落优先级与回测不同 |

**问题描述**:  
回测中 `STRATEGY_SELL_SIGNALS` 按优先级排序：
- 半路追涨: [冲高回落(P1), 利润保护(P2), 高开即卖(P3)]
- 首板打板: [高开即卖(P1)]

`SellSignalChecker.check_early_sell()` 按优先级遍历，命中即返回。

但实盘 `real_trading/position_manager.py` 的 if-elif 链：
```python
if _strategy == '首板打板' and open_rise >= _pullback_threshold:  # 高开即卖
elif open_rise >= _pullback_threshold and current_price < open_p:  # 冲高回落
elif close_rise >= 0.02 and ...:  # 利润保护
elif high > 0 and ...:  # 利润锁定
```

**差异**:  
- 对于首板打板，实盘只在 `open_rise >= _pullback_threshold` 时触发高开即卖，但不检查冲高回落（因为首板打板匹配了第一个 if 后不再进入 elif）。这与回测一致 ✅
- 对于非首板打板，实盘先检查冲高回落，再检查利润保护，再检查利润锁定。与回测优先级一致 ✅
- 但实盘不检查非首板打板的"高开即卖"——回测中半路追涨也有高开即卖(P3)但排在冲高回落(P1)之后，由于冲高回落条件包含高开即卖条件，高开即卖实际被冲高回落覆盖，功能一致 ✅

**结论**: 优先级实际一致，但代码结构脆弱。任何优先级变更都需要同步修改两处。

---

### P1-3: real_trading/position_manager.py 利润保护缺少对 pullback_profit_lock_threshold 的尊重

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L499-501 |
| **影响** | 🟡 **中** — 高利润时利润保护仍可能触发 |

**问题描述**:  
回测中 `check_pullback()` 和 `check_profit_protect()` 是独立函数，`check_pullback` 检查 `pullback_profit_lock_threshold`，但 `check_profit_protect` 不检查。

实盘中，利润保护(elif L499)在冲高回落(elif L484)之后。如果冲高回落因 `pullback_profit_lock_threshold` 被跳过（`pass`），代码会继续进入利润保护分支。而回测中 `check_pullback` 返回 `None` 后，`check_profit_protect` 也可能触发——两者行为一致。

**结论**: 此项实际一致，无需修复。

---

### P1-4: real_trading/position_manager.py 跌停翘板/龙头低吸 pullback_mid_fallback_pct 默认值不一致

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/position_manager.py` |
| **行号** | L459 |
| **影响** | 🟡 **中** — 回落触发阈值可能不一致 |

**问题描述**:  
```python
_pullback_mid_fallback = _strategy_params.get('pullback_mid_fallback_pct', 0.01)
```
默认值 0.01，但回测 `STRATEGY_PULLBACK_PARAMS` 中：
- 跌停翘板: `pullback_mid_fallback_pct = 0.015`
- 龙头低吸: `pullback_mid_fallback_pct = 0.015`

实盘从 `STRATEGY_CONFIGS[id]['params']` 读取，如果 `params` 中没有定义 `pullback_mid_fallback_pct`（目前 strategy_defaults.py 的 params 中确实没有），则 fallback 到 0.01。

**影响**:  
跌停翘板和龙头低吸在 1%-1.5% 回落区间的行为与回测不一致——实盘更容易触发冲高回落（0.01 < 0.015）。

**建议修复**:  
与 P1-1 一起修复——从 `STRATEGY_PULLBACK_PARAMS` 读取策略级冲高回落参数。

---

### P1-5: real_trading/paper_trading.py T+1 阻塞集只在内存中维护

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/paper_trading.py` |
| **行号** | L256, L387 |
| **影响** | 🟡 **中** — 进程重启后 T+1 约束丢失 |

**问题描述**:  
```python
if hasattr(self, '_t1_blocked') and f"{acc_id}:{ts_code}" in self._t1_blocked:
```
`_t1_blocked` 是内存中的 set，不持久化。进程重启后 T+1 约束丢失，当日买入的股票可能被立即卖出。

**建议修复**:  
将 T+1 阻塞信息持久化到 JSON 或 MongoDB，启动时加载。

---

### P1-6: core/managers/live/position_manager.py hold_days() 在 async 上下文中降级为近似值

| 属性 | 值 |
|------|------|
| **文件** | `AgentServer/core/managers/live/position_manager.py` |
| **行号** | L66-87 |
| **影响** | 🟡 **中** — 交易日计算可能偏差 1 天 |

**问题描述**:  
```python
if loop.is_running():
    # 如果在async上下文中,用自然日/1.5近似
    natural_days = (current_dt - buy_dt).days
    return max(0, int(natural_days / 1.5))
```
当在 async 上下文（Web 服务）中运行时，无法使用 `run_until_complete()`，fallback 到自然日/1.5 的近似值。这可能导致：
- 周五买入 → 周一 hold_days=1（近似） vs 回测 hold_days=1（交易日） ✅
- 周一买入 → 周三 hold_days=1（近似） vs 回测 hold_days=2 ❌（近似偏少）

**影响**:  
超期检查可能延迟 1 天触发，导致持仓超过 max_hold_days。

**建议修复**:  
预加载交易日历到内存，避免实时查询 MongoDB：
```python
# 启动时一次性加载交易日历
trade_date_cache = sorted(mongo_manager.db.stock_daily_ak_full.distinct("trade_date"))
```

---

## P2: 代码质量和可维护性

### P2-1: 全局 sys.path.insert 反模式

| 属性 | 值 |
|------|------|
| **文件** | 所有 `real_trading/*.py` 和 `core/managers/live/*.py` |
| **行号** | 每个 file L10-15 附近 |
| **影响** | 🟢 **低** — 不影响功能，但影响可维护性 |

**问题描述**:  
每个文件都有：
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))
```
这导致：
1. 模块搜索顺序依赖文件位置
2. 同名模块（如两个 `position_manager.py`）可能导入错误的版本
3. 不同入口点（CLI vs Web）可能加载不同模块

**建议修复**:  
添加 `setup.py` / `pyproject.toml`，用 `pip install -e .` 安装项目。

---

### P2-2: auto_trade_executor.py 标记为 V52 已废弃但仍存在于目录中

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/auto_trade_executor.py` |
| **行号** | 文件头 |
| **影响** | 🟢 **低** — 混淆维护者 |

**建议修复**:  
移入 `_deprecated/` 目录（与 V54 已废弃的 live/ 模块处理方式一致）。

---

### P2-3: daily_rebalance_report.py 硬编码 hold_days >= 3 超期阈值

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/daily_rebalance_report.py` |
| **行号** | L240 |
| **影响** | 🟢 **低** — 仅影响报告显示，不影响交易 |

**问题描述**:  
```python
if pos["hold_days"] >= 3:
    risks.append(f"⚠️ 持仓超期：{pos['hold_days']}天 ≥ 3天上限")
```
应从策略参数读取 max_hold_days，而非硬编码 3。

**建议修复**:  
从 `STRATEGY_CONFIGS` 读取策略级 `max_hold_days`。

---

### P2-4: risk_checker.py 使用 asyncio.get_event_loop().run_until_complete() 在非 async 上下文中

| 属性 | 值 |
|------|------|
| **文件** | `AgentServer/core/managers/live/risk_checker.py` |
| **行号** | L290 |
| **影响** | 🟢 **低** — 在 async 上下文中可能崩溃 |

**问题描述**:  
```python
if not mongo_manager.client:
    asyncio.get_event_loop().run_until_complete(mongo_manager.initialize())
```
在已运行 event loop 的上下文中会抛出 `RuntimeError`。

**建议修复**:  
使用 `asyncio.run()` 或将整个方法改为 async。

---

### P2-5: pre_buy_risk_check.py trade_history 与 paper_trading 的 trade_history 独立维护

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/pre_buy_risk_check.py` |
| **行号** | L71-84 |
| **影响** | 🟢 **低** — 连续亏损统计可能不准确 |

**问题描述**:  
`PreBuyRiskChecker` 维护独立的 `trade_history.json`，与 `paper_trading.py` 的交易历史不是同一个文件。连续亏损统计可能不准确，因为两个模块不共享交易记录。

**建议修复**:  
统一使用 `paper_trading.py` 的交易历史文件，或使用 MongoDB 存储共享交易记录。

---

### P2-6: nav_tracker.py PaperTradingEngine 初始化方式与 real_trading/ 不兼容

| 属性 | 值 |
|------|------|
| **文件** | `AgentServer/core/managers/live/nav_tracker.py` |
| **行号** | L96-102 |
| **影响** | 🟢 **低** — nav_tracker 可能无法正常初始化 |

**问题描述**:  
`nav_tracker.py` 导入 `core.managers.live.paper_trading_compat.PaperTradingEngine`，该类是 `SimTradingEngine` 的代理，接口与 `real_trading/paper_trading.py` 的 `PaperTradingEngine` 完全不同（async 方法 vs 同步方法、MongoDB vs JSON 存储）。

`nav_tracker.py` 尝试访问 `self.engine.accounts`、`self.engine.position_managers` 等属性，但 `paper_trading_compat.PaperTradingEngine` 没有这些属性。

**影响**:  
`NavTracker` 实例化时会抛出 `AttributeError`。

**建议修复**:  
在 `paper_trading_compat.PaperTradingEngine` 中补充 `accounts` 和 `position_managers` 属性，或让 `nav_tracker.py` 直接使用 `SimTradingEngine` API。

---

### P2-7: performance_calculator.py 和 performance_report.py 功能与 performance_analyzer.py 重叠

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/performance_calculator.py`, `real_trading/performance_report.py` |
| **影响** | 🟢 **低** — 代码冗余 |

**建议修复**:  
统一为 `PerformanceAnalyzer`，删除或合并其他两个文件。

---

### P2-8: paper_trading.py _update_account_performance 用 cost 估算市值

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/paper_trading.py` |
| **行号** | L460-465 |
| **影响** | 🟢 **低** — 已有 current_price fallback |

**问题描述**:  
已修复为优先使用 `current_price`，fallback 到 `buy_price`。但 `current_price` 来源是 `pos.get("current_price")`，这个值由 `daily_check()` 更新。如果 `daily_check()` 未运行，市值仍按成本价计算。

---

### P2-9: multi_account_manager.py 账户间无隔离——共享同一个 JSON 文件

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/multi_account_manager.py` |
| **行号** | L27-40 |
| **影响** | 🟢 **低** — 多账户并发写入可能数据丢失 |

**问题描述**:  
多账户使用 `paper_accounts.json` 和 `positions_*.json`，没有文件锁保护。并发写入可能导致数据丢失。

**建议修复**:  
使用 MongoDB 或文件锁保护并发写入。

---

### P2-10: generate_daily_signals.py next_day_open_sell_pct fallback 0.03

| 属性 | 值 |
|------|------|
| **文件** | `real_trading/generate_daily_signals.py` |
| **行号** | L323 |
| **影响** | 🟢 **低** — 仅影响信号生成，不影响交易 |

**建议修复**:  
与 P0-3 一同修复，fallback 改为 0.02。

---

## 审计总结

| 级别 | 数量 | 关键问题 |
|------|------|----------|
| **P0** | 5 | 两套 PositionManager 不一致、利润保护硬编码、fallback 值错误、告警级别不匹配、龙头5天检查不统一 |
| **P1** | 6 | STRATEGY_PULLBACK_PARAMS 未合并、T+1 不持久化、hold_days 近似、fallback 阈值不一致 |
| **P2** | 10 | sys.path 反模式、废弃文件、硬编码阈值、async 兼容、数据源重复 |

### 修复优先级建议

1. **P0-1** (最高): 统一两个 PositionManager 实现——消除代码分叉的根源
2. **P0-3**: 修复 fallback 值 0.03 → 0.02（一行改动，立即生效）
3. **P0-2**: 利润保护参数化（替换硬编码 0.02）
4. **P0-4**: 统一告警级别（warning vs success）
5. **P1-1 + P1-4**: 合并 STRATEGY_PULLBACK_PARAMS 到实盘参数读取

### 整体评估

实盘模块经过 V35-V61 多轮修复，核心风控逻辑（止损止盈、冲高回落、利润保护/锁定）已基本与回测对齐。**最大的系统性风险是两套 PositionManager 并存**——这是未来所有不一致问题的根源。建议优先解决 P0-1，将 `real_trading/position_manager.py` 的内联卖出逻辑替换为 `SellSignalChecker`，与 live/ 版本保持一致。
