# 市场监听持久化全面审计报告

**日期**: 2026-06-29
**审计范围**: `AgentServer/nodes/market_monitor/` + 关联 API
**目的**: 找出"内存有 / 持久化没有" 的数据，分级修复

---

## 一、当前持久化全景

### ✅ 已持久化 (20 集合)

| 集合 | 用途 | 写入位置 | 当前规模 | 索引 | 评估 |
|---|---|---|---|---|---|
| `broker_orders` | 交易记录 | broker.execute_buy/sell | 41 / 14今日 | order_id, ts_code+status, trade_date | ✅ 完整 |
| `broker_positions` | 持仓快照 | sync_save | 10 | account+ts_code unique | ✅ |
| `broker_accounts` | 账户资产 | _recalc_account | 1 | - | ⚠️ 缺索引 |
| `scanner_signals` | 信号历史 | signal_manager._persist_signal_history | 1769 / 160今日 | **❌ 无索引** | ⚠️ |
| `scanner_timeline` | 决策时间线 | runtime_persistence.save_timeline | 2253 / 76今日 | trade_date_desc, ts_code+date | ✅ |
| `scanner_runtime_snapshot` | 运行时状态 | save_runtime_snapshot | 3 / 1今日 | account+trade_date desc, updated_at | ✅ TTL |
| `scan_traces` | 9层链路 | save_scan_traces | 4372 / 102今日 | trade_date_1 | ⚠️ 缺 ts_code |
| `sentiment_scores` | 每日情绪 | persist_realtime_sentiment | 526 / 1今日 | **❌ 无索引** | ⚠️ |
| `sentiment_live_log` | **盘中情绪日志(v2.9.106新)** | intraday_sentiment + emotion_cycle | 29 / 28今日 | trade_date+ts desc, ts TTL 7d | ✅ |
| `premarket_snapshots` | 盘前快照 | runtime_persistence.premarket_auction | 97 / 13今日 | **❌ 无索引** | ⚠️ |
| `audit_log` | 通用审计 | 各处调用 | 15439 | ttl_90d | ✅ |
| `scan_date_cache` | 扫描日期缓存 | runtime_persistence | 29 | - | OK |
| `param_snapshots` | 策略参数快照 | scanner_review | 28 | - | OK |
| `scanner_config` | scanner 配置 | - | 1 | - | OK |
| `strategy_params` | 策略参数 | - | 5 | - | OK |

### ❌ 集合存在但 0 数据 (写入逻辑缺失或被禁用)

| 集合 | 期望用途 | 问题 | 优先级 |
|---|---|---|---|
| **`performance_snapshots`** | **每日资产快照(资金曲线/回撤)** | save_performance_snapshot 定义了但**当日 cron 未跑** | 🔴 P0 |
| **`risk_decisions`** | **风控决策审计(卖出审计)** | 写入逻辑存在(position_checker:713)，但**今日 0 条**说明今日无卖出/或未触发 | 🟡 P1 |
| `scanner_state` | (旧)pending_sells 单一文档 | 已被 `scanner_runtime_snapshot` 替代，但 data_integrity_check 仍引用旧集合 | 🟢 P2 (清理) |
| `broker_account` | (单数)误命名集合 | 实际用的是复数 `broker_accounts`，单数为遗留空集合 | 🟢 P2 (清理) |
| `strategies` | 用户策略库 | 功能未上线 | OK |

### 🔴 完全没持久化的内存状态

