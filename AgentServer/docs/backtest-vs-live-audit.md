# 策略回测 vs 市场监听：全链路审查报告

> 2026-05-13 | 系统性梳理回测引擎(BacktestEngine)与市场扫描器(MarketScanner)的关系、差异与问题

---

## 一、架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│                    strategy_defaults.py                         │
│               【策略参数单一来源 Single Source of Truth】           │
│  STRATEGY_CONFIGS / GLOBAL_RISK / merge_strategy_params()       │
└───────────┬───────────────────────────────┬─────────────────────┘
            │                               │
            ▼                               ▼
┌──────────────────────┐      ┌──────────────────────────────┐
│  回测引擎 BacktestEngine │      │    市场扫描器 MarketScanner    │
│  nodes/backtest_engine/│      │  nodes/market_monitor/        │
│                        │      │                               │
│  数据: MongoDB历史日线   │      │  数据: 东方财富(实时)+必盈(涨停池)│
│  频率: 日线(close)      │      │  频率: 5分钟全量+30秒持仓        │
│  撮合: 内置_rebalance() │      │  撮合: SimulatedBroker         │
│  时间: T+0决策(用当天数据)│      │  时间: T+0决策(用实时数据)      │
│  策略入口:              │      │  策略入口:                      │
│   _build_strategy_     │◄─────│   _build_strategy_            │
│   filter_conditions()  │ 复用  │   filter_conditions()          │
│                        │      │                               │
│  买入价: 策略特定模型     │      │  买入价: 当前实时价+滑点         │
│  卖出价: close          │      │  卖出价: 当前实时价-滑点         │
│  止损: 收盘价检查        │      │  止损: 实时价检查(30秒级)        │
│  情绪周期: 每日计算       │      │  情绪周期: 每日预加载            │
│  仓位: target_weights   │      │  仓位: PositionSizer比例        │
└──────────────────────┘      └──────────────────────────────┘
            │                               │
            ▼                               ▼
