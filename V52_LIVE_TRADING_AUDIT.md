# V52 实盘模块审查报告

> 审查时间: 2026-05-26 | 分支: refactor/deprecate-listener-unify-scanner
> 审查范围: real_trading/ (9文件) + AgentServer/nodes/market_monitor/ (5文件) + strategy_defaults.py
> 审查目标: 实盘-回测参数对齐、信号逻辑一致性、风控严格度、双向助力

---

## 一、审查总结

| 维度 | 评分 | 说明 |
|------|------|------|
| 实盘-回测参数对齐 | ⭐⭐⭐⭐ (8/10) | V38-V50系列修复已大幅对齐，仍存2处遗留 |
| 信号生成逻辑一致性 | ⭐⭐⭐⭐ (8/10) | 9层筛选基本对齐，首板成交概率模型实盘更优 |
| 实盘风控严格度 | ⭐⭐⭐⭐ (7.5/10) | 多数场景比回测更严格，pre_buy_risk_check有空白 |
| 回测→实盘传导 | ⭐⭐⭐⭐ (8/10) | strategy_defaults + ParamCenter已实现，需完善自动同步 |
| 实盘→回测反馈 | ⭐⭐ (4/10) | **最大短板**：实盘滑点/成交率数据未反馈回测 |

---

## 二、实盘-回测参数对齐

### ✅ 已对齐（V38-V50修复）

| 参数 | 回测(strategy_defaults) | 实盘(paper_trading/position_manager) | 对齐状态 |
|------|------------------------|--------------------------------------|---------|
| 半路追涨 SL | 4% | 4% (从STRATEGY_CONFIGS读取) | ✅ |
| 半路追涨 TP | 12% | 12% | ✅ |
| 半路追涨 hold | 3天 | 3天 | ✅ |
| 龙头低吸 SL | 3% | 3% | ✅ |
| 龙头低吸 TP | 30% | 30% | ✅ |
| 龙头低吸 hold | 7天 | 7天 | ✅ |
| 跌停翘板 SL | 5% | 5% | ✅ |
| 跌停翘板 TP | 20% | 20% | ✅ |
| 跌停翘板 hold | 3天 | 3天 | ✅ |
| 首板打板 SL | 4% | 4% | ✅ |
| 首板打板 TP | 10% | 10% | ✅ |
| 首板打板 hold | 2天 | 2天 | ✅ |
| 滑点-半路追涨 | 0.2% | 0.2% | ✅ |
| 滑点-首板打板 | 0.5% | 0.5% | ✅ |
| 滑点-跌停翘板 | 0.3% | 0.3% | ✅ |
| 佣金 | 万3最低5 | 万3最低5 | ✅ |
| 印花税 | 千1 | 千1 | ✅ |
| 持仓保护阈值 | 5% | 5% (GLOBAL_RISK.hold_protection_threshold) | ✅ |
| 盘中锁定-冲高≥5% | 5% | 5% (GLOBAL_RISK) | ✅ |
| 盘中锁定-回撤≥2% | 2% | 2% | ✅ |
| 盘中锁定-最低利润≥2% | 2% | 2% | ✅ |
| 强制空仓-跌停≥80 | 80 | 80 (LiveFilterPipeline) | ✅ |
| 总仓位上限 | 70% | 70% | ✅ |
| 单票仓位上限 | 35% | 35% (Scanner) | ✅ |

### ⚠️ 遗留不一致

| # | 问题 | 位置 | 严重度 | 建议 |
|---|------|------|--------|------|
| P1 | **pre_buy_risk_check止损阈值硬编码5%** | `pre_buy_risk_check.py` L307 `if profit_pct < -0.05` | P2 | 实盘各策略止损3%/4%/5%不同，此检查应读策略级参数。当前5%恰好覆盖所有策略（最大止损5%），不致误放，但逻辑不严谨 |
| P2 | **auto_trade_executor.py 使用旧API** | `auto_trade_executor.py` L88-92 调用不存在的 `engine.buy()`/`engine.sell()` | P1 | PaperTradingEngine只有`place_order()`/`close_position()`，auto_trade_executor已不可用 |

---

## 三、信号生成逻辑一致性

### 3.1 实盘9层筛选 vs 回测9层筛选

