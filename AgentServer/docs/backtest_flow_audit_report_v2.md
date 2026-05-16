# 回测流程第二轮全面审查报告

**审查日期**: 2026-05-16  
**审查范围**: 前端 → Web API → 回测引擎 → 因子选股 → 结果返回  
**代码总量**: 后端11,140行 + 前端3,409行 = 14,549行  
**上一轮**: 24个问题已全部修复 (P0×3 + P1×10 + P2×9 + P3×2)

---

## 📊 本轮发现汇总

| 编号 | 严重度 | 问题描述 | 位置 |
|------|--------|---------|------|
| N01 | **P0** | `config`变量未定义导致BacktestNode启动NameError | node.py:65 |
| N02 | **P0** | 策略日志中参数为None时TypeError(必崩) | portfolio_backtest.py:331/347 |
| N03 | **P1** | `cleanup_expired_mock_tasks()`定义但从未调用 | common.py:34 |
| N04 | **P1** | debug日志`SL_DEBUG`残留未清理 | portfolio_backtest.py:749-751 |
| N05 | **P1** | `self._initial_cash`重复赋值 | portfolio_backtest.py:747/752 |
| N06 | **P1** | `strategy_name_map`在ultra_short.py中重复定义 | ultra_short.py:111 |
| N07 | **P2** | 8个未使用的import | 多个文件 |
| N08 | **P2** | `涨停开板`日志部分参数缺少默认值fallback | portfolio_backtest.py:329-340 |
| N09 | **P2** | `龙头低吸`日志部分参数缺少默认值fallback | portfolio_backtest.py:341-353 |
| N10 | **P2** | `半路追涨`日志部分参数缺少默认值fallback | portfolio_backtest.py:301-307 |
| N11 | **P2** | `首板打板`日志部分硬编码"竞价涨幅: 2.0% ~ 5.0%" | portfolio_backtest.py:320 |
| N12 | **P3** | `strategy_risk_params`字段在Web API中未传递(死字段) | models.py / ultra_short.py |

---

## 🔍 详细发现

### N01: [P0] `config`变量未定义 — BacktestNode启动必崩

**位置**: `nodes/backtest_engine/node.py:65`

```python
def __init__(self, node_id=None, rpc_port=0):
    ...
    self._worker_count = config.get('worker_count', 1)  # ← config未定义!
```

**问题**: `config`在`__init__`中不存在，`BacktestNode()`实例化时会抛出`NameError`。  
**原因**: P1-3修复时把硬编码的`self._worker_count = 1`改为了`config.get('worker_count', 1)`，但`config`只在`run_ultra_short_backtest`方法中才定义。  
**修复**: 改回硬编码默认值1，或从settings读取。

---

### N02: [P0] 策略日志中参数为None时TypeError

**位置**: `portfolio_backtest.py`多处

**涨停开板** (L331):
```python
_raw_turnover = params.get("min_turnover_rate")  # 可能为None
min_turnover = _raw_turnover * 100 if _raw_turnover < 1 else _raw_turnover  
# ← None < 1 → TypeError!
```

**龙头低吸** (L347):
```python
min_correction = params.get("min_correction_pct")  # None
await self.log(f"回调幅度: {min_correction*100:.1f}%")  # None*100 → TypeError!
```

**半路追涨** (L306):
```python
min_rise_pct = params.get("min_rise_pct")  # None
await self.log(f"涨幅区间: {min_rise_pct*100:.1f}%")  # None*100 → TypeError!
```

**问题**: 策略日志部分的`params.get()`没有默认值fallback，当参数缺失时直接对None做算术运算，必定抛出TypeError。  
**根因**: `_build_strategy_filter_conditions`已修复了默认值(P1-9)，但日志打印部分(`_apply_strategy_filter`内部)未同步修复。  
**影响**: 如果前端未传某个策略参数，回测引擎会崩溃。

---

### N03: [P1] `cleanup_expired_mock_tasks()`定义但从未调用

**位置**: `nodes/web/api/backtest/common.py:34`

```python
def cleanup_expired_mock_tasks():
    """清理超过TTL的mock_tasks条目，防止内存泄漏"""
    ...
```

**问题**: 此函数P2-3修复时添加，但没有任何地方调用。TTL清理机制完全失效，mock_tasks仍然会无限增长。  
**修复**: 在每次写入mock_tasks时调用，或在status/history查询时定期调用。

