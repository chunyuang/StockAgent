# 🔍 StockAgent 全面复查报告

> **复查日期：** 2026-04-28  
> **基线文档：** `DOC/backtest-deep-analysis-20260427.md`（保留不动）  
> **复查范围：** 对照深度分析报告的34个问题，逐一验证修复状态，发现新问题  
> **最近提交：** `54edb1e` task-28 → task-16, task-18, task-20, task-24, task-28

---

## 一、🔴 严重问题修复状态

### ✅ 已修复（13个）

| # | 原问题 | 修复方式 | 验证点 |
|---|--------|----------|--------|
| 2 | 强制空仓逻辑——日志阈值50 vs 实际200 | `enable_force_empty` 从config读取，条件逻辑重构 | L717-720: `enable_force_empty = config.get("enable_force_empty", True)` ✅ |
| 5 | 进度(progress)不经Redis推送 | task-28: `redis_manager.publish(f"backtest:progress:{task_id}")` | ultra_short.py L101-103 ✅ |
| 7 | 功能开关(enable_force_empty)后端未使用 | task-20: 从API params迁移到config | L454: config中读取 ✅ |
| 9 | 同一条日志被logger写了两次 | task-18: 统一日志系统，去除重复调用 | portfolio_backtest.py 中所有日志走 `self.log()` 统一入口 ✅ |
| 10 | 因子完整性检测55次聚合→11秒 | 改用 `$facet` 单次聚合 | L610-641: 一次pipeline完成所有因子检测 ✅ |
| 11 | _get_prices全表扫描5500条 | 改用 `$in` + ts_code 数据库层过滤 | L1823: `query = {"trade_date": trade_date_int, "ts_code": {"$in": ...}}` ✅ |
| 12 | 净值曲线中间天daily_profit全为0 | 逐日计算 `daily_profit = current_net_value - last_net_value` | L1349 ✅ |
| 13 | max_drawdown从从未设置的getattr取值 | 引入PerformanceAnalyzer计算 | L1512-1535 ✅ |
| 21 | _rebalance买入reason固定"rebalance" | 修复#45: reason带上具体策略名 | L1293, 1440: `strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip()` ✅ |
| 24 | ST股票查询无缓存 | 添加缓存，ST名单不会每日变化 | universe.py L133: 注释标记修复#24 ✅ |
| 25 | 次新股判断用自然日365 vs 交易日250 | 改为250个交易日 | universe.py L49: `NEW_STOCK_DAYS = 250` ✅ |
| 26/27 | PerformanceAnalyzer完全未被使用 | 已引入并使用 | portfolio_backtest.py L56, L1512 ✅ |
| 29 | volume_threshold参数名三层传递混乱 | 统一命名 | L229-234: `volume_threshold = params.get("volume_threshold", params.get("min_volume_ratio", 2.5))` ✅ |

### ⚠️ 部分修复（5个）

| # | 原问题 | 当前状态 | 残留风险 |
|---|--------|----------|----------|
| 1 | mock_tasks与MongoDB双写 | MongoDB优先读取，mock_tasks仅临时缓存 | ⚠️ mock_tasks仍存在，RPC失败时mock_tasks残留初始logs，可能误导前端 |
| 3 | 日志双重输出（logger + push_log） | 回测引擎已统一 | ⚠️ Web层(ultra_short.py)仍有手拼mock_logs，与回测节点真实日志格式不一致 |
| 4 | MongoDB存日志与Redis推日志内容不一致 | 部分对齐 | ⚠️ push_log_fn推送纯文本，MongoDB $push可能取logger格式化后的文本，仍可能有差异 |
| 6 | 策略筛选参数4处重复定义 | 前端→API→回测引擎链路清晰化 | ⚠️ `defaults.py`、`models.py`、`portfolio_backtest.py`、`ultra_short.py` 各有默认值，仍不完全一致 |
| 17 | 前后端数据结构不匹配 | task-28做部分对齐 | ⚠️ 前端TypeScript `BacktestMetrics` 有嵌套结构(returns/risk/trades/exposure/costs)，后端result dict仍是扁平结构 |