| 内存字段 | 位置 | 用途 | 重启影响 | 优先级 |
|---|---|---|---|---|
| `quote_manager._realtime_cache` | quote_manager.py:36 | 实时行情(每5秒覆盖) | 重启丢失，但下次扫描会重建 | 🟢 P3 (可不存) |
| `quote_manager._prev_realtime_cache` | quote_manager.py:37 | 上次行情(算 momentum 用) | 重启丢失 → momentum 第1次扫描为0 | 🟡 P2 |
| `scanner._timeline` | scanner_initializer:84 | 内存 timeline list | 已通过 save_timeline 持久化 ✅ | OK |
| `scanner._active_signals` | scanner_initializer:83 | 当前 active 信号 | 已通过 scanner_signals 持久化 ✅ | OK |
| **`intraday_calculator._prev_up_down_ratio`** | intraday_sentiment.py:54 | momentum 计算用上次涨跌比 | 重启 → momentum 第1次0 | 🟡 P2 |
| **`intraday_calculator._static_cache`** | intraday_sentiment.py:55 | 当日静态维度缓存(zt_premium 等) | 重启 → 需重新查 MongoDB（已有 fallback） | 🟢 P3 |
| **`emotion_cycle._cache`** | emotion_cycle.py:144 | EmotionScore 缓存 | 历史模式：影响速度不影响正确性 | 🟢 P3 |
| `data_source_router._statuses` | data_source_router.py:91 | 数据源健康状态 | 重启重建 | 🟢 P3 |
| `data_source_router._sources` | data_source_router.py:89 | 数据源实例 | 重启重建 | 🟢 P3 |
| **`strategy_scorer._last_missing_condition_fields`** | strategy_scorer.py:41 | 哪些策略缺哪些条件字段 | 调试用，丢失也行 | 🟢 P3 |
| `risk_watchdog._last_alerts` | risk_watchdog.py:106 | 告警冷却时间 | 重启 → 重启后第1次会重发已发过的告警 | 🟡 P2 |

### 🟠 写入了但**索引缺失**导致查询慢的集合

| 集合 | 缺失索引 | 慢查询场景 |
|---|---|---|
| `scanner_signals` | trade_date, ts_code, account_id | 查"今日信号"全表扫 1769 行 |
| `sentiment_scores` | trade_date | 按日期查询全表扫 526 行 |
| `premarket_snapshots` | trade_date, account_id | 盘前竞价查询 |
| `broker_accounts` | account_id | account查询 |
| `scan_traces` | ts_code, account_id | 看某只股票 9 层链路慢 |

### 🔴 已识别但未持久化的"事件流"

| 事件流 | 用途 | 价值 |
|---|---|---|
| **数据源切换事件** | 量脉→东财→Mongo 降级时机 | 复盘"为什么 14:00 数据卡了" |
| **行情降级事件** | quote_degrade_level 0→1→2 | 复盘行情质量 |
| **风控告警事件** | risk_watchdog 触发的告警 | 历史告警审计 |
| **策略打分快照** | strategy_scorer 每次评分结果 | 复盘"为什么这只没选上" |
| **websocket 推送事件** | 哪些信号被推送给前端 | 排查"前端没收到信号" |
| **scanner 主循环异常** | _scan_loop_error_count 计数器存在但不存日志 | 排查不稳定循环 |

---

## 二、根因分析

### 为什么这么多没存？

1. **早期设计**: scanner 以"实时计算 + 重启重建"为主，没把可观测性当一等公民
2. **集合规划混乱**: `scanner_state`(旧) vs `scanner_runtime_snapshot`(新) vs `broker_account`(单数空) vs `broker_accounts`(复数有数据)
3. **索引滞后**: 写代码时没有索引规范，集合达到几千几万行后才发现慢
4. **事件即丢失**: 大量 `logger.info` 出现"切换/降级/告警"字样但不存 MongoDB

---

## 三、系统化修复方案

### 🔴 P0 — 立即修

#### 1. performance_snapshots 写入恢复
- **现状**: 定义了 `save_performance_snapshot()`，但**主循环不调用**
- **修**: 
  - 在 `scanner._scan_loop` 每 10 轮调用一次 `save_performance_snapshot(force_in_session=False)`
  - 在 daily_settlement 强制调用一次
  - 加索引: `(account_id, trade_date desc, timestamp desc)`

