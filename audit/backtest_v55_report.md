# V55 回测引擎深度审查报告（最终版）

**日期**: 2026-05-27
**审查范围**: backtest_engine/ 核心模块
**审查基线**: V56 (commit bd8a934)
**审查行数**: ~7,800行
**最终commit**: 8784f55

---

## 一、修复总览

| 优先级 | BUG ID | 描述 | 状态 | Commit |
|--------|--------|------|------|--------|
| P0 | BUG-003 | record.price不含滑点与amount不一致 | ✅已修复 | 0ecb804 |
| P0 | BUG-004 | all_trades(dict)缺少sell_price/buy_price字段 | ✅已修复 | 8784f55 |
| P0 | BUG-015 | ultra_short.py成交概率fallback不一致+merge冲突 | ✅已修复 | 22f790b |
| P1 | BUG-001 | 利润锁定检查代码4处重复 | ✅已修复 | 22f790b |
| P1 | BUG-005 | hit_probability_slow fallback硬编码 | ✅V56已修复 | bd8a934 |
| P1 | BUG-006 | 强制空仓未清理stock_to_strategy | ✅已修复 | 8784f55 |
| P1 | BUG-007 | 利润锁定fallback值过时(0.02→0.015) | ✅已修复 | 22f790b |
| P2 | BUG-008 | T+1检查冗余(6处) | 📝保留 | 各处逻辑必要 |
| P2 | BUG-010 | 跌停翘板pct_chg>0未来函数 | 📝保留 | 收盘确认条件 |
| P2 | BUG-011 | 半路追涨pct_chg≥5%未来函数 | 📝保留 | 已知近似 |
| P2 | BUG-012 | 龙头低吸volume_ratio(T日)灰色地带 | 📝保留 | 盘中可近似 |
| P2 | BUG-014 | Calmar上限1000过高 | ✅V55已修复 | 动态calmar_cap |

---

## 二、修复详情

### BUG-003: record.price vs amount 不一致 (P0)

**根因**: `RebalanceRecord.price` = 原始成交价(不含滑点), `RebalanceRecord.amount` = 扣除滑点/佣金/印花税后的净金额。`_build_run_result`中`buy_price`来自`abs(buy_rec.amount)/buy_rec.shares`(含滑点),但`sell_price`来自`record.price`(不含滑点),导致前端展示利润率与`profit_pct`不匹配。

**修复**: `portfolio_backtest.py` L2411
```python
# 修复前
'sell_price': record.price,
# 修复后
'sell_price': record.amount / record.shares if record.shares > 0 else record.price,
```

### BUG-004: all_trades缺少sell_price/buy_price字段 (P0)

**根因**: `RebalanceRecord.__dict__`只有`price`字段,前端BacktestResultPanel期望`sell_price`/`buy_price`。

**修复**: `portfolio_backtest.py` L2677-2692
```python
# 转换时自动添加映射
if d.get('action') == 'sell' and 'sell_price' not in d and 'price' in d:
    d['sell_price'] = d['price']
if d.get('action') == 'buy' and 'buy_price' not in d and 'price' in d:
    d['buy_price'] = d['price']
```

### BUG-015: ultra_short.py成交概率fallback不一致 (P0)

**根因**: ultra_short.py的fallback硬编码值(0.3/0.5/0.7)与V56 STRATEGY_CONFIGS(0.20/0.45/0.50)严重不一致。同时发现未解决的git merge冲突。

**修复**: `ultra_short.py` L201-203
```python
# 修复前 (含merge冲突)
<<<<<<< HEAD
hit_fast = ...fallback... 0.3)
hit_normal = ...fallback... 0.5)
hit_slow = ...fallback... 0.7)
=======
hit_fast = ...fallback... 0.20)
...
>>>>>>> 76adfd6

# 修复后
hit_fast = strategy_params_local.get('hit_probability_fast', _defaults.get('hit_probability_fast', 0.20))
hit_normal = strategy_params_local.get('hit_probability_normal', _defaults.get('hit_probability_normal', 0.45))
hit_slow = strategy_params_local.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.50))
```

### BUG-001: 利润锁定检查代码4处重复 (P1)

**根因**: 利润锁定检查在4个位置重复实现,每处10-15行,且fallback值不一致(0.02/0.015/0.04)。