---

### N04: [P1] debug日志`SL_DEBUG`残留

**位置**: `portfolio_backtest.py:749-751`

```python
import logging as _logging
_logging.getLogger('backtest').info(f'[SL_DEBUG] _strategy_risk_params = {self._strategy_risk_params}')
_logging.getLogger('backtest').info(f'[SL_DEBUG] risk_config stop_loss = {risk_config.get("stop_loss_pct")}')
```

**问题**: 调试日志残留，生产环境不应存在。每次回测都会打印敏感参数到日志。  
**修复**: 删除这3行。

---

### N05: [P1] `self._initial_cash`重复赋值

**位置**: `portfolio_backtest.py:747/752`

```python
747:  self._initial_cash = initial_cash
749:  import logging as _logging          # debug残留
750:  _logging.getLogger(...)             # debug残留
751:  _logging.getLogger(...)             # debug残留
752:  self._initial_cash = initial_cash   # ← 重复赋值
```

**问题**: `self._initial_cash`被赋值了两次，中间夹着debug日志。  
**修复**: 删除debug日志后，第二个赋值自然消失。

---

### N06: [P1] `strategy_name_map`重复定义

**位置**: 
- `ultra_short.py:111` (本地定义)
- `nodes/web/api/backtest/models.py:139` (已定义并导出)

```python
# ultra_short.py:111
strategy_name_map = {
    "halfway_chase": "半路追涨",
    ...
}
```

**问题**: `strategy_name_map`在Web API的models.py中已有定义并导出，ultra_short.py又本地重复定义。修改一处容易遗漏另一处。  
**修复**: ultra_short.py从models.py导入。

---

### N07: [P2] 8个未使用的import

**portfolio_backtest.py**:
- `PortfolioSnapshot`, `RunState`, `RiskConfig` (from models)
- `dataclass` (from dataclasses)
- `os` (from os)
- `np` (from numpy)
- `FactorQualityLevel` (from factor_quality_checker)
- `merge_strategy_risk_params` (from strategy_defaults)

**其他文件**: `ultra_short.py`的`List, Dict, Any`等。

---

### N08/09/10: [P2] 策略日志部分缺少默认值fallback

与N02同根因，但这里只关注"日志显示不正确"而非崩溃：
- 涨停开板: `min_consecutive`, `min_volume_ratio`等无fallback
- 龙头低吸: `min_consecutive`, `support_level`等无fallback
- 半路追涨: `min_rise_pct`, `max_rise_pct`等无fallback

---

### N11: [P2] 首板打板日志硬编码"竞价涨幅: 2.0% ~ 5.0%"

**位置**: `portfolio_backtest.py:320`

```python
await self.log(f"   │        • 竞价涨幅: 2.0% ~ 5.0%")  # ← 硬编码!
```

应改为从params读取`opening_pct_min`/`opening_pct_max`。

---

### N12: [P3] `strategy_risk_params`字段死代码

**位置**: `models.py`的`UltraShortBacktestRequest.strategy_risk_params`字段

**问题**: 
1. 前端提交的`strategy_risk_params`在`root_validator`中可能不触发(因为strategies非空时跳过构建)
2. Web API构建`task_info`时未包含此字段
3. 引擎侧从`selected_strategies[].riskParams`读取，不依赖此顶层字段

**修复**: 删除`strategy_risk_params`字段声明，或改为从`selected_strategies`自动提取。

---

## 📋 修复优先级

| 优先级 | 编号 | 修复方式 |
|--------|------|---------|
| 🔴 立即修 | N01 | `config.get()` → 硬编码1或从settings读取 |
| 🔴 立即修 | N02 | 策略日志部分添加默认值fallback(与_build_strategy_filter_conditions对齐) |
| 🟡 尽快修 | N03 | 在写入mock_tasks时调用cleanup_expired_mock_tasks() |
| 🟡 尽快修 | N04 | 删除SL_DEBUG调试日志 |
| 🟡 尽快修 | N05 | 与N04一起修复(删debug行后重复赋值自动消失) |
| 🟡 尽快修 | N06 | 从models.py导入strategy_name_map |
| 🟢 可选修 | N07 | 清理未使用import |
| 🟢 可选修 | N08-11 | 策略日志默认值与N02一起修 |
| ⚪ 低优先 | N12 | 删除死字段或自动提取 |
