# 数据架构审计 — v2.9.97c
> 日期: 2026-06-16 | 审计人: AI | 触发: 前端数据不一致（15 vs 10）

## 一、MongoDB 集合 — 真相源分层

### 🟢 第一层：唯一真相源（Primary Source of Truth）

| 集合 | 职责 | 写入者 | 文档数 | 关键字段 |
|------|------|--------|--------|----------|
| `broker_orders` | 真实成交记录 | broker.execute_buy/sell | 71 | ts_code, side, filled_qty, filled_price, profit_pct, trade_date, status |
| `broker_positions` | 当前持仓状态 | broker.save_state / runtime_persistence | 15 | ts_code, total_qty, avg_cost, current_price, profit_pct, strategy, stop_loss_price |
| `broker_accounts` | 账户资金 | broker.save_state | 1 | total_assets, available_cash, market_value |

### 🟡 第二层：业务日志（Derived / Append-Only）

| 集合 | 职责 | 写入者 | 文档数 | 关键字段 |
|------|------|--------|--------|----------|
| `scanner_timeline` | 决策日志(blocked) | runtime_persistence.save_timeline | 872+ | action(blocked), reason, decision_detail |
| `scan_traces` | 扫描链路追踪 | runtime_persistence.save_scan_traces | ? | scan_id, candidates, layer_results |
| `sentiment_scores` | 情绪周期评分 | EmotionCycleManager | 515 | score, phase, date |
| `limit_list` | 涨跌停数据 | daily_sync | 69k | ts_code, limit_times, fd_amount |

### 🔵 第三层：行情数据（Reference Data）

| 集合 | 职责 | 来源 | 文档数 |
|------|------|------|--------|
| `stock_daily_ak_full` | 日线OHLCV | AKShare/东财 | 2.7M |
| `daily_basic` | PE/PB/换手率/市值 | AKShare/东财 | 2.8M |
| `stock_basic` | 股票基础信息 | AKShare | ? |
| `index_daily` | 指数日线 | AKShare | ? |

### ⚪ 第四层：回测/配置

| 集合 | 职责 |
|------|------|
| `backtest_results` | 回测结果 |
| `scanner_config` / `strategy_params` | 策略配置 |
| `param_snapshots` | 参数快照(漂移检测) |
| `performance_snapshots` | 策略表现快照 |

---

## 二、后端 API → MongoDB 读取映射

### 持仓数据（3条路径 → 已统一为1条）

```
                    broker_positions (唯一真相源)
                         │
              ┌──────────┼──────────┐
              │          │          │
        /all(15✅)  /analysis(15✅)  /unified/positions(15✅)
              │          │          │
         scanner内存  broker_positions  broker_positions
              │
         broker.get_positions()
              │
         /account position_count(15✅)  ← 从broker_positions实查
```

**已修复**: `/account` 之前读 `broker_accounts.position_count`(缓存值=0)，现在从 `broker_positions` 实查。

### 交易数据（2条路径 → 已统一为1条）

```
                    broker_orders (唯一真相源)
                         │
         ┌───────────────┼───────────────┐
         │               │               │
  /analysis KPI     /trade-audit    /unified/trades
  total_trades=28   38 trades       10 today
  daily_detail=5                    
         │               │               │
  broker_orders     broker_orders    broker_orders
  (sell records)    (buy+sell)       (buy+sell by date)
```

**已修复**: 之前6个端点各自选不同数据源(scanner_timeline vs broker_orders)，现在统一。

### 决策日志（1条路径）

```
                    scanner_timeline (决策日志)
                         │
                  /timeline/history
                  blocked=872
                         │
                  只写 blocked 等非交易记录
                  不再写 buy/sell
```

---

## 三、前端 Tab → API → MongoDB 完整数据通路

### AccountTab（账户+持仓+风控）
```
AccountTab
  └─ inject('scanner-monitor')
       └─ useScannerMonitor
            └─ /scanner/analysis  →  broker_positions (持仓)
                               →  broker_orders (交易KPI)
                               →  broker_accounts (资金)
  
  额外: 点击个股 → /analysis/stock/{code}  →  broker_orders (交易明细)
  
  显示: 15只持仓 ✅ | 止损状态 ✅ | KPI ✅ | daily_detail ✅
```

### AnalysisTab（分析+回测对比）
```
AnalysisTab
  └─ inject('scanner-monitor')
       └─ useScannerMonitor
            └─ /scanner/analysis  →  broker_orders (KPI/每日明细)
                               →  broker_positions (持仓列表)
  
  显示: kpi.total_trades=28 ✅ | daily_detail=5 ✅ | positions=15 ✅
```

### ReviewTab（复盘+逐笔归因）
```
ReviewTab
  └─ inject('scanner-monitor')
       └─ useScannerMonitor
            └─ useReviewMonitor
                 └─ /unified/trades?date=X  →  broker_orders (buy+sell配对)
                 └─ /scanner/discipline-check  →  scan_traces
                 └─ /scanner/daily-report  →  broker_orders + sentiment_scores
  
  显示: 逐笔归因(buy+sell配对) ✅ | 纪律检查 ✅
```