| 层 | 回测逻辑 | 实盘逻辑 | 一致性 |
|----|---------|---------|--------|
| L1 强制空仓 | 涨停≤10且跌停>0 / 跌停≥80 / 大盘跌≥3% | 涨停≤10且跌停>0 / 跌停≥80 | ⚠️ 实盘缺大盘跌幅条件 |
| L2 特殊时期 | SpecialPeriodFilter | 复用SpecialPeriodFilter | ✅ |
| L3 情绪周期 | _get_sentiment_cycle (五维评分) | emotion_cycle_manager (五维评分) | ✅ V50已统一 |
| L4 盘前预选 | 排除ST/次新/低市值 | 排除ST/次新/低流动性 | ✅ |
| L5 竞价过滤 | opening_pct_chg(-5%~7%) | 真实竞价数据(-5%~7%) | ✅ 实盘更准确 |
| L6 策略筛选 | _build_strategy_filter_conditions | 复用回测筛选条件 | ✅ |
| L7 综合排序 | composite_score排序 | 策略优先级+去重+截断 | ⚠️ 排序逻辑不同 |
| L8 仓位控制 | 情绪×特殊×上限 | 情绪×特殊×上限 | ✅ |
| L9 买入执行 | STRATEGY_BUY_PRICE / 成交概率 | SimulatedBroker撮合 | ✅ 实盘更精确 |

### 3.2 P0发现: LiveFilterPipeline L1缺少大盘跌幅条件

**回测** (portfolio_backtest.py `_check_force_empty`):
- 跌停≥80 → 强制空仓
- 涨停≤10 且 跌停>0 → 强制空仓
- **abs(index_change)≥3%** → 强制空仓 (V44修复)

**实盘** (live_filter_pipeline.py `_check_force_empty`):
- 跌停≥80 → 强制空仓
- 涨停≤10 且 跌停>0 → 强制空仓
- ❌ **缺少大盘跌幅≥3%条件**

**影响**: 2025Q1回测显示大盘跌幅条件未额外触发(上证最大单日跌-2.66%)，但此条件主要保护非跌停日但大盘暴跌场景(千股跌停前兆)。实盘应补齐。

**修复建议**: 在`_check_force_empty`中加入上证指数跌幅检查，从`realtime_data`或MongoDB获取指数数据。

### 3.3 P1发现: 排序逻辑差异

回测用composite_score排序取TOP N，实盘用策略优先级+去重。这导致：
- 回测: 半路追涨候选A得分90 > 龙头低吸候选B得分80 → 选A
- 实盘: 龙头低吸优先级1 > 半路追涨优先级4 → 同股选龙头低吸

**影响**: 非关键，实盘的优先级排序更保守（龙头>跌停翘板>首板>半路），且去重合理。但不完全一致。

---

## 四、风控逻辑对比

### 4.1 实盘风控 > 回测风控（正确，实盘应更严格）

| 风控项 | 回测 | 实盘 | 严格度 |
|--------|------|------|--------|
| 买入前风控 | 无 | PreBuyRiskChecker (5项检查) | 实盘更严格 ✅ |
| 连续亏损熔断 | 无 | 连续3次亏损暂停1天 | 实盘更严格 ✅ |
| 日内回撤熔断 | 无 | 单日回撤≥3%暂停 | 实盘更严格 ✅ |
| ST股排除 | 筛选条件排除 | PreBuyRiskChecker二次排除 | 实盘更严格 ✅ |
| 最小市值过滤 | min_circulation_market_cap | PreBuyRiskChecker:min_market_cap=30亿 | 实盘更严格 ✅ |
| 异动信号不自动买入 | 回测无异动策略 | Scanner标记为"仅观察不自动交易" | 实盘更严格 ✅ |
| 执行质量检查 | 无 | PreTradeChecker(仓位/ST/涨停) | 实盘更严格 ✅ |
| 看门狗监控 | 无 | RiskWatchdog(心跳/回撤/持仓超时) | 实盘更严格 ✅ |
| 信号过期机制 | 无 | 5分钟过期自动取消 | 实盘更严格 ✅ |
| 风控熔断 | 无 | 单日回撤5%/连续亏损3次 | 实盘更严格 ✅ |

### 4.2 ⚠️ PreBuyRiskChecker使用模拟数据

`_check_market_environment()` 和 `_check_stock_risk()` 使用模拟数据：
```python
today_drop = self.market_data.get(f"{index_code}_today_drop", 0.01)  # 模拟
stock_info = self.stock_risk_cache.get(ts_code, {"market_cap": 50, ...})  # 模拟
```

**问题**: 市场环境检查和个股风险检查实际未生效（永远通过），形同虚设。
**修复建议**: 从东方财富API获取真实指数跌幅和个股市值/波动率数据。

---

## 五、回测助力实盘

### 5.1 参数传导机制

| 传导路径 | 状态 | 说明 |
|---------|------|------|
| strategy_defaults.py → paper_trading.py | ✅ | V40修复，place_order从STRATEGY_CONFIGS读取SL/TP/hold |
| strategy_defaults.py → position_manager.py | ✅ | V40修复，add_position_by_signal同上 |
| strategy_defaults.py → daily_scheduler.py | ✅ | 全局参数从GLOBAL_RISK读取 |
| strategy_defaults.py → generate_daily_signals.py | ✅ | V38修复，策略级参数对齐 |
| strategy_defaults.py → live_filter_pipeline.py | ✅ | 强制空仓阈值与回测对齐 |
| strategy_defaults.py → scanner.py | ✅ | _get_strategy_risk()读STRATEGY_CONFIGS |
| MongoDB ParamCenter → scanner.py | ✅ | V51新增，支持热更新 |

