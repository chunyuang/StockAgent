# 市场监听持久化方案 v1.0

> 2026-06-26 系统化梳理，分3个优先级落地

## 一、当前问题（已修复）

| # | 问题 | 影响 | 修复状态 |
|---|------|------|---------|
| 1 | `_check_strategy_params_filter` 6个分支不写 `signal_status` | 39个半路追涨信号状态停在`new`，实际已被过滤 | ✅ v2.9.106 |
| 2 | `scanner_timeline.trade_date` 存 string，其他集合存 int | 用 int 查不到 timeline，前端历史页面空白 | ✅ v2.9.106 |
| 3 | `save_performance_snapshot` 从未被调用 | `performance_snapshots` 表0条，无每日盈亏曲线 | 待修 |

## 二、持久化现状全景

### ✅ 已持久化（正常工作）

| 集合 | 写入时机 | 内容 | 今日记录 |
|------|---------|------|---------|
| `scanner_signals` | 每轮扫描新增信号时 upsert | 信号完整信息(策略/价格/量比/状态/factors) | 212条 |
| `broker_orders` | 买入/卖出成功时 | 订单记录(唯一真相源) | 3条 |
| `broker_positions` | save_state 时 | 持仓(止损止盈/成本/数量) | 3条 |
| `scan_traces` | 每轮扫描 | 9层链路追踪(passed/rejected/layer_results) | 132条 |
| `premarket_snapshots` | 盘前竞价扫描 | 竞价快照(市场宽度/漏斗/候选) | 16条 |
| `sentiment_scores` | 盘中每次情绪计算 | 7维情绪(score/period/limit_up/down) | 1条 |
| `scanner_runtime_snapshot` | 每轮扫描 | 运行时状态(信号数/持仓/trailing_stops/circuit_breaker) | 1条(upsert) |
| `scanner_timeline` | 每轮扫描 | 决策日志(blocked原因/buy/sell) | 501条 |
| `param_snapshots` | 盘前 | 策略参数快照 | — |

### 🔴 缺失/未调用（需修复）

| # | 集合/功能 | 代码状态 | 问题 | 优先级 |
|---|----------|---------|------|--------|
| 3 | `performance_snapshots` | 代码存在但未调用 | `save_performance_snapshot` 只在收盘事件中调用，但收盘事件未触发 | P0 |
| 4 | 风控决策审计 trail | 无 | 止损/止盈/熔断决策无持久化，无法回溯 | P1 |
| 5 | 行情快照历史 | 无 | 无法回溯某一时刻行情状态(涨跌家数/涨停数) | P2 |
| 6 | 策略漏斗时序 | 无 | 9层漏斗(5735→10→5)变化趋势无时序记录 | P2 |

## 三、修复方案

### P0: performance_snapshots 未调用（今日修）

**问题**: `save_performance_snapshot` 代码完整，只在 `scanner_event_subscribers.py:389` 的收盘事件中调用。但收盘事件 `market_close` 可能未正确触发。

**修复**: 在 `persist_stop_state`（scanner 停止时调用）中增加 `save_performance_snapshot` 调用作为兜底。同时在 `persist_scan_result` 中每 N 轮保存一次。

```python
# runtime_persistence.py - persist_scan_result 末尾增加
if scanner._scan_count % 10 == 0:  # 每10轮保存一次绩效快照
    try:
        await self.save_performance_snapshot(scanner._trade_date)
    except Exception as _e:
        logger.debug(f"[SCAN] 绩效快照保存失败: {_e}")
```

### P1: 风控决策审计 trail（本周修）

**问题**: 止损/止盈/熔断/强制空仓等风控决策只写 timeline log，没有结构化记录。

**方案**: 新增 `risk_decisions` 集合，在风控决策点写入结构化文档：

