# 🔍 超短策略回测系统完整深度分析报告

> 分析日期：2026-04-27  
> 分析范围：回测全流程 + 实时日志系统 + 因子引擎 + 前端交互  
> 分析原则：只做分析，不做修改  
> 合并自：主报告 + 补充篇 + 完整流程篇

---

## 〇、端到端完整调用链

```
用户点击【开始回测】
    │
    ▼
① 前端 submitUltraShort(request)
    │   POST /backtest/ultra-short
    ▼
② Web层 ultra_short.py: submit_ultra_short_backtest()
    │   ├─ 生成 task_id, 构建 mock_logs[] (手拼≈30行)
    │   ├─ mock_tasks[task_id] = {status:"running", logs:mock_logs}
    │   ├─ mongo_manager.insert_one("backtest_tasks", task_info)
    │   ├─ RPCClient().broadcast_by_type("backtest", "run_ultra_short_backtest")
    │   └─ 返回 {task_id, status:"running"}
    ▼
③ 前端收到 task_id → 启动 WebSocket / 回退轮询
    ▼
④ BacktestNode node.py → ultra_short.py: execute_ultra_short_backtest()
    │   ├─ logger打印 + push_log打印（各一份，格式不同）
    │   ├─ 更新MongoDB status="running", progress=10/20/30
    │   ├─ PortfolioBacktester().run(config)
    │   └─ 结果存MongoDB + 返回
    ▼
⑤ portfolio_backtest.py: run()
    │   ├─ 数据一致性校验 (1次聚合)
    │   ├─ 因子完整性检测 (55次聚合！≈11秒)
    │   ├─ 加载基准数据
    │   └─ 逐日循环 ──►⑥
    ▼
⑥ 每日处理 (≈7次MongoDB查询/天)
    │   ├─ _print_market_environment() ← 1次聚合
    │   ├─ 强制空仓判断 (阈值日志50 vs 实际200)
    │   ├─ IF 调仓日:
    │   │   ├─ 股票池+ST+次新+流动性 ← 4次查询
    │   │   ├─ compute_factors() ← 1次查询
    │   │   ├─ 5策略筛选 (纯内存)
    │   │   ├─ _get_prices() ← 全表扫描5500条！
    │   │   ├─ _rebalance() (买入reason固定"rebalance")
    │   │   └─ 收盘汇总
    │   └─ IF 强制空仓: 选股白算 + 跳过收盘汇总
    ▼
⑦ 结果汇总
    │   ├─ 净值曲线: 中间天daily_profit全为0
    │   ├─ 夏普比率 = 0.0 (硬编码)
    │   ├─ max_drawdown 从从未设置的getattr取值
    │   └─ 返回dict (结构与前端TypeScript类型不匹配)
    ▼
⑧ 日志推送链路 (同一条消息4种格式)
    │   ├─ logger本地文件: [HH:MM:SS] [✅SUCCESS] [SEQ:n] [TASK:us_xxx] [🔧INIT] 消息
    │   ├─ MongoDB ($push): 取logger最后一条 或 fallback手拼
    │   ├─ Redis → WebSocket: 原始文本(无时间戳)
    │   ├─ mock_tasks: Web层手拼 [HH:MM:SS] ✅ 消息
    │   └─ 前端addLog: [本地HH:MM:SS] 消息
    ▼
⑨ 前端展示
    ├─ 日志面板: 双重时间戳 + 重复3遍参数 + 格式混乱
    ├─ 结果面板: 数据结构不匹配，大概率空白
    └─ 进度条: 永远停在0%（progress不经Redis推送）
```

---

## 一、🔴极高 / 🔴高 严重问题（17个）

---

### 问题1：mock_tasks与MongoDB数据双写，查询返回初始日志而非实时日志

**文件：** `web/api/backtest/__init__.py` + `ultra_short.py`

**现象：** 提交回测时Web层往 `mock_tasks[task_id]` 写入初始日志；回测执行时BacktestNode往MongoDB写入实时日志。查询 `/status/{task_id}` 时**优先返回mock_tasks**，导致前端只能看到提交参数，看不到回测过程。

**这是"回测结果完全没有信息"的直接原因。**

**前端表现（问题28）：** WebSocket连接失败时回退轮询 `/status`，只能拿到mock_tasks的初始日志，看不到实时回测过程。

---

### 问题2：强制空仓逻辑——日志阈值与实际阈值不一致 + 选股计算浪费 + 跳过收盘汇总

**文件：** `portfolio_backtest.py` `run()`