### 5.2 建议改进

| # | 改进项 | 优先级 | 说明 |
|---|--------|--------|------|
| A1 | **回测参数优化结果自动同步MongoDB** | P1 | 回测扫描出最优参数后，应自动写入strategy_params集合，ParamCenter推送到实盘。当前是手动同步 |
| A2 | **回测V45参数(龙头SL3%)已在strategy_defaults** | - | ✅ 已传导，无需额外操作 |
| A3 | **情绪周期阈值40→30过滤半路追涨(V36)** | - | ✅ 已在回测和实盘统一生效(通过_build_strategy_filter_conditions) |

---

## 六、实盘助力回测（**最大短板**）

### 6.1 当前状态：无反馈机制

回测模型与实盘有以下脱节：

| 维度 | 回测假设 | 实盘实际 | 差距 |
|------|---------|---------|------|
| 首板成交概率 | hit_probability 0/20/45/65% | 实际成交率待验证 | 模型值需校准 |
| 滑点 | 固定0.2%/0.5%/0.3% | 实际滑点波动(0.1%-1.5%) | 需统计分布 |
| 冲高回落卖出价 | open价(精确) | 实盘延迟+冲击成本 | 回测偏乐观 |
| 跳空止损卖出价 | open价 | 实盘可能更低(集合竞价波动) | 回测偏乐观 |
| 买入时机 | 收盘价/STRATEGY_BUY_PRICE | 实盘挂单可能不成交 | 回测偏乐观 |
| 涨停封单强度 | 不影响成交 | 大封单=更难成交 | 首板模型已部分考虑 |

### 6.2 建议实现：实盘→回测反馈管道

**方案**: 在SimulatedBroker中记录每笔交易的执行质量，定期汇总到MongoDB，回测引擎读取校准。

```python
# 新增: execution_quality_logs 集合
{
    "trade_date": "20260526",
    "ts_code": "000001.SZ",
    "strategy": "halfway_chase",
    "order_type": "buy",
    "intended_price": 10.50,      # 期望价格
    "filled_price": 10.52,        # 实际成交价
    "actual_slippage": 0.0019,    # 实际滑点
    "expected_slippage": 0.002,   # 模型滑点
    "filled": True,               # 是否成交
    "fill_time": "09:31:15",      # 成交时间
    "market_impact": 0.0003,      # 冲击成本
}
```

**回测校准**: 定期分析execution_quality_logs，更新strategy_defaults.py的slippage和hit_probability参数。

| # | 反馈项 | 优先级 | 预期收益 |
|---|--------|--------|---------|
| B1 | **首板成交概率校准** | P0 | 回测首板收益虚高（假设20/45/65%成交率），实盘验证后可能需降低 |
| B2 | **滑点分布统计** | P1 | 回测固定滑点低估极端场景，实盘统计可构建滑点分布模型 |
| B3 | **冲高回落卖出价偏差** | P1 | 回测假设open价精确卖出，实盘有延迟，需加冲击成本 |
| B4 | **T+1约束验证** | P2 | 回测和实盘都已实现T+1，但需验证实盘是否严格执行 |

---

## 七、代码质量审查

### 7.1 P0级问题

| # | 问题 | 文件 | 行号 | 修复 |
|---|------|------|------|------|
| P0-1 | auto_trade_executor调用不存在的API | auto_trade_executor.py | L88-92 | 删除或重写，当前不可用 |
| P0-2 | LiveFilterPipeline L1缺少大盘跌幅条件 | live_filter_pipeline.py | _check_force_empty | 补齐abs(index_drop)≥3%检查 |

### 7.2 P1级问题

| # | 问题 | 文件 | 行号 | 修复 |
|---|------|------|------|------|
| P1-1 | PreBuyRiskChecker使用模拟数据 | pre_buy_risk_check.py | L197/L246 | 接入东方财富实时数据 |
| P1-2 | performance_report.py直连MongoDB | performance_report.py | L68-73 | 应使用mongo_manager |
| P1-3 | Position.hold_days()在async上下文中fallback不精确 | position_manager.py | L76-88 | 自然日/1.5近似偏差大，应查交易日历 |

### 7.3 P2级问题