```python
# 新增集合: risk_decisions
{
    "trade_date": 20260626,  # int
    "timestamp": "2026-06-26T14:30:00",
    "scan_id": 25,
    "decision_type": "stop_loss" | "take_profit" | "circuit_breaker" | "force_empty" | "trailing_stop",
    "ts_code": "603661.SH",
    "stock_name": "恒林股份",
    "trigger_price": 40.05,
    "current_price": 40.06,
    "quantity": 1500,
    "reason": "止损价40.05, 现价40.06, 触发止损",
    "action_taken": "hold" | "sell" | "pause_trading" | "reduce_position",
    "account_id": "default",
}
```

**写入点**:
- `position_checker.py` 止损/止盈检查
- `scanner.py` risk_loop 熔断检查
- `scanner.py` 强制空仓确认

### P2: 行情快照 + 策略漏斗时序（后续迭代）

**行情快照** (`quote_snapshots`):
```python
{
    "trade_date": 20260626,
    "timestamp": "2026-06-26T13:05:02",
    "source": "eastmoney_delay",
    "total_stocks": 5732,
    "up_count": 2800,
    "down_count": 2400,
    "limit_up": 71,
    "limit_down": 50,
    "avg_pct_chg": 0.35,
    "degrade_level": 0,
}
```

**策略漏斗时序** (`strategy_funnel_history`):
```python
{
    "trade_date": 20260626,
    "scan_id": 25,
    "timestamp": "2026-06-26T13:05:02",
    "funnel": {
        "L1_force_empty": {"input": 5732, "output": 5732, "rejected": 0},
        "L2_special_period": {"input": 5732, "output": 5732, "rejected": 0},
        "L3_sentiment": {"input": 5732, "output": 5732, "rejected": 0},
        "L4_premarket": {"input": 5732, "output": 3807, "rejected": 1925},
        "L5_auction": {"input": 3807, "output": 3807, "rejected": 0},
        "L6_strategy": {"input": 3807, "output": 10, "rejected": 3797},
        "L7_ranking": {"input": 10, "output": 10, "rejected": 0},
        "L8_position": {"input": 10, "output": 10, "rejected": 0},
    },
    "strategy_hits": {"halfway_chase": 6, "first_limit_up": 4},
    "sentiment_score": 52.6,
    "position_ratio": 0.25,
}
```

> 注: `scan_traces` 已有类似数据，但格式不同且不含时序聚合。P2 可以直接从 scan_traces 聚合生成，不需要新集合。

## 四、trade_date 类型统一规范

**规则**: 所有集合的 `trade_date` 字段统一存为 **int** (`20260626`)。

| 集合 | 当前类型 | 修复 |
|------|---------|------|
| scanner_signals | int ✅ | — |
| broker_orders | int ✅ | — |
| scan_traces | int ✅ | — |
| premarket_snapshots | int ✅ | — |
| sentiment_scores | int ✅ | — |
| scanner_timeline | int ✅ | v2.9.106 已修 |
| scanner_runtime_snapshot | string | 待修(下次重启自动转) |
| performance_snapshots | string | 新写入用 int |

## 五、实施计划

| 阶段 | 内容 | 时机 | 状态 |
|------|------|------|------|
| ✅ 已完成 | 修复 signal_status 不写 + timeline 类型统一 | v2.9.106 | ✅ |
| ✅ 已完成 | P0: performance_snapshots 兜底调用 | v2.9.106 | ✅ |
| ✅ 已完成 | P1: risk_decisions 审计 trail + API端点 | v2.9.106 | ✅ |
| ✅ 已完成 | runtime_snapshot trade_date 统一 int | v2.9.106 | ✅ |
| ✅ 已完成 | P2: funnel-timeseries API + quote-snapshots API | v2.9.106 | ✅ |
| ✅ 已完成 | trade_date 类型守卫脚本 | v2.9.106 | ✅ |
| ✅ 已完成 | 4个纯内存风控字段持久化 (cooldown/force_empty/overrides/premarket) | v2.9.106 | ✅ |
| 🔲 补充 | trade_date 类型守卫脚本 cron化 (每日07:00) | 后续 | 待定 |