### OpsTab（操作+时间线）
```
OpsTab
  └─ inject('scanner-monitor')
       └─ useScannerMonitor
            └─ /scanner/timeline/history  →  scanner_timeline(blocked)
                                           →  broker_orders(buy/sell)
  
  显示: 时间线(blocked+buy+sell合并) ✅
```

### SentimentTab（情绪周期）
```
SentimentTab
  └─ inject('scanner-monitor')
       └─ useSentimentMonitor
            └─ /scanner/market-sentiment  →  sentiment_scores
            └─ /scanner/sentiment-timeline  →  sentiment_scores
            └─ /scanner/sentiment-strategy-matrix  →  broker_orders
  
  显示: 情绪评分/周期/策略矩阵 ✅
```

### ScanTraceTab（扫描追踪）
```
ScanTraceTab
  └─ inject('scanner-monitor')
       └─ useScanTraceMonitor
            └─ /scanner/scan-traces  →  scan_traces
            └─ /scanner/execution-quality  →  broker_orders + scan_traces
  
  显示: 扫描漏斗/层级详情 ✅
```

### PremarketTab（盘前）
```
PremarketTab
  └─ inject('scanner-monitor')
       └─ usePremarketMonitor
            └─ /scanner/premarket-status  →  scanner内存
            └─ /scanner/limit-pools  →  limit_list (非开盘) / 必盈API (开盘)
  
  显示: 盘前状态/涨停池 ✅
```

---

## 四、数据写入路径 — 谁在写什么

### 交易执行（唯一写入口）
```
用户/自动 → broker.execute_buy() / execute_sell()
              │
              ├─ 写 broker_orders (成交记录)
              ├─ 写 broker_positions (持仓更新)  
              ├─ 写 broker_accounts (资金更新)
              └─ 写 scanner._timeline (内存，运行时决策日志)
                   └─ save_timeline() → scanner_timeline (只写blocked)
```

### 定期持久化（save_state）
```
scanner.stop() / risk_loop / 定时
  └─ runtime_persistence.save_state()
       ├─ broker_orders → MongoDB broker_orders
       ├─ broker_positions → MongoDB broker_positions
       └─ broker_accounts → MongoDB broker_accounts
```

### 启动恢复（load_state）
```
scanner.start()
  └─ runtime_persistence.load_state()
       ├─ broker_orders → MongoDB (read)
       ├─ broker_positions → MongoDB (read)
       ├─ broker_accounts → MongoDB (read)
       └─ load_timeline()
            ├─ scanner_timeline → 只读 blocked
            └─ broker_orders → 读 buy/sell (恢复到内存timeline)
```

---

## 五、当前架构规则（v2.9.97c 后）

### 规则1: broker_orders 是交易数据唯一真相源
- buy/sell 记录：只从 broker_orders 读
- 所有前端Tab看到的交易数据：最终来自 broker_orders
- 不允许从 scanner_timeline 读 buy/sell

### 规则2: broker_positions 是持仓数据唯一真相源
- 持仓列表：只从 broker_positions 读
- 不允许从 scanner_timeline 累加推算持仓

### 规则3: scanner_timeline 只写决策日志
- 允许写: blocked / rejected / 其他非交易记录
- 禁止写: buy / sell
- 历史遗留的 buy/sell 数据保留（向后兼容读取）

### 规则4: broker_accounts 只是资金缓存
- position_count 不再信任（可能为0）
- 从 broker_positions 实查持仓数量

---

## 六、残留风险（仍需关注）

### P2: scanner进程崩溃时 save_state 不可靠
- 000608.SZ 止损事故：进程崩溃 → save_state() 未执行 → 持仓丢失
- 修复: runtime_persistence 启动时检测持仓丢失，从 broker_orders 重建
- 风险: 如果 broker_orders 也丢了(极不可能)，无法恢复

### P2: 前端 useScannerMonitor 持有两份持仓数据
- `positions` (来自 /all → scanner内存)
- `unified.positions` (来自 /unified/positions → broker_positions)
- 目前 AccountTab 读 positions (via /analysis)，不用 unified.positions
- 长期: 统一为只用 unified

### P3: scanner_timeline 历史遗留数据
- 有 70 条 buy/sell 记录（6/16之前的旧数据）
- 不影响功能（新代码不读），但占用存储
- 可选: 一次性清理

---

## 七、数据一致性自动检查（建议增加）

| 检查项 | 频率 | 方法 |
|--------|------|------|
| 持仓数量: /all vs /analysis vs /unified | 每次部署后 | API对比测试 |
| 交易笔数: /unified/trades vs /trade-audit | 每次部署后 | API对比测试 |
| broker_orders vs scanner_timeline buy/sell | 每日 | MongoDB聚合对比 |
| /account position_count vs broker_positions | 每次部署后 | API测试 |
| scanner_timeline 不应有新 buy/sell | 每日 | count_documents check |