| 项目 | 日志显示 | 实际逻辑 |
|------|---------|---------|
| 跌停空仓阈值 | `limit_down_count >= 50` → "触发强制空仓" | `limit_down_count >= 200` 才真正空仓 |

**三重问题：**
- **阈值不一致**：日志说触发了但实际没触发（或反过来）
- **选股白算**：强制空仓分支先执行完整选股流程（universe+因子+筛选），然后 `continue` 丢弃结果
- **跳过收盘汇总**：`continue` 跳过每日收盘汇总，用户不知道空仓后账户总额

---

### 问题3：日志双重输出——同一内容走两条路，格式不一致

**文件：** `node.py` `_push_log()` + `ultra_short.py`

- `ultra_short.py` 调用 `logger.success("INIT", ...)` → 格式化文本 `[HH:MM:SS] [✅SUCCESS] [SEQ:123]`
- 然后又调用 `push_log_fn(task_id, ...)` → 原始文本 `✅ 因子计算完成`
- **同一条消息两种格式，前端刷新页面后格式突变**

---

### 问题4：MongoDB存日志与Redis推日志内容不一致

**文件：** `node.py` `_push_log()`

- MongoDB `$push` 的是 `latest_log`（从 `logger.get_task_logs()` 取最后一条，带格式化前缀）
- Redis publish 的是 `log_text`（原始文本，无前缀）
- **当 `logger.get_task_logs()` 返回空时**，fallback到手拼 `f"[{datetime}] {log_text}"`，与logger标准格式不同
- **结果：MongoDB中同时存在格式化文本、手拼文本、原始文本三种格式**

---

### 问题5：进度(progress)不经过Redis推送，前端进度条永远停在0%

**文件：** `ultra_short.py` + `redis_ws_bridge.py`

- BacktestNode更新进度直接写MongoDB，不publish到 `backtest:progress` 频道
- RedisWSBridge虽然订阅了进度频道，但从未收到消息
- 前端进度条只在WebSocket收到 `progress` 类型消息时更新 → 永远收不到 → 永远0%
- 前端进度条在回测完成后隐藏（`v-if="backtestState.running"`），所以用户看不到"卡在0%完成"的尴尬

---

### 问题6：策略筛选参数4处重复定义且默认值不一致

**文件：** `ultra_short.py`(Web层打印) + `ultra_short.py`(BacktestNode打印) + `portfolio_backtest.py`(强制空仓分支) + `portfolio_backtest.py`(正常分支)

| 参数 | Web层 | 强制空仓分支 | 正常分支 |
|------|-------|-------------|---------|
| 涨停开板 `min_turnover_rate` | 0.15→打印15% | 未定义 | 15 |
| 首板打板 `opening_pct_chg` | ✅有 | ❌缺失 | ✅有 |
| 首板打板 `sentiment_period_in` | ❌缺失 | ❌缺失 | ✅有 |
| 首板打板 `limit_up_time` | ❌缺失 | ❌缺失 | ✅有 |

**影响：** 强制空仓分支和正常分支的筛选条件不同，同一策略在不同分支可能选出不同股票。`min_turnover_rate` 的0.15 vs 15差100倍，筛选结果完全不同。

---

### 问题7：功能开关(enable_force_empty等)后端未真正使用

**文件：** `ultra_short.py` + `portfolio_backtest.py`

- 前端传递 `enable_force_empty` / `enable_sentiment_cycle` / `enable_auction_filter`
- BacktestNode读取这些值但**只用在日志打印**
- `portfolio_backtest.py` 中 `force_empty_triggered` 是硬编码判断：`limit_down_count >= 200`
- `enable_sentiment_cycle` 无论开/关，情绪周期计算始终执行
- `enable_auction_filter` 竞价过滤逻辑**根本不存在**（代码未实现）

**用户关闭开关以为功能停了，实际后台照样跑。**

---

### 问题8：PerformanceAnalyzer专业绩效模块完全未被使用

**文件：** `performance.py` + `portfolio_backtest.py`

`PerformanceAnalyzer` 支持：夏普/索提诺/卡玛比率、最大回撤（带日期）、连续盈亏统计等。但 `portfolio_backtest.py` 完全没用，自行简化计算：
- 夏普比率 = **0.0**（硬编码）
- 最大回撤基于简化净值曲线
- 没有索提诺/卡玛/连续盈亏

同时，`PerformanceAnalyzer` 期望 `BacktestResult` 类型，与 `portfolio_backtest.py` 返回的dict不兼容（问题27），无法直接替换。

---

### 问题9：同一条日志被logger写了两次