### ❌ 未修复（9个）

| # | 原问题 | 严重程度 | 说明 |
|---|--------|----------|------|
| 8 | ~~PerformanceAnalyzer未使用~~ | — | **已在26/27修复，可移除** |
| 14 | 前端addLog双重时间戳 | 🟡中 | 前端问题，需检查前端代码 |
| 15 | mock_logs在RPC调用前谎报"WebSocket已连接" | 🔴高 | ultra_short.py中仍存在，前端看到"已连接"但WebSocket可能未真正建立 |
| 16 | 参数日志三处各打印一次 | 🟡低 | 信息冗余，不影响功能 |
| 22 | **两套独立情绪系统互相矛盾** | 🔴极高 | `map_sentiment()`(L1015): ≥70→rising, ≥40→chaos; `_print_market_environment()`(L182): ≥80→高潮期, ≥60→修复期。**阈值和标签完全不同**，选股用rising/chaos/depression，显示用高潮期/修复期/震荡期 |
| 30 | RPC超时10s + BacktestNode崩溃无感知 | 🔴高 | 回测节点崩溃后，前端只看到"running"永远不结束 |
| 32 | MongoDB日志双写冲突（BacktestNode直写 vs Bridge异步写） | 🟡中 | 可能导致日志重复或丢失 |
| 33 | logger全局单例task_id并发问题 | 🟡中 | 多个回测并发时task_id可能串 |
| 34 | 交易日历缓存无失效机制 | 🟢低 | 长时间运行后数据可能过时 |

---

## 二、🆕 本次复查新发现的问题

### 🔴 新问题1：sentiment_score在factor_df中的NaN处理缺失

**文件：** `portfolio_backtest.py` L1015-1023

```python
def map_sentiment(score):
    if score >= 70: return 'rising'
    elif score >= 40: return 'chaos'
    else: return 'depression'
factor_df['sentiment_period_in'] = factor_df['sentiment_score'].apply(map_sentiment)
```

**问题：** 当 `sentiment_score` 为 NaN 时，`score >= 70` 返回 `False`，NaN 进入 `else` 分支，被标记为 `'depression'`。这意味着**缺失情绪数据的股票被强制进入冰点期，可能被错误过滤掉**。

**影响：** 如果大量股票缺少sentiment_score，几乎所有股票都会被标记为depression，导致策略筛选时只保留depression周期的候选股，严重影响选股结果。

**修复建议：**
```python
def map_sentiment(score):
    if pd.isna(score): return None  # 或 'unknown'
    if score >= 70: return 'rising'
    elif score >= 40: return 'chaos'
    else: return 'depression'
```

---

### 🔴 新问题2：情绪阈值体系矛盾（问题22深化）

两套情绪系统并存，且**阈值不匹配**：

| 系统 | 分数范围 | 标签 | 用途 |
|------|----------|------|------|
| `map_sentiment()` (L1015) | ≥70/≥40/else | rising/chaos/depression | **选股过滤** |
| `_print_market_environment()` (L182) | ≥80/≥60/≥40/≥20/else | 高潮期/修复期/震荡期/冰点期/极致冰点 | **显示+仓位控制** |

**矛盾1：** 同一个score=65，`map_sentiment`判为chaos，`_print_market_environment`判为修复期  
**矛盾2：** 仓位控制用80/60/40/20五档，但选股过滤只有70/40两档，粒度不匹配  
**矛盾3：** 两套标签体系无法互相映射，代码维护时极易搞混

**修复建议：** 统一为一套情绪系统，选股和仓位控制共享同一组阈值和标签。

---

### 🟡 新问题3：PerformanceAnalyzer临时文件竞态风险

**文件：** `portfolio_backtest.py` L1522-1530

```python
temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
json.dump(merged_trades, temp_file, ensure_ascii=False, indent=2)
temp_file.close()
analyzer = PerformanceAnalyzer(temp_file.name)
...
os.unlink(temp_file.name)
```

