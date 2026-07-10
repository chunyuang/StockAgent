# 数据流闭环审查报告 — 2026-07-11 00:53

## Phase 0: Issue队列
- ✅ 待修队列为空

## Phase 1: 数据链路

### 1.1 scanner→Redis→WS→前端 ✅
- **写入**: `scanner_event_subscribers._push_to_redis()` 
  - position事件 → `scanner:position` (Redis Stream xadd, maxlen=5000, 不丢)
  - status事件 → `scanner:status` (Pub/Sub publish, 允许丢)
- **转发**: `redis_ws_bridge.py` 订阅Redis频道 → `broadcast_task_update/broadcast_scanner_event`
- **推送**: `websocket.py` → `send_json` 到前端
- **重连补发**: subscribe时 `catchup_logs(task_id, ws)`, v2.9.83修复从last_stream_id补发

### 1.2 quote_manager 数据源切换 ✅
- **主力**: 东方财富 (EastmoneyAdapter, priority=5)
- **降级链**: eastmoney → sina fallback → MongoDB日线
- **L1降级**: 东财数据为空且degrade_level>=1 → MongoDB
- **L2降级**: degrade_level>=2 → 直接MongoDB日线
- **v2.9.86修复**: 非交易时间缓存为空时,无论degrade_level都fallback到MongoDB

### 1.3 非交易时间读MongoDB ✅
- `quote_manager.get_realtime_snapshot()` 检测 `is_trading`
- 非交易时间: 先用东财缓存 → 缓存为空则MongoDB → 最终返回{}
- 逻辑清晰,无死路

### 1.4 WS断线重连+数据新鲜度 ✅
- **心跳**: 前端ping → 后端pong
- **断线处理**: `manager.disconnect()` 清理
- **重连补发**: subscribe_scanner时从last_signal_stream_id/last_position_stream_id补发
- **新鲜度**: `get_staleness()` 返回上次更新距现在的秒数, 测试覆盖

## Phase 2: MongoDB集合健康

| 集合 | 行数 | 最新trade_date | 类型 |
|------|------|---------------|------|
| stock_daily_ak_full | 2,807,735 | 20260710 | int ✅ |
| daily_basic | 2,836,253 | 20260710 | int ✅ |
| limit_list | 57,584 | 20260710 | int ✅ |
| sentiment_scores | 528 | 20260710 | int ✅ |
| scan_traces | 5,098 | 20260710 | int ✅ |
| broker_orders | 175 | 20260710 | int ✅ |

- ✅ 所有集合数据更新至7月10日(昨日交易日)
- ✅ trade_date类型全部为int,无混合类型

## Phase 3: 9层卖出时间防护 ✅

### 卖出门控检查点(全部覆盖):
1. **broker.place_order()** → `MarketPhase.is_continuous_auction()` 硬保护 (L920)
2. **broker._validate_sell()** → 含position校验+MongoDB兜底 (L869)
3. **scanner._execute_risk_sell()** → `MarketPhase.is_continuous_auction()` (L871)
4. **scanner stop/liquidate** → 委托`_position_manager.liquidate_positions`
5. **position_checker** → `MarketPhase.is_continuous_auction()` (L1478)
6. **sell_signal_checker** → `MarketPhase.is_continuous_auction()` (L1225, L1445)
7. **非交易时间卖出** → `place_order`硬拒,返回"非连续竞价时间"
8. **尾盘禁止新开仓** → `MarketPhase.is_open_allowed()` (broker L816)
9. **broker._execute_sell avg_cost保存** ✅
   - 正常path: 从内存position取avg_cost
   - 兜底path1: 从MongoDB broker_positions查
   - 兜底path2: 从broker_orders查最近buy的filled_price
   - order.avg_cost在buy时写入(L1002)

## Phase 4: unified.py覆盖率

### 绕过unified直查MongoDB的文件(14个):

**已有unified import但仍直查(4个):**
- scanner_core.py: bo=32, bp=23 ← 最大绕过者
- scanner_report.py: bo=12
- scanner_review.py: bo=9, bp=2
- scanner_scan.py: bo=10

**无unified import直查(5个):**
- scanner_analysis.py: bo=11, bp=11 ← 持仓/交易详情
- scanner_trading.py: bo=25 ← 交易操作
- scanner_sentiment.py: bo=7
- scanner_strategy.py: bo=3, bp=2
- trading_archive.py: bo=1, bp=1

**低优先级(5个):**
- pnl_helper.py: unified的fallback工具,合理
- admin_db.py/scan_insight.py/system.py/stop_loss_analysis.py: 元数据/管理,非交易数据

### 评估:
- **核心问题**: scanner_core.py(32+23)和scanner_trading.py(25)是最大绕过者
- **风险**: 数据漂移 — 不同端点可能对同一数据返回不同结果
- **建议**: 下次迭代优先迁移scanner_core和scanner_trading到unified

## 测试结果
- ✅ pytest: 1594 passed, 4 skipped, 0 failed (75.52s)
- ✅ vite build: 成功 (12.99s)

## 审查结论
**全链路健康,无需修复。**
- 数据流完整(scanner→Redis→WS→前端)
- MongoDB集合数据新鲜(7/10),类型一致(int)
- 9层卖出时间防护全覆盖
- unified覆盖率待提升(14个绕过文件),但不影响正确性