**文件：** `portfolio_backtest.py` `self.log()` + `node.py` `_push_log()`

`self.log(msg)` 内部：`logger.info('BACKTEST', msg)` — 第1次写入  
`push_log_fn(task_id, msg)` 内部：`logger.info('BACKTEST', msg)` — 第2次写入

**本地日志文件中每条消息出现两次。** 50天回测≈500条日志 → 本地文件1000条记录。

---

### 问题10：因子完整性检测55次聚合查询，回测还没开始就浪费11秒

**文件：** `portfolio_backtest.py` `run()` 开头

```python
for field in REQUIRED_FACTOR_FIELDS:  # 55个字段
    pipeline = [{"$match": {..., field: {"$ne": None}}}, {"$count": "valid_count"}]
    result = await mongo_manager.aggregate("stock_daily_ak_full", pipeline)
```

每个字段一次全表聚合（≈200ms），55次≈11秒。应改用1次 `$facet` 聚合同时检查所有字段。

---

### 问题11：_get_prices() 全表扫描，每日返回5500条只用10-20条

**文件：** `portfolio_backtest.py` `_get_prices()`

```python
query = {"trade_date": trade_date_int}  # 没有ts_code过滤！
docs = await mongo_manager.find_many("stock_daily_ak_full", query)
```

注释说明：曾尝试复合索引 `(ts_code, trade_date)` + `$in` 但失败，退回全表扫描。50天回测 = 50 × 5500 = 275,000条无用数据传输。

---

### 问题12：净值曲线中间天daily_profit全为0，衍生指标全部失真

**文件：** `portfolio_backtest.py` 结果汇总部分

```python
for i, day_records in enumerate(rebalance_records_dict):
    day_profit = 0.0
    if i == len(rebalance_records_dict) - 1:
        day_profit = final_value - current_value  # 只有最后一天计算
    # 中间天 day_profit 全部 = 0.0
```

**连锁影响：**
- `sharpe_ratio = 0.0`（daily_profit标准差为0）
- `profit_loss_ratio` 不准确
- `max_drawdown` 基于失真的净值曲线
- 前端净值图表是一条水平线，最后一天跳跃

---

### 问题13：max_drawdown从从未设置的getattr取值

**文件：** `portfolio_backtest.py` 结果汇总

```python
max_drawdown = getattr(self, 'max_drawdown', 0.0)  # self.max_drawdown从未被设置！→ 0.0
```

这行代码在净值曲线计算**之前**执行，取到的永远是0.0。后面重新计算了max_drawdown并覆盖，但这个设计说明代码在重构过程中遗留了混乱的初始化逻辑。

---

### 问题14：前端addLog双重时间戳，日志显示混乱

**文件：** `UltraShortBacktestViewV2.vue` `addLog()`

```javascript
const addLog = (text: string) => {
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  logs.value.push(`[${timestamp}] ${text}`)
}
```

- mock_tasks日志自带时间戳 `[20:15:30] ✅ 消息` → addLog再加一层 → `[20:18:05] [20:15:30] ✅ 消息`
- WebSocket推送日志无时间戳 → addLog加一层 → `[20:18:05] ✅ 消息`
- **两种日志格式不统一**

---

### 问题15：mock_logs在RPC调用前谎报"WebSocket已连接"

**文件：** `web/api/backtest/ultra_short.py`

```python
mock_logs.append(f"[{timestamp}] ✅ WebSocket已连接，实时日志推送已开启")
```

此时WebSocket连接**还没建立**（前端还没收到task_id）。这条日志是虚假的。

---

### 问题16：参数日志三处各打印一次，内容有微妙差异

**文件：** `ultra_short.py`(Web层) + `ultra_short.py`(BacktestNode) + `portfolio_backtest.py`

| 位置 | 格式 | 示例 |
|------|------|------|
| Web层 mock_logs | 手拼树形缩进 | `[20:15] ├─ 流动性门槛: 500 万元` |
| BacktestNode logger | 格式化 | `[✅SUCCESS] [🔧INIT] 流动性门槛500万` |
| portfolio_backtest self.log | 原始文本 | `📋 === 🔧 全局公共参数 ===` |

**同组参数出现3次，格式各异，用户无法判断哪个是权威版本。**

---

### 问题17：前后端数据结构严重不匹配，结果面板大概率空白

**文件：** `backtest.ts`(前端类型) + `portfolio_backtest.py`(后端返回)