**问题：**
1. `delete=False` + 手动 `os.unlink` — 如果中间抛异常，临时文件不会自动清理
2. 并发回测时可能文件名冲突（虽然tempfile做了随机化，风险极低）
3. 如果PerformanceAnalyzer构造函数抛异常，`os.unlink`不执行

**修复建议：** 用 `try/finally` 包裹，或用 `tempfile.TemporaryDirectory()` 上下文管理器。

---

### 🟡 新问题4：前端默认volume_threshold=1.5，后端多处默认2.5

| 位置 | 默认值 |
|------|--------|
| `models.py` L115 | `volume_threshold: float = Field(default=1.5)` |
| `portfolio_backtest.py` L233 | `params.get("volume_threshold", params.get("min_volume_ratio", 2.5))` |
| `portfolio_backtest.py` L1067 | `params.get("min_volume_ratio", 2.5)` |
| `portfolio_backtest.py` L1924 | `converted_params.get("min_volume_ratio", 2.5)` |

**前端提交1.5，但如果后端某条路径没收到前端值，会fallback到2.5**，导致回测结果不可预期。

---

### 🟡 新问题5：_get_prices中trade_date类型转换位置隐患

**文件：** `portfolio_backtest.py` L1827

```python
trade_date_int = int(trade_date)
```

之前的BUG是trade_date存字符串但传入整数。现在强制`int()`转换，但如果`trade_date`已经是字符串`"20260120"`没问题，如果是`None`或其他类型会直接崩溃。缺少防御性检查。

---

### 🟡 新问题6：买入reason格式约定脆弱

当前reason格式为 `"半路追涨 策略选股调入"`，提取策略名靠字符串替换：
```python
strategy_name = first_buy.reason.replace(' 策略选股调入', '').strip()
```

**风险：** 如果reason格式稍有变化（如多了个空格、繁体字、新策略名含"策略"二字），提取就会失败，显示"-"。

**修复建议：** 用结构化方式存储策略信息，如 `reason = "策略选股调入"` + 独立字段 `strategy = "半路追涨"`。

---

### 🟢 新问题7：_rebalance中现金不足时按比例缩减买入，但无日志

`portfolio_backtest.py` 现金不足时的缩减逻辑没有日志输出，用户看到买入数量比预期少却不知道原因。

---

## 三、📊 总体状态汇总

```
原34个问题：
  ✅ 已修复：    13个 (38%)
  ⚠️ 部分修复：  5个 (15%)
  ❌ 未修复：    9个 (26%)  ← 其中8个仍需处理（#8可移除）
  🆕 新发现：    7个

仍需处理的🔴高/极高优先级：
  #22 两套情绪系统矛盾（极高）
  #15 mock_logs谎报WebSocket已连接（高）
  #30 回测节点崩溃无感知（高）
  #17 前后端数据结构不匹配（高）
  新#1 sentiment_score NaN处理（高）
```

---

## 四、🎯 建议修复优先级

### P0 — 必须立即修复

1. **统一情绪系统**（#22 + 新#1）：合并两套阈值/标签，增加NaN处理
2. **移除mock_logs中"WebSocket已连接"的谎言**（#15）：改为"回测任务已提交"等客观描述
3. **前后端结果数据结构对齐**（#17）：后端result dict → 前端BacktestMetrics嵌套结构

### P1 — 尽快修复

4. **回测节点崩溃感知**（#30）：添加心跳/超时检测，崩溃后自动标记task为failed
5. **volume_threshold默认值统一**（新#4）：全局统一为同一默认值
6. **PerformanceAnalyzer临时文件安全**（新#3）：try/finally包裹

### P2 — 优化项

7. 买入reason结构化（新#6）
8. trade_date防御性检查（新#5）
9. 现金缩减买入加日志（新#7）
10. mock_tasks残留清理（#1残留）
11. 日志格式完全统一（#3/#4残留）
12. logger并发安全（#33）

---

*本报告基于 2026-04-28 代码快照生成，不修改任何已有文档。*