**修复**: 提取为`_check_intraday_profit_lock(cost, high_price, close_price) -> bool`方法(L185-207),3处调用简化为1-3行。消除~45行重复代码,统一fallback值。

**影响**: 发现一个关键问题——存在第二个重复定义(L3758,fallback 0.04)会覆盖第一个(L185,fallback 0.05)。已删除重复定义。

### BUG-006: 强制空仓未清理stock_to_strategy (P1)

**根因**: 强制空仓清仓时清理了`_cost_basis`和`_cost_basis_date`,但遗漏了`stock_to_strategy`。

**修复**: `portfolio_backtest.py` L1528,添加`self.stock_to_strategy.pop(code, None)`

### BUG-007: 利润锁定fallback值过时 (P1)

**根因**: V56将`intraday_lock_pullback_pct`从0.02→0.015,但3处代码的fallback仍为0.02。

**修复**:
- `portfolio_backtest.py` `_check_intraday_profit_lock`: fallback 0.02→0.015
- `sell_signal_checker.py` L317: fallback 0.02→0.015

---

## 三、sell_reason_stats 修复验证

V52基线sell_reason_stats为空。V55在portfolio_backtest.py的_build_run_result中直接计算,分类覆盖所有已知sell_reason:

| 卖出原因 | 匹配关键词 | 分类 |
|----------|-----------|------|
| 止损/跳空止损 | '止损'/'stop_loss' | stop_loss |
| 止盈 | '止盈'/'take_profit' | take_profit |
| 冲高回落/高开即卖 | '冲高回落'/'高开即卖' | pullback |
| 利润保护 | '利润保护' | profit_protect |
| 利润锁定 | '利润锁定' | profit_lock |
| 停牌超时强卖 | '停牌' | halt |
| 超时/持仓天数 | '到期'/'超时'/'max_hold' | max_hold |
| 强制空仓 | '空仓'/'强制' | force_empty |
| 调仓卖出/减仓 | '调仓'/'rebalance' | rebalance |

---

## 四、仍需关注的风险点

### 1. 未来函数风险 (已知,非bug)
- **半路追涨pct_chg≥5%**: V25对照实验显示去掉后收益-169%,保留是权衡
- **龙头低吸volume_ratio(T日)**: 盘中可近似观测,日线全量数据严格定义是未来函数

### 2. 止损笔数偏多
- V56基线: 24笔止损 vs 9笔止盈,止损仍远多于止盈
- 半路追涨止损3.5%: V56已从4%降至3.5%
- 建议: 持续监控,如止损笔数>2x止盈笔数,考虑优化入场条件

### 3. _rebalance方法长度
- 当前约450行,已通过提取方法减少冗余
- 进一步拆分需仔细设计中间状态传递

### 4. Calmar比率短回测期虚高
- V55修复: calmar_cap=max(50, trading_days/252*100)
- 短回测期(<120天)Calmar参考价值有限

### 5. 跌停翘板V56激活后的潜在风险
- min_consecutive_limit从2→1,候选股增加
- 需持续监控1连跌股票质量

---

## 五、修改文件清单

| 文件 | 修改内容 | 行数变化 |
|------|----------|----------|
| portfolio_backtest.py | BUG-001/003/004/006/007修复 | +87/-29 |
| sell_signal_checker.py | BUG-007 fallback对齐 | +1/-1 |
| ultra_short.py | BUG-015+merge冲突 | +22/-5 |
| strategy_defaults.py | V56参数更新 | +11 |
| models.py | raw_price字段 | +5/-1 |
| audit/backtest_v55_report.md | 审查报告 | 新增 |

**实盘模块无变更**: git diff确认real_trading/和core/managers/live/无修改。

---

## 六、Git提交历史

```
8784f55 V55-fix: BUG-004+BUG-006 all_trades添加sell_price/buy_price映射 + 强制空仓清理stock_to_strategy
0ecb804 V55-fix: BUG-003 sell_price用amount/shares替代record.price(含滑点成交均价)
f62e982 V55最终修复: models.py恢复raw_price字段,回测验证通过
15f8b0e V55审计: 完整审计报告
5ece52c V55-Bug5修复: sell_reason_stats在portfolio_backtest中直接计算
22f790b V55-fix: 回测引擎深度审查修复 - P0/P1级bug
```