| 前端期望 | 后端实际 | 状态 |
|---------|---------|------|
| `result.summary.ts_code` | 不存在 | ❌缺失 |
| `result.summary.final_equity` | `final_value` | ⚠️字段名不同 |
| `result.metrics.returns.total_return_pct` | `total_return`(小数) | ⚠️单位不同(5.0 vs 0.05) |
| `result.metrics.risk.volatility_pct` | 不存在 | ❌缺失 |
| `result.metrics.risk.sortino_ratio` | 不存在 | ❌缺失 |
| `result.charts.nav_series.dates[]` | `net_value_series[].trade_date` | ⚠️结构不同 |
| `result.trades[].direction` | `action` | ⚠️字段名不同 |
| `result.trades[].commission` | 不存在 | ❌缺失 |

**两套并行回测引擎的根因：** 前端为 `backtester.py`(单股) 设计，实际运行 `portfolio_backtest.py`(组合)，输出格式完全不同。

---

## 二、🟡中等问题（15个）

---

### 问题18：日志推送链路竞态条件，Redis断开无重试

**文件：** `node.py` `_push_log()`

MongoDB `$push` 是同步等待的，Redis publish失败只打warning。如果Redis断开，日志只写入MongoDB，前端WebSocket收不到推送，也没有重试机制。

---

### 问题19：策略参数重复打印3遍

`ultra_short.py` push_log打印1遍 → `portfolio_backtest.py` `_print_single_strategy_filtering` 打印1遍 → 正常分支手动打印1遍。**同组参数前端出现3次。**

---

### 问题20：WebSocket重连补发可能重复

**文件：** `redis_ws_bridge.py` `catchup_logs()`

补发时从内存缓存或MongoDB读取历史日志，但Web层mock_tasks已存了初始日志，补发时再次发送，导致前端看到重复。且缓存是原始文本，MongoDB是格式化文本，补发格式与之前不同。

---

### 问题21：_rebalance买入reason固定"rebalance"，丢失策略来源

**文件：** `portfolio_backtest.py` `_rebalance()`

传入 `_rebalance()` 的只有 `target_weights: dict[str, float]`（股票→权重），没有策略来源信息。所有买入记录reason="rebalance"，最终交易明细策略列全显示"rebalance"。

---

### 问题22：两套独立情绪系统互相矛盾

**位置1：** `_print_market_environment()` — 实时计算，5档（高潮/修复/震荡/冰点/极致冰点），影响仓位系数  
**位置2：** factor_df的 `sentiment_score` → 3档（rising/chaos/depression），影响策略筛选

可能出现"冰点期降仓30%"但策略筛选要求"rising期才买入"的矛盾。

---

### 问题23：实盘模式逐日查询MongoDB，性能灾难

**文件：** `factor_engine.py` `_load_all_data()`

lookback_days=120时 = 120次×2(行情+指标) = 240次MongoDB查询。回测模式无此问题。

---

### 问题24：ST股票查询无缓存，每日重复查询

**文件：** `universe.py` `_get_st_stocks()`

50天回测 = 50次相同查询。实例级别缓存即可解决。

---

### 问题25：次新股判断用自然日(365天)而非交易日(250天)

**文件：** `universe.py` `_get_new_stocks()`

代码注释 `NEW_STOCK_DAYS = 250` 但从未使用，实际 `timedelta(days=365)`。

---

### 问题26：特殊时期月末/季末/年末用自然日判断

**文件：** `special_period_filter.py`

应基于交易日，但用自然日近似。影响有限（只在交易日调用）。

---

### 问题27：特殊时期配置硬编码+历史年份缺失

**文件：** `special_period_filter.py`

只有2025年配置，回测2024年时特殊时期过滤形同虚设。无法从前端配置。

---

### 问题28：前端Set去重性能问题+无增量获取

**文件：** `UltraShortBacktestViewV2.vue`

```javascript
logs.value = [...new Set([...logs.value, ...data.logs])]
```

每次轮询合并全量日志，Set越来越大。不同时间戳的相同日志无法去重。

---

### 问题29：volume_threshold参数名在三层的传递混乱

前端 `volume_threshold` / `min_volume_ratio` → Web层两个都传 → BacktestNode强行同步。同一参数两个名字，不一致时后者覆盖前者。

---

### 问题30：RPC超时10s + BacktestNode崩溃无感知

**文件：** `ultra_short.py`(Web层)

RPC `timeout=10.0` 只等投递确认。如果BacktestNode在回测中崩溃，MongoDB任务永远停留在 `running`。

---

### 问题31：PerformanceAnalyzer与portfolio_backtest输出不兼容

**文件：** `performance.py` + `portfolio_backtest.py`

