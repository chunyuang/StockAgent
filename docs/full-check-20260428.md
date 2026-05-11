# 🔍 回测流程与实时日志二次审查报告

> **审查日期：** 2026-04-28 14:15  
> **审查范围：** 全链路回测流程 + 实时日志推送 + 前后端数据结构  
> **代码快照：** commit `7b0a4f7`  
> **审查原则：** 只做分析，不做修改

---

## 🔴 严重风险（3个）

### 风险1：ultra_short.py 与 portfolio_backtest.py 数据结构断裂

**这是最严重的新发现。**

`portfolio_backtest.py`（L1760）的 `run()` 方法现在返回**嵌套结构**：
```python
result = {
    "success": True,
    "initial_cash": ...,
    "final_value": ...,
    "metrics": {           # ← 嵌套
        "returns": { "total_return": ..., "annualized_return": ... },
        "risk": { "max_drawdown": ..., "sharpe_ratio": ... },
        "trades": { "total_trades": ..., "winning_trades": ... },
        "positions": { ... },
        "performance": { ... },
        "metadata": { ... }
    }
}
```

但 `ultra_short.py`（L320-368）还在用**扁平结构**读取：
```python
perf["win_rate"] = result.get('win_rate', 0.0)         # ← 找不到！在 result.metrics.risk 下
perf["total_return"] = result.get('total_return', 0.0)  # ← 找不到！在 result.metrics.returns 下
perf["sharpe_ratio"] = result.get('sharpe_ratio', 0.0)  # ← 找不到！在 result.metrics.risk 下
```

**后果：**
- 所有 `result.get('xxx', 0.0)` 全部返回 0.0（fallback默认值）
- `result.get('all_trades', [])` 返回空 — `all_trades` 在 `result.metrics.performance.all_trades`
- `result.get('net_value_series', [])` 返回空 — 在 `result.metrics.positions.net_value_series`
- **ultra_short.py 构建的perf字典全部为0值 + 空数组，最终返回给前端的结果完全错误**
- `result['win_rate'] = result.get('win_rate', 0.0)` 永远是0.0

**影响范围：** 每次超短策略回测的结果都是错误的（全0+空数据），前端结果面板必然空白。

---

### 风险2：前端BacktestMetrics结构与后端嵌套结构字段名不匹配

后端 `metrics.returns` 的字段名：
```
total_return, annualized_return, benchmark_return, excess_return
```

前端 TypeScript `BacktestMetrics.returns` 期望：
```
total_return_pct, annual_return_pct, benchmark_return_pct, alpha_pct
```

| 后端字段 | 前端期望 | 匹配？ |
|----------|----------|--------|
| `total_return` | `total_return_pct` | ❌ |
| `annualized_return` | `annual_return_pct` | ❌ |
| `benchmark_return` | `benchmark_return_pct` | ❌ |
| `excess_return` | `alpha_pct` | ❌ |
| `max_drawdown` | `max_drawdown_pct` | ❌ |
| `win_rate` | `win_rate_pct` | ❌ |

**全部不匹配。** 即使嵌套结构对齐了，字段名也全对不上，前端取值为 undefined。

---

### 风险3：double百分比转换导致数值膨胀

`portfolio_backtest.py` 已经做了 `×100` 转换：
```python
"total_return": total_return * 100,     # 0.05 → 5.0 (表示5%)
"max_drawdown": max_drawdown * 100,     # 0.10 → 10.0 (表示10%)
```

如果前端再 `×100` 显示（前端TypeScript注释写的是 `pct` 后缀，暗示已经是百分比值），就不会出错。但如果前端按小数 `0.05` 预期再乘100，就会变成 `500%`。

**无法确定前端怎么处理**，因为没有找到前端渲染结果面板的组件代码。

---

## 🟡 中等风险（5个）

### 风险4：Bridge的MongoDB写入队列仍是死代码

`redis_ws_bridge.py` 的 `_flush_batch()` 方法体是 `pass`，但：
- `_mongo_batch_writer()` 仍在运行，仍在往 `_mongo_write_queue` 塞数据
- 队列满了只是 `logger.warning` 并丢弃日志
- `_mongo_writer_task` 占用一个协程但什么都不写

**建议：** 既然Bridge不再写MongoDB，应该删除 `_mongo_write_queue`、`_mongo_writer_task`、`_mongo_batch_writer()` 相关代码，`_handle_log_message` 中也删除 `put_nowait`。

---

### 风险5：10分钟悬挂检测过于粗暴

`__init__.py` L158-170：running超过10分钟就标failed。但大型回测（3个月+5策略）完全可能运行超过10分钟。

**建议：** 检测逻辑改为"running超过X分钟且**无新日志**"才标failed，而非仅看时长。

---

### 风险6：_worker_loop中return导致worker永久退出

`node.py` L120：任务失败后 `return`，这会导致**整个worker协程退出**，不再处理后续任务。

```python
except Exception as e:
    ...
    await self._update_task_result(task_id, "failed", error=str(e))
    return  # ← 整个worker退出！
```

应该用 `continue` 而非 `return`。

---

### 风险7：竞价过滤无数据时整个过滤无效

如果 `stock_bid_auction` 集合为空（实际大概率如此，除非专门导入），所有候选股都会被 `continue` 跳过，导致 `all_candidates` 变空集，当日跳过调仓。

当前代码只在无数据时打印warning，但**不跳过竞价过滤逻辑**，候选集仍被清空。

**建议：** 无竞价数据时应直接跳过竞价过滤步骤，不清空候选集。

---

### 风险8：map_sentiment仍无NaN单值防御

虽然添加了全NaN检测（`isna().all()`），但单个值为NaN时仍走else→depression。如果1000只股票中有1只NaN，它会被错误标记。

---

## 🟢 低风险（3个）

### 风险9：ultra_short.py中半路追涨的volume_threshold默认值仍是2.5

L239: `sp.get("min_volume_ratio", 2.5)` — 虽然portfolio_backtest.py已统一为1.5，但ultra_short.py的all_factors构建部分仍用2.5。

---

### 风险10：git rev-parse在代码中执行

`ultra_short.py` 每次回测都 `subprocess.check_output("git rev-parse")` — 如果.git目录不存在或损坏，会抛异常。已有try/except静默处理，但无意义地增加了每次回测的延迟。

---

### 风险11：result的扁平字段残留

portfolio_backtest.py返回的result中，顶层仍有 `initial_cash`、`final_cash`、`final_value`、`final_equity`，和 `metrics` 内部字段可能有语义重叠。前端如果从不同路径读取可能不一致。

---

## 📊 风险汇总

| 严重程度 | 数量 | 编号 |
|----------|------|------|
| 🔴 严重 | 3 | 风险1/2/3 |
| 🟡 中等 | 5 | 风险4/5/6/7/8 |
| 🟢 低 | 3 | 风险9/10/11 |

---

## 🎯 最紧急修复项

**风险1是当前最高优先级**：`ultra_short.py` 无法正确读取 `portfolio_backtest.py` 返回的嵌套结构，导致**每次回测结果都是0值+空数据**。有两种修复方向：

1. **方案A（推荐）：** ultra_short.py 适配嵌套结构，从 `result['metrics']['returns']['total_return']` 等读取
2. **方案B：** portfolio_backtest.py 同时在顶层保留扁平字段做兼容（`result['total_return'] = total_return * 100`）

同时需要**解决风险2的字段名不匹配**问题，确保后端字段名与前端TypeScript类型定义一致。

---

*本报告基于 commit `7b0a4f7` (2026-04-28) 代码快照，仅做分析不做修改。*