#### 2. risk_decisions 链路连通验证
- **现状**: 写入代码已存在(position_checker:713)，今日 0 条因今天没卖出
- **修**:
  - 加索引: `(account_id, trade_date desc, timestamp desc)` ✅ 已有
  - 增加 cron 检查：如果当日有 broker_orders(side=sell, status=filled) 但 risk_decisions 缺失 → 告警

### 🟡 P1 — 本周修

#### 3. scanner_signals 加索引
```python
await db.scanner_signals.create_indexes([
    IndexModel([("trade_date", -1), ("account_id", 1)]),
    IndexModel([("ts_code", 1), ("trade_date", -1)]),
    IndexModel([("scan_time", -1)]),
])
```

#### 4. sentiment_scores 加索引
```python
await db.sentiment_scores.create_index([("trade_date", -1)], unique=True)
```

#### 5. premarket_snapshots 加索引
```python
await db.premarket_snapshots.create_indexes([
    IndexModel([("trade_date", -1), ("account_id", 1)]),
])
```

#### 6. quote_manager 行情降级事件持久化
- 新建集合 `quote_degrade_events`
- `_set_degrade_level()` 时 insert 一条 `{trade_date, ts, from_level, to_level, reason}`
- TTL 30 天

#### 7. data_source_router 切换事件持久化
- 新建集合 `data_source_events`
- `_switch_to()` 时 insert 一条 `{trade_date, ts, from, to, reason}`
- TTL 30 天

#### 8. risk_watchdog 告警持久化
- 新建集合 `risk_alerts`
- 告警触发时 insert（不只是 logger.warning）
- TTL 90 天，加 `(check_name, ts desc)` 索引

### 🟢 P2 — 本月修

#### 9. 清理冗余集合
```python
# 1. broker_account 单数空集合 → drop
await db.broker_account.drop()

# 2. scanner_state 旧集合 → 数据迁移完后 drop
# data_integrity_check.py:175/186 改为查 scanner_runtime_snapshot
```

#### 10. intraday_calculator._prev_up_down_ratio 持久化
- 写到 `scanner_runtime_snapshot.intraday_state`
- 重启后 restore_start_state 恢复，避免第 1 次 momentum=0

#### 11. risk_watchdog._last_alerts 持久化
- 写到 `scanner_runtime_snapshot.risk_state.last_alerts`
- 重启后避免立即重发同一告警

#### 12. strategy_scorer 评分快照持久化
- 新集合 `strategy_score_logs` (TTL 7天)
- 每次打分后 insert：`{trade_date, scan_time, ts_code, strategy, score, missing_fields, factors}`
- 价值：复盘为什么某只没选上

#### 13. signal_dispatcher 推送记录
- 新集合 `signal_dispatch_events` (TTL 7天)  
- `dispatch()` 时写：`{ts_code, channel, status, ts}`
- 价值：排查“前端未收到信号”

---

## 四、实现优先级与工量评估

| 优先级 | 项 | 代码量 | 预期价值 |
|---|---|---|---|
| 🔴 P0 | performance_snapshots 接入主循环 | ~30行 | 资金曲线/回撤可看 |
| 🔴 P0 | risk_decisions cron 告警 | ~50行 cron | 发现卸货损失 |
| 🟡 P1 | 5个集合补索引 | ~40行 | 查询提速10x |
| 🟡 P1 | quote_degrade_events | ~20行 | 行情质量可复盘 |
| 🟡 P1 | data_source_events | ~20行 | 数据源切换可复盘 |
| 🟡 P1 | risk_alerts | ~30行 | 告警历史可查 |
| 🟢 P2 | 清理凗余集合 + 其他 | ~50行 | 代码净化 |

**总工量**: ~240 行，分 3 个 commit。

---

## 五、下一步行动

建议以 P0 开始：
1. performance_snapshots 主循环接入 → commit
2. risk_decisions 告警 cron + 嵌入 `data_consistency_guard.py`
3. 5个集合补索引 (在 mongo_manager.initialize 统一初始化)
4. 三个事件流集合，并提供查询 API

是否让我开始实现 P0？