`PerformanceAnalyzer.analyze()` 期望 `BacktestResult` 对象(来自backtester.py)，与portfolio_backtest返回的dict结构不同。需要适配层或重构输出。

---

### 问题32：MongoDB日志双写冲突（BacktestNode直写 vs Bridge异步写）

**文件：** `node.py` + `redis_ws_bridge.py`

两个写入者同时对 `backtest_tasks.logs[]` 执行 `$push`，可能导致顺序不一致。当前单worker下冲突概率低，但架构不正确。

---

## 三、🟢低优先级问题（2个）

---

### 问题33：logger全局单例task_id并发问题

**文件：** `core/utils/logger.py`

logger是全局单例，`_current_task_id` 在并发任务时会互相覆盖。当前worker_count=1不触发。

---

### 问题34：交易日历缓存无失效机制

**文件：** `universe.py`

缓存设计合理（类级别+双重检查锁），但永不失效。回测场景下可接受。

---

## 四、核心架构缺陷总结

### 缺陷1：三套日志系统并存，同一条消息4种格式

```
mock_tasks (Web层)   ──→ [HH:MM:SS] ✅ 消息         (手拼格式化)
logger (BacktestNode)──→ [HH:MM:SS] [✅SUCCESS] [SEQ:n] [TASK:us_xxx] [🔧INIT] 消息
Redis→WebSocket      ──→ 消息                         (原始文本)
前端addLog           ──→ [本地HH:MM:SS] 消息           (加本地时间戳)
```

三次重构，每次叠加新逻辑未清旧代码：mock_tasks(第1次) → logger(第2次) → RedisWSBridge(第3次)。

### 缺陷2：两套并行回测引擎，前端为错误的引擎设计

| | backtester.py (未使用) | portfolio_backtest.py (实际运行) |
|---|---|---|
| 绩效系统 | PerformanceAnalyzer(专业) | 自行简化(夏普=0) |
| 输出格式 | BacktestResult对象(前端兼容) | dict(前端不兼容) |
| 因子引擎 | 不依赖 | 依赖MongoDB预计算 |

### 缺陷3：参数传递四重定义，同一个值4个地方各写一次

Web层mock_logs / BacktestNode push_log / portfolio_backtest强制空仓分支 / 正常分支。默认值互不一致。

### 缺陷4：净值曲线严重失真，衍生指标全部不可信

只有调仓日有数据点，中间天daily_profit=0 → 夏普=0、盈亏比不准、回撤不准、前端水平线。

---

## 五、修复优先级

### P0 — 必须立即修复（核心功能不可用）

| 修复项 | 涉及问题 | 方向 |
|--------|---------|------|
| 消除mock_tasks对查询的影响 | 1, 28 | /status接口统一从MongoDB读取，mock_tasks仅做临时缓存 |
| 强制空仓逻辑重构 | 2 | 统一阈值、先判断再选股、不跳过收盘汇总 |
| 策略筛选参数统一 | 6 | 抽取为独立方法，消除4处重复定义 |
| 功能开关真正生效 | 7 | enable_force_empty等条件加入实际判断逻辑 |
| 前后端数据结构对齐 | 17 | 定义统一BacktestResult协议，后端适配前端格式 |

### P1 — 尽快修复（影响体验/指标质量）

| 修复项 | 涉及问题 | 方向 |
|--------|---------|------|
| 日志格式统一 | 3,4,9,14,15,16 | push_log只推原始文本，前端统一加时间戳；mock_logs不再谎报WS连接 |
| 统一绩效分析模块 | 8,12,13 | 让portfolio_backtest使用PerformanceAnalyzer，或构建每日净值曲线 |
| 进度通过Redis推送 | 5 | BacktestNode更新进度时同时publish到Redis |
| 因子完整性检测优化 | 10 | 1次$facet聚合替代55次循环 |
| _get_prices性能 | 11 | 排查复合索引问题，用$in替代全表扫描 |

### P2 — 优化项

| 修复项 | 涉及问题 | 方向 |
|--------|---------|------|
| reason包含策略名 | 21 | target_weights传入策略来源 |
| 情绪系统统一 | 22 | 合并两套情绪系统 |
| ST缓存+实盘优化 | 23,24,25 | 实例级缓存+范围查询替代逐日循环 |
| 特殊时期增强 | 26,27 | 增加历史年份+交易日判断+前端可配 |
| 日志去重+增量 | 19,20,28,30 | 后端支持since参数+前端增量合并 |

---

*分析完毕。共识别34个问题：🔴高17个 + 🟡中15个 + 🟢低2个。以上为纯分析，不做任何修改。*