┌──────────────────────┐      ┌──────────────────────────────┐
│  结果: MongoDB        │      │  结果: MongoDB持久化            │
│  backtest_tasks       │      │  broker.save_state()           │
│  (胜率/夏普/回撤/交易明细)│      │  (持仓/订单/账户)               │
└──────────────────────┘      └──────────────────────────────┘
```

---

## 二、代码复用关系

| 组件 | 回测引擎 | 市场扫描器 | 共享方式 |
|------|---------|-----------|---------|
| **策略参数** | `strategy_defaults.py` | `strategy_defaults.py` | ✅ 单一来源 |
| **筛选条件** | `_build_strategy_filter_conditions()` | 调用同一个方法 | ⚠️ 通过import复用 |
| **因子引擎** | `FactorEngine.compute_factors()` | `FactorEngine.compute_factors()` | ✅ 共用 |
| **行情数据** | MongoDB `stock_daily_ak_full` | 东方财富API + 必盈API | ❌ **完全不同** |
| **撮合引擎** | `_rebalance()` 内置 | `SimulatedBroker` | ❌ **完全不同** |
| **止损止盈** | `_get_sl_tp_for_code()` | `_check_positions()` | ❌ **逻辑不同** |
| **仓位管理** | `target_weights` + 情绪系数 | `PositionSizer` + 熔断器 | ❌ **完全不同** |
| **情绪周期** | `_print_market_environment()` | 预加载+日级因子 | ⚠️ 计算来源不同 |

---

## 三、关键差异详细分析

### 🔴 P0: 未来函数 / 前瞻偏差

| 差异点 | 回测引擎 | 市场扫描器 | 风险 |
|--------|---------|-----------|------|
| **买入价** | open价(半路追涨) / 涨停价(首板) / low价(低吸/翘板) | 当前实时价+滑点 | **回测用open≈9:30价, 半路追涨要求涨2-5%时买入, 实际应在10:00左右** |
| **卖出价** | close价 | 当前实时价-滑点 | **回测用收盘价卖出, 实际止损可能在盘中任何时刻** |
| **因子数据** | 当天OHLCV(含close) | 实时快照(只有到当前时刻的数据) | **回测用了当天close选股=未来函数** |
| **决策时刻** | 假设T日收盘看数据→T日买卖 | T日盘中实时看数据→T日买卖 | **回测逻辑是T-1选股→T日执行,但实际是T日选T日买** |

**核心问题**: 回测引擎的选股逻辑在T日使用了T日的close数据来筛选,但买入用的是open价。这意味着:
- 半路追涨: 用close(15:00价)筛选"涨2-7%",但用open(9:30价)买入 → **在9:30时根本不知道收盘涨多少**
- 首板打板: 用close判断涨停,但用涨停价买入 → **收盘才确认涨停,无法在盘中确认**
- 跌停翘板: 用close判断跌停→翘板,但用low价买入 → **盘中不知道收盘会跌停**

### 🔴 P0: 撮合逻辑差异

| 方面 | 回测引擎 `_rebalance()` | 扫描器 `SimulatedBroker` |
|------|------------------------|------------------------|
| 佣金 | 万3(综合) | 万2(券商)+千1(印花税) |
| 滑点 | 策略级0.2-0.5% | 固定0.1% |
| T+1 | ❌ **未实现** (当日买入当日可卖) | ✅ today_buy_qty追踪 |
| 涨跌停限制 | `_get_limit_up_price()` 判断 | `_calc_limit_prices()` 判断 |
| 100股整手 | ✅ | ✅ |
| 停牌处理 | `_last_valid_price` | 跳过 |
| 市价单撮合 | 用open/涨停价/low价模型 | 最新价+滑点 |

**最严重**: 回测引擎**没有T+1限制**。当日买入的股票在当日就可以被卖出(止损/调仓),这在实盘中不可能。

### 🟡 P1: 仓位管理差异

| 方面 | 回测引擎 | 扫描器 |
|------|---------|--------|
| 仓位模型 | `target_weights` = 等权/因子加权 | `PositionSizer` = 按策略强度分配 |
| 仓位系数 | 情绪周期系数 × 特殊时期系数 | 无(固定比例) |
| 单票上限 | `max_position_per_stock` 20% | 硬编码15% |
| 总仓位 | `max_total_position` 70% | 硬编码70% |
| 熔断器 | ❌ 无 | ✅ 单日回撤5%+连续亏损3次 |
| 强制空仓 | ✅ 涨停数<5或跌停数>50 | ❌ 无(有竞价预选) |

### 🟡 P1: 止损止盈差异

| 方面 | 回测引擎 | 扫描器 |
|------|---------|--------|
| 检查频率 | 每日1次(收盘价) | 30秒1次(实时价) |
| 止损触发 | 收盘profit_pct ≤ -止损% | 实时profit_pct ≤ -止损% |
| 跳空缺口 | ❌ 无法处理(收盘价无跳空) | ✅ 实时检测 |
| 最大持仓天数 | ✅ `_cost_basis_date`追踪 | ❌ **未实现** |
| 策略级参数 | `_get_sl_tp_for_code()` | `_get_strategy_risk()` |

### 🟡 P1: 数据源差异

| 因子 | 回测引擎来源 | 扫描器来源 | 一致性 |
|------|------------|-----------|--------|
| pct_chg | MongoDB日K | 东方财富实时 | ⚠️ 实时vs收盘不同 |
| volume_ratio | MongoDB因子 | 东方财富实时 | ⚠️ 东方财富可能无量比 |
| turnover_rate | MongoDB因子 | 东方财富实时 | ✅ 基本一致 |
| is_limit_up | MongoDB因子(0/1) | 必盈涨停池 | ⚠️ 计算逻辑不同 |
| limit_up_count | MongoDB因子 | 必盈涨停池limit_times | ⚠️ 语义不同(5日累计 vs 当日连板) |
| circ_mv | MongoDB因子 | 东方财富实时 | ✅ 基本一致 |
| 情绪周期 | `_print_market_environment()` | 预加载日级因子 | ⚠️ 实时可能无数据 |
| 涨停池详情 | MongoDB因子(封单/连板/开板) | 必盈API(实时) | ❌ 字段名/单位不同 |

### 🟢 P2: 信号去重差异

| 方面 | 回测引擎 | 扫描器 |
|------|---------|--------|
| 多策略选同股 | ✅ `stock_to_strategy` 追踪 | ✅ `ts_code\|strategy` 去重 |
| 同股多策略持仓 | ✅ 合并持仓 | ❌ 只保留第一个策略的仓位 |

---

## 四、Scanner 对 PortfolioBacktester 的依赖问题

当前 `MarketScanner._apply_strategies()` 的做法:

```python
from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
bt = PortfolioBacktester()
conditions = bt._build_strategy_filter_conditions(strategy_name, params)
```

**问题**:
1. **实例化整个PortfolioBacktester只为调用一个方法** — 浪费资源(PortfolioBacktester有3450行)
2. **调用私有方法 `_build_strategy_filter_conditions`** — 耦合内部实现
3. **条件应用逻辑重复** — scanner自己又写了一遍 `>=`, `<=`, `==` 的mask逻辑,和portfolio_backtest中的另一套逻辑重复
4. **DailyScheduler也做了同样的事** — 3个地方都在手写条件应用逻辑

---

## 五、数据流差异导致的回测失真

### 5.1 半路追涨 — 最严重的偏差

```
回测: 
  T-1日收盘 → 算因子 → T日open价买入
  问题: 因子用了T日数据(pct_chg=当日涨幅), 但买入价=open(9:30)
  实际: 9:30开盘时不知道今天收盘涨多少, 无法用pct_chg选股

实盘:
  实时扫描 → 涨2-5%的股票 → 当前价买入
  实际: 10:00左右股票涨到2-5%才触发信号, 买入价=当时价(不是open)

差异: 回测用open价买(9:30), 实盘在10:00-14:30之间买
      → 回测买入价偏低, 收益虚高
```

### 5.2 首板打板

```
回测:
  T日is_limit_up=1 → 涨停价买入
  问题: 收盘才确认涨停, 盘中无法确认
  实际: 盘中封板时才能确认, 回测假设了知道当天收盘会涨停