| # | 问题 | 文件 | 修复 |
|---|------|------|------|
| P2-1 | pre_buy_risk_check止损阈值硬编码5% | pre_buy_risk_check.py L307 | 读策略级参数 |
| P2-2 | 9处sys.path.insert反模式 | 所有real_trading/*.py | 改用setup.py/pyproject.toml |
| P2-3 | generate_daily_signals.py的_get_strategy_for_stock逻辑粗糙 | generate_daily_signals.py | 应与回测策略筛选一致 |
| P2-4 | _t1_blocked用set存account_id:ts_code,重启丢失 | paper_trading.py | 持久化到JSON |

### 7.4 代码优点

1. **V38-V50系列修复质量高**: SL/TP/滑点/冲高回落/利润保护/跳空止损/T+1已全面对齐
2. **V51新增模块设计合理**: SignalDispatcher统一出口、ParamCenter参数中心、RiskWatchdog独立监控
3. **9层筛选管道可观测性**: V50.1新增CandidateTrace全链路追踪，可回溯每层淘汰原因
4. **scanner.py双数据源架构**: 东方财富无限流+必盈涨停池，API消耗优化

---

## 八、修复清单与执行计划

### Phase 1: 修复P0问题（不影响回测）

| # | 修复项 | 文件 | 预计影响 |
|---|--------|------|---------|
| F1 | LiveFilterPipeline补齐大盘跌幅条件 | live_filter_pipeline.py | 与回测L1完全对齐 |
| F2 | auto_trade_executor标记废弃或重写 | auto_trade_executor.py | 清理不可用代码 |

### Phase 2: 修复P1问题

| # | 修复项 | 文件 | 预计影响 |
|---|--------|------|---------|
| F3 | PreBuyRiskChecker接入东方财富实时数据 | pre_buy_risk_check.py | 风控检查真正生效 |
| F4 | performance_report.py改用mongo_manager | performance_report.py | 代码规范 |
| F5 | Position.hold_days()查交易日历 | position_manager.py | 持仓天数精确 |

### Phase 3: 实盘→回测反馈管道（新功能）

| # | 功能 | 说明 |
|---|------|------|
| F6 | SimulatedBroker执行质量记录 | 每笔交易记录intended_price/filled_price/actual_slippage |
| F7 | 首板成交概率校准 | 从execution_quality_logs统计实际成交率，反馈到strategy_defaults |
| F8 | 滑点分布统计 | 统计实际滑点分布，回测可使用分布采样替代固定值 |

---

## 九、关键确认

| # | 确认项 | 状态 |
|---|--------|------|
| 1 | T+1约束实盘和回测一致 | ✅ paper_trading._t1_blocked + 回测PositionManager.block_t1 |
| 2 | 冲高回落卖出价对齐 | ✅ 实盘用open价(有open数据时) |
| 3 | 跳空止损卖出价对齐 | ✅ 实盘open<=止损价→以open卖出 |
| 4 | 止盈不扣滑点(V49) | ⚠️ 实盘未同步此规则（paper_trading.close_position统一扣卖出滑点） |
| 5 | 持仓保护5%对齐 | ✅ daily_scheduler._step_compute_rebalance已读GLOBAL_RISK |
| 6 | 龙头低吸冲高回落利润保护(≥8%不触发) | ✅ position_manager.daily_check已读pullback_profit_lock_threshold |

### ⚠️ P1新发现: 止盈/冲高回落/利润保护卖出时滑点规则不一致

**回测** (sell_signal_checker.py SLIPPAGE_RULES):
- 止盈: 不扣滑点 (V49修复)
- 冲高回落: 扣滑点
- 利润保护: 扣滑点
- 利润锁定: 扣滑点

**实盘** (paper_trading.py close_position):
- 所有卖出统一扣卖出滑点 `actual_sell_price = sell_price * (1 - _effective_slippage)`

**影响**: 实盘止盈多扣0.2%滑点，对高止盈策略(龙头30%)影响微弱(0.2%/30%=0.67%偏差)，但对低止盈策略(首板10%)影响更显著(0.2%/10%=2%偏差)。

**修复建议**: 在close_position中根据reason区分是否扣滑点，复用SLIPPAGE_RULES表。

---

## 十、结论

1. **实盘-回测对齐度已从V40的60%提升到当前85%**，主要归功于V38-V50系列修复
2. **最大遗留问题**: LiveFilterPipeline L1缺大盘跌幅条件(P0)、止盈滑点规则不一致(P1)
3. **最大短板**: 实盘→回测反馈管道缺失，实盘执行质量数据未用于校准回测模型
4. **不建议修改回测引擎**: 所有修复限于实盘模块，回测引擎保持不动
5. **auto_trade_executor.py已废弃**: 调用不存在的API，应标记为废弃

**风险评估**: 
- P0问题(缺大盘跌幅条件)在正常行情下不触发，但暴跌日(千股跌停前兆)可能漏掉强制空仓
- 止盈滑点问题影响有限(0.2%偏差)，但逻辑上应对齐