实盘:
  必盈涨停池 → 确认封板 → 涨停价买入
  差异: 实盘能区分"一字板"和"盘中封板", 回测无法区分
```

### 5.3 跌停翘板

```
回测:
  T日limit_down_yesterday=1 + open_above_limit_down=1 → low价买入
  问题: 用T日数据选股+T日low价买入, 又是未来函数

实盘:
  实时检测跌停撬板 → 当前价买入
  差异: 实盘是盘中事件驱动, 回测是收盘确认
```

---

## 六、修复优先级

### P0 — 回测可信度(不修=回测结果不可信)

| # | 问题 | 修复方案 | 工作量 |
|---|------|---------|--------|
| P0-1 | **T日选股用T日数据(未来函数)** | 改为T-1日选股→T日执行, 或引入信号延迟模型 | 大 |
| P0-2 | **回测无T+1限制** | `_rebalance()` 加入today_buy追踪,当日买入不可卖 | 中 |
| P0-3 | **买入价模型失真** | 半路追涨改用 VWAP或典型盘中价, 非open | 中 |

### P1 — 回测与实盘一致性(不修=实盘行为偏离回测预期)

| # | 问题 | 修复方案 | 工作量 |
|---|------|---------|--------|
| P1-1 | **仓位管理不统一** | Scanner复用回测的情绪系数+特殊时期过滤 | 中 |
| P1-2 | **Scanner无最大持仓天数** | 加入hold_days追踪和强制卖出 | 小 |
| P1-3 | **_build_strategy_filter_conditions 耦合** | 提取为独立模块 `strategy_filter.py`, 3处共用 | 小 |
| P1-4 | **条件应用逻辑3处重复** | 提取 `apply_conditions(df, conditions)` 工具函数 | 小 |
| P1-5 | **DailyScheduler与Scanner功能重叠** | 明确职责: Scheduler=定时调度, Scanner=实时扫描 | 中 |

### P2 — 架构优化(不修=维护成本高)

| # | 问题 | 修复方案 | 工作量 |
|---|------|---------|--------|
| P2-1 | **PortfolioBacktester 3450行过大** | 拆分为选股/撮合/风控/结果4个模块 | 大 |
| P2-2 | **SimulatedBroker与回测_rebalance两套撮合** | 回测也用SimulatedBroker | 大 |
| P2-3 | **因子字段名/单位不统一** | 统一因子层抽象, 隔离数据源差异 | 中 |

---

## 七、核心结论

### 现状: 回测与实盘是"同参数、不同引擎"

两者共享策略参数(`strategy_defaults.py`)和选股条件(`_build_strategy_filter_conditions`), 但从数据源到撮合引擎到风控逻辑, 几乎每一步都有差异:

```
选股条件: ✅ 统一(同一方法)
参数来源: ✅ 统一(strategy_defaults.py)
数据输入: ❌ 不同(MongoDB vs 实时API)
买入价格: ❌ 不同(模型价 vs 实时价)
撮合规则: ❌ 不同(内置 vs SimulatedBroker)
T+1:      ❌ 不同(无 vs 有)
止损检查: ❌ 不同(日频 vs 30秒)
仓位管理: ❌ 不同(权重+系数 vs 比例+熔断)
情绪周期: ❌ 不同(日频计算 vs 预加载)
```

### 风险: 回测收益虚高

当前2年回测收益2.1万倍, 主要来自:
1. **未来函数**: T日用T日close选股 → 信号胜率虚高
2. **无T+1**: 当日止损/止盈可在买入当天执行 → 风控比实盘松
3. **买入价偏低**: open价(9:30)买半路追涨(实际10:00+才触发)
4. **无跳空风险**: 收盘价止损无法反映盘中跳空 → 止损偏乐观

### 建议: 最小可信回测

先修P0-1(未来函数)和P0-2(T+1), 重新跑回测, 看真实收益是多少。如果修完后收益仍然可观, 说明策略本身有alpha; 如果收益大幅下降, 说明之前的收益主要来自回测偏差。

---

## 八、DailyScheduler 与 MarketScanner 的重叠

两者都做"选股+交易", 职责边界不清:

| 功能 | DailyScheduler | MarketScanner |
|------|---------------|---------------|
| 盘前数据更新 | ✅ `_update_daily_data()` | ✅ `premarket_prepare()` |
| 信号生成 | ✅ `_generate_signals()` | ✅ `_apply_strategies()` |
| 实时行情 | `_fetch_realtime_data()` (从Scanner缓存) | ✅ 东方财富+必盈 |
| 止损止盈 | `_check_stop_loss_take_profit()` | `_check_positions()` |
| 持仓管理 | ❌ 无独立撮合 | ✅ SimulatedBroker |
| 调度 | 定时步骤(盘前/盘中/盘后) | 5分钟扫描循环 |
| 竞价预选 | ❌ | ✅ `_premarket_auction()` |
| 异动监控 | ❌ | ✅ `_detect_anomalies()` |
| 日报 | ✅ `_push_daily_report()` | ❌ |

**结论**: MarketScanner功能更完整, DailyScheduler的信号生成和止损逻辑应统一到Scanner, Scheduler只做调度编排。
